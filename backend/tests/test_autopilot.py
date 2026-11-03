"""Mode automatique : endpoints `/autopilot` et chaînage des étapes par le worker."""
import asyncio

import pytest
from sqlalchemy import select

from app import worker
from app.models import MusicTrack, Project, ProviderCall, Step
from app.providers.fal import FAL_KEY_MISSING
from app.services import steps as step_service
from tests.test_api_steps import new_project, set_status, statuses
from tests.test_worker import events  # noqa: F401  (fixture : worker branché sur la base de test)


@pytest.fixture
def queue(events, monkeypatch):  # noqa: F811
    """File simulée du worker : jobs enfilés par le chaînage (projet, étape, scène)."""
    jobs = []

    async def enqueue(project_id, step, scene_id=None, overrides=None, *, timeout=None):
        jobs.append((project_id, step))

    monkeypatch.setattr(worker, "enqueue_step", enqueue)
    return jobs


async def project(session, pid):
    return await session.get(Project, pid, populate_existing=True)


async def autopilot(api, pid):
    return (await api.get(f"/api/projects/{pid}")).json()["autopilot"]


async def start(api, session, pid, approved=(), running="idea"):
    """Autopilot lancé (`idea` en cours) ; ou, pour simuler un enchaînement avancé, `approved` validées et `running`
    en cours."""
    assert (await api.post(f"/api/projects/{pid}/autopilot")).status_code == 202
    await set_status(session, approved, "approved")
    await set_status(session, [running], "running")


async def finish(pid, step, status="awaiting_validation"):
    """Job `step` exécuté par le worker, le pipeline (simulé) terminant l'étape avec `status`."""
    async def done(ctx, project_id, name, scene_id):
        await ctx.session.execute(Step.__table__.update().where(Step.project_id == project_id, Step.name == name)
                                  .values(status=status))
        await ctx.session.commit()

    worker.run_step = done
    await worker.run_step_job({}, pid, step, None)


@pytest.fixture(autouse=True)
def restore_run_step():
    original = worker.run_step
    yield
    worker.run_step = original


# --- API ---------------------------------------------------------------------------------------------------------

async def test_post_autopilot_launches_idea_and_sets_flag(api):
    pid = await new_project(api)
    assert await autopilot(api, pid) is False
    assert (await api.post(f"/api/projects/{pid}/autopilot")).status_code == 202
    assert api.enqueued == [(pid, "idea", None)]
    assert await autopilot(api, pid) is True and (await statuses(api, pid))["idea"] == "running"


async def test_post_autopilot_refused_while_a_step_runs(api, session):
    pid = await new_project(api)
    await set_status(session, ["voice"], "running")
    assert (await api.post(f"/api/projects/{pid}/autopilot")).status_code == 409
    assert api.enqueued == [] and await autopilot(api, pid) is False


async def test_post_autopilot_twice_enqueues_once(api):
    pid = await new_project(api)
    assert (await api.post(f"/api/projects/{pid}/autopilot")).status_code == 202
    assert (await api.post(f"/api/projects/{pid}/autopilot")).status_code == 409
    assert api.enqueued == [(pid, "idea", None)]


async def test_post_autopilot_with_queue_down_fails_idea_and_clears_flag(api):
    from app.main import app
    from app.queue import get_enqueue

    async def broken(*args, **kwargs):
        raise ConnectionError("redis down")

    app.dependency_overrides[get_enqueue] = lambda: broken
    pid = await new_project(api)
    assert (await api.post(f"/api/projects/{pid}/autopilot")).status_code == 503
    assert (await statuses(api, pid))["idea"] == "failed" and await autopilot(api, pid) is False


async def test_autopilot_unknown_project_is_404(api):
    assert (await api.post("/api/projects/999/autopilot")).status_code == 404
    assert (await api.delete("/api/projects/999/autopilot")).status_code == 404


