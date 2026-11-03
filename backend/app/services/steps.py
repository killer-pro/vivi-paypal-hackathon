"""Lancement d'une étape et mode automatique (autopilot), partagés par l'API et le worker.

Toute action qui lance une étape ou change le drapeau autopilot verrouille d'abord la ligne du projet
(`SELECT … FOR UPDATE`) : lancements, chaînage du worker et arrêt de l'autopilot sont ainsi sérialisés par projet.
Les refus sont des `HTTPException` (409/404/503) : l'API les renvoie tels quels, le worker arrête l'autopilot.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import AppSettings
from app.models import AUTOPILOT_UNTIL, Asset, CreditReservation, MusicTrack, Project, Scene, Step, User
from app.providers.gemini import estimate_image_cost
from app.providers.registry import ProviderRegistry
from app.services import access, credits
from app.services.access import SubscriptionRequired
from app.services.budget import PAID_STEPS, BudgetExceeded, clip_scene_costs_usd, ensure_within_budget
from app.services.credits import CreditsRefused
from app.services.flow import (
    COMPLETED,
    RUN_ASSET_KIND,
    StepBusy,
    done_in_run,
    ensure_not_running,
    latest_by_scene,
    load_steps,
    mark_stale,
    scene_run_id,
    sync_status,
)
from app.services.pipeline import clip_model, clip_provider_name, job_timeout, reference_choice, start_image_provider
from app.services.pricing import Pricing, load_pricing
from app.services.video_models import ModelRefused, ensure_clip_model_usable, ensure_image_model_usable
from app.state import OPTIONAL_STEPS, STEP_NAMES, can_start, dependents, downstream

# Libellés du registre des crédits (mêmes noms que l'admin).
STEP_REASONS = {"idea": "l'idée", "story": "l'histoire", "script": "le script", "reference": "les images de référence",
                "clips": "les clips", "voice": "les voix", "final": "les métadonnées"}
Enqueue = Callable[..., Awaitable[None]]
Publish = Callable[[dict], Awaitable[None]]


async def lock_project(session: AsyncSession, project_id: int) -> Project:
    """Projet relu et verrouillé jusqu'au prochain commit ; 404 s'il n'existe pas."""
    project = await session.get(Project, project_id, with_for_update=True, populate_existing=True)
    if project is None:
        raise HTTPException(404, "Projet introuvable")
    return project


async def steps_and_step(session: AsyncSession, project_id: int, name: str) -> tuple[list[Step], Step]:
    if name not in STEP_NAMES:
        raise HTTPException(404, f"Étape inconnue : {name}")
    steps = await load_steps(session, [project_id])
    if not steps:
        raise HTTPException(404, "Projet introuvable")
    return steps, next(s for s in steps if s.name == name)


async def claim_step(session: AsyncSession, project_id: int, name: str, run_id: str | None = None) -> bool:
    """Passage atomique à `running` : de deux requêtes concurrentes, une seule obtient la ligne. `run_id` identifie le
    lancement (complet, pour une étape par scène) : voir `Step.run_id`."""
    res = await session.execute(
        update(Step).where(Step.project_id == project_id, Step.name == name, Step.status != "running")
        .values(status="running", error=None, run_id=run_id).returning(Step.id))
    await session.commit()
    return res.first() is not None


async def _check_clips(session: AsyncSession, app_settings: AppSettings, owner: User, project_id: int, params: dict,
                       scene_id: int | None, skip_scene_ids: frozenset[int],
                       pricing: Pricing | None) -> tuple[str, dict[int, float]]:
    """Provider vidéo du lancement des clips et coût de revient de chaque scène qu'il va générer (les autres étapes
    coûtent quelques centimes) ; ComfyUI est chiffré au forfait de `pricing` s'il est donné. `ModelRefused` (400/409) si
    le modèle est inconnu ou indisponible."""
    provider, model = await clip_provider_name(params, app_settings), await clip_model(params, app_settings)
    await access.require(app_settings, owner, "profile", model)  # profil réservé à l'abonnement : 403 avant tout le reste
    async with ProviderRegistry(app_settings) as registry:
        has_reference = bool(await session.scalar(
            select(func.count(Asset.id)).where(Asset.project_id == project_id, Asset.kind == "reference")))
        await ensure_clip_model_usable(registry, provider, model, has_reference=has_reference)
        image_usd = 0.0
        if has_reference and await start_image_provider(params, app_settings, provider) == "gemini":
            image_model = await app_settings.get("gemini_image_model")  # clé manquante : 409 avant de réclamer l'étape
            await ensure_image_model_usable(registry, "gemini", image_model)
            image_usd = estimate_image_cost(image_model)
        return provider, await clip_scene_costs_usd(session, registry, project_id, provider, model, scene_id,
                                                    skip_scene_ids, image_usd, pricing)


