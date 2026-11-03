from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import worker
from app.models import Asset, CreditEntry, CreditReservation, Scene, Step
from app.services import credits, pipeline
from app.services.pipeline import run_step
from tests.test_api_steps import new_project, set_status
from tests.test_launch_credits import CLIP_3S, client_project
from tests.test_pipeline import SlowVideo, use_video
from tests.test_worker import events  # noqa: F401  (fixture : worker branché sur la base de test)

START = 1000


async def clips_project(api_as, make_user, fund, session, scenes=3):
    """Client financé, projet prêt pour les clips (`scenes` scènes de 3 s, prompts p1…pN)."""
    user, c, pid = await client_project(api_as, make_user, fund, amount=START)
    session.add_all(Scene(project_id=pid, position=i, voice_text=f"v{i}", visual_prompt=f"p{i}", duration_s=3)
                    for i in range(1, scenes + 1))
    await session.commit()
    await set_status(session, ["idea", "story", "script", "reference"], "approved")
    return user.id, c, pid


async def launch(c, pid, name="clips", **body):
    r = await c.post(f"/api/projects/{pid}/steps/{name}/run", json=body)
    assert r.status_code == 202, r.text


async def net_debit(session, uid) -> int:
    return START - (await credits.balance(session, uid)).total


async def reservation(session) -> CreditReservation:
    return (await session.scalars(select(CreditReservation).order_by(CreditReservation.id.desc()))).first()


async def run_clips_concurrently(ctx, pid, video):
    """Exécute les clips avec un générateur « fal » simulé : plusieurs clips à la fois, toutes les scènes sont tentées."""
    await ctx.app_settings.set("default_video_provider", "fal")
    use_video(ctx, video)
    try:
        await run_step(ctx, pid, "clips")
    finally:
        await ctx.app_settings.set("default_video_provider", "comfyui")


async def test_success_charges_full_price(api_as, make_user, fund, session, ctx):
    user, c, pid = await client_project(api_as, make_user, fund, amount=START)
    await launch(c, pid, "idea")
    await run_step(ctx, pid, "idea")
    r = await reservation(session)
    assert r.status == "closed" and r.used == r.amount == 1 and await net_debit(session, user.id) == 1


async def test_failed_non_scene_step_refunds_everything(api_as, make_user, fund, session, ctx, monkeypatch):
    user, c, pid = await client_project(api_as, make_user, fund, amount=START)

    async def boom(*args):
        raise RuntimeError("LLM en panne")

    monkeypatch.setitem(pipeline.EXECUTORS, "idea", boom)
    await launch(c, pid, "idea")
    await run_step(ctx, pid, "idea")
    assert (await session.scalar(select(Step.status).where(Step.project_id == pid, Step.name == "idea"))) == "failed"
    assert (await reservation(session)).used == 0 and await net_debit(session, user.id) == 0


async def test_clips_partial_failure_charges_only_produced_scenes(api_as, make_user, fund, session, ctx):
    uid, c, pid = await clips_project(api_as, make_user, fund, session)
    await launch(c, pid)
    assert await net_debit(session, uid) == 3 * CLIP_3S
    await run_clips_concurrently(ctx, pid, SlowVideo(fail_on="p3", delay=0))
    assert (await session.scalar(select(Step.status).where(Step.name == "clips"))) == "failed"
    assert (await reservation(session)).used == 2 * CLIP_3S and await net_debit(session, uid) == 2 * CLIP_3S


async def test_single_scene_rerun_charges_one_scene(api_as, make_user, fund, session, ctx):
    uid, c, pid = await clips_project(api_as, make_user, fund, session)
    scene_id = await session.scalar(select(Scene.id).where(Scene.project_id == pid, Scene.position == 2))
    await launch(c, pid, scene_id=scene_id)
    assert await net_debit(session, uid) == CLIP_3S
    use_video(ctx, SlowVideo(delay=0))
    await run_step(ctx, pid, "clips", scene_id)
    assert (await reservation(session)).used == CLIP_3S and await net_debit(session, uid) == CLIP_3S


async def test_failed_single_scene_rerun_is_not_charged(api_as, make_user, fund, session, ctx):
    uid, c, pid = await clips_project(api_as, make_user, fund, session)
    scene_id = await session.scalar(select(Scene.id).where(Scene.project_id == pid, Scene.position == 2))
    await launch(c, pid, scene_id=scene_id)
    use_video(ctx, SlowVideo(fail_on="p2", delay=0))
    await run_step(ctx, pid, "clips", scene_id)
    assert await net_debit(session, uid) == 0


async def test_resume_charges_only_new_scenes(api_as, make_user, fund, session, ctx):
    uid, c, pid = await clips_project(api_as, make_user, fund, session)
    await launch(c, pid)
    await run_clips_concurrently(ctx, pid, SlowVideo(fail_on="p3", delay=0))
    assert await net_debit(session, uid) == 2 * CLIP_3S
    await launch(c, pid, resume=True)
    r = await reservation(session)
    assert r.amount == CLIP_3S  # seule la scène manquante est retenue
    ctx.overrides = {"skip_scenes": [int(i) for i in (await session.scalars(select(Asset.scene_id))).all()]}
    use_video(ctx, SlowVideo(delay=0))
    await run_step(ctx, pid, "clips")
    assert (await reservation(session)).used == CLIP_3S and await net_debit(session, uid) == 3 * CLIP_3S