async def test_delete_autopilot_clears_flag_and_keeps_running_step(api):
    pid = await new_project(api)
    await api.post(f"/api/projects/{pid}/autopilot")
    assert (await api.delete(f"/api/projects/{pid}/autopilot")).status_code == 204
    assert await autopilot(api, pid) is False and (await statuses(api, pid))["idea"] == "running"


async def test_editing_final_result_keeps_autopilot_flag(api, session):
    pid = await new_project(api)
    await api.post(f"/api/projects/{pid}/autopilot")
    await set_status(session, ["idea"], "approved")
    await set_status(session, ["final"], "awaiting_validation")
    meta = {"title": "T", "description": "D", "hashtags": [], "autopilot": False}
    assert (await api.patch(f"/api/projects/{pid}/steps/final", json={"result": meta})).status_code == 200
    data = (await api.get(f"/api/projects/{pid}")).json()
    assert data["autopilot"] is True and data["metadata_json"]["title"] == "T"


# --- Chaînage par le worker ------------------------------------------------------------------------------------------

async def test_finished_step_is_approved_and_next_one_launched(api, session, queue, events):  # noqa: F811
    pid = await new_project(api)
    await start(api, session, pid)
    await finish(pid, "idea")
    status = await statuses(api, pid)
    assert status["idea"] == "approved" and status["story"] == "running"
    assert queue == [(pid, "story")]
    assert events == [{"project_id": pid, "step": "story", "status": "running", "error": None}]


async def test_step_approved_by_hand_before_worker_still_chains(api, session, queue):
    pid = await new_project(api)
    await start(api, session, pid)
    await finish(pid, "idea", status="approved")
    assert (await statuses(api, pid))["story"] == "running" and queue == [(pid, "story")]
    assert await autopilot(api, pid) is True


async def test_approved_step_whose_next_is_running_launches_nothing(api, session, queue):
    pid = await new_project(api)
    await start(api, session, pid, ["idea"], "story")
    await finish(pid, "idea", status="approved")
    assert queue == [] and await autopilot(api, pid) is True


async def test_reference_is_skipped_after_script(api, session, queue):
    pid = await new_project(api)
    await start(api, session, pid, ["idea", "story"], "script")
    await finish(pid, "script")
    status = await statuses(api, pid)
    assert status["script"] == "approved" and status["reference"] == "approved" and status["clips"] == "running"
    assert queue == [(pid, "clips")]


async def test_reference_runs_when_script_lists_recurring_elements(api, session, queue):
    pid = await new_project(api)
    await start(api, session, pid, ["idea", "story"], "script")
    await session.execute(Step.__table__.update().where(Step.project_id == pid, Step.name == "script")
                          .values(result={"references": [{"id": "cat", "prompt": "a ginger cat"}]}))
    await session.commit()
    await finish(pid, "script")
    status = await statuses(api, pid)
    assert status["script"] == "approved" and status["reference"] == "running" and status["clips"] == "pending"
    assert queue == [(pid, "reference")]
    await finish(pid, "reference")
    assert (await statuses(api, pid))["clips"] == "running" and queue[-1] == (pid, "clips")


async def chain_to_music(api, session):
    pid = await new_project(api)
    await start(api, session, pid, ["idea", "story", "script", "reference", "clips"], "voice")
    await finish(pid, "voice")
    return pid


async def music_params(session, pid):
    return (await session.scalar(select(Step).where(Step.project_id == pid, Step.name == "music")
                                 .execution_options(populate_existing=True))).params


async def test_music_uses_first_library_track(api, session, queue):
    session.add_all([MusicTrack(name="b", key="m/b.mp3"), MusicTrack(name="a", key="m/a.mp3")])
    await session.commit()
    first = await session.scalar(select(MusicTrack.id).order_by(MusicTrack.id))
    pid = await chain_to_music(api, session)
    assert queue == [(pid, "music")] and (await music_params(session, pid)) == {"track_id": first}


