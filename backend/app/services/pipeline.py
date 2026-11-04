import asyncio
import json
import math
import mimetypes
import re
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
from app.providers.comfyui import CLIP_TIMEOUT_S as COMFYUI_CLIP_TIMEOUT_S
from app.providers.comfyui import KONTEXT_PREFIX, ComfyUIImage
from app.providers.fal import IMAGE_MODELS
from app.providers.registry import ProviderRegistry
from app.services import credits, langfuse, montage, styles
from app.services.costs import DEFAULT_ATTEMPTS, WriteGate, tracked_call
from app.services.flow import RUN_ASSET_KIND, latest_by_scene
from app.services.llm_json import (
    SCENE_MAX_S,
    SCENE_MIN_S,
    fill_durations,
    json_value,
    ref_id,
    scene_duration,
    scene_text,
)
from app.services.story import (
    INVENTORY_SCHEMA,
    MAX_BIBLE_CHARS,
    MAX_DESCRIPTOR_CHARS,
    MAX_KONTEXT_IMAGES,
    MAX_REFERENCES,
    STORY_SCHEMA,
    assign_voices,
    build_bible,
    compact_prompt,
    descriptor_head,
    elements_in,
    extra_references,
    main_reference,
    parse_story,
    references_from,
    story_problems,
)
from app.storage import Storage

STEP_TIMEOUTS = {"clips": 900, "montage": 600}
CLIP_TIMEOUTS = {"comfyui": COMFYUI_CLIP_TIMEOUT_S}  # providers vidéo locaux, plus lents que le cloud
DEFAULT_TIMEOUT = 300
PER_SCENE_STEPS = set(RUN_ASSET_KIND)  # un appel provider par scène : clips et voix
# Appels simultanés par étape. ComfyUI tourne sur un GPU local : un clip à la fois. Les providers cloud acceptent
# quelques appels en parallèle ; la voix reste à 2 (limite de concurrence des offres ElevenLabs d'entrée de gamme).
CLIP_CONCURRENCY = {"fal": 3, "comfyui": 1}
DEFAULT_CLIP_CONCURRENCY = 1
VOICE_CONCURRENCY = 2
LLM_CALLS = {"script": 10, "story": 4}  # appels LLM possibles par lancement (dont ceux d'une scène à la fois pour un script à partir de la story)
JOB_MARGIN_S = 120  # téléchargements, stockage, écritures en base
MAX_JOB_TIMEOUT = 24 * 3600  # un projet long de clips ComfyUI séquentiels (un GPU) dépasse 6 h
IDEA_SYSTEM = "Tu es stratège de contenus viraux pour TikTok, Reels et Shorts."
SCRIPT_SYSTEM = "Tu es scénariste de vidéos verticales virales. Réponds uniquement en JSON."
FINAL_SYSTEM = "Tu rédiges les métadonnées de publication de vidéos virales. Réponds uniquement en JSON."
WORDS_PER_SECOND = 2.5  # débit d'une voix off française naturelle
# Style de prompt visuel de Wan 2.2 (mesuré, Tâche 20A) : un prompt long qui commence par le sujet et son action, avec une
# phrase de caméra explicite, donne un sujet net et une caméra qui bouge ; un prompt court donne un sujet minuscule et un
# plan fixe. Règles de composition (benchmark des profils, 2026-10-21) : sujet de taille modérée avec de la marge, action
# visible, intérieur/extérieur séparés. Le prompt a deux paragraphes car trois modèles le lisent : Flux/Kontext dessinent
# l'image de départ (paragraphe 1 seul : la caméra y est inutile), Wan I2V anime cette image (paragraphe « Motion: » seul :
# redécrire l'image concurrence l'image fournie), Wan T2V lit les deux (`providers.base.split_prompt`). Partagé par le
# script, le chat du plan et l'assistant IA.
VISUAL_PROMPT_GUIDE = (
    "deux paragraphes séparés par une ligne vide. "
    "Premier paragraphe, l'image de départ (80 à 130 mots), dans cet ordre : le sujet principal dans sa pose de départ, "
    "avec des détails physiques ; le décor ; la lumière (moment, direction, couleurs) ; le style d'image de la fiche "
    "visuelle, repris tel quel, avec « sharp focus on the subject, shallow depth of field ». "
    "Il est autonome : le générateur ne connaît ni les autres scènes ni la fiche visuelle, donc chaque personnage, "
    "objet et marque présent y est redécrit en entier, mot pour mot comme dans la fiche ; une marque est nommée et son "
    "logo décrit par sa forme, ses couleurs et son emplacement, jamais par les lettres qu'il porte (le générateur ne "
    "sait pas écrire : ex. « a red aluminium can with a flowing white script logo across its front »). "
    "Composition : le sujet est de taille modérée, avec de la marge autour, jamais remplissant le conteneur ; "
    "l'intérieur et l'extérieur sont séparés explicitement (« derrière le verre », vue de côté fixe). "
    "Second paragraphe, qui commence par « Motion: » (30 à 60 mots) : le sujet en quelques mots, puis son action "
    "principale, faite de 2 ou 3 gestes enchaînés qui remplissent toute la durée de la scène et décrits par ce qu'on "
    "voit (« un bras pousse le dessous du couvercle », pas « dévisser »), puis une phrase de caméra explicite (ex. « "
    "low-angle tracking shot, the camera smoothly dollies backward following the subject », « slow dolly in », « slow "
    "pan left »). Le sujet et la caméra bougent dès la première seconde, à vitesse naturelle (jamais de ralenti). "
    "Format vertical 9:16. Les deux paragraphes ne contiennent aucune négation (« no », « without », « don't ») ni "
    "demande de texte à l'écran : ils décrivent ce qu'on voit, jamais ce qu'on évite (le générateur ne lit pas les "
    "négations)")
