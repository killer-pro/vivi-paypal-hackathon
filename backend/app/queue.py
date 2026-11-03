import asyncio
import json
import weakref
from collections.abc import Awaitable, Callable

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis.asyncio import Redis

from app.config import settings

EVENTS_CHANNEL = "vv:events"

# Un client par boucle d'événements, créé à la demande et réutilisé (reconnexion automatique par redis-py) : plus de
# connexion ouverte puis fermée à chaque job enfilé ou événement publié.
_pools: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, ArqRedis]" = weakref.WeakKeyDictionary()
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Redis]" = weakref.WeakKeyDictionary()


async def _arq_pool() -> ArqRedis:
    loop = asyncio.get_running_loop()
    if loop not in _pools:
        _pools[loop] = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _pools[loop]


def _redis() -> Redis:
    loop = asyncio.get_running_loop()
    if loop not in _clients:
        _clients[loop] = Redis.from_url(settings.redis_url)
    return _clients[loop]


async def close_connections() -> None:
    """Ferme les clients de la boucle courante (arrêt de l'API ou du worker)."""
    loop = asyncio.get_running_loop()
    for registry in (_pools, _clients):
        client = registry.pop(loop, None)
        if client is not None:
            await client.aclose()


async def enqueue_step(project_id: int, step: str, scene_id: int | None = None, overrides: dict | None = None, *,
                       timeout: int | None = None) -> None:
    """`timeout` : durée max du job (secondes), dimensionnée par l'API selon le nombre de scènes et appliquée par le
    worker (Arq 0.28 n'a pas de timeout par job)."""
    await (await _arq_pool()).enqueue_job("run_step_job", project_id, step, scene_id, overrides, timeout)


async def publish_event(event: dict) -> None:
    await _redis().publish(EVENTS_CHANNEL, json.dumps(event))


def get_enqueue() -> Callable[..., Awaitable[None]]:
    return enqueue_step