async def _check_reference(app_settings: AppSettings, params: dict) -> None:
    """Modèle d'image de l'étape reference utilisable : `ModelRefused` (400 inconnu, 409 indisponible, ex. clé Gemini
    ou fal manquante) avant de réclamer l'étape, plutôt qu'un échec tardif dans le worker."""
    provider, model = await reference_choice(params, app_settings)
    async with ProviderRegistry(app_settings) as registry:
        await ensure_image_model_usable(registry, provider, model)


async def _scene_to_reprompt(session: AsyncSession, project_id: int, name: str, scene_id: int | None,
                             visual_prompt: str | None) -> Scene | None:
    """Scène dont le prompt visuel change au lancement ; 422 si le nouveau prompt ne s'applique pas, 404 si la scène
    n'est pas au projet."""
    if visual_prompt is None:
        return None
    if name != "clips" or scene_id is None:
        raise HTTPException(422, "Un nouveau prompt visuel ne se donne que pour une scène de l'étape clips")
    scene = await session.get(Scene, scene_id)
    if scene is None or scene.project_id != project_id:
        raise HTTPException(404, "Scène introuvable")
    return scene


async def _ensure_previous_clip(session: AsyncSession, project_id: int, name: str, scene_id: int | None) -> None:
    """409 si la scène enchaînée (`continue`) qu'on régénère seule part du clip d'une scène précédente qui n'existe pas
    encore : sa première image serait celle de l'image de référence, pas la dernière image du clip précédent."""
    if name != "clips" or scene_id is None:
        return
    scenes = list((await session.scalars(select(Scene).where(Scene.project_id == project_id).order_by(Scene.position))).all())
    index = next((i for i, s in enumerate(scenes) if s.id == scene_id), None)
    if index and scenes[index].continuity == "continue" and scenes[index - 1].selected_clip_asset_id is None:
        raise HTTPException(409, f"Générez d'abord le clip de la scène {scenes[index - 1].position} : la scène "
                                 f"{scenes[index].position} part de sa dernière image")


async def _scenes_to_skip(session: AsyncSession, project_id: int, step: Step, scene_id: int | None, resume: bool,
                          only_missing: bool) -> dict[int, int]:
    """Scènes que le lancement ne régénère pas : {scène: son dernier asset}. Vide hors reprise ; 409 (ou 422) si la
    reprise demandée ne s'applique pas."""
    if not (resume or only_missing):
        return {}
    if resume and only_missing:
        raise HTTPException(422, "Choisissez la reprise du dernier lancement ou les scènes manquantes, pas les deux")
    if step.name not in RUN_ASSET_KIND or scene_id is not None:
        raise HTTPException(422, "La reprise concerne une étape par scène (clips, voix), pour toutes les scènes")
    scene_ids = set((await session.scalars(select(Scene.id).where(Scene.project_id == project_id))).all())
    if resume:
        if step.status != "failed":
            raise HTTPException(409, "Rien à reprendre : l'étape n'est pas en échec")
        produced = set(await done_in_run(session, project_id, step.name, step.run_id)) & scene_ids
        if not produced:
            raise HTTPException(409, "Rien à reprendre : le dernier lancement n'a produit aucune scène")
        skip = produced
    else:
        skip = set(await latest_by_scene(session, project_id, RUN_ASSET_KIND[step.name], scene_ids))
        if skip == scene_ids:
            raise HTTPException(409, "Aucune scène manquante")
    return await latest_by_scene(session, project_id, RUN_ASSET_KIND[step.name], skip)


