import asyncio
import logging
from datetime import timedelta

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select, update

from app.app_settings import AppSettings
from app.config import settings
from app.db import SessionFactory
from app.models import Step
from app.providers.registry import ProviderRegistry
from app.queue import close_connections, enqueue_step, publish_event
from app.services import credits, langfuse
from app.services.pipeline import PipelineContext, run_step
from app.services.queue_runs import dispatch_queue, projects_with_queue
from app.services.steps import advance, start_reference_after_script, stop_autopilot
from app.services.timeouts import MAX_JOB_TIMEOUT
from app.storage import get_storage

INTERRUPTED = "job interrompu ou expiré"
RESTARTED = "job interrompu (worker redémarré)"
STOP_POLL_S = 5  # fréquence à laquelle un job vérifie qu'on ne lui a pas demandé de s'arrêter
DEFAULT_JOB_TIMEOUT = 1200  # jobs enfilés sans timeout (avant son dimensionnement par l'API)

logger = logging.getLogger("app")


async def fail_running_steps(error: str, *conditions) -> None:
    """Passe en `failed` les étapes encore `running` (filtrées par `conditions`) : elles redeviennent relançables, leurs
    crédits réservés sont réglés (scènes produites) ou rendus, et l'autopilot de leurs projets s'arrête."""
    async with SessionFactory() as session:
        failed = (await session.execute(update(Step).where(Step.status == "running", *conditions)
                                        .values(status="failed", error=error)
                                        .returning(Step.project_id, Step.name))).all()
        for project_id, name in failed:
            await credits.close_for_step(session, project_id, name, completed=False)
        await session.commit()
        await stop_autopilot(session, [project_id for project_id, _ in failed])


async def startup(ctx):
    await get_storage().ensure_bucket()
    # Worker unique : aucun job ne peut tourner au démarrage, un `running` restant est orphelin.
    await fail_running_steps(RESTARTED)
    async with SessionFactory() as session:  # demandes en file avant l'arrêt : elles repartent
        for project_id in await projects_with_queue(session):
            await dispatch_queue(session, project_id, enqueue_step, publish_event)


async def shutdown(ctx):
    langfuse.shutdown()  # envoie les traces en attente
    await close_connections()


async def _still_running(project_id: int, step: str, run_id: str | None = None, *, same_run: bool = False) -> bool:
    """L'étape tourne-t-elle encore ? Avec `same_run`, c'est aussi le même lancement (`Step.run_id`) : une étape arrêtée
    puis relancée aussitôt ne doit pas prolonger l'ancien job."""
    async with SessionFactory() as session:
        row = (await session.execute(select(Step.status, Step.run_id).where(Step.project_id == project_id,
                                                                            Step.name == step))).first()
    return row is not None and row.status == "running" and (not same_run or row.run_id == run_id)


async def _current_run_id(project_id: int, step: str) -> str | None:
    async with SessionFactory() as session:
        return await session.scalar(select(Step.run_id).where(Step.project_id == project_id, Step.name == step))


async def _cancel_when_stopped(task: asyncio.Task, project_id: int, step: str, run_id: str | None, stopped: list) -> None:
    """Annule `task` dès que l'étape n'est plus en cours pour ce lancement (arrêt demandé par l'utilisateur)."""
    while True:
        await asyncio.sleep(STOP_POLL_S)
        if not await _still_running(project_id, step, run_id, same_run=True):
            stopped.append(True)
            task.cancel()  # le provider interrompt alors l'appel en cours (ComfyUI : /interrupt)
            return


async def _next_in_queue(project_id: int) -> None:
    """Une génération vient de finir (ou d'être arrêtée) : la suivante de la file du projet peut partir."""
    async with SessionFactory() as session:
        await dispatch_queue(session, project_id, enqueue_step, publish_event)


async def run_step_job(ctx, project_id: int, step: str, scene_id: int | None, overrides: dict | None = None,
                       timeout: float | None = None):
    # Job resté en file alors que l'étape a été réinitialisée (worker redémarré) : ne pas rejouer d'appel payant.
    if not await _still_running(project_id, step):
        return
    run_id, stopped = await _current_run_id(project_id, step), list[bool]()
    try:
        async with asyncio.timeout(timeout or DEFAULT_JOB_TIMEOUT), SessionFactory() as session:
            app_settings = AppSettings(session)
            registry = ProviderRegistry(app_settings)
            run = asyncio.ensure_future(run_step(PipelineContext(session, get_storage(), registry, app_settings,
                                                                 publish_event, overrides or {}),
                                                 project_id, step, scene_id))
            watcher = asyncio.ensure_future(_cancel_when_stopped(run, project_id, step, run_id, stopped))
            try:
                await run
            finally:
                watcher.cancel()
                await registry.aclose()
    except asyncio.CancelledError:
        if stopped:  # arrêt demandé par l'utilisateur : l'API a déjà marqué l'étape, rien à enregistrer ni à enchaîner
            await _next_in_queue(project_id)
            return
        await fail_running_steps(INTERRUPTED, Step.project_id == project_id, Step.name == step)
        await publish_event({"project_id": project_id, "step": step, "status": "failed", "error": INTERRUPTED})
        raise
    except TimeoutError:  # timeout du job : non intercepté par run_step
        await fail_running_steps(INTERRUPTED, Step.project_id == project_id, Step.name == step)
        await publish_event({"project_id": project_id, "step": step, "status": "failed", "error": INTERRUPTED})
        await _next_in_queue(project_id)
        return
    try:
        async with SessionFactory() as session:  # mode automatique : validation et lancement de l'étape suivante
            if step == "script":
                try:
                    await start_reference_after_script(session, project_id, enqueue_step, publish_event)
                except Exception:  # le job du script a réussi : un échec du lancement des références ne l'annule pas
                    logger.exception("Lancement des images de référence impossible (projet %s)", project_id)
                    await session.rollback()
            await advance(session, project_id, step, enqueue_step, publish_event)
    finally:
        await _next_in_queue(project_id)


async def sweep_reservations(ctx):
    """Tâche périodique : rend les crédits des réservations orphelines (job mort sans les régler)."""
    async with SessionFactory() as session:
        timeout_min = int(await AppSettings(session).get("credits_reservation_timeout_min"))
        swept = await credits.sweep_stale(session, timedelta(minutes=timeout_min))
        await session.commit()
    if swept:
        logger.warning("%s réservation(s) de crédits orpheline(s) fermée(s)", swept)


class WorkerSettings:
    functions = [run_step_job]
    cron_jobs = [cron(sweep_reservations, minute=set(range(0, 60, 10)), second=0)]  # toutes les 10 minutes
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    job_timeout = MAX_JOB_TIMEOUT + 60  # plafond Arq ; le timeout réel de chaque job est appliqué par run_step_job
    max_jobs = 2
    max_tries = 1  # jamais de relance automatique : un appel provider payant ne doit pas être rejoué
