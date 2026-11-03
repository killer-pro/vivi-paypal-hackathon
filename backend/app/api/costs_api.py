from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_user
from app.api.projects import ensure_access, fields
from app.db import get_session
from app.models import Project, ProviderCall, User

router = APIRouter(tags=["costs"])

CALLS_LIMIT, MAX_CALLS_LIMIT = 200, 1000
CALL_FIELDS = ("id", "project_id", "step", "provider", "model", "cost_usd", "duration_ms", "status", "error", "created_at")


async def sum_by(session: AsyncSession, column, filters: list) -> dict:
    rows = await session.execute(select(column, func.sum(ProviderCall.cost_usd)).where(*filters).group_by(column))
    return {str(key): round(float(total), 6) for key, total in rows if key is not None}


@router.get("/costs")
async def costs(project_id: int | None = None, provider: str | None = None, since: datetime | None = None,
                limit: int = Query(CALLS_LIMIT, ge=1, le=MAX_CALLS_LIMIT), offset: int = Query(0, ge=0),
                user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """Totaux (tous les appels qui correspondent aux filtres) et une page d'appels, du plus récent au plus ancien :
    `calls` (`limit` à partir de `offset`) et `calls_total` (nombre d'appels correspondants). L'admin voit tous les
    appels ; un utilisateur, ceux de ses projets seulement (les appels sans projet sont réservés à l'admin), et un
    `project_id` qui n'est pas à lui donne 404."""
    if project_id is not None:
        await ensure_access(session, project_id, user)
    conditions = {ProviderCall.project_id: project_id, ProviderCall.provider: provider}
    filters = [col == value for col, value in conditions.items() if value is not None]
    if not user.is_admin:
        filters.append(ProviderCall.project_id.in_(select(Project.id).where(Project.user_id == user.id)))
    if since is not None:
        filters.append(ProviderCall.created_at >= since)
    by_provider = await sum_by(session, ProviderCall.provider, filters)
    calls: Select = select(ProviderCall).where(*filters).order_by(ProviderCall.created_at.desc(), ProviderCall.id.desc())
    rows = (await session.scalars(calls.limit(limit).offset(offset))).all()
    calls_total = await session.scalar(select(func.count()).select_from(ProviderCall).where(*filters))
    return {"total_usd": round(sum(by_provider.values()), 6), "by_provider": by_provider, "calls_total": calls_total,
            "by_project": await sum_by(session, ProviderCall.project_id, filters),
            "calls": [fields(r, CALL_FIELDS) for r in rows]}
