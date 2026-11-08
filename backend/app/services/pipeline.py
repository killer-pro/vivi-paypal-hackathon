import asyncio
import mimetypes
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import VOICE_ID, AppSettings, parse_voice_catalog
from app.models import Asset, MusicTrack, Project, Scene, Step
from app.providers.base import GenerationResult, ProviderError, TextResult, split_prompt
from app.providers.comfyui import KONTEXT_PREFIX
from app.providers.registry import ProviderRegistry
from app.services import credits, langfuse, montage
from app.services.choices import clip_model, clip_provider_name, reference_choice, start_image_provider
from app.services.costs import WriteGate, tracked_call
from app.services.flow import RUN_ASSET_KIND, latest_by_scene, references_to_make
from app.services.llm_json import json_value, scene_text
from app.services.prompts import (
    FINAL_SYSTEM,
    IDEA_SYSTEM,
    SCRIPT_SYSTEM,
    corrected,
    inventory_prompt,
    project_brief,
    reference_look,
    reference_suffix,
    scene_prompt,
    script_prompt,
    story_prompt,
)
from app.services.script_parsing import (
    ENGAGEMENT_FALLBACK,
    FINAL_SCHEMA,
    SCENE_SCHEMA,
    SCENES_SCHEMA,
    apply_descriptors,
    extract_json,
    has_engagement,
    parse_bible,
    parse_references,
    parse_scenes,
    script_max_tokens,
    script_problems,
    with_descriptors,
)
from app.services.story import (
    INVENTORY_SCHEMA,
    MAX_KONTEXT_IMAGES,
    STORY_SCHEMA,
    assign_voices,
    build_bible,
    compact_prompt,
    elements_in,
    extra_references,
    main_reference,
    parse_story,
    references_from,
    story_problems,
)
from app.services.timeouts import step_timeout
from app.storage import Storage

# Appels simultanés par étape. ComfyUI tourne sur un GPU local : un clip à la fois. Les providers cloud acceptent
# quelques appels en parallèle ; la voix reste à 2 (limite de concurrence des offres ElevenLabs d'entrée de gamme).
CLIP_CONCURRENCY = {"fal": 3, "comfyui": 1, "comfycloud": 2}  # Comfy Cloud : file du service, I2V un à un (`_keyframe_slot`)
DEFAULT_CLIP_CONCURRENCY = 1
VOICE_CONCURRENCY = 2

R = TypeVar("R", GenerationResult, TextResult)
Item = TypeVar("Item")  # élément traité par `_per_scene` : scène ou beat
W = TypeVar("W")  # résultat du traitement


@dataclass
class PipelineContext:
    session: AsyncSession
    storage: Storage
    registry: ProviderRegistry
    app_settings: AppSettings
    publish: Callable[[dict], Awaitable[None]]
    overrides: dict = field(default_factory=dict)  # paramètres valables pour ce lancement seulement (non enregistrés)
    # Écritures en base sérialisées (et à l'abri de l'annulation) quand plusieurs scènes sont générées à la fois.
    writes: WriteGate = field(default_factory=WriteGate)


async def _call(ctx: PipelineContext, step: Step, provider, model: str, fn: Callable[[], Awaitable[R]],
                timeout: float | None = None, input: list[dict] | None = None) -> R:
    """Appel provider tracké ; une réponse vide est une erreur (pas d'asset, coût non facturé)."""
    async def checked() -> R:
        result = await fn()
        if not (result.data if isinstance(result, GenerationResult) else result.text.strip()):
            raise ProviderError(f"{step.name}: réponse vide du provider {provider.name}")
        return result

    return await tracked_call(ctx.session, project_id=step.project_id, step=step.name, provider=provider.name,
                              model=model, fn=checked, timeout=timeout or step_timeout(step.name, provider.name), writes=ctx.writes, input=input)


