import base64
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Project, Step
from app.services import steps
from tests.test_api_steps import new_project, set_status
from tests.test_launch_credits import add_scenes, client_project

LOCKED = "Réservé à l'abonnement"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


async def subscribe(session, user, days=30):
    user.subscription_ends_at = datetime.now(UTC) + timedelta(days=days)
    await session.commit()


async def ready_for_clips(session, pid):
    await add_scenes(session, pid, 2)
    await set_status(session, ["idea", "story", "script", "reference"], "approved")


async def test_locked_profile_refused_at_launch_and_by_price(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    await ready_for_clips(session, pid)
    for action in ("run", "price"):
        r = await c.post(f"/api/projects/{pid}/steps/clips/{action}", json={"model": "precision"})
        assert r.status_code == 403 and LOCKED in r.json()["detail"] and "Précision" in r.json()["detail"], action
    assert c.enqueued == []
    assert (await c.post(f"/api/projects/{pid}/steps/clips/run", json={"model": "fast"})).status_code == 202


async def test_saved_locked_profile_is_refused_too(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    await ready_for_clips(session, pid)
    step = await session.scalar(select(Step).where(Step.project_id == pid, Step.name == "clips"))
    step.params = {"provider": "comfyui", "model": "max"}
    await session.commit()
    r = await c.post(f"/api/projects/{pid}/steps/clips/run", json={})
    assert r.status_code == 403 and "Maximum" in r.json()["detail"]


async def test_subscriber_uses_locked_profiles_and_expired_subscription_does_not(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    await ready_for_clips(session, pid)
    await subscribe(session, user)
    assert (await c.post(f"/api/projects/{pid}/steps/clips/price", json={"model": "precision"})).status_code == 200
    await subscribe(session, user, days=-1)
    assert (await c.post(f"/api/projects/{pid}/steps/clips/price", json={"model": "precision"})).status_code == 403


async def test_project_owner_decides_not_the_admin_who_helps(api, api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    await ready_for_clips(session, pid)
    assert (await api.post(f"/api/projects/{pid}/steps/clips/price", json={"model": "precision"})).status_code == 403
    await subscribe(session, user)
    assert (await api.post(f"/api/projects/{pid}/steps/clips/price", json={"model": "precision"})).status_code == 200


async def test_admin_own_projects_use_everything(api, session):
    pid = await new_project(api)
    await ready_for_clips(session, pid)
    assert (await api.post(f"/api/projects/{pid}/steps/clips/price", json={"model": "max"})).status_code == 200


async def test_reference_generation_is_locked_without_subscription(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    await set_status(session, ["idea", "story", "script"], "approved")
    r = await c.post(f"/api/projects/{pid}/steps/reference/run", json={})
    assert r.status_code == 403 and LOCKED in r.json()["detail"] and "référence" in r.json()["detail"]
    await subscribe(session, user)
    assert (await c.post(f"/api/projects/{pid}/steps/reference/run", json={})).status_code == 202


async def test_reference_upload_cannot_bypass_the_lock(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    files = {"file": ("a.png", PNG, "image/png")}
    r = await c.post(f"/api/projects/{pid}/reference/upload", files=files)
    assert r.status_code == 403 and LOCKED in r.json()["detail"]
    await subscribe(session, user)
    assert (await c.post(f"/api/projects/{pid}/reference/upload", files=files)).status_code == 201


async def test_styles_are_locked_at_creation_and_edition(api_as, make_user, session):
    user = await make_user("s@x.fr")
    c = await api_as(user)
    body = {"title": "t", "theme": "chats", "platform": "tiktok", "target_duration_s": 30}
    r = await c.post("/api/projects", json={**body, "style": "anime"})
    assert r.status_code == 403 and LOCKED in r.json()["detail"]
    assert (await c.post("/api/projects", json={**body, "style": ""})).status_code == 201
    pid = (await c.get("/api/projects")).json()["items"][0]["id"]
    assert (await c.patch(f"/api/projects/{pid}", json={"style": "anime"})).status_code == 403
    assert (await c.patch(f"/api/projects/{pid}", json={"title": "autre"})).status_code == 200
    await subscribe(session, user)
    assert (await c.patch(f"/api/projects/{pid}", json={"style": "anime"})).status_code == 200
    assert (await c.post("/api/projects", json={**body, "style": "anime"})).status_code == 201


async def test_autopilot_without_subscription_skips_reference(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    await add_scenes(session, pid, 2)
    await set_status(session, ["idea", "story"], "approved")
    await set_status(session, ["script"], "awaiting_validation")
    script = await session.scalar(select(Step).where(Step.project_id == pid, Step.name == "script"))
    script.result = {"references": [{"id": "lea", "name": "Léa", "prompt": "woman"}]}
    (await session.get(Project, pid)).autopilot = True
    await session.commit()
    events = []

    async def publish(event):
        events.append(event)

    async def enqueue(*args, **kwargs):
        c.enqueued.append(args)

    await steps.advance(session, pid, "script", enqueue, publish)
    states = {s.name: s.status for s in await session.scalars(select(Step).where(Step.project_id == pid))}
    clips = await session.scalar(select(Step).where(Step.project_id == pid, Step.name == "clips"))
    assert states["reference"] == "approved" and states["clips"] == "running", clips.error
    assert events[-1]["step"] == "clips" and events[-1]["status"] == "running"