@dataclass
class Quote:
    """Prix en crédits d'un lancement, calculé une seule fois : annoncé (`/price`) puis réservé (`launch_step`)."""
    credits: int = 0
    scene_prices: dict[int, int] = field(default_factory=dict)  # étapes par scène : crédits de chaque scène à générer


@dataclass
class Launch:
    """Lancement validé, sans aucun effet de bord : ce que `launch_step` exécute."""
    project: Project
    owner: User
    steps: list[Step]
    step: Step
    scene: Scene | None
    overrides: dict | None
    done: dict[int, int]
    provider: str | None
    quote: Quote

    @property
    def unlimited(self) -> bool:
        return self.owner.is_admin


async def _quote(session: AsyncSession, pricing: Pricing, project_id: int, name: str, scene_id: int | None,
                 skip: frozenset[int], clip_costs_usd: dict[int, float]) -> Quote:
    """Prix du lancement : clips et voix par scène à générer, les autres étapes au forfait, musique et montage gratuits."""
    if name == "clips":
        prices = {sid: pricing.clip_credits(cost) for sid, cost in clip_costs_usd.items()}
        return Quote(sum(prices.values()), prices)
    if name == "voice":
        query = select(Scene.id).where(Scene.project_id == project_id, Scene.id.not_in(skip))
        if scene_id is not None:
            query = query.where(Scene.id == scene_id)
        prices = {sid: pricing.action_credits("voice") for sid in (await session.scalars(query)).all()}
        return Quote(sum(prices.values()), prices)
    return Quote(pricing.action_credits(name) if name in pricing.flat_usd else 0)


async def preflight_launch(session: AsyncSession, project_id: int, name: str, scene_id: int | None = None,
                           overrides: dict | None = None, *, resume: bool = False, only_missing: bool = False,
                           visual_prompt: str | None = None, params: dict | None = None) -> Launch:
    """Toute la validation d'un lancement sans effet de bord (le projet est seulement verrouillé) : état des étapes,
    modèle utilisable, reprise, budget en dollars (projets de l'admin) et devis en crédits (projets des clients).
    `launch_step` et l'endpoint de prix l'appellent : le prix annoncé est donc le prix réservé."""
    project = await lock_project(session, project_id)
    steps, step = await steps_and_step(session, project_id, name)
    scene = await _scene_to_reprompt(session, project_id, name, scene_id, visual_prompt)  # 422/404 avant les 409 d'état
    await _ensure_previous_clip(session, project_id, name, scene_id)
    if not can_start({s.name: s.status for s in steps}, name):
        raise HTTPException(409, "Étape précédente non validée")
    # clips attend aussi la fin des images de référence, sinon ils seraient produits sans elles (lues au démarrage)
    ensure_not_running(steps, [name, *dependents(name), *(["reference"] if name == "clips" else [])])
    done = await _scenes_to_skip(session, project_id, step, scene_id, resume, only_missing)
    if done:  # scènes ignorées : l'exécuteur reprend leur dernier asset tel quel
        overrides = {**(overrides or {}), "skip_scenes": sorted(done)}
    if visual_prompt is not None:  # nouveau prompt voulu : le nouveau clip remplace le clip choisi de la scène
        overrides = {**(overrides or {}), "select_new": True}
    app_settings = AppSettings(session)
    owner = await session.get(User, project.user_id)
    assert owner is not None
    if name == "reference":
        await access.require(app_settings, owner, "reference")
    pricing = None if owner.is_admin else await load_pricing(app_settings)
    provider: str | None = None
    clip_costs: dict[int, float] = {}
    if name == "clips":
        provider, clip_costs = await _check_clips(session, app_settings, owner, project_id, {**step.params, **(overrides or {})},
                                                  scene_id, frozenset(done), pricing)
    elif name == "reference":
        await _check_reference(app_settings, {**step.params, **(params or {})})
    quote = Quote()
    if pricing is None:  # budget en dollars : projets de l'admin seulement ; pour un client, les crédits font office de budget
        if name in PAID_STEPS:
            await ensure_within_budget(session, project_id, app_settings, sum(clip_costs.values()))
    else:
        quote = await _quote(session, pricing, project_id, name, scene_id, frozenset(done), clip_costs)
    return Launch(project, owner, steps, step, scene, overrides, done, provider, quote)