# Dernière scène : appel à l'engagement (liker, commenter, partager). Partagée par le script, le chat du plan et l'assistant.
ENGAGEMENT_RULE = (
    "La dernière scène est toujours l'appel à l'engagement : elle dure 4 à 5 secondes et sa voix off (10 mots au plus) contient obligatoirement les trois "
    "gestes, « like », « commente » et « partage », avec une question précise sur le sujet pour déclencher les "
    "commentaires (ex. « Quelle est ta pire habitude du soir ? Dis-le en commentaire, mets un like et partage à "
    "quelqu'un qui dort mal ! », à adapter au sujet). "
    "L'avant-dernière scène porte la chute ou l'idée forte ; le visuel de la dernière scène prolonge cette chute avec "
    "le sujet principal qui regarde la caméra, sans texte à l'écran"
)
ENGAGEMENT_FALLBACK = "Si ça t'a plu, like, commente et partage !"
# Un appel à l'engagement nomme les trois gestes (« liker », « commenter », « partager » et leurs formes courantes).
ENGAGEMENT_WORDS = (r"\b(like\w*|aim\w*)", r"\bcomment\w*", r"\bpartag\w*")
DURATION_TOLERANCE = 0.2  # écart toléré entre la somme des durées et la cible (le prompt demande 10 %)
WORDS_TOLERANCE = 1.5  # voix off au plus 1,5 fois le budget de mots de sa scène, plus 3 mots
SCENE_KEYS = ("voice_text", "visual_prompt", "duration_s")
MAX_SCRIPT_TOKENS = 16000  # plafond du budget de sortie du script, quels que soient les paramètres
# Noms rencontrés dans les réponses des LLM pour les champs d'une scène (le premier non vide l'emporte).
SCENE_ALIASES = {
    "voice_text": ("voice_text", "voiceover", "voice_over", "voice", "narration", "text"),
    "visual_prompt": ("visual_prompt", "visual", "visual_description", "video_prompt", "prompt"),
    "duration_s": ("duration_s", "duration", "seconds", "duree_s", "duree"),
}
# Sorties structurées (schéma OpenAPI au format Gemini) des étapes qui attendent du JSON.
SCENES_SCHEMA = {
    "type": "OBJECT",
    "properties": {"bible": {"type": "STRING"}, "scenes": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {"voice_text": {"type": "STRING"}, "visual_prompt": {"type": "STRING"},
                       "duration_s": {"type": "NUMBER"}, "reference": {"type": "STRING"}},
        "required": list(SCENE_KEYS), "propertyOrdering": [*SCENE_KEYS, "reference"]}},
        "references": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"id": {"type": "STRING"}, "prompt": {"type": "STRING"}, "descriptor": {"type": "STRING"}},
            "required": ["id", "prompt", "descriptor"], "propertyOrdering": ["id", "prompt", "descriptor"]}}},
    "required": ["bible", "scenes"], "propertyOrdering": ["bible", "references", "scenes"],
}
FINAL_SCHEMA = {
    "type": "OBJECT",
    "properties": {"title": {"type": "STRING"}, "description": {"type": "STRING"},
                   "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}}},
    "required": ["title", "description", "hashtags"], "propertyOrdering": ["title", "description", "hashtags"],
}

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


def step_timeout(step: str, video_provider: str | None = None) -> int:
    """Timeout d'un appel provider ; pour les clips, il dépend du provider vidéo (ComfyUI local : plus long)."""
    if step == "clips" and video_provider in CLIP_TIMEOUTS:
        return CLIP_TIMEOUTS[video_provider]
    return STEP_TIMEOUTS.get(step, DEFAULT_TIMEOUT)


async def reference_choice(params: dict, app_settings: AppSettings) -> tuple[str, str]:
    """(provider, modèle) de l'image de référence : paramètres de l'étape, sinon réglage `image_provider` et son modèle
    par défaut (`gemini_image_model`, ou Flux pour fal). Un ancien paramètre `model: flux` sans provider vaut fal."""
    provider = params.get("provider") or ("fal" if params.get("model") in IMAGE_MODELS
                                          else await app_settings.get("image_provider"))
    default = (await app_settings.get("gemini_image_model") if provider == "gemini"
               else ComfyUIImage.MODEL if provider == "comfyui" else next(iter(IMAGE_MODELS)))
    return provider, params.get("model") or default


async def clip_provider_name(params: dict, app_settings: AppSettings) -> str:
    """Provider vidéo d'un lancement de l'étape clips : choix ponctuel/paramètres, sinon réglage par défaut."""
    return params.get("provider") or await app_settings.get("default_video_provider")


async def start_image_provider(params: dict, app_settings: AppSettings, video_provider: str) -> str:
    """Générateur de l'image de départ des scènes qui ont des images de référence : choix du lancement, sinon réglage
    `start_image_provider` (`comfyui` = Flux Kontext, `gemini`). Seul ComfyUI a cette étape : fal anime sa propre image."""
    choice = params.get("start_image") or await app_settings.get("start_image_provider")
    return choice if video_provider == "comfyui" else "comfyui"


async def clip_model(params: dict, app_settings: AppSettings) -> str:
    """Modèle vidéo (profil ComfyUI ou modèle fal) d'un lancement de l'étape clips, résolu comme le provider."""
    return params.get("model") or await app_settings.get("default_video_model")


def job_timeout(step: str, scene_count: int, video_provider: str | None = None) -> int:
    """Timeout du job Arq : chaque appel (un par scène pour clips/voix) peut durer jusqu'à son timeout à chaque
    tentative de tracked_call, plus le backoff ; borné par MAX_JOB_TIMEOUT."""
    calls = max(scene_count, 1) if step in PER_SCENE_STEPS else LLM_CALLS.get(step, 1)
    per_call = step_timeout(step, video_provider) * DEFAULT_ATTEMPTS + 2**DEFAULT_ATTEMPTS
    return min(calls * per_call + JOB_MARGIN_S, MAX_JOB_TIMEOUT)


def _extract_json(text: str, what: str) -> dict:
    """Objet JSON de la réponse ; tolère les blocs ``` et le texte autour."""
    data = json_value(text)
    if not isinstance(data, dict):
        raise ProviderError(f"{what}: JSON invalide (réponse du LLM non exploitable)")
    return data


def _scene_field(scene: dict, key: str):
    return next((scene[k] for k in SCENE_ALIASES[key] if scene.get(k) not in (None, "", [])), None)


def parse_bible(text: str) -> str:
    """Fiche visuelle (personnages, marques, décor, style) d'une réponse de script ; vide si la réponse n'en a pas."""
    data = json_value(text)
    bible = scene_text(data.get("bible")) if isinstance(data, dict) else ""
    return bible[:MAX_BIBLE_CHARS]


def parse_references(text: str) -> list[dict]:
    """Éléments de référence du script (`id`, `prompt`, `descriptor` s'il y en a un) : sans doublon ni entrée incomplète,
    `MAX_REFERENCES` au plus."""
    data = json_value(text)
    raw = data.get("references") if isinstance(data, dict) else None
    found: dict[str, dict] = {}
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and (rid := ref_id(item.get("id"))) and (prompt := scene_text(item.get("prompt"))):
            descriptor = scene_text(item.get("descriptor"))[:MAX_DESCRIPTOR_CHARS]
            found.setdefault(rid, {"id": rid, "prompt": prompt, **({"descriptor": descriptor} if descriptor else {})})
    return list(found.values())[:MAX_REFERENCES]


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())


