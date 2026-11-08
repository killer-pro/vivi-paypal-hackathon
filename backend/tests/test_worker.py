import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import worker
from app.models import Project, Step
from app.state import STEP_NAMES
from tests.conftest import ensure_admin


@pytest.fixture
def events(session, monkeypatch):
    """Le worker utilise la base de test et enregistre les événements publiés."""
    published = []

    async def publish(event):
        published.append(event)

    class Bucketless:
        async def ensure_bucket(self):
            pass

    monkeypatch.setattr(worker, "SessionFactory", async_sessionmaker(session.bind, expire_on_commit=False))
    monkeypatch.setattr(worker, "publish_event", publish)
    monkeypatch.setattr(worker, "get_storage", Bucketless)
    return published


async def seed(session, running):
    p = Project(title="t", user_id=(await ensure_admin(session)).id)
    session.add(p)
    await session.flush()
    session.add_all(Step(project_id=p.id, name=n, status="running" if n in running else "pending") for n in STEP_NAMES)
    await session.commit()
    return p.id


async def statuses(session, pid):
    steps = (await session.scalars(select(Step).where(Step.project_id == pid)
                                   .execution_options(populate_existing=True))).all()
    return {s.name: (s.status, s.error) for s in steps}


async def test_cancelled_job_marks_step_failed_and_reraises(session, events, monkeypatch):
    pid = await seed(session, {"clips", "idea"})
    started = asyncio.Event()

    async def slow_run_step(ctx, project_id, step, scene_id):
        started.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(worker, "run_step", slow_run_step)
    job = asyncio.create_task(worker.run_step_job({}, pid, "clips", None))
    await started.wait()
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    status = await statuses(session, pid)
    assert status["clips"] == ("failed", worker.INTERRUPTED)
    assert status["idea"] == ("running", None)  # seule l'étape du job est concernée
    assert events == [{"project_id": pid, "step": "clips", "status": "failed", "error": worker.INTERRUPTED}]


async def test_startup_fails_orphan_running_steps(session, events):
    pid = await seed(session, {"clips"})
    await worker.startup({})
    status = await statuses(session, pid)
    assert status["clips"] == ("failed", worker.RESTARTED) and status["idea"] == ("pending", None)


def test_jobs_are_never_retried():
    assert worker.WorkerSettings.max_tries == 1


async def test_job_passes_run_overrides_to_pipeline(session, events, monkeypatch):
    pid = await seed(session, {"clips"})
    seen = []

    async def fake_run_step(ctx, project_id, step, scene_id):
        seen.append((step, scene_id, ctx.overrides))

    monkeypatch.setattr(worker, "run_step", fake_run_step)
    await worker.run_step_job({}, pid, "clips", 3, {"provider": "comfyui"})
    await worker.run_step_job({}, pid, "clips", None)  # jobs enfilés avant l'ajout du paramètre
    assert seen == [("clips", 3, {"provider": "comfyui"}), ("clips", None, {})]


async def test_job_timeout_argument_fails_step_without_reraising(session, events, monkeypatch):
    pid = await seed(session, {"clips"})

    async def slow_run_step(ctx, project_id, step, scene_id):
        await asyncio.sleep(60)

    monkeypatch.setattr(worker, "run_step", slow_run_step)
    await worker.run_step_job({}, pid, "clips", None, None, 0.05)
    assert (await statuses(session, pid))["clips"] == ("failed", worker.INTERRUPTED)
    assert events == [{"project_id": pid, "step": "clips", "status": "failed", "error": worker.INTERRUPTED}]


def test_arq_limit_never_cuts_a_sized_job_first():
    from app.services.timeouts import MAX_JOB_TIMEOUT

    assert worker.WorkerSettings.job_timeout > MAX_JOB_TIMEOUT


async def test_stale_queued_job_is_skipped_when_step_no_longer_running(session, events, monkeypatch):
    pid = await seed(session, set())
    await session.execute(Step.__table__.update().where(Step.name == "clips").values(status="failed", error="x"))
    await session.commit()
    called = []

    async def fake_run_step(ctx, project_id, step, scene_id):
        called.append(step)

    monkeypatch.setattr(worker, "run_step", fake_run_step)
    await worker.run_step_job({}, pid, "clips", None)
    assert called == [] and events == []
    assert (await statuses(session, pid))["clips"] == ("failed", "x")