async def test_music_without_library_runs_without_track(api, session, queue):
    pid = await chain_to_music(api, session)
    assert queue == [(pid, "music")] and (await music_params(session, pid)) == {}


async def test_music_keeps_a_chosen_track(api, session, queue):
    session.add(MusicTrack(name="a", key="m/a.mp3"))
    await session.commit()
    pid = await new_project(api)
    await session.execute(Step.__table__.update().where(Step.name == "music").values(params={"track_id": 42}))
    await session.commit()
    await start(api, session, pid, ["idea", "story", "script", "reference", "clips"], "voice")
    await finish(pid, "voice")
    assert (await music_params(session, pid)) == {"track_id": 42}


async def test_final_approved_marks_project_done_and_stops(api, session, queue):
    pid = await new_project(api)
    await start(api, session, pid, ["idea", "story", "script", "reference", "clips", "voice", "music", "montage"], "final")
    await finish(pid, "final")
    p = await project(session, pid)
    assert (await statuses(api, pid))["final"] == "approved" and p.status == "done" and p.autopilot is False
    assert queue == [] and "autopilot" not in p.metadata_json


async def test_failed_step_stops_autopilot_and_stays_relaunchable(api, session, queue):
    pid = await new_project(api)
    await start(api, session, pid)
    await finish(pid, "idea", "failed")
    assert queue == [] and await autopilot(api, pid) is False
    assert (await api.post(f"/api/projects/{pid}/steps/idea/run", json={})).status_code == 202


async def test_stopped_autopilot_does_not_chain(api, session, queue):
    pid = await new_project(api)
    await start(api, session, pid)
    assert (await api.delete(f"/api/projects/{pid}/autopilot")).status_code == 204
    await finish(pid, "idea")
    assert queue == [] and (await statuses(api, pid))["idea"] == "awaiting_validation"


async def test_manual_mode_never_chains(api, session, queue):
    pid = await new_project(api)
    await set_status(session, ["idea"], "running")
    await finish(pid, "idea")
    assert queue == [] and (await statuses(api, pid))["idea"] == "awaiting_validation"


async def test_chaining_twice_launches_next_step_once(api, session, queue):
    pid = await new_project(api)
    await start(api, session, pid)
    await set_status(session, ["idea"], "awaiting_validation")
    async with worker.SessionFactory() as s1, worker.SessionFactory() as s2:
        await asyncio.gather(step_service.advance(s1, pid, "idea", worker.enqueue_step, worker.publish_event),
                             step_service.advance(s2, pid, "idea", worker.enqueue_step, worker.publish_event))
    assert queue == [(pid, "story")] and await autopilot(api, pid) is True


