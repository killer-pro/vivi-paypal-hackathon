from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import SCENE_FIELDS, STEP_FIELDS, fields
from app.db import get_session
from app.models import Asset, Scene
from app.queue import get_enqueue, publish_event
from app.services import credits
from app.services.flow import ensure_not_running, load_steps, mark_stale, plan_until, script_stale_names, sync_status
from app.services.llm_json import ref_id
from app.services.queue_runs import dispatch_queue, remove_queued, run_or_queue
from app.services.steps import (
    cancel_step,
    lock_project,
    preflight_launch,
    start_autopilot,
    start_reference_after_script,
    steps_and_step,
    stop_autopilot,
)
from app.services.story import MAX_KONTEXT_IMAGES, MAX_REFERENCES_TOTAL, story_result_errors
from app.state import OPTIONAL_STEPS, RERUN_WHEN_STALE, InvalidTransition, dependents, transition

router = APIRouter(prefix="/projects/{project_id}", tags=["steps"])

MAX_VISUAL_PROMPT_CHARS = 4000
MAX_INSTRUCTION_CHARS = 1000
CLIP_CHOICE_DEPENDENTS = ("montage", "final")  # voix et musique ne dépendent pas du clip choisi
VOICE_TEXT_DEPENDENTS = ("voice", *dependents("voice"))  # la voix n'a plus le bon texte
REORDER_DEPENDENTS = CLIP_CHOICE_DEPENDENTS  # idem pour l'ordre : clips et voix sont attachés à leur scène


NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SceneIn(BaseModel):
    id: int | None = None
    voice_text: NonBlank  # sans texte : ni voix ni sous-titre pour la scène
    visual_prompt: NonBlank
    duration_s: float = Field(gt=0)
    reference: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]{0,30}$")] | None = None  # None : inchangée


class StepPatch(BaseModel):
    params: dict | None = None
    result: dict | None = None
    scenes: list[SceneIn] | None = None


class RunIn(BaseModel):
    scene_id: int | None = None
    # Choix ponctuel du générateur vidéo (étape clips) : vaut pour ce lancement seulement, `params` restent inchangés.
    provider: str | None = None
    model: str | None = None
    # Générateur de l'image de départ des scènes (étape clips) pour ce lancement ; sinon réglage `start_image_provider`.
    start_image: Literal["comfyui", "gemini"] | None = None
    # Clips : chaque scène repart de l'image de départ de son clip choisi, sans nouvelle composition (changer de modèle
    # vidéo ou lip-sync en gardant l'image validée, sans repayer Kontext). Faute d'image gardée, composition habituelle.
    reuse_start_image: bool = False
    # Reprise d'une étape par scène en échec : seules les scènes manquantes sont générées (clips, voix).
    resume: bool = False
    # Étape par scène, quel que soit son état : ne génère que les scènes qui n'ont encore aucun clip / aucune voix.
    only_missing: bool = False
    # Nouveau prompt visuel de la scène `scene_id` (clips) : enregistré sur la scène, puis clip régénéré.
    visual_prompt: NonBlank | None = Field(None, max_length=MAX_VISUAL_PROMPT_CHARS)
    # Consigne de l'utilisateur pour (re)générer le script : valable pour ce lancement seulement (étape script).
    instruction: NonBlank | None = Field(None, max_length=MAX_INSTRUCTION_CHARS)
    # Un seul élément de référence à (re)générer (étape reference).
    reference_id: str | None = Field(None, pattern=r"^[a-z0-9_-]{1,30}$")
    # Paramètres de l'étape reference (prompts par élément, générateur) appliqués au démarrage, y compris depuis la file.
    params: dict | None = None

    def overrides(self) -> dict:
        return {k: v for k, v in (("provider", self.provider), ("model", self.model),
                                  ("instruction", self.instruction), ("reference_id", self.reference_id),
                                  ("start_image", self.start_image), ("reuse_start_image", self.reuse_start_image))
                if v}


class SelectClipIn(BaseModel):
    asset_id: int


class SceneReferenceIn(BaseModel):
    reference: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]{0,30}$")]  # "" : aucune
    # Éléments dont l'image part avec le clip, principale comprise (`None` : inchangés), au plus `MAX_KONTEXT_IMAGES`.
    elements: list[Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]{1,30}$")]] | None = None


class SceneContinuityIn(BaseModel):
    continuity: Literal["cut", "continue"]


