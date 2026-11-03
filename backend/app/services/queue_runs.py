"""File d'attente des générations d'un projet : une demande qui tombe pendant qu'une génération bloque l'étape (la même
étape, ou une étape qui en dépend) n'est pas refusée mais gardée, puis lancée dans l'ordre quand plus rien ne la bloque."""
import logging

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import QueuedRun
from app.services.flow import StepBusy, load_steps
from app.services.steps import Enqueue, Publish, launch_step, lock_project

MAX_QUEUED = 5  # demandes en attente par projet
log = logging.getLogger(__name__)


async def queued_runs(session: AsyncSession, project_id: int) -> list[QueuedRun]:
    return list((await session.scalars(select(QueuedRun).where(QueuedRun.project_id == project_id)
                                       .order_by(QueuedRun.id))).all())


async def run_or_queue(session: AsyncSession, project_id: int, name: str, enqueue: Enqueue, scene_id: int | None,
                       overrides: dict | None, **options) -> bool:
    """Lance l'étape ; si une génération la bloque, la met en file. Renvoie `True` si elle a été mise en file, 409 si la
    file est pleine. Les autres refus (étape précédente non validée, budget, modèle…) restent des erreurs immédiates."""
    try:
        await launch_step(session, project_id, name, enqueue, scene_id, overrides, **options)
        return False
    except StepBusy as busy:
        await session.rollback()
        await lock_project(session, project_id)
        whole_step = scene_id is None and not (overrides or {}).get("reference_id")  # un élément seul se met en file
        if whole_step and any(st.name == name and st.status == "running" for st in await load_steps(session, [project_id])):
            raise  # relancer l'étape entière pendant qu'elle tourne : rien à mettre en attente
        request = {"overrides": overrides or {}, **{k: v for k, v in options.items() if v}}
        queued = await queued_runs(session, project_id)
        if any((q.step, q.scene_id, q.request) == (name, scene_id, request) for q in queued):
            return True  # déjà en file à l'identique
        if len(queued) >= MAX_QUEUED:
            raise HTTPException(409, f"File d'attente pleine ({MAX_QUEUED} générations) : {busy.detail}") from busy
        session.add(QueuedRun(project_id=project_id, step=name, scene_id=scene_id, request=request))
        await session.commit()
        return True


async def remove_queued(session: AsyncSession, project_id: int, queued_id: int) -> None:
    res = await session.execute(delete(QueuedRun).where(QueuedRun.id == queued_id, QueuedRun.project_id == project_id).returning(QueuedRun.id))
    if res.first() is None:
        raise HTTPException(404, "Cette génération n'est plus en file")
    await session.commit()


async def dispatch_queue(session: AsyncSession, project_id: int, enqueue: Enqueue, publish: Publish) -> None:
    """Lance, dans l'ordre, les demandes en file que plus rien ne bloque ; les autres attendent la fin d'une génération.
    Une demande devenue impossible (étape précédente périmée, budget, modèle indisponible…) est retirée et son motif
    publié avec l'événement du projet."""
    for item in await queued_runs(session, project_id):
        item_id, step, scene_id, request = item.id, item.step, item.scene_id, dict(item.request)  # avant tout rollback
        try:
            await launch_step(session, project_id, step, enqueue, scene_id, request.pop("overrides", None), **request)
        except StepBusy:
            continue
        except HTTPException as e:
            log.warning("génération en file abandonnée (projet %s, %s) : %s", project_id, step, e.detail)
            await session.rollback()
            event = {"project_id": project_id, "step": step, "status": "failed", "error": e.detail}
        else:
            event = {"project_id": project_id, "step": step, "status": "running", "error": None}
        await session.execute(delete(QueuedRun).where(QueuedRun.id == item_id))
        await session.commit()
        await publish(event)


async def projects_with_queue(session: AsyncSession) -> list[int]:
    return list((await session.scalars(select(QueuedRun.project_id).group_by(QueuedRun.project_id))).all())
