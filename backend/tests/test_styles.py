"""Style visuel d'un projet : colonne, API et consigne injectée dans le prompt du script."""
from app.models import Project
from app.services import styles
from app.services.prompts import script_prompt
from tests.test_api_steps import set_status


async def create(api, **extra):
    return await api.post("/api/projects", json={"title": "t", "theme": "chats", **extra})


async def test_create_project_with_style(api):
    r = await create(api, style="anime")
    assert r.status_code == 201
    assert r.json()["style"] == "anime"


async def test_unknown_style_is_422(api):
    r = await create(api, style="cubisme")
    assert r.status_code == 422
    assert "Style inconnu" in r.text


async def test_default_style_is_empty(api):
    assert (await create(api)).json()["style"] == ""


async def test_styles_endpoint_lists_ids_and_labels(api):
    items = (await api.get("/api/styles")).json()
    assert [i["id"] for i in items] == ["realistic", "anime", "illustration"]
    assert all(i["label"] for i in items)


def test_script_prompt_includes_style_directive():
    with_style = script_prompt(Project(theme="x", platform="tiktok", target_duration_s=30, style="anime"), "angle")
    assert styles.directive("anime") in with_style and "Style visuel imposé" in with_style
    without = script_prompt(Project(theme="x", platform="tiktok", target_duration_s=30, style=""), "angle")
    assert "Style visuel imposé" not in without


async def test_style_change_marks_steps_stale(api, session):
    pid = (await create(api)).json()["id"]
    await set_status(session, ["idea"], "awaiting_validation")
    assert (await api.patch(f"/api/projects/{pid}", json={"style": "anime"})).status_code == 200
    steps = {s["name"]: s["status"] for s in (await api.get(f"/api/projects/{pid}")).json()["steps"]}
    assert steps["idea"] == "stale"