async def _reserve_credits(session: AsyncSession, launch: Launch, name: str, run_id: str | None) -> CreditReservation | None:
    """Retient le prix du lancement sur le compte du propriétaire du projet (admin : rien). Pour les clips, refuse
    aussi un lancement si le compte en génère déjà sur un autre projet (verrou du solde pris avant de compter)."""
    owner = launch.owner
    if launch.unlimited:
        return None
    if name == "clips":
        await credits.lock_account(session, owner.id)
        running = await session.scalar(
            select(func.count()).select_from(Step).join(Project, Project.id == Step.project_id)
            .where(Project.user_id == owner.id, Step.name == "clips", Step.status == "running",
                   Step.project_id != launch.project.id))
        if (running or 0) >= int(await AppSettings(session).get("credits_max_parallel_clips")):
            await session.rollback()
            raise credits.ParallelLimit()
    if launch.quote.credits == 0:
        return None
    return await credits.reserve(session, owner.id, launch.quote.credits, project_id=launch.project.id, step=name,
                                 run_id=run_id, scene_prices=launch.quote.scene_prices, reason=f"Génération : {STEP_REASONS.get(name, name)}")


async def launch_step(session: AsyncSession, project_id: int, name: str, enqueue: Enqueue,
                      scene_id: int | None = None, overrides: dict | None = None, *, resume: bool = False,
                      only_missing: bool = False, visual_prompt: str | None = None,
                      params: dict | None = None) -> None:
    """Lance une étape : étape précédente validée, aval à l'arrêt, crédits réservés (projets des clients), passage
    atomique à `running`, aval produit périmé, job enfilé avec un timeout dimensionné. File indisponible : l'étape passe
    en `failed` (relançable), les crédits sont rendus et l'autopilot s'arrête (503).
    - `resume` : reprend une étape par scène (clips, voix) en échec en ne générant que les scènes que son dernier
      lancement complet n'avait pas produites (409 s'il n'y en a aucune à reprendre) ;
    - `only_missing` : étape par scène dans n'importe quel état, ne génère que les scènes sans aucun asset du type
      (409 s'il n'en manque aucune) ;
    - `visual_prompt` : nouveau prompt visuel de la scène `scene_id`, enregistré au lancement (clips seulement) ;
    - `params` : paramètres fusionnés à ceux de l'étape au démarrage (reference : prompts, générateur). Ils voyagent avec
      la demande, donc aussi quand elle attend en file pendant que l'étape tourne (un `PATCH` serait refusé).
    Clips (modèle vidéo) et reference (modèle d'image) : modèle inconnu (400) ou indisponible (409, raison de sa carte)
    refusé avant tout job enfilé. Crédits insuffisants : 409 (`CreditsRefused`) avant tout job enfilé."""
    launch = await preflight_launch(session, project_id, name, scene_id, overrides, resume=resume,
                                    only_missing=only_missing, visual_prompt=visual_prompt, params=params)
    project, step, steps, overrides, done = launch.project, launch.step, launch.steps, launch.overrides, launch.done
    # Lancement complet : identifiant repris par « Reprendre ». Une seule scène : « scene:<id> », pour que « Relancer »
    # après un échec ne refasse que cette scène.
    run_id = None
    if name in RUN_ASSET_KIND:
        run_id = uuid4().hex if scene_id is None else scene_run_id(scene_id)
    reservation = await _reserve_credits(session, launch, name, run_id)
    if not await claim_step(session, project_id, name, run_id):  # commit : la réservation est écrite, puis rendue
        if reservation:
            await credits.refund_all(session, reservation)
            await session.commit()
        raise StepBusy("Étape déjà en cours")
    if params:
        step.params = {**step.params, **params}
    if launch.scene is not None and visual_prompt is not None:
        launch.scene.visual_prompt = visual_prompt
    mark_stale(steps, dependents(name))
    await sync_status(session, project_id, steps)
    await session.commit()
    total = scene_id and 1 or await session.scalar(select(func.count()).select_from(Scene).where(Scene.project_id == project_id)) or 0
    try:
        await enqueue(project_id, name, scene_id, overrides or None,
                      timeout=job_timeout(name, max(total - len(done), 1), launch.provider))
    except Exception as e:  # sans job, l'étape resterait `running` (et bloquée) indéfiniment
        await lock_project(session, project_id)
        step.status, step.error = "failed", f"File d'attente indisponible : {e}"
        project.autopilot = False
        if reservation:
            await credits.refund_all(session, reservation)
        await session.commit()
        raise HTTPException(503, step.error) from e