def with_descriptors(visual_prompt: str, present: list[dict]) -> str:
    """Garantit la cohérence des personnages et produits : le prompt visuel commence par le descripteur (et l'état) de
    chaque élément présent, mot pour mot. Le LLM est prié de le faire ; quand il l'a paraphrasé ou oublié, le serveur
    l'ajoute (on ne compte pas sur la recopie par un modèle léger)."""
    missing = [e for e in present if e.get("descriptor") and _plain(e["descriptor"]) not in _plain(visual_prompt)]
    return f"{descriptor_head(missing)}. {visual_prompt}" if missing else visual_prompt


def apply_descriptors(scenes: list[dict], references: list[dict]) -> None:
    """Ancien chemin du script : le descripteur de l'élément de référence de chaque scène ouvre son prompt visuel."""
    descriptors = {r["id"]: r["descriptor"] for r in references if r.get("descriptor")}
    for scene in scenes:
        if descriptor := descriptors.get(scene["reference"]):
            scene["visual_prompt"] = with_descriptors(scene["visual_prompt"], [{"descriptor": descriptor, "state": ""}])


def parse_scenes(text: str, target_duration_s: float | None = None) -> list[dict]:
    """Scènes normalisées (`voice_text`, `visual_prompt`, `duration_s`, `reference`) d'une réponse de LLM. Tolère les noms
    de champs courants, les champs en trop, une durée en texte ; une durée absente reçoit une part égale du reste de
    la durée cible. Voix off et prompt visuel sont obligatoires : l'erreur nomme chaque scène et champ manquant."""
    data = json_value(text)
    scenes = data.get("scenes") if isinstance(data, dict) else data
    if not isinstance(scenes, list) or not scenes:
        raise ProviderError("script: JSON invalide ou aucune scène")
    parsed: list[dict[str, Any]] = []
    problems: list[str] = []
    for i, raw in enumerate(scenes, 1):
        if not isinstance(raw, dict):
            problems.append(f"scène {i} n'est pas un objet JSON")
            continue
        scene = {"voice_text": scene_text(_scene_field(raw, "voice_text")),
                 "visual_prompt": scene_text(_scene_field(raw, "visual_prompt")),
                 "duration_s": scene_duration(_scene_field(raw, "duration_s")),
                 "reference": ref_id(raw.get("reference"))}
        missing = [k for k in ("voice_text", "visual_prompt") if not scene[k]]
        if missing:
            problems.append(f"scène {i} incomplète ({' et '.join(missing)} vide{'s' if len(missing) > 1 else ''})")
        parsed.append(scene)
    if problems:
        raise ProviderError(f"script: {' ; '.join(problems)}")
    fill_durations(parsed, target_duration_s)
    return parsed


