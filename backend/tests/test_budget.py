"""Garde-fous de coût : budget par projet, plafond de durée, suppression sûre."""
import pytest

from app.models import Asset, MusicTrack, ProviderCall, Scene
from tests.test_api_steps import new_project, set_status, statuses
from tests.test_autopilot import autopilot, finish, queue, start  # noqa: F401  (fixtures et aides d'autopilot)
from tests.test_worker import events  # noqa: F401


async def spend(session, pid, usd):
    session.add(ProviderCall(project_id=pid, step="clips", provider="fal", model="kling", cost_usd=usd, status="ok"))
    await session.commit()


async def add_scenes(session, pid, count=2, duration_s=5):
    session.add_all(Scene(project_id=pid, position=i, voice_text="a", visual_prompt="b", duration_s=duration_s)
                    for i in range(1, count + 1))
    await session.commit()


async def set_budget(api, value):
    assert (await api.put("/api/settings", json={"project_budget_usd": value})).status_code == 200


# --- Réglage ---------------------------------------------------------------------------------------------------------

async def test_budget_defaults_to_ten_dollars_and_is_validated(api):
    assert (await api.get("/api/settings")).json()["project_budget_usd"] == "10"
    for bad in ("beaucoup", "-1", "inf", "nan"):
        assert (await api.put("/api/settings", json={"project_budget_usd": bad})).status_code == 400
    await set_budget(api, "2,5")  # virgule décimale acceptée
    assert (await api.get("/api/settings")).json()["project_budget_usd"] == "2,5"


# --- Lancement manuel ------------------------------------------------------------------------------------------------

async def test_launch_is_refused_once_the_budget_is_spent(api, session):
    pid = await new_project(api)
    await set_budget(api, "1")
    await spend(session, pid, 1.5)
    r = await api.post(f"/api/projects/{pid}/steps/idea/run", json={})
    assert r.status_code == 409 and "Budget" in r.json()["detail"] and "1.00 $" in r.json()["detail"]
    assert api.enqueued == [] and (await statuses(api, pid))["idea"] == "pending"


async def test_zero_budget_means_no_limit(api, session):
    pid = await new_project(api)
    await set_budget(api, "0")
    await spend(session, pid, 500)
    assert (await api.post(f"/api/projects/{pid}/steps/idea/run", json={})).status_code == 202


async def test_clips_launch_counts_the_estimated_cost(api, session):
    """Rien n'est encore dépensé, mais l'estimation des clips dépasse déjà le budget : refus avant tout appel payant."""
    pid = await new_project(api)
    await add_scenes(session, pid, count=4)
    await set_status(session, ["idea", "story", "script", "reference"], "approved")
    await set_budget(api, "0.01")
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={})
    assert r.status_code == 409 and "à venir" in r.json()["detail"]
    assert api.enqueued == []
    await set_budget(api, "1000")
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={})).status_code == 202


