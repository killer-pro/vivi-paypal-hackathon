from app.app_settings import AppSettings
from app.services.queue_runs import dispatch_queue
from tests.test_access_enforcement import subscribe
from tests.test_api_steps import new_project, set_status, statuses
from tests.test_launch_credits import add_scenes, client_project


async def clips_running(api, session):
    """Projet dont les clips tournent (scènes et script validés), de quoi mettre des demandes en file."""
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    await AppSettings(session).set("default_video_provider", "comfyui")
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={})).status_code == 202
    api.enqueued.clear()
    return pid


async def queue(api, pid):
    return [(q["step"], q["scene_id"]) for q in (await api.get(f"/api/projects/{pid}")).json()["queue"]]


async def test_scene_run_while_clips_run_is_queued_then_started(api, session):
    pid = await clips_running(api, session)
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": 7})
    assert r.status_code == 202 and r.json() == {"queued": True}
    assert await queue(api, pid) == [("clips", 7)] and api.enqueued == []
    await set_status(session, ["clips"], "awaiting_validation")  # la génération en cours se termine
    events = []

    async def publish(event):
        events.append(event)

    await dispatch_queue(session, pid, api_enqueue(api), publish)
    assert api.enqueued == [(pid, "clips", 7)] and await queue(api, pid) == []
    assert (await statuses(api, pid))["clips"] == "running"
    assert events == [{"project_id": pid, "step": "clips", "status": "running", "error": None}]


def api_enqueue(api):
    async def enqueue(project_id, step, scene_id=None, overrides=None, *, timeout=None):
        api.enqueued.append((project_id, step, scene_id) + ((overrides,) if overrides else ()))

    return enqueue


async def client_clips_running(api_as, make_user, fund, session):
    """Projet d'un client dont les clips tournent, et les scènes de quoi mettre des demandes en file."""
    user, c, pid = await client_project(api_as, make_user, fund)
    scene_ids = await add_scenes(session, pid, 4)
    await set_status(session, ["idea", "story", "script", "reference"], "approved")
    await AppSettings(session).set("default_video_provider", "comfyui")
    assert (await c.post(f"/api/projects/{pid}/steps/clips/run", json={})).status_code == 202
    return user, c, pid, scene_ids


async def test_free_queue_holds_one_request(api_as, make_user, fund, session):
    user, c, pid, scenes = await client_clips_running(api_as, make_user, fund, session)
    assert (await c.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": scenes[0]})).status_code == 202
    assert (await c.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": scenes[0]})).json() == {"queued": True}
    full = await c.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": scenes[1]})
    detail = full.json()["detail"]
    assert full.status_code == 409 and "File d'attente pleine" in detail and "forfait Starter : 2 demandes en file" in detail


async def test_starter_queue_holds_two(api_as, make_user, fund, session):
    user, c, pid, scenes = await client_clips_running(api_as, make_user, fund, session)
    await subscribe(session, user, plan_id="starter")
    for scene_id in scenes[:2]:
        assert (await c.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": scene_id})).status_code == 202
    assert len(await queue(c, pid)) == 2
    assert (await c.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": scenes[2]})).status_code == 409


async def test_admin_queue_is_not_limited(api, session):
    pid = await clips_running(api, session)
    for scene_id in range(1, 11):
        assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": scene_id})).status_code == 202
    assert len(await queue(api, pid)) == 10


async def test_remove_from_queue(api, session):
    pid = await clips_running(api, session)
    await api.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": 3})
    (item,) = (await api.get(f"/api/projects/{pid}")).json()["queue"]
    assert (await api.delete(f"/api/projects/{pid}/queue/{item['id']}")).status_code == 204
    assert await queue(api, pid) == []
    assert (await api.delete(f"/api/projects/{pid}/queue/{item['id']}")).status_code == 404


async def test_full_run_of_the_running_step_is_refused_not_queued(api, session):
    pid = await clips_running(api, session)
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={})).status_code == 409
    assert await queue(api, pid) == []


async def test_cancel_starts_the_next_queued_run(api, session):
    pid = await clips_running(api, session)
    await api.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": 4})
    assert (await api.post(f"/api/projects/{pid}/steps/clips/cancel")).status_code == 202
    assert api.enqueued == [(pid, "clips", 4)] and await queue(api, pid) == []


async def test_impossible_queued_run_is_dropped_with_its_reason(api, session):
    pid = await clips_running(api, session)
    await api.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": 4})
    await set_status(session, ["clips"], "awaiting_validation")
    await set_status(session, ["script"], "stale")  # le script a changé entre-temps : les clips ne peuvent plus partir
    events = []

    async def publish(event):
        events.append(event)

    await dispatch_queue(session, pid, api_enqueue(api), publish)
    assert await queue(api, pid) == [] and api.enqueued == []
    assert events[0]["status"] == "failed" and "précédente" in events[0]["error"]