def has_engagement(text: str) -> bool:
    return all(re.search(word, text, re.I) for word in ENGAGEMENT_WORDS)


def script_problems(scenes: list[dict], target_duration_s: float, noun: str = "scène",
                    last: str = "la dernière scène") -> list[str]:
    """Défauts de qualité d'un script structurellement valide : durée totale loin de la cible, voix off trop longue pour
    sa scène (le montage étirerait le clip), dernière scène sans appel à l'engagement."""
    problems = []
    total = sum(s["duration_s"] for s in scenes)
    if abs(total - target_duration_s) > DURATION_TOLERANCE * target_duration_s:
        problems.append(f"la somme des duration_s vaut {total:g} s au lieu de {target_duration_s:g} s")
    for i, s in enumerate(scenes, 1):
        words, budget = len(s["voice_text"].split()), word_budget(s["duration_s"])
        if words > budget * WORDS_TOLERANCE + 3:
            problems.append(f"{noun} {i} : {words} mots de voix off pour {s['duration_s']:g} s (maximum {budget})")
    if not has_engagement(scenes[-1]["voice_text"]):
        problems.append(f"{last} doit inviter à liker, commenter et partager")
    return problems


async def _call(ctx: PipelineContext, step: Step, provider, model: str, fn: Callable[[], Awaitable[R]],
                timeout: float | None = None, input: list[dict] | None = None) -> R:
    """Appel provider tracké ; une réponse vide est une erreur (pas d'asset, coût non facturé)."""
    async def checked() -> R:
        result = await fn()
        if not (result.data if isinstance(result, GenerationResult) else result.text.strip()):
            raise ProviderError(f"{step.name}: réponse vide du provider {provider.name}")
        return result

    return await tracked_call(ctx.session, project_id=step.project_id, step=step.name, provider=provider.name,
                              model=model, fn=checked, timeout=timeout or step_timeout(step.name), writes=ctx.writes, input=input)


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