async def test_cancel_charges_produced_scenes_and_is_idempotent_with_worker_end(api_as, make_user, fund, session):
    uid, c, pid = await clips_project(api_as, make_user, fund, session)
    await launch(c, pid)
    run_id = await session.scalar(select(Step.run_id).where(Step.project_id == pid, Step.name == "clips"))
    first = await session.scalar(select(Scene.id).where(Scene.project_id == pid, Scene.position == 1))
    session.add(Asset(project_id=pid, scene_id=first, kind="clip", key="k", content_type="video/mp4", meta={"run": run_id}))
    await session.commit()
    assert (await c.post(f"/api/projects/{pid}/steps/clips/cancel")).status_code == 202
    assert await net_debit(session, uid) == CLIP_3S  # la scène déjà produite reste facturée
    refunds = await session.scalar(select(func.count()).select_from(CreditEntry).where(CreditEntry.kind == "refund"))
    assert await credits.close_for_step(session, pid, "clips", completed=True) == 0  # fin du job après l'annulation
    await session.commit()
    assert await net_debit(session, uid) == CLIP_3S
    assert await session.scalar(select(func.count()).select_from(CreditEntry).where(CreditEntry.kind == "refund")) == refunds


async def test_cancel_of_non_scene_step_refunds_everything(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund, amount=START)
    await launch(c, pid, "idea")
    assert (await c.post(f"/api/projects/{pid}/steps/idea/cancel")).status_code == 202
    assert await net_debit(session, user.id) == 0


async def test_timeout_and_interrupted_job_refund(api_as, make_user, fund, session, events, monkeypatch):  # noqa: F811
    user, c, pid = await client_project(api_as, make_user, fund, amount=START)
    await launch(c, pid, "idea")

    async def never(ctx, project_id, step, scene_id):
        import asyncio
        await asyncio.sleep(60)

    monkeypatch.setattr(worker, "run_step", never)
    await worker.run_step_job({}, pid, "idea", None, timeout=0.05)
    assert (await session.scalar(select(Step.status).where(Step.project_id == pid, Step.name == "idea").execution_options(
        populate_existing=True))) == "failed"
    assert (await reservation(session)).status == "closed" and await net_debit(session, user.id) == 0


async def test_worker_restart_closes_open_reservations(api_as, make_user, fund, session, events):  # noqa: F811
    uid, c, pid = await clips_project(api_as, make_user, fund, session)
    await launch(c, pid)
    run_id = await session.scalar(select(Step.run_id).where(Step.project_id == pid, Step.name == "clips"))
    first = await session.scalar(select(Scene.id).where(Scene.project_id == pid, Scene.position == 1))
    session.add(Asset(project_id=pid, scene_id=first, kind="clip", key="k", content_type="video/mp4", meta={"run": run_id}))
    await session.commit()
    await worker.fail_running_steps(worker.RESTARTED)
    assert (await reservation(session)).status == "closed" and await net_debit(session, uid) == CLIP_3S


async def _age(session, r: CreditReservation, minutes: int):
    r.created_at = datetime.now(UTC) - timedelta(minutes=minutes)
    await session.commit()


async def test_sweeper_closes_only_stale_reservations_and_second_run_is_noop(api_as, make_user, fund, session):
    user, c, old_project = await client_project(api_as, make_user, fund, amount=START)
    recent_project = await new_project(c)
    await launch(c, old_project, "idea")
    await launch(c, recent_project, "idea")
    old, recent = (await session.scalars(select(CreditReservation).order_by(CreditReservation.id))).all()
    await _age(session, old, 31)
    await _age(session, recent, 5)
    # le job du premier projet est mort sans fin : l'étape n'est plus `running`
    await session.execute(Step.__table__.update().where(Step.project_id == old_project, Step.name == "idea")
                          .values(status="failed"))
    await session.commit()
    assert await credits.sweep_stale(session, timedelta(minutes=30)) == 1
    await session.commit()
    assert await credits.sweep_stale(session, timedelta(minutes=30)) == 0
    await session.refresh(old)
    await session.refresh(recent)
    assert (old.status, recent.status) == ("closed", "open") and await net_debit(session, user.id) == 1


async def test_sweeper_leaves_reservations_of_steps_still_running(api_as, make_user, fund, session):
    """Un job de clips légitime peut durer des heures : tant que l'étape tourne, sa réservation n'est pas balayée."""
    user, c, pid = await client_project(api_as, make_user, fund, amount=START)
    await launch(c, pid, "idea")
    await _age(session, await reservation(session), 600)
    assert await credits.sweep_stale(session, timedelta(minutes=30)) == 0


async def test_sweep_task_uses_the_timeout_setting(api_as, make_user, fund, session, events):  # noqa: F811
    user, c, pid = await client_project(api_as, make_user, fund, amount=START)
    await launch(c, pid, "idea")
    await session.execute(Step.__table__.update().where(Step.name == "idea").values(status="failed"))
    await _age(session, await reservation(session), 20)
    await worker.sweep_reservations({})
    assert (await reservation(session)).status == "open"  # 20 min < 30 min par défaut
    await worker.AppSettings(session).set("credits_reservation_timeout_min", "10")
    await worker.sweep_reservations({})
    await session.refresh(await reservation(session))
    assert (await reservation(session)).status == "closed"
    assert any(job.coroutine is worker.sweep_reservations for job in worker.WorkerSettings.cron_jobs)


async def test_ledger_still_sums_to_balance_after_failures(api_as, make_user, fund, session, ctx):
    uid, c, pid = await clips_project(api_as, make_user, fund, session)
    await launch(c, pid)
    await run_clips_concurrently(ctx, pid, SlowVideo(fail_on="p3", delay=0))
    await launch(c, pid, resume=True)
    await c.post(f"/api/projects/{pid}/steps/clips/cancel")
    total = await session.scalar(select(func.sum(CreditEntry.amount)).where(CreditEntry.user_id == uid))
    assert total == (await credits.balance(session, uid)).total
    assert pytest.approx(0) == await session.scalar(select(func.count()).select_from(CreditReservation)
                                                    .where(CreditReservation.status == "open"))