async def _per_scene(ctx: PipelineContext, scenes: list[Item], limit: int,
                     work: Callable[[Item], Awaitable[W]]) -> list[W]:
    """`work(scène)` pour chaque scène (ou beat), `limit` à la fois au plus ; résultats dans l'ordre des scènes. À la première
    erreur, les scènes pas encore lancées sont abandonnées, les appels en cours annulés (les écritures déjà engagées
    vont à leur terme) et l'erreur d'origine est relancée telle quelle (pas de groupe d'erreurs : `run_step` l'affiche
    à l'utilisateur)."""
    gate = asyncio.Semaphore(limit)

    async def guarded(scene: Item) -> W:
        async with gate:
            return await work(scene)

    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(guarded(scene)) for scene in scenes]
    except ExceptionGroup as errors:
        await ctx.writes.settle()  # la session sert ensuite à enregistrer l'échec : plus d'écriture en vol
        raise errors.exceptions[0] from None
    return [task.result() for task in tasks]


async def _ask_llm(ctx: PipelineContext, step: Step, system: str, prompt: str, json_schema: dict | None = None,
                   max_tokens: int | None = None) -> str:
    llm = await ctx.writes.run(ctx.registry.llm)  # lit les réglages en base : une seule opération à la fois sur la session
    # `json_schema` et `max_tokens` seulement s'ils servent : un LLM à l'ancienne signature reste utilisable pour les
    # étapes texte.
    extra: dict[str, Any] = {k: v for k, v in (("json_schema", json_schema), ("max_tokens", max_tokens)) if v is not None}
    result = await _call(ctx, step, llm, getattr(llm, "model", llm.name),
                         lambda: llm.complete(system, prompt, **extra), input=langfuse.messages(prompt, system))
    return result.text


async def _store(ctx: PipelineContext, project_id: int, kind: str, result: GenerationResult,
                 scene_id: int | None = None, run: str | None = None, meta: dict | None = None) -> Asset:
    """Stocke le fichier puis crée l'Asset, avec une nouvelle variante (max+1) par (projet, type, scène). `run` :
    lancement de l'étape qui l'a produit (`Step.run_id`), pour pouvoir le reprendre après un échec ; `meta` : champs
    ajoutés aux métadonnées."""
    ext = (mimetypes.guess_extension(result.content_type) or ".bin").lstrip(".")
    key = f"projects/{project_id}/{kind}/{uuid4().hex}.{ext}"
    await ctx.storage.put(key, result.data, result.content_type)
    last = await ctx.session.scalar(select(func.max(Asset.variant)).where(
        Asset.project_id == project_id, Asset.kind == kind, Asset.scene_id == scene_id))
    asset = Asset(project_id=project_id, scene_id=scene_id, kind=kind, key=key, content_type=result.content_type,
                  variant=(last or 0) + 1, meta={"model": result.model, "cost_usd": result.cost_usd, **({"run": run} if run else {}), **(meta or {})})
    ctx.session.add(asset)
    await ctx.session.flush()
    return asset


async def _store_id(ctx: PipelineContext, project_id: int, kind: str, result: GenerationResult,
                    scene_id: int | None = None, run: str | None = None) -> int:
    return (await _store(ctx, project_id, kind, result, scene_id, run)).id


async def _skipped(ctx: PipelineContext, project_id: int, step: Step, scene_id: int | None, scenes: list[Scene]
                   ) -> tuple[dict[int, int], list[Scene]]:
    """Reprise (`skip_scenes` dans les paramètres du lancement) : dernier asset des scènes ignorées, et scènes restant
    à produire (toutes, hors reprise)."""
    skip = (ctx.overrides.get("skip_scenes") or []) if scene_id is None else []
    done = await latest_by_scene(ctx.session, project_id, RUN_ASSET_KIND[step.name], skip)
    return done, [s for s in scenes if s.id not in done]


def _in_scene_order(scenes: list[Scene], done: dict[int, int], produced: list[Scene], ids: list[int]) -> list[int]:
    made = dict(zip((s.id for s in produced), ids, strict=True))
    return [done[s.id] if s.id in done else made[s.id] for s in scenes]


async def _latest_asset(ctx: PipelineContext, project_id: int, kind: str, scene_id: int | None = None) -> Asset | None:
    return await ctx.session.scalar(select(Asset).where(
        Asset.project_id == project_id, Asset.kind == kind, Asset.scene_id == scene_id).order_by(Asset.id.desc()).limit(1))


async def _scenes(ctx: PipelineContext, project_id: int, scene_id: int | None, step_name: str) -> list[Scene]:
    query = select(Scene).where(Scene.project_id == project_id).order_by(Scene.position)
    if scene_id is not None:
        query = query.where(Scene.id == scene_id)
    scenes = list((await ctx.session.scalars(query)).all())
    if not scenes:
        raise ProviderError(f"{step_name}: aucune scène, validez d'abord le script")
    return scenes