class SceneLipsyncIn(BaseModel):
    lipsync: bool


class ReferenceElementIn(BaseModel):
    name: NonBlank = Field(max_length=60)  # « Ouvrier de l'Égypte ancienne » → id `ouvrier_de_l_gypte_ancienne`
    prompt: str = Field("", max_length=MAX_VISUAL_PROMPT_CHARS)  # vide : élément ajouté avec une image importée
    # Élément de l'histoire promu en référence : garde son id (celui des scènes) et son descripteur.
    story_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]{1,30}$")] | None = None


class VoiceTextIn(BaseModel):
    voice_text: NonBlank


class ReorderIn(BaseModel):
    scene_ids: list[int]


async def replace_scenes(session: AsyncSession, project_id: int, scenes: list[SceneIn]) -> None:
    """Met à jour les scènes par `id` (le clip sélectionné est conservé), crée les nouvelles, supprime les absentes."""
    existing: dict[int | None, Scene] = {s.id: s for s in (await session.scalars(select(Scene).where(Scene.project_id == project_id))).all()}
    kept = {s.id for s in scenes}
    for scene_id, scene in existing.items():
        if scene_id not in kept:
            await session.delete(scene)
    for position, s in enumerate(scenes, 1):
        scene = existing.get(s.id) or Scene(project_id=project_id)
        scene.position, scene.voice_text, scene.visual_prompt, scene.duration_s = (
            position, s.voice_text, s.visual_prompt, s.duration_s)
        if s.reference is not None:
            scene.reference = s.reference
        session.add(scene)


@router.patch("/steps/{name}")
async def edit_step(project_id: int, name: str, body: StepPatch, session: AsyncSession = Depends(get_session)) -> dict:
    if body.scenes is not None and name != "script":
        raise HTTPException(422, "Les scènes ne s'éditent que sur l'étape script")
    steps, step = await steps_and_step(session, project_id, name)
    if step.status == "running":
        raise HTTPException(409, "Étape en cours, attendez la fin de la génération")
    ensure_not_running(steps, dependents(name))
    if name == "story" and body.result and (errors := story_result_errors(body.result)):
        raise HTTPException(422, " ; ".join(errors))
    result_before = step.result
    if body.params is not None:
        step.params = body.params
    if body.result is not None:
        step.result = body.result
    if body.scenes is not None:
        await replace_scenes(session, project_id, body.scenes)
    if name == "final" and body.result is not None:
        # Les métadonnées publiées vivent dans le projet (écrites par l'exécuteur final) : une seule source.
        (await lock_project(session, project_id)).replace_metadata(body.result)
    mark_stale(steps, script_stale_names(result_before, step.result) if name == "script" else dependents(name))
    await sync_status(session, project_id, steps)
    await session.commit()
    return fields(step, STEP_FIELDS)


def _check_run_options(name: str, body: RunIn) -> None:
    """422 si une option du lancement ne s'applique pas à l'étape (partagé par le lancement et le prix)."""
    if (body.provider or body.model) and name != "clips":
        raise HTTPException(422, "Provider et modèle ne se choisissent au lancement que pour l'étape clips")
    if body.reuse_start_image and name != "clips":
        raise HTTPException(422, "La reprise de l'image de départ ne s'applique qu'à l'étape clips")
    if body.start_image and name != "clips":
        raise HTTPException(422, "Le générateur d'image de départ ne se choisit qu'au lancement de l'étape clips")
    if body.instruction and name not in ("story", "script"):
        raise HTTPException(422, "La consigne ne s'applique qu'aux étapes story et script")
    if body.reference_id and name != "reference":
        raise HTTPException(422, "L'élément de référence ne se choisit que pour l'étape reference")
    if body.params and name != "reference":
        raise HTTPException(422, "Les paramètres ne se passent au lancement que pour l'étape reference")


@router.post("/steps/{name}/run", status_code=202)
async def run(project_id: int, name: str, body: RunIn, session: AsyncSession = Depends(get_session),
              enqueue=Depends(get_enqueue)) -> JSONResponse:
    """Lance l'étape, ou la met en file d'attente si une génération la bloque (`{"queued": true}`)."""
    _check_run_options(name, body)
    queued = await run_or_queue(session, project_id, name, enqueue, body.scene_id, body.overrides(), resume=body.resume,
                                only_missing=body.only_missing, visual_prompt=body.visual_prompt, params=body.params)
    return JSONResponse({"queued": queued}, status_code=202)