async def test_free_steps_still_run_when_the_budget_is_exceeded(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script", "reference", "clips", "voice"], "approved")
    await set_budget(api, "1")
    await spend(session, pid, 5)
    assert (await api.post(f"/api/projects/{pid}/steps/music/run", json={})).status_code == 202


# --- Autopilot -------------------------------------------------------------------------------------------------------

async def test_autopilot_stops_on_the_step_that_would_exceed_the_budget(api, session, queue, events):  # noqa: F811
    pid = await new_project(api)
    await set_budget(api, "1")
    await start(api, session, pid)
    await spend(session, pid, 2)
    await finish(pid, "idea")
    status = await statuses(api, pid)
    assert status["idea"] == "approved" and status["story"] == "failed" and queue == []
    assert await autopilot(api, pid) is False
    error = next(s for s in (await api.get(f"/api/projects/{pid}")).json()["steps"] if s["name"] == "story")["error"]
    assert "Budget" in error and events[-1]["status"] == "failed" and events[-1]["step"] == "story"


# --- Plafonds de saisie ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("field, value", [("target_duration_s", 181), ("theme", "x" * 2001)])
async def test_project_inputs_are_capped(api, field, value):
    body = {"title": "t", "theme": "", "platform": "tiktok", "target_duration_s": 30, field: value}
    assert (await api.post("/api/projects", json=body)).status_code == 422
    pid = await new_project(api)
    assert (await api.patch(f"/api/projects/{pid}", json={field: value})).status_code == 422
    assert (await api.post("/api/projects", json={**body, field: 180 if field == "target_duration_s" else "x"})
            ).status_code == 201


async def test_music_name_is_capped(api):
    r = await api.post("/api/music", data={"name": "x" * 201}, files={"file": ("a.mp3", b"abc", "audio/mpeg")})
    assert r.status_code == 422


# --- Suppression -----------------------------------------------------------------------------------------------------

async def test_delete_project_refused_while_a_step_runs(api, session):
    pid = await new_project(api)
    await set_status(session, ["clips"], "running")
    r = await api.delete(f"/api/projects/{pid}")
    assert r.status_code == 409 and "Génération en cours" in r.json()["detail"]
    assert (await api.get(f"/api/projects/{pid}")).status_code == 200


async def test_delete_project_removes_its_files(api, session):
    pid, other = await new_project(api), await new_project(api)
    for project_id, key in ((pid, "projects/a/clip.mp4"), (pid, "projects/a/voice.mp3"), (other, "projects/b/clip.mp4")):
        session.add(Asset(project_id=project_id, kind="clip", key=key, content_type="video/mp4"))
        await api.storage.put(key, b"x", "video/mp4")
    await session.commit()
    assert (await api.delete(f"/api/projects/{pid}")).status_code == 204
    assert set(api.storage.files) == {"projects/b/clip.mp4"}


async def test_delete_music_removes_its_file(api, session):
    track = MusicTrack(name="beat", key="music/beat.mp3")
    session.add(track)
    await session.commit()
    await api.storage.put("music/beat.mp3", b"x", "audio/mpeg")
    assert (await api.delete(f"/api/music/{track.id}")).status_code == 204
    assert api.storage.files == {}


async def test_project_detail_justifies_its_cost_by_step_and_exposes_the_budget(api, session):
    pid = (await api.post("/api/projects", json={"title": "t", "theme": "x", "platform": "tiktok",
                                                   "target_duration_s": 30})).json()["id"]
    session.add_all([
        ProviderCall(project_id=pid, step="clips", provider="fal", model="k", cost_usd=1.5, status="ok"),
        ProviderCall(project_id=pid, step="assist:voice_text", provider="gemini", model="g", cost_usd=0.01, status="ok"),
        ProviderCall(project_id=pid, step="assist:angle", provider="gemini", model="g", cost_usd=0.02, status="ok"),
        ProviderCall(project_id=pid, step="voice", provider="elevenlabs", model="m", cost_usd=0, status="error"),
    ])
    await session.commit()
    detail = (await api.get(f"/api/projects/{pid}")).json()
    assert detail["cost_by_step"] == {"clips": 1.5, "assist": 0.03}  # assistant regroupé, étapes à 0 $ omises
    assert detail["cost_usd"] == 1.53 and detail["budget_usd"] == 10  # réglage par défaut


async def test_a_gemini_start_image_adds_its_cost_to_the_launch_estimate(api, session):
    """Budget juste au-dessus du coût des clips : refusé avec l'image Gemini de chaque scène, accepté sans."""
    from app.providers.gemini import estimate_image_cost
    pid = await new_project(api)
    await add_scenes(session, pid, count=2)
    await session.execute(Asset.__table__.insert().values(project_id=pid, kind="reference", key="k",
                                                          content_type="image/png"))
    await session.commit()
    await set_status(session, ["idea", "story", "script", "reference"], "approved")
    query = {"provider": "comfyui", "model": "fast"}
    clips_usd = (await api.get(f"/api/projects/{pid}/estimate", params=query)).json()["cost_usd"]
    await set_budget(api, str(clips_usd + estimate_image_cost("gemini-3.1-flash-image")))  # entre les deux : 1 image de trop
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={**query, "start_image": "gemini"})
    assert r.status_code == 409 and "à venir" in r.json()["detail"] and api.enqueued == []
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json=query)).status_code == 202


async def test_client_project_has_credits_spent_no_dollars(api_as, make_user, fund, session):
    from app.models import CreditReservation
    from tests.test_launch_credits import client_project
    user, c, pid = await client_project(api_as, make_user, fund)
    session.add(ProviderCall(project_id=pid, step="clips", provider="fal", model="k", cost_usd=1.5, status="ok"))
    session.add_all([CreditReservation(user_id=user.id, project_id=pid, step="idea", amount=5, parts={}, status="closed", used=3),
                     CreditReservation(user_id=user.id, project_id=pid, step="clips", amount=40, parts={}, status="open")])
    await session.commit()
    detail = (await c.get(f"/api/projects/{pid}")).json()
    assert detail["credits_spent"] == 43
    assert detail["cost_usd"] is None and detail["cost_by_step"] is None and detail["budget_usd"] is None
    (item,) = (await c.get("/api/projects")).json()["items"]
    assert item["credits_spent"] == 43 and item["cost_usd"] is None
    assert (await c.get(f"/api/projects/{pid}/estimate")).json()["cost_usd"] is None
    session.add(Asset(project_id=pid, kind="reference", key="r.png", content_type="image/png",
                      meta={"model": "flux", "cost_usd": 0.04, "ref": "lea"}))
    await session.commit()
    (asset,) = (await c.get(f"/api/projects/{pid}")).json()["assets"]
    assert asset["meta"] == {"model": "flux", "ref": "lea"}  # pas de coût en dollars dans les fichiers


async def test_admin_project_keeps_dollars(api, session):
    pid = await new_project(api)
    detail = (await api.get(f"/api/projects/{pid}")).json()
    assert detail["cost_usd"] == 0 and detail["budget_usd"] is not None and detail["credits_spent"] is None