async def _step(ctx: PipelineContext, project_id: int, name: str) -> Step:
    # populate_existing : params/statut ont pu être modifiés par une autre session (API).
    return (await ctx.session.execute(select(Step).where(Step.project_id == project_id, Step.name == name)
                                      .execution_options(populate_existing=True))).scalar_one()


async def _music_track(ctx: PipelineContext, track_id) -> MusicTrack | None:
    if track_id is None:
        return None
    track = await ctx.session.get(MusicTrack, int(track_id))
    if track is None:
        raise ProviderError(f"music: piste {track_id} introuvable dans la bibliothèque")
    return track


async def _download(ctx: PipelineContext, key: str, dest: Path) -> Path:
    path = dest.with_suffix(Path(key).suffix)
    path.write_bytes(await ctx.storage.get(key))
    return path


async def _idea(ctx, project, step, scene_id):
    hint = step.params.get("hint", "")
    prompt = (f"{project_brief(project)}\n" + (f"Piste de départ : {hint}\n" if hint else "")
              + "Propose un angle direct pour cette vidéo verticale virale : une seule proposition, en 2 à 4 phrases "
              "(l'accroche des 2 premières secondes, le fil conducteur, la chute), "
              "sans introduction ni formule de politesse et sans markdown (ni titre, ni liste, ni gras).")
    return {"angle": (await _ask_llm(ctx, step, IDEA_SYSTEM, prompt)).strip()}


def _read_beats(answer: str, target: float) -> tuple[list[dict] | None, list[str]]:
    """(beats, défauts) d'une réponse de la passe histoire ; beats None si elle est illisible (le défaut est l'erreur)."""
    try:
        beats = parse_story(answer, "", target)["beats"]
    except ProviderError as e:
        return None, [str(e)]
    return beats, script_problems(beats, target, "beat", "le dernier beat")


async def _story_beats(ctx, step, prompt: str, target: float, budget: int) -> tuple[str, list[dict], list[str]]:
    """Passe histoire : (réponse, beats, défauts restants), avec une seule relance ciblée ; échec si aucune des deux
    réponses n'est lisible."""
    answer = await _ask_llm(ctx, step, SCRIPT_SYSTEM, prompt, STORY_SCHEMA, budget)
    beats, problems = _read_beats(answer, target)
    if beats is not None and not problems:
        return answer, beats, []
    retry = await _ask_llm(ctx, step, SCRIPT_SYSTEM, corrected(
        prompt, answer, " ; ".join(problems), "renvoie le JSON complet de tous les beats."), STORY_SCHEMA, budget)
    again, again_problems = _read_beats(retry, target)
    if again is not None:
        return retry, again, again_problems
    if beats is None:
        raise ProviderError(f"{again_problems[0]} (après une relance automatique)")
    return answer, beats, problems  # la première réponse était exploitable : ses défauts sont signalés


async def _story(ctx, project, step, scene_id):
    angle = (await _step(ctx, project.id, "idea")).result.get("angle", "")
    target, scene_length = project.target_duration_s, step.params.get("scene_length_s")
    budget = script_max_tokens(target, scene_length)
    prompt = story_prompt(project, angle, scene_length, ctx.overrides.get("instruction", ""))
    answer, beats, problems = await _story_beats(ctx, step, prompt, target, budget)
    inventory_ask = inventory_prompt(project, beats)
    inventory = await _ask_llm(ctx, step, SCRIPT_SYSTEM, inventory_ask, INVENTORY_SCHEMA, budget)
    story = parse_story(answer, inventory, target)
    found = story_problems(story)
    if found:  # une seule relance ciblée de l'inventaire
        retry = await _ask_llm(ctx, step, SCRIPT_SYSTEM, corrected(
            inventory_ask, inventory, " ; ".join(found), "renvoie le JSON complet de l'inventaire."),
            INVENTORY_SCHEMA, budget)
        fixed = parse_story(answer, retry, target)
        story, found = fixed, story_problems(fixed)
    catalog = parse_voice_catalog(await ctx.app_settings.get("voice_catalog") or "[]") or []
    assign_voices(story, catalog, narrator=await ctx.app_settings.get("default_voice_id"))
    last = story["beats"][-1]
    if not has_engagement(last["voice_text"]):
        last["voice_text"] = f"{last['voice_text'].rstrip()} {ENGAGEMENT_FALLBACK}"
    warnings = [*script_problems(story["beats"], target, "beat", "le dernier beat"), *found]
    return {**story, **({"warnings": warnings} if warnings else {})}