@router.post("/steps/{name}/price")
async def price(project_id: int, name: str, body: RunIn, session: AsyncSession = Depends(get_session)) -> dict:
    """Prix en crédits du lancement `run` de mêmes options, sans rien lancer ni réserver : le compte facturé est le
    propriétaire du projet (compte administrateur : illimité). Mêmes refus que le lancement (état, modèle, reprise)."""
    _check_run_options(name, body)
    try:
        launch = await preflight_launch(session, project_id, name, body.scene_id, body.overrides(), resume=body.resume,
                                        only_missing=body.only_missing, visual_prompt=body.visual_prompt,
                                        params=body.params)
        if launch.unlimited:
            return {"credits": 0, "balance": None, "sufficient": True, "unlimited": True}
        available = (await credits.balance(session, launch.owner.id)).total
        return {"credits": launch.quote.credits, "balance": available, "sufficient": available >= launch.quote.credits,
                "unlimited": False}
    finally:
        await session.rollback()  # libère le verrou du projet : aucun effet de bord


@router.post("/steps/{name}/cancel", status_code=202)
async def cancel(project_id: int, name: str, session: AsyncSession = Depends(get_session),
                 enqueue=Depends(get_enqueue)) -> Response:
    """Arrête la génération en cours (clips, voix…) : l'étape passe en échec « Arrêtée par l'utilisateur », les clips ou
    voix déjà produits sont gardés, et le worker interrompt l'appel en cours (ComfyUI : le clip en cours est annulé).
    La génération suivante de la file démarre."""
    await cancel_step(session, project_id, name)
    await dispatch_queue(session, project_id, enqueue, publish_event)
    return Response(status_code=202)


@router.delete("/queue/{queued_id}", status_code=204)
async def unqueue(project_id: int, queued_id: int, session: AsyncSession = Depends(get_session)) -> Response:
    """Retire une génération de la file d'attente avant son départ."""
    await remove_queued(session, project_id, queued_id)
    return Response(status_code=204)


@router.post("/steps/{name}/approve")
async def approve(project_id: int, name: str, session: AsyncSession = Depends(get_session),
                  enqueue=Depends(get_enqueue)) -> dict:
    """Valide l'étape. Script : les images de référence qui n'existent pas encore (`pending`/`stale`) sont lancées
    (job enfilé, comme `/run`) ; un refus (budget…) laisse l'étape lançable à la main sans faire échouer la
    validation."""
    steps, step = await steps_and_step(session, project_id, name)
    if name in OPTIONAL_STEPS and step.status == "pending":
        step.status = "approved"  # étape optionnelle ignorée (hors machine à états)
    elif name in RERUN_WHEN_STALE and step.status == "stale":
        raise HTTPException(409, "Le montage ne correspond plus aux clips ou voix choisis : relancez-le avant de le valider")
    else:
        try:
            step.status = transition(step.status, "approved")
        except InvalidTransition:
            raise HTTPException(409, f"Validation impossible depuis le statut « {step.status} »") from None
    if name == "clips":  # les références n'ont pas de bouton « Valider » : les clips qui s'en servent les entérinent
        reference = next(s for s in steps if s.name == "reference")
        if reference.status in ("awaiting_validation", "stale"):
            reference.status = "approved"
    await sync_status(session, project_id, steps)
    await session.commit()
    result = fields(step, STEP_FIELDS)
    if name == "script":
        await start_reference_after_script(session, project_id, enqueue, publish_event)
    return result


@router.post("/scenes/{scene_id}/select-clip")
async def select_clip(project_id: int, scene_id: int, body: SelectClipIn,
                      session: AsyncSession = Depends(get_session)) -> dict:
    scene = await session.get(Scene, scene_id)
    if scene is None or scene.project_id != project_id:
        raise HTTPException(404, "Scène introuvable")
    asset = await session.get(Asset, body.asset_id)
    if asset is None or asset.kind != "clip" or asset.scene_id != scene.id:
        raise HTTPException(404, "Clip introuvable pour cette scène")
    steps = await load_steps(session, [project_id])
    ensure_not_running(steps, ("clips", "montage"))
    scene.selected_clip_asset_id = asset.id
    mark_stale(steps, CLIP_CHOICE_DEPENDENTS)
    await sync_status(session, project_id, steps)
    await session.commit()
    return fields(scene, SCENE_FIELDS)


