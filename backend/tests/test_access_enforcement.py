import base64
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Project, Step
from app.services import steps
from tests.test_api_steps import new_project, set_status
from tests.test_launch_credits import add_scenes, client_project

LOCKED = "Réservé au forfait"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


async def subscribe(session, user, days=30, plan_id=None):
    user.subscription_ends_at, user.plan_id = datetime.now(UTC) + timedelta(days=days), plan_id
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


async def test_autopilot_without_subscription_generates_references(api_as, make_user, fund, session):
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
    assert states["reference"] == "running" and states["clips"] == "pending", clips.error
    assert events[-1]["step"] == "reference" and events[-1]["status"] == "running"


async def script_with_references(session, pid, count):
    await set_status(session, ["idea", "story"], "approved")
    await set_status(session, ["script"], "awaiting_validation")
    script = await session.scalar(select(Step).where(Step.project_id == pid, Step.name == "script"))
    script.result = {"references": [{"id": f"e{i}", "name": f"E{i}", "prompt": "p"} for i in range(count)]}
    await session.commit()


def upload_reference(c, pid, ref):
    return c.post(f"/api/projects/{pid}/reference/upload", files={"file": ("a.png", PNG, "image/png")}, data={"ref": ref})


async def test_reference_upload_over_limit_refused(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)

    def upload(ref):
        return upload_reference(c, pid, ref)
    assert (await upload("")).status_code == 201  # l'image du projet compte pour un élément
    assert (await upload("lea")).status_code == 201
    r = await upload("tom")
    assert r.status_code == 403 and "2 images de référence" in r.json()["detail"] and "Starter" in r.json()["detail"]
    await subscribe(session, user, plan_id="starter")
    assert (await upload("tom")).status_code == 201


async def test_reference_upload_replacing_existing_element_allowed(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    for ref in ("lea", "tom", "lea", "tom"):
        assert (await upload_reference(c, pid, ref)).status_code == 201, ref


async def test_reference_launch_over_limit_refused(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    await script_with_references(session, pid, 3)
    await set_status(session, ["script"], "approved")
    r = await c.post(f"/api/projects/{pid}/steps/reference/run", json={})
    assert r.status_code == 403 and "Limite de votre forfait" in r.json()["detail"]
    one = await c.post(f"/api/projects/{pid}/steps/reference/run", json={"reference_id": "e2"})
    assert one.status_code == 202  # un seul élément : dans la limite


async def test_autopilot_generates_only_allowed_references(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    await add_scenes(session, pid, 2)
    await script_with_references(session, pid, 3)
    (await session.get(Project, pid)).autopilot = True
    await session.commit()

    async def publish(event):
        pass

    async def enqueue(*args, **kwargs):
        c.enqueued.append(args)

    await steps.advance(session, pid, "script", enqueue, publish)
    states = {s.name: s.status for s in await session.scalars(select(Step).where(Step.project_id == pid))}
    assert states["reference"] == "running"
    assert c.enqueued[-1][1] == "reference" and c.enqueued[-1][3] == {"reference_ids": ["e0", "e1"]}


async def test_project_duration_over_limit_refused(api_as, make_user, session):
    user = await make_user("d@x.fr")
    c = await api_as(user)
    body = {"title": "t", "theme": "chats", "platform": "tiktok"}
    r = await c.post("/api/projects", json={**body, "target_duration_s": 60})
    assert r.status_code == 403 and r.json()["detail"] == "Limite de votre forfait : 30 s (forfait Starter : 60 s)"
    pid = (await c.post("/api/projects", json={**body, "target_duration_s": 30})).json()["id"]
    assert (await c.patch(f"/api/projects/{pid}", json={"target_duration_s": 90})).status_code == 403
    await subscribe(session, user, plan_id="starter")
    assert (await c.patch(f"/api/projects/{pid}", json={"target_duration_s": 60})).status_code == 200


async def test_generated_length_is_checked_at_launch(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    await add_scenes(session, pid, 10, duration=6.0)  # 60 s écrits par le chat du plan, projet de 30 s
    await set_status(session, ["idea", "story", "script", "reference"], "approved")
    for step in ("clips", "voice"):
        r = await c.post(f"/api/projects/{pid}/steps/{step}/price", json={})
        assert r.status_code == 403 and "Limite de votre forfait : 30 s" in r.json()["detail"], step


async def test_script_slightly_over_target_still_launches(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    await add_scenes(session, pid, 11, duration=3.0)  # 33 s : dans la tolérance du script
    await set_status(session, ["idea", "story", "script", "reference"], "approved")
    assert (await c.post(f"/api/projects/{pid}/steps/clips/price", json={})).status_code == 200