SCENE_CALLS = 4  # prompts visuels de scènes demandés au LLM en même temps
SCENE_MAX_TOKENS = 1500


async def _scene_visual(ctx, project, step, story: dict, index: int) -> dict:
    """Scène du beat `index` (à partir de 1) : prompt visuel écrit par le LLM, descripteurs garantis par le serveur."""
    beats = story["beats"]
    beat = beats[index - 1]
    present = elements_in(beat, story["elements"])
    previous = beats[index - 2]["summary"] if index > 1 else ""
    answer = await _ask_llm(ctx, step, SCRIPT_SYSTEM, scene_prompt(project, story.get("bible", ""), beat, present, previous,
                                                                  index, len(beats), ctx.overrides.get("instruction", "")), SCENE_SCHEMA, SCENE_MAX_TOKENS)
    data = json_value(answer)
    visual = scene_text(data.get("visual_prompt")) if isinstance(data, dict) else ""
    if not visual:
        raise ProviderError(f"script: beat {index} sans visual_prompt")
    return {"voice_text": beat["voice_text"], "duration_s": beat["duration_s"],
            "visual_prompt": with_descriptors(visual, present), "elements": beat["elements"],
            "continuity": beat.get("continuity", "cut"), "speaker": beat.get("speaker", ""),
            "reference": main_reference(present, story["elements"])}


async def _script_from_story(ctx, project, step, story: dict):
    """Scènes écrites à partir de la story validée : un appel court par beat. Voix off et durées viennent de la story ; les
    scènes ne sont remplacées qu'une fois tous les prompts reçus."""
    scenes = await _per_scene(ctx, list(range(1, len(story["beats"]) + 1)), SCENE_CALLS,
                              lambda i: _scene_visual(ctx, project, step, story, i))
    await ctx.session.execute(delete(Scene).where(Scene.project_id == project.id))
    ctx.session.add_all(Scene(project_id=project.id, position=i, voice_text=s["voice_text"], visual_prompt=s["visual_prompt"],
                              duration_s=float(s["duration_s"]), reference=s["reference"], elements=s["elements"],
                              continuity=s["continuity"], speaker=s["speaker"])
                        for i, s in enumerate(scenes, 1))
    bible = build_bible(story.get("bible", ""), story["elements"])
    references = references_from(story["elements"])
    return {"scene_count": len(scenes), **({"bible": bible} if bible else {}),
            **({"references": references} if references else {})}


async def _story_result(ctx, project_id: int) -> dict:
    """Résultat de l'étape story ; vide pour un projet sans story écrite (ancien chemin du script)."""
    step = await ctx.session.scalar(select(Step).where(Step.project_id == project_id, Step.name == "story")
                                    .execution_options(populate_existing=True))
    return step.result if step else {}