@router.post("/references", status_code=201)
async def add_reference_element(project_id: int, body: ReferenceElementIn, session: AsyncSession = Depends(get_session)) -> dict:
    """Ajoute un élément récurrent (personnage, produit) à ceux du script, en plus de ceux que l'IA a listés (ou un élément de l'histoire sans image, `story_id`). Rien n'est
    périmé : l'élément n'a pas d'image tant qu'on ne l'a pas générée ou importée. Un nouveau script remplace la liste."""
    script = (await steps_and_step(session, project_id, "script"))[1]
    if script.status == "running":
        raise HTTPException(409, "Script en cours, attendez la fin de la génération")
    if not script.result:
        raise HTTPException(409, "Le script n'est pas encore généré")
    elements = list(script.result.get("references") or [])
    story_element = None
    if body.story_id:
        story = (await steps_and_step(session, project_id, "story"))[1].result or {}
        story_element = next((e for e in story.get("elements") or [] if e.get("id") == body.story_id), None)
        if story_element is None:
            raise HTTPException(422, f"Élément de l'histoire inconnu : {body.story_id}")
    rid = body.story_id or ref_id(body.name)
    if not rid:
        raise HTTPException(422, "Nom inexploitable : utilisez des lettres ou des chiffres")
    if any(e["id"] == rid for e in elements):
        raise HTTPException(409, f"L'élément « {rid} » existe déjà")
    if len(elements) >= MAX_REFERENCES_TOTAL:
        raise HTTPException(409, f"{MAX_REFERENCES_TOTAL} éléments au plus")
    descriptor = (story_element or {}).get("descriptor")
    element = {"id": rid, "prompt": body.prompt.strip() or body.name, **({"descriptor": descriptor} if descriptor else {})}
    script.result = {**script.result, "references": [*elements, element]}
    await session.commit()
    return element


@router.put("/scenes/{scene_id}/voice-text")
async def set_scene_voice_text(project_id: int, scene_id: int, body: VoiceTextIn,
                               session: AsyncSession = Depends(get_session)) -> dict:
    """Nouveau texte prononcé (et sous-titré) de la scène. La voix déjà produite est conservée mais périmée, ainsi que le
    montage et le rendu final : il faut la régénérer pour qu'elle dise le nouveau texte."""
    scene = await session.get(Scene, scene_id)
    if scene is None or scene.project_id != project_id:
        raise HTTPException(404, "Scène introuvable")
    steps = await load_steps(session, [project_id])
    ensure_not_running(steps, ("voice", "montage"))
    if scene.voice_text != body.voice_text:
        scene.voice_text = body.voice_text
        mark_stale(steps, VOICE_TEXT_DEPENDENTS)
        await sync_status(session, project_id, steps)
    await session.commit()
    return fields(scene, SCENE_FIELDS)


@router.put("/scenes/{scene_id}/reference")
async def set_scene_reference(project_id: int, scene_id: int, body: SceneReferenceIn,
                              session: AsyncSession = Depends(get_session)) -> dict:
    """Élément de référence dont l'image sert au clip de la scène (`""` : aucun) et, avec `elements`, la liste complète des
    éléments dont l'image part avec le clip, principale comprise (leur `state` est conservé ; les éléments de la scène sans
    référence ne changent pas). Le clip déjà produit n'est pas touché :
    il faut le régénérer. Autorisé pendant les clips : le choix vaut pour les scènes qui n'ont pas encore démarré."""
    scene = await session.get(Scene, scene_id)
    if scene is None or scene.project_id != project_id:
        raise HTTPException(404, "Scène introuvable")
    script = (await steps_and_step(session, project_id, "script"))[1]
    known = {r["id"] for r in (script.result or {}).get("references") or []}
    elements = list(dict.fromkeys(body.elements)) if body.elements is not None else None
    if unknown := [i for i in [body.reference, *(elements or [])] if i and i not in known]:
        raise HTTPException(422, f"Élément de référence inconnu : {unknown[0]}")
    if elements is not None:
        if len({*elements, body.reference} - {""}) > MAX_KONTEXT_IMAGES:
            raise HTTPException(422, f"{MAX_KONTEXT_IMAGES} images au plus par scène")
        states = {e["id"]: e.get("state", "") for e in scene.elements}
        hidden = [e for e in scene.elements if e["id"] not in known]  # visibles dans la scène mais sans image de référence
        scene.elements = [*hidden, *({"id": i, "state": states.get(i, "")} for i in elements)]
    scene.reference = body.reference
    await session.commit()
    return fields(scene, SCENE_FIELDS)


