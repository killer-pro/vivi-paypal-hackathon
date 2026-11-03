import asyncio

import pytest
from sqlalchemy import select

from app.models import ProviderCall
from app.providers.base import GenerationResult, ProviderError
from app.services.costs import WriteGate, tracked_call

OK = GenerationResult(b"x", "video/mp4", 0.5, "m")


async def test_success_logs_one_ok_row(session):
    async def fn():
        return OK
    assert await tracked_call(session, project_id=None, step="clips", provider="p", model="m", fn=fn) is OK
    rows = (await session.scalars(select(ProviderCall))).all()
    assert [(r.status, r.cost_usd) for r in rows] == [("ok", 0.5)]


async def test_retryable_error_is_retried_then_succeeds(session):
    n = {"c": 0}

    async def fn():
        n["c"] += 1
        if n["c"] < 3:
            raise ProviderError("503", retryable=True)
        return OK

    await tracked_call(session, project_id=None, step="clips", provider="p", model="m", fn=fn, base_delay=0)
    rows = (await session.scalars(select(ProviderCall))).all()
    assert [r.status for r in rows] == ["error", "error", "ok"]


async def test_non_retryable_error_is_not_retried(session):
    n = {"c": 0}

    async def fn():
        n["c"] += 1
        raise ProviderError("quota")

    with pytest.raises(ProviderError):
        await tracked_call(session, project_id=None, step="clips", provider="p", model="m", fn=fn, base_delay=0)
    assert n["c"] == 1


async def test_timeout_becomes_provider_error(session):
    import asyncio

    async def fn():
        await asyncio.sleep(5)

    with pytest.raises(ProviderError, match="timeout"):
        await tracked_call(session, project_id=None, step="clips", provider="p", model="m", fn=fn, timeout=0.05)


async def test_write_gate_serializes_and_survives_cancellation():
    """Une écriture engagée va à son terme même si la tâche qui l'attend est annulée, et `settle` l'attend."""
    gate, log = WriteGate(), []

    async def write(name, delay):
        log.append(f"début {name}")
        await asyncio.sleep(delay)
        log.append(f"fin {name}")
        return name

    first = asyncio.create_task(gate.run(lambda: write("a", 0.05)))
    second = asyncio.create_task(gate.run(lambda: write("b", 0.01)))
    await asyncio.sleep(0.01)
    first.cancel()  # annulée en plein écriture
    with pytest.raises(asyncio.CancelledError):
        await first
    assert log == ["début a"]
    await gate.settle()  # attend « a » puis « b » (déjà en file)
    assert log == ["début a", "fin a", "début b", "fin b"]  # jamais deux écritures à la fois
    assert (await second) == "b"