async def _script(ctx, project, step, scene_id):
    if (story := await _story_result(ctx, project.id)).get("beats"):
        return await _script_from_story(ctx, project, step, story)
    angle = (await _step(ctx, project.id, "idea")).result.get("angle", "")
    prompt = script_prompt(project, angle, step.params.get("scene_length_s"), ctx.overrides.get("instruction", ""))
    target = project.target_duration_s
    budget = script_max_tokens(target, step.params.get("scene_length_s"))
    answer = await _ask_llm(ctx, step, SCRIPT_SYSTEM, prompt, SCENES_SCHEMA, budget)
    try:
        scenes = parse_scenes(answer, target)
        problems = script_problems(scenes, target)
        error = ProviderError("script: " + " ; ".join(problems)) if problems else None
    except ProviderError as e:  # structure invalide : une relance, le script reste refusé si elle échoue aussi
        scenes, error = [], e
    if error:  # une seule relance ciblée, les défauts renvoyés au LLM
        retry = corrected(prompt, answer, str(error), "renvoie le JSON complet de toutes les scènes, chacune avec "
                          "voice_text, visual_prompt et duration_s non vides.")
        first = answer
        try:
            answer = await _ask_llm(ctx, step, SCRIPT_SYSTEM, retry, SCENES_SCHEMA, budget)
            scenes = parse_scenes(answer, target)
        except ProviderError as again:
            if not scenes:
                raise ProviderError(f"{again} (après une relance automatique)") from again
            answer = first  # la première réponse était exploitable : on la garde, ses défauts sont signalés
    # Défauts de qualité restants : l'appel à l'engagement est garanti, le reste est signalé dans le résultat.
    if not has_engagement(scenes[-1]["voice_text"]):
        scenes[-1]["voice_text"] = f"{scenes[-1]['voice_text'].rstrip()} {ENGAGEMENT_FALLBACK}"
    warnings = script_problems(scenes, target)
    # Les assets existants sont conservés (scene_id passe à NULL via la FK).
    await ctx.session.execute(delete(Scene).where(Scene.project_id == project.id))
    references = parse_references(answer)
    known = {r["id"] for r in references}
    for scene in scenes:  # une référence inconnue ne compte pas
        scene["reference"] = scene["reference"] if scene["reference"] in known else ""
    apply_descriptors(scenes, references)
    ctx.session.add_all(Scene(project_id=project.id, position=i, voice_text=str(s["voice_text"]).strip(),
                              visual_prompt=str(s["visual_prompt"]).strip(), duration_s=float(s["duration_s"]),
                              reference=s["reference"])
                        for i, s in enumerate(scenes, 1))
    bible = parse_bible(answer)
    return {"scene_count": len(scenes), **({"bible": bible} if bible else {}),
            **({"references": references} if references else {}), **({"warnings": warnings} if warnings else {})}


async def _reference(ctx, project, step, scene_id):
    """Images de référence. Le script liste des éléments récurrents (`references`) : une image par élément (ou celle de
    `reference_id` seulement, ou celles de `reference_ids`), au prompt du script ou de `params.prompts[id]`. Sans élément : une image unique du projet,
    d'après la fiche visuelle (anciens projets)."""
    script = (await _step(ctx, project.id, "script")).result
    elements = script.get("references") or []
    provider, model = await reference_choice(step.params, ctx.app_settings)
    image = await ctx.registry.image(provider)

    async def make(prompt: str, ref: str = "") -> int:
        result = await _call(ctx, step, image, model, lambda: image.generate(prompt, model=model),
                             input=langfuse.messages(prompt))
        return (await _store(ctx, project.id, "reference", result, meta={"ref": ref} if ref else None)).id

    try:
        return await _reference_assets(ctx, project, step, script, elements, make)
    finally:
        if hasattr(image, "release"):  # provider local qui garde ses modèles chargés entre deux images
            await image.release()


async def _reference_assets(ctx, project, step, script, elements, make) -> dict:
    """Génère les images (une par élément récurrent, ou une seule sans élément) ; renvoie le résultat de l'étape."""
    if not elements:
        bible = script.get("bible")
        prompt = step.params.get("prompt") or (
            f"{bible}\nVertical 9:16, {reference_look(project)}, consistent style." if bible
            else f"{project.theme}, vertical 9:16, {reference_look(project)}, consistent style")
        ids = [await make(prompt)]
    else:
        todo = references_to_make(elements, ctx.overrides)
        if not todo:
            raise ProviderError(f"reference: élément inconnu : {ctx.overrides.get('reference_id')}")
        prompts = step.params.get("prompts") or {}
        ids = [await make(f"{prompts.get(e['id']) or e['prompt']}\n{reference_suffix(project)}", e["id"]) for e in todo]
    return {"asset_id": ids[0], "asset_ids": ids}


async def _reference_images(ctx: PipelineContext, project_id: int) -> dict[str, bytes]:
    """Dernière image de chaque élément de référence, par id (`""` : image du projet, importée ou d'avant les éléments)."""
    assets = (await ctx.session.scalars(select(Asset).where(
        Asset.project_id == project_id, Asset.kind == "reference").order_by(Asset.id))).all()
    latest = {a.meta.get("ref", ""): a for a in assets}
    return {ref: await ctx.storage.get(a.key) for ref, a in latest.items()}


