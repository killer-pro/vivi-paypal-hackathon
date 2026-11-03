import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_user
from app.config import settings
from app.db import SessionFactory, get_session
from app.models import Project, User
from app.queue import EVENTS_CHANNEL

PING_INTERVAL_S = 15

router = APIRouter(tags=["events"])

Allowed = Callable[[int | None], Awaitable[bool]]


def event_project(data: bytes) -> int | None:
    """`project_id` de l'événement ; `None` s'il n'en a pas (ou s'il est illisible)."""
    try:
        project_id = json.loads(data).get("project_id")
    except (ValueError, AttributeError):
        return None
    return project_id if isinstance(project_id, int) else None


async def visible_events(pubsub, allowed: Allowed) -> AsyncIterator[str]:
    """Relaie en `data: …` chaque message du canal dont `allowed(project_id)` est vrai (`project_id` `None` : événement
    sans projet). Si rien n'a été envoyé depuis 15 s (aucun message, ou seulement des messages filtrés), envoie un
    commentaire `: ping`."""
    last = time.monotonic()
    while True:
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=PING_INTERVAL_S)
        if msg and await allowed(event_project(msg["data"])):
            yield f"data: {msg['data'].decode()}\n\n"
        elif msg is None or time.monotonic() - last >= PING_INTERVAL_S:
            yield ": ping\n\n"
        else:
            continue
        last = time.monotonic()


async def project_owner(project_id: int) -> int | None:
    """Propriétaire du projet, dans une session courte : le flux ne garde aucune connexion à la base ouverte."""
    async with SessionFactory() as session:
        return await session.scalar(select(Project.user_id).where(Project.id == project_id))


async def _everything(project_id: int | None) -> bool:
    return True


def owner_filter(user: User) -> Allowed:
    """Filtre d'une connexion : l'admin voit tout ; un utilisateur, les événements de ses projets seulement (pas ceux
    sans projet). Propriétaires mis en cache pour la connexion : un projet ne change pas de propriétaire."""
    if user.is_admin:
        return _everything
    user_id, owners = user.id, {}

    async def allowed(project_id: int | None) -> bool:
        if project_id is None:
            return False
        if project_id not in owners:
            owners[project_id] = await project_owner(project_id)
        return owners[project_id] == user_id

    return allowed


@router.get("/events")
async def events(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    allowed = owner_filter(user)
    # La session de la requête (celle de `current_user`) resterait ouverte tant que dure le flux : on la libère.
    await session.close()

    async def gen():
        redis = Redis.from_url(settings.redis_url)
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(EVENTS_CHANNEL)
            async for chunk in visible_events(pubsub, allowed):
                yield chunk
        finally:  # client déconnecté : Starlette annule le générateur
            await pubsub.aclose()
            await redis.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