def script_max_tokens(target_duration_s: float, scene_length_s: float | None = None) -> int:
    """Budget de sortie du script, réflexion comprise. Environ 330 tokens par scène (prompt visuel de ~190 mots anglais et
    voix off) plus la fiche et les références (~1500) : le défaut de 4000 tronquait les vidéos de 30 s et plus."""
    length = scene_length_s if isinstance(scene_length_s, (int, float)) and scene_length_s >= 1 else 3.5  # params non typés
    return min(3000 + 400 * math.ceil(target_duration_s / length), MAX_SCRIPT_TOKENS)


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


def project_brief(project: Project) -> str:
    return (f"Thème : {project.theme}\nPlateforme : {project.platform}\n"
            f"Durée totale cible : {project.target_duration_s} secondes")


async def _idea(ctx, project, step, scene_id):
    hint = step.params.get("hint", "")
    prompt = (f"{project_brief(project)}\n" + (f"Piste de départ : {hint}\n" if hint else "")
              + "Propose un angle direct pour cette vidéo verticale virale : une seule proposition, en 2 à 4 phrases "
              "(l'accroche des 2 premières secondes, le fil conducteur, la chute), "
              "sans introduction ni formule de politesse et sans markdown (ni titre, ni liste, ni gras).")
    return {"angle": (await _ask_llm(ctx, step, IDEA_SYSTEM, prompt)).strip()}


def word_budget(duration_s: float) -> int:
    return round(duration_s * WORDS_PER_SECOND)