async def _selected_clip(ctx: PipelineContext, scene: Scene) -> bytes | None:
    """Fichier du clip sélectionné d'une scène, None si elle n'en a pas."""
    asset = await ctx.session.get(Asset, scene.selected_clip_asset_id) if scene.selected_clip_asset_id else None
    return await ctx.storage.get(asset.key) if asset else None


async def _clips(ctx, project, step, scene_id):
    scenes = await _scenes(ctx, project.id, scene_id, "clips")
    params = {**step.params, **ctx.overrides}
    provider_name = await clip_provider_name(params, ctx.app_settings)
    model = await clip_model(params, ctx.app_settings)
    video = await ctx.registry.video(provider_name)
    composer = None  # Gemini compose l'image de départ à la place de Kontext
    if await start_image_provider(params, ctx.app_settings, provider_name) == "gemini":
        composer = await ctx.registry.image("gemini"), await ctx.app_settings.get("gemini_image_model")
    references = await _reference_images(ctx, project.id)
    everything = scenes if scene_id is None else await _scenes(ctx, project.id, None, "clips")
    before = {s.id: everything[i - 1] for i, s in enumerate(everything) if i}  # scène qui précède, par scène
    produced: dict[int, bytes] = {}  # clips générés pendant ce lancement, pour les scènes enchaînées qui les suivent

    story_elements = {e["id"]: e for e in (await _story_result(ctx, project.id)).get("elements", [])}
    kinds = {i: e["kind"] for i, e in story_elements.items()}

    async def start_images(scene: Scene) -> tuple[list[bytes], list[str]]:
        """Images d'entrée de la scène, la principale d'abord : la dernière image du clip précédent pour une scène
        « continue » (clip produit pendant ce lancement, sinon clip sélectionné de la scène précédente), sinon, ou faute de
        clip précédent, son élément de référence ; puis les images des autres éléments visibles (`extra_references`), dont la
        référence de la scène quand une scène enchaînée présente un sujet absent de la scène précédente."""
        previous, main = before.get(scene.id), None
        main_id: str | None = scene.reference
        if scene.continuity == "continue" and previous is not None:
            data = produced.get(previous.id) or await ctx.writes.run(lambda: _selected_clip(ctx, previous))
            if data:
                main, main_id = await montage.last_frame(data), None
        if main is None:
            main = references.get(scene.reference) or references.get("")
        # Scène enchaînée : la dernière image tient lieu de principale. Si le sujet de la scène n'était pas déjà dans la
        # scène précédente, sa référence part parmi les autres (sinon son identité n'est nulle part dans les entrées).
        seen = {previous.reference, *(e["id"] for e in previous.elements)} if previous is not None else set()
        entering = [scene.reference] if main_id is None and scene.reference and scene.reference not in seen else []
        shown = [*entering, *(e["id"] for e in scene.elements)]
        extras = extra_references(shown, kinds, set(references) - {""}, {main_id or ""},
                                  MAX_KONTEXT_IMAGES - (main is not None))
        sent = [*([main_id] if main_id and main is not None else []), *extras]
        return [*([main] if main is not None else []), *(references[i] for i in extras)], sent

    async def clip(scene: Scene) -> int:
        found, sent = await start_images(scene)
        images: list[bytes | None] = [*found] or [None]
        image, *others = images
        prompt = compact_prompt(scene.visual_prompt, [story_elements[i] for i in sent if i in story_elements])
        # `references` seulement s'il y en a : un provider sans cette option reste utilisable
        extra: dict[str, Any] = {"references": [*others]} if others else {}
        if composer is not None and image is not None:  # Gemini replace les images dans la scène, ComfyUI l'anime
            gemini, gemini_model = composer
            still = split_prompt(prompt)[0]
            composed = await _call(ctx, step, gemini, gemini_model, lambda: gemini.generate(
                KONTEXT_PREFIX + still, model=gemini_model, references=images), input=langfuse.messages(KONTEXT_PREFIX + still))
            extra = {"start_image": composed.data}
        result = await _call(ctx, step, video, model, lambda: video.generate(
            prompt, model=model, duration_s=scene.duration_s + montage.PAD_S, image=image, **extra),
            timeout=step_timeout("clips", provider_name), input=langfuse.messages(prompt))
        produced[scene.id] = result.data

        async def keep() -> int:
            asset = await _store(ctx, project.id, "clip", result, scene.id, step.run_id)
            if result.keyframe:  # image de départ (profil Précision) : conservée, rattachée à son clip, sans coût
                keyframe = GenerationResult(result.keyframe, "image/png", 0.0, result.model)
                await _store(ctx, project.id, "keyframe", keyframe, scene.id, meta={"clip_asset_id": asset.id})
            # Première variante sélectionnée d'office ; un choix existant n'est écrasé que si le lancement vient d'un nouveau
            # prompt (`select_new`) : l'utilisateur attend alors ce clip dans le montage.
            if scene.selected_clip_asset_id is None or ctx.overrides.get("select_new"):
                scene.selected_clip_asset_id = asset.id
            return asset.id

        return await ctx.writes.run(keep)

    done, todo = await _skipped(ctx, project.id, step, scene_id, scenes)
    # Un enchaînement attend le clip précédent : une scène à la fois, dans l'ordre des positions.
    chained = any(s.continuity == "continue" for s in todo)
    limit = 1 if chained else CLIP_CONCURRENCY.get(provider_name, DEFAULT_CLIP_CONCURRENCY)
    return {"asset_ids": _in_scene_order(scenes, done, todo, await _per_scene(ctx, todo, limit, clip))}