async def test_chaining_with_queue_down_fails_next_step_and_stops(api, session, events, monkeypatch):  # noqa: F811
    async def broken(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(worker, "enqueue_step", broken)
    pid = await new_project(api)
    await start(api, session, pid)
    await finish(pid, "idea")
    status = await statuses(api, pid)
    assert status["idea"] == "approved" and status["story"] == "failed" and await autopilot(api, pid) is False


async def test_interrupted_job_stops_autopilot(api, session, queue):
    pid = await new_project(api)
    await api.post(f"/api/projects/{pid}/autopilot")

    async def slow(ctx, project_id, step, scene_id):
        await asyncio.sleep(60)

    worker.run_step = slow
    await worker.run_step_job({}, pid, "idea", None, None, 0.05)
    assert (await statuses(api, pid))["idea"] == "failed" and await autopilot(api, pid) is False
    assert queue == []


async def test_worker_restart_stops_autopilot(api, session, queue):
    pid = await new_project(api)
    await api.post(f"/api/projects/{pid}/autopilot")
    await worker.startup({})
    assert (await statuses(api, pid))["idea"] == "failed" and await autopilot(api, pid) is False


async def test_autopilot_stops_before_clips_when_the_video_model_is_unavailable(api, session, queue, events,  # noqa: F811
                                                                                 monkeypatch):
    """Même contrôle que `POST …/steps/clips/run` : modèle grisé, l'autopilot s'arrête au lancement des clips (aucun
    job), la raison est affichée sur l'étape, relançable une fois le modèle disponible."""
    from app.config import settings

    monkeypatch.setattr(settings, "fake_providers", False)  # vrai provider fal, sans clé
    assert (await api.put("/api/settings", json={"default_video_provider": "fal", "default_video_model": "kling"})
            ).status_code == 200
    pid = await new_project(api)
    await start(api, session, pid, ["idea", "story"], "script")
    await finish(pid, "script")
    status = await statuses(api, pid)
    assert status["script"] == "approved" and status["clips"] == "failed" and queue == []
    assert await autopilot(api, pid) is False
    clips = next(s for s in (await api.get(f"/api/projects/{pid}")).json()["steps"] if s["name"] == "clips")
    assert clips["error"] == FAL_KEY_MISSING
    assert events[-1] == {"project_id": pid, "step": "clips", "status": "failed", "error": FAL_KEY_MISSING}


async def test_autopilot_stops_before_clips_when_the_video_model_is_unknown(api, session, queue, events):  # noqa: F811
    pid = await new_project(api)
    await session.execute(Step.__table__.update().where(Step.project_id == pid, Step.name == "clips")
                          .values(params={"provider": "comfyui", "model": "turbo"}))
    await session.commit()
    await start(api, session, pid, ["idea", "story"], "script")
    await finish(pid, "script")
    assert (await statuses(api, pid))["clips"] == "failed" and queue == [] and await autopilot(api, pid) is False
    assert events[-1]["error"] == "Modèle vidéo inconnu pour comfyui : turbo"


async def test_autopilot_launches_clips_when_comfyui_is_only_busy(api, session, queue, monkeypatch):
    from tests.test_video_models import BUSY, comfy_availability

    await comfy_availability(monkeypatch, BUSY)
    pid = await new_project(api)
    await start(api, session, pid, ["idea", "story"], "script")
    await finish(pid, "script")
    assert (await statuses(api, pid))["clips"] == "running" and queue == [(pid, "clips")]
    assert await autopilot(api, pid) is True


# --- Autopilot borné : génération du plan (idea → story, ou idea → script pour un projet existant) ---------------------

async def test_bounded_autopilot_stops_at_story_on_a_new_project(api, session, queue, events):  # noqa: F811
    pid = await new_project(api)
    assert (await api.post(f"/api/projects/{pid}/plan/generate")).status_code == 202
    await finish(pid, "idea")
    assert (await statuses(api, pid))["story"] == "running" and queue == [(pid, "story")]
    await finish(pid, "story")
    status = await statuses(api, pid)
    p = await project(session, pid)
    assert status["idea"] == "approved" and status["story"] == "awaiting_validation" and status["script"] == "pending"
    assert p.autopilot is False and p.autopilot_until is None
    assert queue == [(pid, "story")]  # ni script ni clips enfilés
    assert events[-1] == {"project_id": pid, "step": "story", "status": "awaiting_validation", "error": None}


async def test_bounded_autopilot_keeps_the_script_bound_on_an_existing_project(api, session, queue):  # noqa: F811
    pid = await new_project(api)
    await set_status(session, ["story"], "approved")  # projet existant : story validée et vide (ancien chemin)
    assert (await api.post(f"/api/projects/{pid}/plan/generate")).status_code == 202
    assert (await project(session, pid)).autopilot_until == "script"
    await finish(pid, "idea")
    assert queue == [(pid, "script")]
    await finish(pid, "script")
    status = await statuses(api, pid)
    assert status["script"] == "awaiting_validation" and (await project(session, pid)).autopilot is False


async def test_plan_generate_endpoint_returns_202_and_runs_idea(api, session):
    pid = await new_project(api)
    assert (await api.post(f"/api/projects/{pid}/plan/generate")).status_code == 202
    assert api.enqueued == [(pid, "idea", None)]
    assert (await statuses(api, pid))["idea"] == "running"
    assert (await project(session, pid)).autopilot_until == "story"


async def test_plan_generate_409_when_step_running(api, session):
    pid = await new_project(api)
    await set_status(session, ["voice"], "running")
    assert (await api.post(f"/api/projects/{pid}/plan/generate")).status_code == 409
    assert api.enqueued == []


async def test_replace_metadata_keeps_bounds(api, session):
    pid = await new_project(api)
    await api.post(f"/api/projects/{pid}/plan/generate")
    p = await project(session, pid)
    p.replace_metadata({"title": "T"})
    assert p.autopilot is True and p.autopilot_until == "story" and p.metadata_json["title"] == "T"
    p.autopilot = False
    assert p.autopilot_until is None


# --- Images de référence lancées dès que le script est écrit ---------------------------------------------------------

REFERENCES = {"references": [{"id": "cat", "prompt": "a ginger cat"}]}


async def script_result(session, pid, result):
    await session.execute(Step.__table__.update().where(Step.project_id == pid, Step.name == "script")
                          .values(result=result))
    await session.commit()


async def test_script_done_starts_reference(api, session, queue):
    pid = await new_project(api)
    await set_status(session, ["idea", "story"], "approved")
    await set_status(session, ["script"], "running")
    await script_result(session, pid, REFERENCES)
    await finish(pid, "script")
    status = await statuses(api, pid)
    assert status["script"] == "awaiting_validation" and status["reference"] == "running"
    assert queue == [(pid, "reference")]


async def test_script_without_references_starts_nothing(api, session, queue):
    pid = await new_project(api)
    await set_status(session, ["idea", "story"], "approved")
    await set_status(session, ["script"], "running")
    await finish(pid, "script")
    assert queue == [] and (await statuses(api, pid))["reference"] == "pending"


async def test_reference_start_refused_by_budget_is_silent(api, session, queue):
    pid = await new_project(api)
    await set_status(session, ["idea", "story"], "approved")
    await set_status(session, ["script"], "awaiting_validation")
    await script_result(session, pid, REFERENCES)
    await api.put("/api/settings", json={"project_budget_usd": "0.01"})
    await session.execute(ProviderCall.__table__.insert().values(project_id=pid, step="script", provider="gemini",
                                                                 model="m", cost_usd=1, status="ok"))
    await session.commit()
    assert await step_service.start_reference_after_script(session, pid, worker.enqueue_step, worker.publish_event) is False
    status = await statuses(api, pid)
    assert status["script"] == "awaiting_validation" and status["reference"] == "pending" and queue == []


async def test_autopilot_does_not_double_start_reference(api, session, queue):
    pid = await new_project(api)
    await start(api, session, pid, ["idea", "story"], "script")
    await script_result(session, pid, REFERENCES)
    await finish(pid, "script")
    assert queue == [(pid, "reference")]


async def test_reference_start_crash_does_not_fail_script_job(api, session, queue, monkeypatch):
    """Erreur inattendue au lancement des références : le job du script réussit et la file du projet repart."""
    async def crash(*args):
        raise RuntimeError("boum")

    dispatched = []

    async def next_in_queue(project_id):
        dispatched.append(project_id)

    monkeypatch.setattr(worker, "start_reference_after_script", crash)
    monkeypatch.setattr(worker, "_next_in_queue", next_in_queue)
    pid = await new_project(api)
    await set_status(session, ["idea", "story"], "approved")
    await set_status(session, ["script"], "running")
    await finish(pid, "script")
    assert dispatched == [pid] and (await statuses(api, pid))["script"] == "awaiting_validation"