def scene_count(target_duration_s: float, scene_length_s: float | None = None) -> tuple[str, str]:
    """(nombre de scènes, durée de chacune) tels que le prompt les demande : « 6 à 15 », « de 2 à 5 secondes »."""
    if scene_length_s:  # durée de scène imposée : nombre de scènes ≈ durée cible / durée de scène
        fewest = most = max(1, round(target_duration_s / scene_length_s))
        length = f"d'environ {scene_length_s:g} secondes chacune"
    else:
        fewest = max(1, math.ceil(target_duration_s / SCENE_MAX_S))
        most = max(fewest, int(target_duration_s // SCENE_MIN_S))
        length = f"de {SCENE_MIN_S} à {SCENE_MAX_S} secondes"
    return (f"{fewest}" if fewest == most else f"{fewest} à {most}"), length


def script_prompt(project: Project, angle: str, scene_length_s: float | None = None, instruction: str = "") -> str:
    target = project.target_duration_s
    count, length = scene_count(target, scene_length_s)
    rate = str(WORDS_PER_SECOND).replace(".", ",")
    return (f"{project_brief(project)}\n"
            "Angle retenu (matière de travail ; ne reprends pas sa mise en forme markdown) :\n"
            f"<<<\n{angle}\n>>>\n"
            + (f"Consigne de l'utilisateur, à appliquer en priorité : {instruction.strip()}\n" if instruction.strip() else "")
            + style_line(project)
            + "Commence par `bible`, la fiche visuelle de la vidéo, en anglais : pour chaque personnage récurrent (nom, "
            "âge, visage, coiffure, vêtements, signe distinctif), chaque objet ou produit clé, le décor principal, la "
            "palette de couleurs et le style d'image. Si le sujet est une marque ou un produit réel, nomme-le "
            "exactement et décris son apparence reconnaissable (forme, couleurs, logo : emplacement, typographie, "
            "couleurs). Elle sert de référence unique à toutes les scènes.\n"
            f"Puis `references` : au plus {MAX_REFERENCES} éléments RÉCURRENTS dont l'apparence doit rester identique d'une "
            "scène à l'autre (personnage qui revient, produit ou marque réels), chacun avec `id` (court, minuscules, sans "
            "espace, ex. « kroc », « coca_can »), `prompt` : image de référence en anglais, sujet seul sur fond neutre "
            "uni, plein cadre vertical, mêmes mots que la fiche (marque nommée, logo décrit), et `descriptor` : "
            "l'apparence physique de l'élément en anglais, 40 mots au plus, sans décor, fond ni action (le premier "
            "paragraphe de chaque visual_prompt de scène qui l'utilise commence par ce descripteur, mot pour mot). "
            "Aucun élément qui n'apparaît qu'une fois. Dans chaque scène, `reference` = id de l'élément principal "
            "visible dans la scène, ou \"\" s'il n'y en a pas. Le visual_prompt nomme toujours le personnage ou la marque "
            "par son nom (« Ray Kroc », « Coca-Cola »), même quand une référence existe.\n"
            f"Découpe ensuite la vidéo en {count} scènes {length} : la somme des "
            f"duration_s doit faire {target} secondes (à 10 % près).\n"
            f"Voix off en français, au débit d'environ {rate} mots par seconde : "
            f"environ {word_budget(target)} mots au total, et pour chaque scène environ "
            f"{rate} × duration_s mots (ex. {word_budget(4)} mots pour 4 s). "
            "voice_text ne contient que le texte prononcé (ni didascalie, ni markdown, ni numéro de scène). "
            "La première scène est l'accroche : une phrase choc ou une question qui retient le spectateur dès les 2 "
            f"premières secondes. {ENGAGEMENT_RULE}.\n"
            f"visual_prompt est en anglais, pour un générateur texte-vers-vidéo : {VISUAL_PROMPT_GUIDE}.\n"
            "Continuité : les scènes qui se suivent gardent les mêmes personnages, le même décor et la même lumière "
            "(mêmes mots que la fiche), mais changent de cadrage (plan large, moyen, gros plan, plongée, travelling…) "
            "pour ne jamais ressembler à un doublon ; une scène qui prolonge la précédente commence là où celle-ci "
            "s'arrête.\n"
            'Réponds avec {"bible": "fiche visuelle", "references": [{"id": "kroc", "prompt": "image de référence", "descriptor": "apparence physique"}], '
            '"scenes": [{"voice_text": "texte de la voix off", "visual_prompt": "description visuelle en anglais", '
            '"duration_s": 4, "reference": "kroc"}]}.')


STORY_SYSTEM = "Tu es scénariste de vidéos verticales virales. Réponds uniquement en JSON."


def style_line(project: Project) -> str:
    return (f"Style visuel imposé : {style}. Applique-le à la fiche visuelle et à chaque prompt visuel.\n"
            if (style := styles.directive(project.style)) else "")


def story_prompt(project: Project, angle: str, scene_length_s: float | None = None, instruction: str = "") -> str:
    """Passe histoire : les beats (une scène chacun), sans rien de visuel, avec une causalité vérifiable."""
    target = project.target_duration_s
    count, length = scene_count(target, scene_length_s)
    rate = str(WORDS_PER_SECOND).replace(".", ",")
    return (f"{project_brief(project)}\n"
            "Angle retenu (matière de travail ; ne reprends pas sa mise en forme markdown) :\n"
            f"<<<\n{angle}\n>>>\n"
            + (f"Consigne de l'utilisateur, à appliquer en priorité : {instruction.strip()}\n" if instruction.strip() else "")
            + f"Écris l'histoire de la vidéo en {count} beats (un beat = une scène) {length} : la somme des duration_s "
            f"doit faire {target} secondes (à 10 % près).\n"
            "Chaque beat a `summary` (1 à 2 phrases en français : qui fait quoi, quel objet est touché et ce qui change "
            "pour lui), `voice_text` (voix off en français, texte prononcé seulement, au débit d'environ "
            f"{rate} mots par seconde, soit {word_budget(4)} mots pour 4 s), `duration_s` et `continuity` : « continue » "
            "si le beat se passe au même endroit, dans la suite immédiate du précédent (la caméra change de cadrage mais "
            "l'action et le décor continuent), « cut » pour un changement de lieu ou une ellipse ; le premier beat est "
            "toujours « cut ».\n"
            "Causalité : chaque beat découle du précédent. Tout objet introduit est repris dans un beat suivant ou "
            "résolu dans l'un des deux derniers beats (une histoire où un objet annoncé n'a aucune suite est refusée) ; "
            "aucun élément n'apparaît sans avoir été amené. Le premier beat est l'accroche : une phrase choc ou une "
            f"question dès les 2 premières secondes. {ENGAGEMENT_RULE}.\n"
            'Réponds avec {"beats": [{"summary": "...", "voice_text": "...", "duration_s": 4, "continuity": "cut"}]}.')


def inventory_prompt(project: Project, beats: list[dict]) -> str:
    """Passe inventaire : fiche visuelle, éléments suivis et, pour chaque beat, les éléments visibles avec leur état."""
    summaries = json.dumps([{"beat": i, "summary": b["summary"]} for i, b in enumerate(beats, 1)], ensure_ascii=False)
    return (f"{project_brief(project)}\nVoici les beats de l'histoire :\n<<<\n{summaries}\n>>>\n"
            + style_line(project)
            + "Dresse l'inventaire, en anglais. `bible` : style d'image, décor principal et palette de couleurs, 80 mots "
            "au plus, sans décrire les personnages. `elements` : chaque personnage récurrent, chaque accessoire qui "
            "compte dans l'histoire (objet touché, abîmé, déplacé) et chaque lieu, avec `id` (court, minuscules, sans "
            "espace), `kind` (character, prop ou place), `name`, `descriptor` (apparence figée, 40 mots au plus : forme, "
            "matière, couleurs, détails distinctifs, jamais de décor ni d'action ; pour une marque réelle, son nom "
            "exact ; un personnage est un humain ordinaire et original, jamais le visage, le nom ou le sosie d'une "
            "personnalité réelle, politique ou célèbre) et `prompt` (image de référence : sujet seul sur fond neutre uni, plein cadre vertical, mêmes mots "
            "que le descripteur ; vide pour un lieu).\n"
            f"Puis `beats` : exactement {len(beats)} objets, dans l'ordre, chacun avec `elements` : les éléments visibles "
            "dans ce beat, chacun avec son `state` : sa condition physique visible, courte et en anglais (objet : « dry », "
            "« wet with a visible spill », « zipper jammed » ; personnage : tenue ou apparence qui change, « hair messy », "
            "« lipstick smeared on cheek »), jamais l'action en cours, qui est dans `summary`, ni un lieu ; vide si rien "
            "ne change. L'état change quand un événement le modifie et ne revient jamais en arrière sans événement. Tout accessoire est visible dans au moins deux beats, ou dans l'un des deux derniers. Chaque beat a aussi "
            "`speaker` : l'id du personnage qui prononce la voix off de ce beat quand c'est sa réplique ou sa pensée à la "
            "première personne, sinon vide (le narrateur) ; la plupart des beats d'une voix off racontée restent vides.\n"
            'Réponds avec {"bible": "...", "elements": [{"id": "sac", "kind": "prop", "name": "...", "descriptor": "...", '
            '"prompt": "..."}], "beats": [{"elements": [{"id": "sac", "state": "dry"}], "speaker": ""}]}.')


def corrected(prompt: str, answer: str, problems: str, ask: str) -> str:
    """Prompt de la relance ciblée : la demande, la réponse précédente et ses défauts."""
    return (f"{prompt}\n\nTa réponse précédente est à corriger : {problems}.\nRéponse précédente :\n<<<\n"
            f"{answer[:3000]}\n>>>\nCorrige-la : {ask}")


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
    answer = await _ask_llm(ctx, step, STORY_SYSTEM, prompt, STORY_SCHEMA, budget)
    beats, problems = _read_beats(answer, target)
    if beats is not None and not problems:
        return answer, beats, []
    retry = await _ask_llm(ctx, step, STORY_SYSTEM, corrected(
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
    inventory = await _ask_llm(ctx, step, STORY_SYSTEM, inventory_ask, INVENTORY_SCHEMA, budget)
    story = parse_story(answer, inventory, target)
    found = story_problems(story)
    if found:  # une seule relance ciblée de l'inventaire
        retry = await _ask_llm(ctx, step, STORY_SYSTEM, corrected(
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


SCENE_SCHEMA = {"type": "OBJECT", "properties": {"visual_prompt": {"type": "STRING"}}, "required": ["visual_prompt"]}
SCENE_CALLS = 4  # prompts visuels de scènes demandés au LLM en même temps
SCENE_MAX_TOKENS = 1500


def scene_prompt(project: Project, bible: str, beat: dict, present: list[dict], previous: str, index: int,
                 count: int, instruction: str = "") -> str:
    """Prompt visuel d'une scène à partir de son beat : fiche de style, éléments présents avec leur état, scène précédente."""
    looks = "\n".join(f"- {e['name']} : {e['descriptor']}" + (f" ; état dans cette scène : {e['state']}" if e["state"] else "")
                      for e in present)
    return (style_line(project) + (f"Fiche visuelle (style, décor, palette) : {bible}\n" if bible else "")
            + (f"Consigne de l'utilisateur, à appliquer en priorité : {instruction.strip()}\n" if instruction.strip() else "")
            + f"Scène {index} sur {count}, {beat['duration_s']:g} secondes. Ce qui se passe : {beat['summary']}\n"
            f"Voix off de la scène : {beat['voice_text']}\n"
            + (f"Scène précédente : {previous} Cette scène continue la même action avec un autre cadrage.\n" if previous else "")
            + (f"Éléments visibles, avec leur apparence figée et leur état (reprends chaque descripteur mot pour mot, "
               f"état compris) :\n{looks}\n" if looks else "")
            + f"visual_prompt est en anglais, pour un générateur texte-vers-vidéo : {VISUAL_PROMPT_GUIDE}.\n"
            'Réponds avec {"visual_prompt": "..."}.')


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


def reference_look(project: Project) -> str:
    """Style des images de référence : celui du projet, « cinematic » sans style choisi."""
    return styles.directive(project.style) or "cinematic"


def reference_suffix(project: Project) -> str:
    return f"Vertical 9:16, {reference_look(project)}, the subject alone on a plain neutral background."


async def _reference(ctx, project, step, scene_id):
    """Images de référence. Le script liste des éléments récurrents (`references`) : une image par élément (ou celle de
    `reference_id` seulement), au prompt du script ou de `params.prompts[id]`. Sans élément : une image unique du projet,
    d'après la fiche visuelle (anciens projets)."""
    script = (await _step(ctx, project.id, "script")).result
    elements = script.get("references") or []
    provider, model = await reference_choice(step.params, ctx.app_settings)
    image = await ctx.registry.image(provider)

    async def make(prompt: str, ref: str = "") -> int:
        result = await _call(ctx, step, image, model, lambda: image.generate(prompt, model=model),
                             input=langfuse.messages(prompt))
        return (await _store(ctx, project.id, "reference", result, meta={"ref": ref} if ref else None)).id

    if not elements:
        bible = script.get("bible")
        prompt = step.params.get("prompt") or (
            f"{bible}\nVertical 9:16, {reference_look(project)}, consistent style." if bible
            else f"{project.theme}, vertical 9:16, {reference_look(project)}, consistent style")
        ids = [await make(prompt)]
    else:
        wanted = ctx.overrides.get("reference_id")
        todo = [e for e in elements if wanted in (None, e["id"])]
        if not todo:
            raise ProviderError(f"reference: élément inconnu : {wanted}")
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
    data = _extract_json(await _ask_llm(ctx, step, FINAL_SYSTEM, prompt, FINAL_SCHEMA), "final")
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