async def _voice(ctx, project, step, scene_id):
    """Une voix par scène : celle du personnage qui parle (`Scene.speaker`, voix choisie dans la story), sinon la voix du
    narrateur (`params.voice_id`, sinon réglage `default_voice_id`)."""
    narrator = step.params.get("voice_id") or await ctx.app_settings.get("default_voice_id")
    scenes = await _scenes(ctx, project.id, scene_id, "voice")
    characters = {e["id"]: e.get("voice_id", "") for e in (await _story_result(ctx, project.id)).get("elements", [])}
    voices = {s.id: characters.get(s.speaker) or narrator for s in scenes}
    if not all(voices.values()):
        raise ProviderError("voice: aucune voix configurée (réglage default_voice_id ou paramètre voice_id)")
    if not all(VOICE_ID.fullmatch(str(v)) for v in voices.values()):  # avant tout appel : l'identifiant finit dans l'URL
        raise ProviderError("voice: identifiant de voix invalide (lettres, chiffres, _ et - uniquement)")
    voice = await ctx.registry.voice()

    async def speak(scene: Scene) -> int:
        result = await _call(ctx, step, voice, getattr(voice, "model", voice.name),
                             lambda: voice.synthesize(scene.voice_text, voice_id=voices[scene.id]),
                             input=langfuse.messages(scene.voice_text))
        return await ctx.writes.run(lambda: _store_id(ctx, project.id, "voice", result, scene.id, step.run_id))

    done, todo = await _skipped(ctx, project.id, step, scene_id, scenes)
    return {"asset_ids": _in_scene_order(scenes, done, todo, await _per_scene(ctx, todo, VOICE_CONCURRENCY, speak))}


async def _music(ctx, project, step, scene_id):
    track = await _music_track(ctx, step.params.get("track_id"))
    return {"track_id": track.id if track else None}