@router.put("/scenes/{scene_id}/continuity")
async def set_scene_continuity(project_id: int, scene_id: int, body: SceneContinuityIn,
                               session: AsyncSession = Depends(get_session)) -> dict:
    """`continue` : la première image du clip de la scène est la dernière image du clip de la scène précédente (les
    clips sont alors générés dans l'ordre) ; `cut` : elle part de son image de référence. Le clip déjà produit n'est pas
    touché : il faut le régénérer. La première scène n'a pas de scène précédente (422)."""
    scene = await session.get(Scene, scene_id)
    if scene is None or scene.project_id != project_id:
        raise HTTPException(404, "Scène introuvable")
    if body.continuity == "continue" and scene.position == min(
            await session.scalars(select(Scene.position).where(Scene.project_id == project_id))):
        raise HTTPException(422, "La première scène n'a pas de scène précédente")
    scene.continuity = body.continuity
    await session.commit()
    return fields(scene, SCENE_FIELDS)


@router.put("/scenes/{scene_id}/lipsync")
async def set_scene_lipsync(project_id: int, scene_id: int, body: SceneLipsyncIn,
                            session: AsyncSession = Depends(get_session)) -> dict:
    """Avatar parlant : `false` sort la scène du lip-sync (clip animé ordinaire, voix hors champ) même si le personnage qui
    parle y est visible. Le clip déjà produit n'est pas touché : il faut le régénérer."""
    scene = await session.get(Scene, scene_id)
    if scene is None or scene.project_id != project_id:
        raise HTTPException(404, "Scène introuvable")
    scene.lipsync = body.lipsync
    await session.commit()
    return fields(scene, SCENE_FIELDS)


@router.post("/scenes/reorder")
async def reorder_scenes(project_id: int, body: ReorderIn, session: AsyncSession = Depends(get_session)) -> list[dict]:
    """Nouvel ordre des scènes (liste complète des ids). Clips et voix sont attachés à leur scène et suivent : seuls le
    montage et le rendu final sont périmés."""
    await lock_project(session, project_id)  # 404 si le projet n'existe pas
    scenes = {s.id: s for s in (await session.scalars(select(Scene).where(Scene.project_id == project_id))).all()}
    if sorted(body.scene_ids) != sorted(scenes):
        raise HTTPException(422, "La liste doit contenir chaque scène du projet exactement une fois")
    steps = await load_steps(session, [project_id])
    ensure_not_running(steps, ("clips", "voice", "montage"))
    for position, scene_id in enumerate(body.scene_ids, 1):
        scenes[scene_id].position = position
    mark_stale(steps, REORDER_DEPENDENTS)
    await sync_status(session, project_id, steps)
    await session.commit()
    return [fields(scenes[i], SCENE_FIELDS) for i in body.scene_ids]


@router.post("/autopilot", status_code=202)
async def autopilot_start(project_id: int, session: AsyncSession = Depends(get_session),
                          enqueue=Depends(get_enqueue)) -> Response:
    """Mode automatique : lance `idea`, le worker enchaîne et valide les étapes jusqu'au rendu final."""
    await start_autopilot(session, project_id, enqueue)
    return Response(status_code=202)


@router.post("/plan/generate", status_code=202)
async def plan_generate(project_id: int, session: AsyncSession = Depends(get_session),
                        enqueue=Depends(get_enqueue)) -> Response:
    """Génère le plan : lance `idea` puis `story` et s'arrête là, la story restant à relire ; un projet existant (story
    vide) va jusqu'à `script`, à valider."""
    until = plan_until(await load_steps(session, [project_id]))
    await start_autopilot(session, project_id, enqueue, until=until)
    return Response(status_code=202)


@router.delete("/autopilot", status_code=204)
async def autopilot_stop(project_id: int, session: AsyncSession = Depends(get_session)) -> Response:
    """Arrête l'enchaînement : l'étape en cours finit, la suite n'est pas lancée."""
    await lock_project(session, project_id)  # 404 si le projet n'existe pas
    await stop_autopilot(session, [project_id])
    return Response(status_code=204)