STOPPED_BY_USER = "Arrêtée par l'utilisateur"


async def cancel_step(session: AsyncSession, project_id: int, name: str) -> None:
    """Arrête une étape en cours : elle passe en `failed` (« Arrêtée par l'utilisateur ») et l'autopilot s'arrête ; ce
    qui est déjà produit est conservé (clips et voix se reprennent). Le worker s'en aperçoit (`run_step_job`, quelques
    secondes), interrompt l'appel en cours chez le provider et n'enregistre plus rien. 409 si l'étape ne tourne pas."""
    project = await lock_project(session, project_id)
    steps, step = await steps_and_step(session, project_id, name)
    if step.status != "running":
        raise HTTPException(409, "Cette étape n'est pas en cours")
    step.status, step.error = "failed", STOPPED_BY_USER
    project.autopilot = False
    await credits.close_for_step(session, project_id, name, completed=False)  # les scènes déjà produites restent facturées
    await sync_status(session, project_id, steps)
    await session.commit()


async def start_autopilot(session: AsyncSession, project_id: int, enqueue: Enqueue, until: str | None = None) -> None:
    """Active l'autopilot et lance `idea` ; 409 si une étape du projet tourne. `until` : étape après laquelle il
    s'arrête, sans la valider."""
    project = await lock_project(session, project_id)
    steps = await load_steps(session, [project_id])
    ensure_not_running(steps, STEP_NAMES)
    project.autopilot = True  # validé avec le passage d'`idea` à `running` (même transaction)
    if until:
        project.metadata_json = {**project.metadata_json, AUTOPILOT_UNTIL: until}
    await session.flush()
    await launch_step(session, project_id, "idea", enqueue)


async def stop_autopilot(session: AsyncSession, project_ids) -> None:
    """Coupe l'autopilot des projets (l'étape en cours finit, la suite n'est pas lancée) ; commit."""
    for project_id in sorted(set(project_ids)):  # ordre fixe des verrous : pas d'interblocage
        project = await session.get(Project, project_id, with_for_update=True, populate_existing=True)
        if project is not None:
            project.autopilot = False
    await session.commit()


async def _first_track_id(session: AsyncSession) -> int | None:
    return await session.scalar(select(MusicTrack.id).order_by(MusicTrack.id).limit(1))


async def start_reference_after_script(session: AsyncSession, project_id: int, enqueue: Enqueue,
                                       publish: Publish) -> bool:
    """Lance les images de référence dès que le script est écrit (en relecture) ou à sa validation si elles n'existent
    pas encore, et publie l'événement `running` de `reference`. Vrai si elles sont lancées. Rien n'est lancé si le
    script n'est ni en relecture ni validé, s'il n'a pas d'éléments récurrents, si `reference` n'est pas
    `pending`/`stale` (déjà lancée, produite, ou en échec : « Réessayer » reste à l'utilisateur), ou si l'autopilot est
    actif (`advance` s'en charge). Un refus du lancement (budget, générateur indisponible, file) ne propage rien :
    l'étape reste lançable à la main et ni le job du script ni sa validation n'échouent."""
    project = await lock_project(session, project_id)
    if project.autopilot:
        await session.rollback()
        return False
    by_name = {s.name: s for s in await load_steps(session, [project_id])}
    script, reference = by_name["script"], by_name["reference"]
    if (script.status not in COMPLETED or not (script.result or {}).get("references")
            or reference.status not in ("pending", "stale")):
        await session.rollback()
        return False
    try:
        await launch_step(session, project_id, "reference", enqueue)
    except HTTPException:
        await session.rollback()  # libère le verrou du projet
        return False
    await publish({"project_id": project_id, "step": "reference", "status": "running", "error": None})
    return True


