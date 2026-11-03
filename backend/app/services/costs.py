import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import AppSettings
from app.models import ProviderCall
from app.providers.base import GenerationResult, ProviderError, TextResult
from app.services import langfuse

T = TypeVar("T")
Result = TypeVar("Result", GenerationResult, TextResult)  # résultat d'un provider : porte `cost_usd`
DEFAULT_ATTEMPTS = 3


class WriteGate:
    """Écritures en base d'une session partagée entre des tâches concurrentes (génération de plusieurs scènes à la fois).

    Une session SQLAlchemy ne supporte pas deux opérations simultanées : `run` les passe l'une après l'autre. Chaque
    écriture est à l'abri de l'annulation (`shield`) : une tâche annulée pendant son `commit` laisserait la connexion
    dans un état invalide. `settle` attend les écritures en cours ou en file : à appeler avant de réutiliser la session
    après l'annulation de tâches."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def run(self, write: Callable[[], Awaitable[T]]) -> T:
        async def locked() -> T:
            async with self._lock:
                return await write()

        return await asyncio.shield(asyncio.ensure_future(locked()))

    async def settle(self) -> None:
        async with self._lock:  # le verrou est équitable : passe après toutes les écritures déjà en file
            pass


async def tracked_call(
    session: AsyncSession, *, project_id: int | None, step: str, provider: str, model: str,
    fn: Callable[[], Awaitable[Result]], attempts: int = DEFAULT_ATTEMPTS, base_delay: float = 1.0, timeout: float = 600,
    writes: WriteGate | None = None, input: list[dict] | None = None,
) -> Result:
    """Appel provider journalisé (`provider_calls`), avec retries. `writes` : porte d'écriture quand plusieurs appels
    partagent la même session ; l'appel lui-même reste concurrent. `input` : messages envoyés (`langfuse.messages`),
    journalisés avec chaque tentative dans Langfuse si ses clés sont renseignées."""
    async def under_gate(action: Callable[[], Awaitable[T]]) -> T:
        return await (writes.run(action) if writes else action())

    async def record(**values) -> None:
        async def write() -> None:
            session.add(ProviderCall(project_id=project_id, step=step, provider=provider, model=model, **values))
            await session.commit()

        await under_gate(write)

    config = await under_gate(lambda: langfuse.load_config(AppSettings(session)))
    last: ProviderError | None = None
    for attempt in range(attempts):
        started = time.monotonic()
        with langfuse.generation(config, step=step, provider=provider, model=model, input=input,
                                 project_id=project_id, attempt=attempt + 1) as generation:
            try:
                try:
                    result = await asyncio.wait_for(fn(), timeout)
                except TimeoutError as e:
                    raise ProviderError("timeout", retryable=False) from e
            except ProviderError as e:
                generation.fail(str(e))
                failure: ProviderError | None = e
            else:
                generation.succeed(result, result.cost_usd)
                failure = None
        duration_ms = int((time.monotonic() - started) * 1000)
        if failure is None:
            await record(cost_usd=result.cost_usd, duration_ms=duration_ms, status="ok")
            return result
        await record(cost_usd=0, duration_ms=duration_ms, status="error", error=str(failure))
        last = failure
        if not failure.retryable or attempt == attempts - 1:
            raise failure
        await asyncio.sleep(base_delay * 2**attempt)
    assert last is not None  # pragma: no cover
    raise last  # pragma: no cover