async def _montage(ctx, project, step, scene_id):
    """Montage : chaque scène est encodée une fois (segment mis en cache dans le stockage, voir `montage.segment_key`) ;
    après une régénération de scène, seule cette scène est ré-encodée, les autres segments sont réutilisés."""
    scenes = await _scenes(ctx, project.id, None, "montage")
    track = await _music_track(ctx, (await _step(ctx, project.id, "music")).params.get("track_id"))
    reused = 0
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        segments = []
        for scene in scenes:
            clip = await ctx.session.get(Asset, scene.selected_clip_asset_id) if scene.selected_clip_asset_id else None
            if clip is None:
                raise ProviderError(f"montage: la scène {scene.position} n'a pas de clip sélectionné")
            voice = await _latest_asset(ctx, project.id, "voice", scene.id)
            if voice is None:
                raise ProviderError(f"montage: la scène {scene.position} n'a pas de voix")
            base = montage.segment_key(project.id, clip.id, voice.id)
            if await ctx.storage.exists(f"{base}.mp4") and await ctx.storage.exists(f"{base}.wav"):
                video, audio = d / f"seg{scene.position}.mp4", d / f"seg{scene.position}.wav"
                video.write_bytes(await ctx.storage.get(f"{base}.mp4"))
                audio.write_bytes(await ctx.storage.get(f"{base}.wav"))
                segments.append(montage.Segment(video, audio, await montage.probe_duration(audio), scene.voice_text))
                reused += 1
                continue
            segment = await montage.render_segment(
                montage.SceneInput(await _download(ctx, clip.key, d / f"clip{scene.position}"),
                                   await _download(ctx, voice.key, d / f"voice{scene.position}"), scene.voice_text),
                d, f"seg{scene.position}")
            await ctx.storage.put(f"{base}.mp4", segment.video.read_bytes(), "video/mp4")
            await ctx.storage.put(f"{base}.wav", segment.audio.read_bytes(), "audio/wav")
            segments.append(segment)
        music = await _download(ctx, track.key, d / "music") if track else None
        out = d / "render.mp4"
        duration = await montage.assemble(segments, music, out, d / "work",
                                          str(step.params.get("subtitle_style") or montage.DEFAULT_SUBTITLE_STYLE))
        result = GenerationResult(out.read_bytes(), "video/mp4", 0.0, "ffmpeg")
    asset = await _store(ctx, project.id, "render", result)
    return {"asset_id": asset.id, "duration_s": round(duration, 2), "segments_reused": reused,
            "segments_rendered": len(scenes) - reused}


async def _final(ctx, project, step, scene_id):
    angle = (await _step(ctx, project.id, "idea")).result.get("angle", "")
    narration = " ".join(s.voice_text for s in (await ctx.session.scalars(
        select(Scene).where(Scene.project_id == project.id).order_by(Scene.position))).all())
    prompt = (f"Titre de travail : {project.title}\n{project_brief(project)}\nAngle : {angle}\nVoix off : {narration}\n"
              "Propose les métadonnées de publication. Réponds avec "
              '{"title": "titre court", "description": "description", "hashtags": ["#exemple"]}.')
    data = extract_json(await _ask_llm(ctx, step, FINAL_SYSTEM, prompt, FINAL_SCHEMA), "final")
    hashtags = data.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = hashtags.split()
    metadata = {"title": str(data.get("title") or project.title), "description": str(data.get("description") or ""),
                "hashtags": [str(h) for h in hashtags] if isinstance(hashtags, list) else []}
    # Verrou jusqu'au commit de run_step : un arrêt de l'autopilot pendant l'appel au LLM n'est pas écrasé.
    await ctx.session.refresh(project, with_for_update=True)
    project.replace_metadata(metadata)
    return metadata


EXECUTORS = {"idea": _idea, "story": _story, "script": _script, "reference": _reference, "clips": _clips,
             "voice": _voice, "music": _music, "montage": _montage, "final": _final}


async def run_step(ctx: PipelineContext, project_id: int, step_name: str, scene_id: int | None = None) -> None:
    step = await _step(ctx, project_id, step_name)
    project = await ctx.session.get(Project, project_id)
    traced = langfuse.step_run(await ctx.writes.run(lambda: langfuse.load_config(ctx.app_settings)),
                               project_id=project_id, title=project.title if project else "", step=step_name, scene_id=scene_id)
    with traced as trace:  # trace Langfuse de ce lancement (inactive sans clés) ; son résultat est celui de l'étape
        try:
            step.result = await EXECUTORS[step_name](ctx, project, step, scene_id)
            step.status, step.error = "awaiting_validation", None
        except Exception as e:  # erreur inattendue : visible dans l'admin plutôt qu'un job perdu
            error = str(e) if isinstance(e, ProviderError) else f"{type(e).__name__}: {e}"
            if not ctx.session.is_active:  # erreur DB : la session doit être rollback avant d'enregistrer l'échec
                await ctx.session.rollback()
                step = await _step(ctx, project_id, step_name)  # recharge l'étape expirée par le rollback
            step.status, step.error = "failed", error
        if trace is not None:
            trace.update(output={"status": step.status, "error": step.error},
                         **({"level": "ERROR", "status_message": step.error} if step.error else {}))
    await credits.close_for_step(ctx.session, project_id, step_name, completed=step.status == "awaiting_validation")
    await ctx.session.commit()
    await ctx.publish({"project_id": project_id, "step": step_name, "status": step.status, "error": step.error})