async def advance(session: AsyncSession, project_id: int, step_name: str, enqueue: Enqueue,
                  publish: Publish) -> None:
    """Après le job de `step_name`, si l'autopilot est actif : valide l'étape et lance la suivante.
    - `awaiting_validation` : validée ; `reference` est ignorée (validée sans résultat) sauf si le script liste des
      éléments récurrents (elle est alors générée) ; `music` reçoit la première
      piste de la bibliothèque si aucune n'est choisie ; après `final`, le projet passe `done` et l'autopilot s'arrête.
    - `running` (relancée entre-temps) : rien. `approved` (validée à la main) : la suite est lancée si elle ne l'est pas
      déjà.
    - Sinon (`failed`, périmée…) : l'autopilot s'arrête, l'étape reste relançable à la main."""
    project = await lock_project(session, project_id)
    if not project.autopilot:
        return
    steps = await load_steps(session, [project_id])
    by_name = {s.name: s for s in steps}
    step = by_name[step_name]
    if step.status == "running":
        return
    if step.status not in ("awaiting_validation", "approved"):
        project.autopilot = False
        await session.commit()
        return
    if step_name == project.autopilot_until:  # borne atteinte : l'étape reste à valider par l'utilisateur
        project.autopilot = False
        await sync_status(session, project_id, steps)
        await session.commit()
        await publish({"project_id": project_id, "step": step_name, "status": step.status, "error": None})
        return
    step.status = "approved"  # déjà validée à la main : la suite n'a peut-être pas été lancée
    following = downstream(step_name)
    owner = await session.get(User, project.user_id)
    can_reference = owner is not None and await access.reason(AppSettings(session), owner, "reference") is None
    # éléments récurrents à garder identiques ; sans abonnement, l'étape reference est ignorée (elle est réservée)
    wants_references = can_reference and bool((by_name["script"].result or {}).get("references"))
    while following and following[0] in OPTIONAL_STEPS and not (following[0] == "reference" and wants_references):
        by_name[following.pop(0)].status = "approved"
    while following and by_name[following[0]].status == "approved":  # voix ou musique déjà validées à la main
        following.pop(0)
    if following and by_name[following[0]].status not in ("pending", "stale"):  # suite déjà lancée (ou produite)
        await session.commit()
        return
    if not following:  # `final` validée : vidéo terminée
        project.autopilot = False
        await sync_status(session, project_id, steps)
        await session.commit()
        await publish({"project_id": project_id, "step": step_name, "status": "approved", "error": None})
        return
    name = following[0]
    music = by_name["music"]
    if name == "music" and music.params.get("track_id") is None and (track_id := await _first_track_id(session)):
        music.params = {**music.params, "track_id": track_id}
    await session.flush()
    try:
        await launch_step(session, project_id, name, enqueue)
    except (BudgetExceeded, ModelRefused, CreditsRefused, SubscriptionRequired) as e:
        # l'échec et sa raison apparaissent sur l'étape, relançable une fois le budget relevé ou le modèle disponible
        by_name[name].status, by_name[name].error = "failed", e.detail
        await stop_autopilot(session, [project_id])  # commit
        await publish({"project_id": project_id, "step": name, "status": "failed", "error": e.detail})
        return
    except HTTPException as e:
        if e.status_code != 503:  # 503 : launch_step a déjà marqué l'échec et coupé l'autopilot
            await stop_autopilot(session, [project_id])
        return
    await publish({"project_id": project_id, "step": name, "status": "running", "error": None})