async def test_queue_reuses_one_connection_per_event_loop(monkeypatch):
    """`publish_event` et `enqueue_step` n'ouvrent plus une connexion par appel ; `close_connections` les referme."""
    from app import queue

    created, sent = [], []

    class FakeRedis:
        async def publish(self, channel, payload):
            sent.append((channel, payload))

        async def enqueue_job(self, *args):
            sent.append(args)

        async def aclose(self):
            created.append("closed")

    async def make_pool(settings):
        created.append("pool")
        return FakeRedis()

    monkeypatch.setattr(queue, "create_pool", make_pool)
    monkeypatch.setattr(queue.Redis, "from_url", lambda url: created.append("client") or FakeRedis())
    for _ in range(3):
        await queue.publish_event({"a": 1})
        await queue.enqueue_step(1, "idea")
    assert created == ["client", "pool"] and len(sent) == 6
    await queue.close_connections()
    assert created == ["client", "pool", "closed", "closed"]


async def test_job_stops_when_the_user_stops_the_step(session, events, monkeypatch):
    """Arrêt demandé (étape passée en échec par l'API) : le job interrompt l'appel en cours, n'enregistre plus rien,
    n'écrase pas le message de l'utilisateur et n'enchaîne rien."""
    from app.services.steps import STOPPED_BY_USER, cancel_step

    monkeypatch.setattr(worker, "STOP_POLL_S", 0.02)
    pid = await seed(session, {"clips"})
    started, interrupted, chained = asyncio.Event(), [], []

    async def slow_run_step(ctx, project_id, step, scene_id):
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            interrupted.append(True)  # le provider interrompt alors l'appel en cours (ComfyUI : /interrupt)
            raise

    async def advance(*args):
        chained.append(args)

    monkeypatch.setattr(worker, "run_step", slow_run_step)
    monkeypatch.setattr(worker, "advance", advance)
    job = asyncio.create_task(worker.run_step_job({}, pid, "clips", None))
    await started.wait()
    await cancel_step(session, pid, "clips")
    await asyncio.wait_for(job, 5)  # le job se termine de lui-même, sans lever d'annulation
    assert interrupted == [True] and chained == []
    assert (await statuses(session, pid))["clips"] == ("failed", STOPPED_BY_USER)
    assert events == []  # pas d'événement « job interrompu » : l'arrêt est celui de l'utilisateur


async def test_stopped_then_relaunched_step_does_not_keep_the_old_job_alive(session, events, monkeypatch):
    """Le nouveau lancement porte un autre `run_id` : l'ancien job s'arrête quand même."""
    monkeypatch.setattr(worker, "STOP_POLL_S", 0.02)
    pid = await seed(session, {"clips"})
    await session.execute(Step.__table__.update().where(Step.name == "clips").values(run_id="ancien"))
    await session.commit()
    started, interrupted = asyncio.Event(), []

    async def slow_run_step(ctx, project_id, step, scene_id):
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            interrupted.append(True)
            raise

    monkeypatch.setattr(worker, "run_step", slow_run_step)
    job = asyncio.create_task(worker.run_step_job({}, pid, "clips", None))
    await started.wait()
    await session.execute(Step.__table__.update().where(Step.name == "clips").values(run_id="nouveau"))  # relancée
    await session.commit()
    await asyncio.wait_for(job, 5)
    assert interrupted == [True]


async def test_job_that_finishes_normally_is_not_stopped(session, events, monkeypatch):
    monkeypatch.setattr(worker, "STOP_POLL_S", 0.02)
    pid = await seed(session, {"clips"})
    chained = []

    async def quick_run_step(ctx, project_id, step, scene_id):
        await asyncio.sleep(0.1)

    async def advance(*args):
        chained.append(args)

    monkeypatch.setattr(worker, "run_step", quick_run_step)
    monkeypatch.setattr(worker, "advance", advance)
    await worker.run_step_job({}, pid, "clips", None)
    assert len(chained) == 1  # l'enchaînement de l'autopilot se fait comme avant
