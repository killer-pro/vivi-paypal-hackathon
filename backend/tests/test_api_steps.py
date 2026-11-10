import pytest

from app.api.events import visible_events
from app.api.projects import get_registry
from app.main import app
from app.models import Asset, ProviderCall, Scene, Step
from app.providers.fal import FAL_KEY_MISSING, FalProvider


async def new_project(api):
    r = await api.post("/api/projects", json={"title": "t", "theme": "chats", "platform": "tiktok", "target_duration_s": 30})
    assert r.status_code == 201
    return r.json()["id"]


async def statuses(api, pid):
    return {s["name"]: s["status"] for s in (await api.get(f"/api/projects/{pid}")).json()["steps"]}


async def set_status(session, names, status):
    await session.execute(Step.__table__.update().where(Step.name.in_(names)).values(status=status))
    await session.commit()


async def test_create_project_creates_nine_pending_steps(api):
    pid = await new_project(api)
    data = (await api.get(f"/api/projects/{pid}")).json()
    assert [s["name"] for s in data["steps"]] == ["idea", "story", "script", "reference", "clips", "voice", "music", "montage", "final"]
    assert {s["status"] for s in data["steps"]} == {"pending"}


async def test_list_and_delete_projects(api):
    pid = await new_project(api)
    listed = (await api.get("/api/projects")).json()["items"]
    assert [(p["id"], p["current_step"], p["cost_usd"]) for p in listed] == [(pid, "idea", 0)]
    assert (await api.delete(f"/api/projects/{pid}")).status_code == 204
    assert (await api.get(f"/api/projects/{pid}")).status_code == 404


async def test_list_exposes_card_fields(api, session):
    """Carte d'accueil : statut de l'étape courante, autopilot et vignette (rendu, sinon clip choisi de la 1re scène)."""
    pid = await new_project(api)
    listed = (await api.get("/api/projects")).json()["items"][0]
    assert (listed["current_status"], listed["autopilot"], listed["thumbnail_url"]) == ("pending", False, None)
    assert listed["render_asset_id"] is None

    first, second = Scene(project_id=pid, position=0), Scene(project_id=pid, position=1)
    session.add_all([first, second])
    await session.flush()
    clips = [Asset(project_id=pid, scene_id=s.id, kind="clip", key=f"c{s.position}", content_type="video/mp4")
             for s in (second, first)]
    session.add_all(clips)
    await session.flush()
    second.selected_clip_asset_id, first.selected_clip_asset_id = clips[0].id, clips[1].id
    await session.commit()
    assert (await api.get("/api/projects")).json()["items"][0]["thumbnail_url"] == "http://mem/c0"

    render = Asset(project_id=pid, kind="render", key="r.mp4", content_type="video/mp4")
    session.add(render)
    await session.commit()
    listed = (await api.get("/api/projects")).json()["items"][0]
    assert (listed["thumbnail_url"], listed["render_asset_id"]) == ("http://mem/r.mp4", render.id)


async def test_current_step_skips_pending_optional_reference(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    assert (await api.get(f"/api/projects/{pid}")).json()["current_step"] == "clips"
    await set_status(session, ["reference"], "awaiting_validation")
    assert (await api.get("/api/projects")).json()["items"][0]["current_step"] == "reference"
    await set_status(session, ["reference", "clips", "voice", "music", "montage", "final"], "approved")
    assert (await api.get("/api/projects")).json()["items"][0]["current_step"] is None


async def test_cannot_run_step_before_previous_approved(api):
    pid = await new_project(api)
    assert (await api.post(f"/api/projects/{pid}/steps/script/run", json={})).status_code == 409


async def test_run_then_double_click_is_409_and_enqueues_once(api):
    pid = await new_project(api)
    assert (await api.post(f"/api/projects/{pid}/steps/idea/run", json={})).status_code == 202
    assert (await api.post(f"/api/projects/{pid}/steps/idea/run", json={})).status_code == 409
    assert api.enqueued == [(pid, "idea", None)]


async def test_run_marks_completed_downstream_stale(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    await set_status(session, ["clips"], "awaiting_validation")
    await set_status(session, ["voice"], "failed")
    assert (await api.post(f"/api/projects/{pid}/steps/script/run", json={})).status_code == 202
    status = await statuses(api, pid)
    assert status["script"] == "running" and status["clips"] == "stale"
    assert status["voice"] == "failed" and status["music"] == "pending" and status["idea"] == "approved"


async def test_voice_runs_while_clips_run_and_clips_do_not_stale_it(api, session):
    from app.app_settings import AppSettings

    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    await AppSettings(session).set("default_video_provider", "comfyui")
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={})).status_code == 202
    assert (await api.post(f"/api/projects/{pid}/steps/voice/run", json={})).status_code == 202
    status = await statuses(api, pid)
    assert status["clips"] == "running" and status["voice"] == "running"
    await set_status(session, ["clips"], "approved")
    await set_status(session, ["voice"], "awaiting_validation")
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={})).status_code == 202
    assert (await statuses(api, pid))["voice"] == "awaiting_validation"  # pas périmée par la régénération des clips


async def test_run_with_queue_down_marks_step_failed(api):
    from app.main import app
    from app.queue import get_enqueue

    async def broken(*args, **kwargs):
        raise ConnectionError("redis down")

    app.dependency_overrides[get_enqueue] = lambda: broken
    pid = await new_project(api)
    assert (await api.post(f"/api/projects/{pid}/steps/idea/run", json={})).status_code == 503
    assert (await statuses(api, pid))["idea"] == "failed"


async def test_approve_requires_awaiting_validation(api, session):
    pid = await new_project(api)
    assert (await api.post(f"/api/projects/{pid}/steps/idea/approve")).status_code == 409
    await set_status(session, ["idea"], "awaiting_validation")
    assert (await api.post(f"/api/projects/{pid}/steps/idea/approve")).status_code == 200


async def test_optional_reference_can_be_skipped(api, session):
    pid = await new_project(api)
    assert (await api.post(f"/api/projects/{pid}/steps/reference/approve")).status_code == 200
    assert (await statuses(api, pid))["reference"] == "approved"


async def test_editing_script_marks_downstream_stale_and_keeps_assets(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script", "clips", "voice"], "approved")
    session.add(Asset(project_id=pid, kind="clip", key="k", content_type="video/mp4"))
    await session.commit()
    r = await api.patch(f"/api/projects/{pid}/steps/script", json={"scenes": [{"voice_text": "a", "visual_prompt": "b", "duration_s": 3}]})
    assert r.status_code == 200
    data = (await api.get(f"/api/projects/{pid}")).json()
    status = {s["name"]: s["status"] for s in data["steps"]}
    assert status["script"] == "approved" and status["clips"] == "stale" and status["voice"] == "stale"
    assert len(data["assets"]) == 1 and data["assets"][0]["url"] == "http://mem/k"
    assert [(s["position"], s["voice_text"]) for s in data["scenes"]] == [(1, "a")]


async def test_editing_scenes_keeps_ids_of_existing_scenes(api, session):
    pid = await new_project(api)
    keep, drop = (Scene(project_id=pid, position=i, voice_text="old", visual_prompt="v", duration_s=3) for i in (1, 2))
    session.add_all([keep, drop])
    await session.commit()
    r = await api.patch(f"/api/projects/{pid}/steps/script", json={"scenes": [
        {"voice_text": "new", "visual_prompt": "x", "duration_s": 2},
        {"id": keep.id, "voice_text": "edited", "visual_prompt": "v", "duration_s": 4}]})
    assert r.status_code == 200
    scenes = (await api.get(f"/api/projects/{pid}")).json()["scenes"]
    assert [(s["position"], s["voice_text"]) for s in scenes] == [(1, "new"), (2, "edited")]
    assert scenes[1]["id"] == keep.id and drop.id not in [s["id"] for s in scenes]


async def test_patch_params_and_scenes_only_on_script(api):
    pid = await new_project(api)
    r = await api.patch(f"/api/projects/{pid}/steps/clips", json={"params": {"provider": "fal"}})
    assert r.status_code == 200
    clips = next(s for s in (await api.get(f"/api/projects/{pid}")).json()["steps"] if s["name"] == "clips")
    assert clips["params"] == {"provider": "fal"}
    assert (await api.patch(f"/api/projects/{pid}/steps/clips", json={"scenes": []})).status_code == 422


async def test_select_clip_rejects_foreign_asset(api, session):
    pid = await new_project(api)
    r = await api.post(f"/api/projects/{pid}/scenes/999/select-clip", json={"asset_id": 1})
    assert r.status_code == 404


async def scene_with_clip(session, pid):
    scene = Scene(project_id=pid, position=1, voice_text="a", visual_prompt="b", duration_s=3)
    session.add(scene)
    await session.flush()
    clip = Asset(project_id=pid, scene_id=scene.id, kind="clip", key="c", content_type="video/mp4")
    session.add(clip)
    await session.commit()
    return f"/api/projects/{pid}/scenes/{scene.id}/select-clip", clip


async def test_select_clip_of_scene(api, session):
    pid = await new_project(api)
    url, clip = await scene_with_clip(session, pid)
    voice = Asset(project_id=pid, scene_id=clip.scene_id, kind="voice", key="v", content_type="audio/mpeg")
    session.add(voice)
    await session.commit()
    assert (await api.post(url, json={"asset_id": voice.id})).status_code == 404
    assert (await api.post(url, json={"asset_id": clip.id})).status_code == 200
    scenes = (await api.get(f"/api/projects/{pid}")).json()["scenes"]
    assert scenes[0]["selected_clip_asset_id"] == clip.id


async def test_select_clip_marks_montage_and_final_stale_only(api, session):
    pid = await new_project(api)
    url, clip = await scene_with_clip(session, pid)
    await set_status(session, ["idea", "story", "script", "clips", "voice", "music", "montage"], "approved")
    await set_status(session, ["final"], "awaiting_validation")
    assert (await api.post(url, json={"asset_id": clip.id})).status_code == 200
    status = await statuses(api, pid)
    assert status["montage"] == "stale" and status["final"] == "stale"
    assert {status[n] for n in ("idea", "story", "script", "clips", "voice", "music")} == {"approved"}


async def test_stale_montage_must_be_rerun_before_approval(api, session):
    """Un montage périmé est une vidéo bâtie sur d'anciens clips (ou voix) : le valider tel quel exporterait l'ancien rendu."""
    pid = await new_project(api)
    url, clip = await scene_with_clip(session, pid)
    await set_status(session, ["idea", "story", "script", "clips", "voice", "music", "montage"], "approved")
    assert (await api.post(url, json={"asset_id": clip.id})).status_code == 200
    r = await api.post(f"/api/projects/{pid}/steps/montage/approve")
    assert r.status_code == 409 and "relancez" in r.json()["detail"]
    assert (await statuses(api, pid))["montage"] == "stale"


async def test_approving_clips_approves_the_reference_images_awaiting_review(api, session):
    """L'étape facultative des références n'a pas de bouton « Valider » : valider les clips, qui s'en servent, la valide."""
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    await set_status(session, ["reference", "clips"], "awaiting_validation")
    assert (await api.post(f"/api/projects/{pid}/steps/clips/approve")).status_code == 200
    status = await statuses(api, pid)
    assert status["reference"] == "approved" and status["clips"] == "approved"


@pytest.mark.parametrize("running", ["clips", "montage"])
async def test_select_clip_while_generating_is_409(api, session, running):
    pid = await new_project(api)
    url, clip = await scene_with_clip(session, pid)
    await set_status(session, [running], "running")
    assert (await api.post(url, json={"asset_id": clip.id})).status_code == 409
    scenes = (await api.get(f"/api/projects/{pid}")).json()["scenes"]
    assert scenes[0]["selected_clip_asset_id"] is None


async def three_scenes(session, pid):
    scenes = [Scene(project_id=pid, position=i, voice_text=f"t{i}", visual_prompt="b", duration_s=3) for i in (1, 2, 3)]
    session.add_all(scenes)
    await session.commit()
    return [s.id for s in scenes]


async def test_reorder_scenes_renumbers_and_marks_montage_and_final_stale_only(api, session):
    pid = await new_project(api)
    ids = await three_scenes(session, pid)
    await set_status(session, ["idea", "story", "script", "clips", "voice", "music", "montage"], "approved")
    await set_status(session, ["final"], "awaiting_validation")
    r = await api.post(f"/api/projects/{pid}/scenes/reorder", json={"scene_ids": [ids[2], ids[0], ids[1]]})
    assert r.status_code == 200
    scenes = (await api.get(f"/api/projects/{pid}")).json()["scenes"]
    assert [(s["id"], s["position"]) for s in scenes] == [(ids[2], 1), (ids[0], 2), (ids[1], 3)]
    status = await statuses(api, pid)
    assert status["montage"] == "stale" and status["final"] == "stale"
    assert {status[n] for n in ("idea", "story", "script", "clips", "voice", "music")} == {"approved"}


@pytest.mark.parametrize("scene_ids", [[1, 2], [999, 1000, 1001], "same-twice"])
async def test_reorder_scenes_rejects_a_list_that_is_not_the_project_scenes(api, session, scene_ids):
    pid = await new_project(api)
    ids = await three_scenes(session, pid)
    if scene_ids == "same-twice":
        scene_ids = [ids[0], ids[0], ids[1]]
    r = await api.post(f"/api/projects/{pid}/scenes/reorder", json={"scene_ids": scene_ids})
    assert r.status_code == 422


@pytest.mark.parametrize("running", ["clips", "voice", "montage"])
async def test_reorder_scenes_while_generating_is_409(api, session, running):
    pid = await new_project(api)
    ids = await three_scenes(session, pid)
    await set_status(session, [running], "running")
    assert (await api.post(f"/api/projects/{pid}/scenes/reorder", json={"scene_ids": ids[::-1]})).status_code == 409


async def test_delete_asset(api, session):
    pid = await new_project(api)
    scene = Scene(project_id=pid, position=1, voice_text="a", visual_prompt="b", duration_s=3)
    session.add(scene)
    await session.flush()
    clip1 = Asset(project_id=pid, scene_id=scene.id, kind="clip", key=f"projects/{pid}/clip/c1.mp4", content_type="video/mp4", variant=1)
    clip2 = Asset(project_id=pid, scene_id=scene.id, kind="clip", key=f"projects/{pid}/clip/c2.mp4", content_type="video/mp4", variant=2)
    session.add_all([clip1, clip2])
    await session.flush()
    scene.selected_clip_asset_id = clip2.id
    await session.commit()

    # Supprimer clip2 (qui est sélectionné) : doit sélectionner clip1
    r = await api.delete(f"/api/projects/{pid}/assets/{clip2.id}")
    assert r.status_code == 204
    proj = (await api.get(f"/api/projects/{pid}")).json()
    assert proj["scenes"][0]["selected_clip_asset_id"] == clip1.id
    assert len(proj["assets"]) == 1

    # Supprimer clip1 : selected_clip_asset_id devient None
    r = await api.delete(f"/api/projects/{pid}/assets/{clip1.id}")
    assert r.status_code == 204
    proj = (await api.get(f"/api/projects/{pid}")).json()
    assert proj["scenes"][0]["selected_clip_asset_id"] is None
    assert len(proj["assets"]) == 0


async def test_upload_clip_as_variant(api, session):
    pid = await new_project(api)
    scene = Scene(project_id=pid, position=1, voice_text="a", visual_prompt="b", duration_s=3)
    session.add(scene)
    await session.commit()

    # Upload d'un fichier vidéo
    data = b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2mp41"
    files = {"file": ("my_video.mp4", data, "video/mp4")}
    r = await api.post(f"/api/projects/{pid}/scenes/{scene.id}/upload-clip", files=files)
    assert r.status_code == 201
    asset = r.json()
    assert asset["kind"] == "clip"
    assert asset["variant"] == 1
    assert asset["meta"]["model"] == "upload"

    proj = (await api.get(f"/api/projects/{pid}")).json()
    assert proj["scenes"][0]["selected_clip_asset_id"] == asset["id"]


async def test_estimate_sums_clip_costs(api, session):
    pid = await new_project(api)
    session.add_all(Scene(project_id=pid, position=i, voice_text="a", visual_prompt="b", duration_s=d)
                    for i, d in ((1, 2), (2, 4)))
    await session.commit()
    r = await api.get(f"/api/projects/{pid}/estimate", params={"provider": "fal", "model": "kling"})
    assert r.status_code == 200
    assert r.json() == {"provider": "fal", "model": "kling", "scene_count": 2, "cost_usd": 0.3}
    assert (await api.get(f"/api/projects/{pid}/estimate", params={"provider": "nope"})).status_code == 400


async def test_estimate_rejects_model_unknown_to_provider(api, session):
    class Registry:
        async def video(self, name):
            return FalProvider("k", None)

    pid = await new_project(api)
    session.add(Scene(project_id=pid, position=1, voice_text="a", visual_prompt="b", duration_s=2))
    await session.commit()
    app.dependency_overrides[get_registry] = lambda: Registry()
    try:
        r = await api.get(f"/api/projects/{pid}/estimate", params={"provider": "fal", "model": "nope"})
    finally:
        app.dependency_overrides.pop(get_registry, None)
    assert r.status_code == 400


async def test_event_stream_relays_messages_and_pings():
    class FakePubSub:
        def __init__(self):
            self.messages = [{"data": b'{"step": "idea"}'}, None]

        async def get_message(self, ignore_subscribe_messages, timeout):
            return self.messages.pop(0)

    async def everything(project_id):
        return True

    gen = visible_events(FakePubSub(), everything)
    assert await anext(gen) == 'data: {"step": "idea"}\n\n'
    assert await anext(gen) == ": ping\n\n"


async def test_edit_project_brief_marks_produced_steps_stale(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    await set_status(session, ["clips"], "failed")
    r = await api.patch(f"/api/projects/{pid}", json={"theme": "chiens", "target_duration_s": 20})
    assert r.status_code == 200 and r.json()["theme"] == "chiens" and r.json()["target_duration_s"] == 20
    status = await statuses(api, pid)
    assert status["idea"] == "stale" and status["script"] == "stale" and status["clips"] == "failed"


async def test_edit_project_title_only_marks_final_stale(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script", "reference", "clips", "voice", "music", "montage", "final"], "approved")
    assert (await api.patch(f"/api/projects/{pid}", json={"title": "Nouveau", "theme": "chats"})).status_code == 200
    status = await statuses(api, pid)
    assert status["final"] == "stale" and status["idea"] == "approved" and status["montage"] == "approved"


async def test_edit_project_validates_fields(api):
    pid = await new_project(api)
    assert (await api.patch(f"/api/projects/{pid}", json={"title": ""})).status_code == 422
    assert (await api.patch("/api/projects/999999", json={"title": "x"})).status_code == 404


async def test_download_asset_redirects_with_attachment(api, session):
    pid = await new_project(api)
    render = Asset(project_id=pid, kind="render", key="projects/1/render/r.mp4", content_type="video/mp4")
    session.add(render)
    await session.commit()
    r = await api.get(f"/api/projects/{pid}/assets/{render.id}/download")
    assert r.status_code == 307
    assert r.headers["location"] == "http://mem/projects/1/render/r.mp4?download=vivi-1.mp4"
    other = await new_project(api)
    assert (await api.get(f"/api/projects/{other}/assets/{render.id}/download")).status_code == 404


async def test_skipped_reference_is_not_marked_stale(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    assert (await api.post(f"/api/projects/{pid}/steps/reference/approve")).status_code == 200  # ignorée
    await set_status(session, ["clips"], "awaiting_validation")
    await session.execute(Step.__table__.update().where(Step.name == "clips").values(result={"asset_ids": [1]}))
    await session.commit()
    assert (await api.patch(f"/api/projects/{pid}/steps/script", json={"params": {}})).status_code == 200
    status = await statuses(api, pid)
    assert status["reference"] == "approved" and status["clips"] == "stale"
    assert (await api.get(f"/api/projects/{pid}")).json()["current_step"] == "clips"


async def test_editing_final_result_updates_project_metadata(api, session):
    pid = await new_project(api)
    await set_status(session, ["final"], "awaiting_validation")
    meta = {"title": "Titre", "description": "Desc", "hashtags": ["#a", "#b"]}
    assert (await api.patch(f"/api/projects/{pid}/steps/final", json={"result": meta})).status_code == 200
    data = (await api.get(f"/api/projects/{pid}")).json()
    assert data["metadata_json"] == meta and data["steps"][-1]["result"] == meta


async def test_run_clips_with_override_does_not_touch_step_params(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    body = {"scene_id": 7, "provider": "comfyui", "model": "workflow"}
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json=body)).status_code == 202
    assert api.enqueued == [(pid, "clips", 7, {"provider": "comfyui", "model": "workflow"})]
    clips = next(s for s in (await api.get(f"/api/projects/{pid}")).json()["steps"] if s["name"] == "clips")
    assert clips["params"] == {}


async def test_run_override_is_validated(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    assert (await api.post(f"/api/projects/{pid}/steps/idea/run", json={"model": "x"})).status_code == 422
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={"provider": "nope"})).status_code == 400
    assert (await statuses(api, pid))["clips"] == "pending"  # rien n'a été réclamé ni enfilé
    assert api.enqueued == []


async def test_run_rejects_unknown_model_with_400(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={"provider": "comfyui", "model": "turbo"})
    assert r.status_code == 400 and r.json()["detail"] == "Modèle vidéo inconnu pour comfyui : turbo"
    assert (await statuses(api, pid))["clips"] == "pending" and api.enqueued == []


async def test_run_rejects_unavailable_model_with_409(api, session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "fake_providers", False)  # vrai provider fal, sans clé
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={"provider": "fal", "model": "kling"})
    assert r.status_code == 409 and r.json()["detail"] == FAL_KEY_MISSING
    assert (await statuses(api, pid))["clips"] == "pending" and api.enqueued == []


async def test_legacy_workflow_param_still_runs(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    params = {"provider": "comfyui", "model": "workflow"}  # ancien projet : modèle ComfyUI unique
    assert (await api.patch(f"/api/projects/{pid}/steps/clips", json={"params": params})).status_code == 200
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={})).status_code == 202
    assert api.enqueued == [(pid, "clips", None)]


async def test_run_sizes_job_timeout_from_scene_count(api, session):
    from app.services.timeouts import job_timeout

    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    assert (await api.put("/api/settings", json={"default_video_provider": "fal", "default_video_model": "kling"})
            ).status_code == 200  # provider cloud : timeout par défaut
    session.add_all(Scene(project_id=pid, position=i, voice_text="a", visual_prompt="b", duration_s=3) for i in (1, 2, 3))
    await session.commit()
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={})).status_code == 202
    await set_status(session, ["clips"], "failed")
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": 1})).status_code == 202
    assert api.timeouts == [job_timeout("clips", 3), job_timeout("clips", 1)]


async def test_a_chained_scene_cannot_be_regenerated_before_the_previous_one_has_a_clip(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    assert (await api.put("/api/settings", json={"default_video_provider": "fal", "default_video_model": "kling"})).status_code == 200
    session.add_all(Scene(project_id=pid, position=i, voice_text="a", visual_prompt="b", duration_s=3) for i in (1, 2))
    await session.commit()
    first, second = (await api.get(f"/api/projects/{pid}")).json()["scenes"]
    url = f"/api/projects/{pid}/scenes/{second['id']}/continuity"
    assert (await api.put(f"/api/projects/{pid}/scenes/{first['id']}/continuity", json={"continuity": "continue"})).status_code == 422
    assert (await api.put(url, json={"continuity": "nimporte"})).status_code == 422
    assert (await api.put(f"/api/projects/{pid}/scenes/999/continuity", json={"continuity": "cut"})).status_code == 404
    assert (await api.put(url, json={"continuity": "continue"})).json()["continuity"] == "continue"
    run = f"/api/projects/{pid}/steps/clips/run"
    r = await api.post(run, json={"scene_id": second["id"]})
    assert r.status_code == 409 and "scène 1" in r.json()["detail"] and api.enqueued == []
    assert (await api.post(run, json={"scene_id": first["id"]})).status_code == 202  # la première n'a pas d'amont
    await set_status(session, ["clips"], "failed")
    assert (await api.put(url, json={"continuity": "cut"})).json()["continuity"] == "cut"
    assert (await api.post(run, json={"scene_id": second["id"]})).status_code == 202  # coupée : plus de verrou


async def test_run_sizes_clips_timeout_for_local_comfyui(api, session):
    from app.app_settings import AppSettings
    from app.services.timeouts import job_timeout

    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    session.add(Scene(project_id=pid, position=1, voice_text="a", visual_prompt="b", duration_s=3))
    await session.commit()
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={"provider": "comfyui"})).status_code == 202
    await set_status(session, ["clips"], "failed")
    await AppSettings(session).set("default_video_provider", "comfyui")
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={})).status_code == 202
    assert api.timeouts == [job_timeout("clips", 1, "comfyui")] * 2 and api.timeouts[0] > job_timeout("clips", 1)


async def test_edit_step_while_downstream_running_is_409(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    await set_status(session, ["clips"], "running")
    r = await api.patch(f"/api/projects/{pid}/steps/script", json={"scenes": [{"voice_text": "a", "visual_prompt": "b", "duration_s": 3}]})
    assert r.status_code == 409 and "clips" in r.json()["detail"]
    assert (await api.get(f"/api/projects/{pid}")).json()["scenes"] == []  # rien n'a été modifié
    assert (await api.patch(f"/api/projects/{pid}/steps/final", json={"result": {"title": "x"}})).status_code == 200


async def test_run_while_dependent_running_is_queued_not_started(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story"], "approved")
    await set_status(session, ["montage"], "running")
    r = await api.post(f"/api/projects/{pid}/steps/script/run", json={})
    assert r.status_code == 202 and r.json() == {"queued": True}
    assert (await statuses(api, pid))["script"] == "pending" and api.enqueued == []
    assert [(q["step"], q["scene_id"]) for q in (await api.get(f"/api/projects/{pid}")).json()["queue"]] == [("script", None)]


async def test_edit_project_while_dependent_step_running_is_409(api, session):
    pid = await new_project(api)
    await set_status(session, ["voice"], "running")
    assert (await api.patch(f"/api/projects/{pid}", json={"theme": "chiens"})).status_code == 409
    assert (await api.patch(f"/api/projects/{pid}", json={"title": "Nouveau"})).status_code == 200  # seul final dépend du titre
    await set_status(session, ["final"], "running")
    assert (await api.patch(f"/api/projects/{pid}", json={"title": "Autre"})).status_code == 409
    assert (await api.get(f"/api/projects/{pid}")).json()["theme"] == "chats"


async def test_scene_voice_text_must_not_be_empty(api):
    pid = await new_project(api)
    for text in ("", "   "):
        r = await api.patch(f"/api/projects/{pid}/steps/script", json={"scenes": [{"voice_text": text, "visual_prompt": "b", "duration_s": 3}]})
        assert r.status_code == 422


async def project_status(api, pid):
    return next(p["status"] for p in (await api.get("/api/projects")).json()["items"] if p["id"] == pid)


async def test_project_is_done_when_final_approved_and_back_to_draft_when_invalidated(api, session):
    pid = await new_project(api)
    assert await project_status(api, pid) == "draft"
    await set_status(session, ["idea", "story", "script", "reference", "clips", "voice", "music", "montage"], "approved")
    await set_status(session, ["final"], "awaiting_validation")
    assert (await api.post(f"/api/projects/{pid}/steps/final/approve")).status_code == 200
    assert await project_status(api, pid) == "done"
    assert (await api.patch(f"/api/projects/{pid}", json={"title": "Nouveau titre"})).status_code == 200  # final périmée
    assert await project_status(api, pid) == "draft"
    assert (await api.post(f"/api/projects/{pid}/steps/final/approve")).status_code == 200  # stale → approved
    assert await project_status(api, pid) == "done"
    assert (await api.post(f"/api/projects/{pid}/steps/final/run", json={})).status_code == 202
    assert await project_status(api, pid) == "draft"


async def test_run_refuses_an_instruction_outside_the_script_step(api, session):
    pid = await new_project(api)
    r = await api.post(f"/api/projects/{pid}/steps/idea/run", json={"instruction": "plus court"})
    assert r.status_code == 422


async def test_launch_with_a_reference_image_is_refused_when_its_models_are_missing(api, session, monkeypatch):
    from app.models import Asset
    from app.providers.base import Availability
    from app.providers.fakes import FakeVideo

    async def no_kontext(self, model):
        return Availability(False, "Modèle manquant : flux1-kontext-dev-Q4_K_S.gguf")

    monkeypatch.setattr(FakeVideo, "reference_availability", no_kontext)
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script", "reference"], "approved")
    session.add(Scene(project_id=pid, position=1, voice_text="a", visual_prompt="b", duration_s=3))
    await session.commit()
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={})
    assert r.status_code == 202  # sans image de référence, le modèle se lance comme avant
    await set_status(session, ["clips"], "pending")
    session.add(Asset(project_id=pid, kind="reference", key="k", content_type="image/png"))
    await session.commit()
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={})
    assert r.status_code == 409 and "flux1-kontext" in r.json()["detail"]


async def test_scene_reference_is_set_among_script_elements_and_survives_script_edits(api, session):
    pid = await new_project(api)
    await session.execute(Step.__table__.update().where(Step.project_id == pid, Step.name == "script")
                          .values(result={"references": [{"id": "kroc", "prompt": "p"}]}))
    session.add(Scene(project_id=pid, position=1, voice_text="a", visual_prompt="b", duration_s=3))
    await session.commit()
    scene = (await api.get(f"/api/projects/{pid}")).json()["scenes"][0]
    assert scene["reference"] == ""
    url = f"/api/projects/{pid}/scenes/{scene['id']}/reference"
    assert (await api.put(url, json={"reference": "kroc"})).json()["reference"] == "kroc"
    assert (await api.put(url, json={"reference": "ghost"})).status_code == 422
    # Une édition du script qui ne parle pas de référence la conserve ; « "" » la retire.
    body = {"scenes": [{"id": scene["id"], "voice_text": "a2", "visual_prompt": "b", "duration_s": 3}]}
    assert (await api.patch(f"/api/projects/{pid}/steps/script", json=body)).status_code == 200
    assert (await api.get(f"/api/projects/{pid}")).json()["scenes"][0]["reference"] == "kroc"
    body["scenes"][0]["reference"] = ""
    assert (await api.patch(f"/api/projects/{pid}/steps/script", json=body)).status_code == 200
    assert (await api.get(f"/api/projects/{pid}")).json()["scenes"][0]["reference"] == ""
    assert (await api.put(f"/api/projects/{pid}/scenes/999/reference", json={"reference": ""})).status_code == 404
    await set_status(session, ["clips"], "running")  # le choix reste possible pendant les clips
    assert (await api.put(url, json={"reference": "kroc"})).json()["reference"] == "kroc"


async def test_reference_element_is_added_to_the_script_without_staling_anything(api, session):
    pid = await new_project(api)
    url = f"/api/projects/{pid}/references"
    body = {"name": "Ouvrier de l'Égypte", "prompt": "un ouvrier"}
    assert (await api.post(url, json=body)).status_code == 409  # pas de script encore
    await session.execute(Step.__table__.update().where(Step.project_id == pid, Step.name == "script")
                          .values(status="approved", result={"bible": "b", "references": [{"id": "kroc", "prompt": "p"}]}))
    await session.commit()
    r = await api.post(url, json=body)
    assert r.status_code == 201 and r.json() == {"id": "ouvrier_de_l_egypte", "prompt": "un ouvrier"}
    script = next(s for s in (await api.get(f"/api/projects/{pid}")).json()["steps"] if s["name"] == "script")
    assert [e["id"] for e in script["result"]["references"]] == ["kroc", "ouvrier_de_l_egypte"]
    assert script["result"]["bible"] == "b" and script["status"] == "approved"
    assert (await api.post(url, json=body)).status_code == 409  # doublon
    assert (await api.post(url, json={"name": "!!!", "prompt": "x"})).status_code == 422
    # Élément ajouté avec une image importée, sans description : son nom sert de prompt pour une régénération.
    assert (await api.post(url, json={"name": "Ibou"})).json() == {"id": "ibou", "prompt": "Ibou"}


async def test_story_element_is_promoted_to_a_reference_with_its_id_and_descriptor(api, session):
    pid = await new_project(api)
    story = {"elements": [{"id": "vintage_car", "kind": "prop", "name": "Voiture", "descriptor": "black 1914 car", "prompt": "a car"}]}
    await session.execute(Step.__table__.update().where(Step.project_id == pid, Step.name == "story").values(result=story))
    await session.execute(Step.__table__.update().where(Step.project_id == pid, Step.name == "script")
                          .values(status="approved", result={"bible": "b", "references": [{"id": "kroc", "prompt": "p"}]}))
    await session.commit()
    url = f"/api/projects/{pid}/references"
    r = await api.post(url, json={"name": "Voiture", "prompt": "a car", "story_id": "vintage_car"})
    assert r.status_code == 201 and r.json() == {"id": "vintage_car", "prompt": "a car", "descriptor": "black 1914 car"}
    assert (await api.post(url, json={"name": "Voiture", "prompt": "a car", "story_id": "vintage_car"})).status_code == 409
    assert (await api.post(url, json={"name": "x", "prompt": "p", "story_id": "ghost"})).status_code == 422


async def test_reference_id_only_applies_to_the_reference_step(api, session):
    pid = await new_project(api)
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={"reference_id": "kroc"})
    assert r.status_code == 422


async def test_scene_sends_several_element_images_and_keeps_their_state(api, session):
    pid = await new_project(api)
    refs = [{"id": i, "prompt": "p"} for i in ("kroc", "fries", "chef", "logo")]
    await session.execute(Step.__table__.update().where(Step.project_id == pid, Step.name == "script").values(result={"references": refs}))
    session.add(Scene(project_id=pid, position=1, voice_text="a", visual_prompt="b", duration_s=3, elements=[{"id": "fries", "state": "froid"}]))
    await session.commit()
    scene = (await api.get(f"/api/projects/{pid}")).json()["scenes"][0]
    url = f"/api/projects/{pid}/scenes/{scene['id']}/reference"
    r = await api.put(url, json={"reference": "kroc", "elements": ["fries", "fries"]})
    assert r.json()["elements"] == [{"id": "fries", "state": "froid"}]
    assert (await api.put(url, json={"reference": "kroc"})).json()["elements"] == r.json()["elements"]  # None : inchangés
    assert (await api.put(url, json={"reference": "kroc", "elements": ["fries", "chef"]})).status_code == 422  # 3 images
    assert (await api.put(url, json={"reference": "kroc", "elements": ["ghost"]})).status_code == 422
    assert (await api.put(url, json={"reference": "", "elements": []})).json()["elements"] == []
    # Un élément de la scène sans référence (décor de l'histoire) reste en place et ne compte pas dans le plafond.
    await session.execute(Scene.__table__.update().where(Scene.id == scene["id"]).values(elements=[{"id": "decor", "state": "s"}, {"id": "kroc", "state": ""}]))
    await session.commit()
    r = await api.put(url, json={"reference": "chef", "elements": ["kroc"]})
    assert [e["id"] for e in r.json()["elements"]] == ["decor", "kroc"] and r.json()["elements"][0]["state"] == "s"


async def test_reference_element_is_queued_with_its_params_while_the_step_runs(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    await set_status(session, ["reference"], "running")
    url = f"/api/projects/{pid}/steps/reference/run"
    r = await api.post(url, json={"reference_id": "kroc", "params": {"prompts": {"kroc": "nouveau"}}})
    assert r.status_code == 202 and r.json() == {"queued": True}
    queue = (await api.get(f"/api/projects/{pid}")).json()["queue"]
    assert [(q["step"], q["scene_id"]) for q in queue] == [("reference", None)]
    assert (await api.post(url, json={})).status_code == 409  # l'étape entière, elle, n'attend pas
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={"params": {"a": 1}})).status_code == 422


async def test_scene_voice_text_is_edited_and_stales_voice_montage_and_final(api, session):
    pid = await new_project(api)
    session.add(Scene(project_id=pid, position=1, voice_text="a", visual_prompt="b", duration_s=3))
    await session.commit()
    scene = (await api.get(f"/api/projects/{pid}")).json()["scenes"][0]
    url = f"/api/projects/{pid}/scenes/{scene['id']}/voice-text"
    await set_status(session, ["script", "voice", "montage", "final"], "approved")
    assert (await api.put(url, json={"voice_text": "  "})).status_code == 422
    assert (await api.put(f"/api/projects/{pid}/scenes/999/voice-text", json={"voice_text": "x"})).status_code == 404
    assert (await api.put(url, json={"voice_text": "a"})).json()["voice_text"] == "a"  # inchangé : rien n'est périmé
    statuses = lambda steps: {s["name"]: s["status"] for s in steps}  # noqa: E731
    assert statuses((await api.get(f"/api/projects/{pid}")).json()["steps"])["voice"] == "approved"
    assert (await api.put(url, json={"voice_text": " Nouveau texte "})).json()["voice_text"] == "Nouveau texte"
    steps = statuses((await api.get(f"/api/projects/{pid}")).json()["steps"])
    assert (steps["script"], steps["voice"], steps["montage"], steps["final"]) == ("approved", "stale", "stale", "stale")
    await set_status(session, ["voice"], "running")
    assert (await api.put(url, json={"voice_text": "Autre"})).status_code == 409


def test_mark_stale_ignores_an_empty_story_but_not_a_written_one():
    """Projet existant : sa story validée et vide n'a rien produit, elle ne devient jamais périmée."""
    from app.services.flow import mark_stale

    empty = Step(name="story", status="approved", result={})
    written = Step(name="story", status="approved", result={"beats": [{"summary": "s"}]})
    script = Step(name="script", status="approved", result={})
    mark_stale([empty, script], {"story", "script"})
    assert empty.status == "approved" and script.status == "stale"
    mark_stale([written], {"story"})
    assert written.status == "stale"


def test_plan_until_is_script_only_for_an_existing_project_with_an_empty_approved_story():
    from app.services.flow import plan_until

    assert plan_until([Step(name="story", status="approved", result={})]) == "script"
    assert plan_until([Step(name="story", status="pending", result={})]) == "story"
    assert plan_until([Step(name="story", status="approved", result={"beats": [{"summary": "s"}]})]) == "story"
    assert plan_until([]) == "story"


STORY_RESULT = {"bible": "b", "elements": [{"id": "chloe", "kind": "character", "name": "Chloe", "descriptor": "d", "prompt": "p"}],
                "beats": [{"summary": "s", "voice_text": "v", "duration_s": 4, "elements": [{"id": "chloe", "state": ""}]}]}


async def test_editing_the_story_refuses_a_malformed_result_and_makes_the_script_stale_otherwise(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    bad = {**STORY_RESULT, "beats": [{"summary": "s", "voice_text": "v", "duration_s": "4 s"}]}
    r = await api.patch(f"/api/projects/{pid}/steps/story", json={"result": bad})
    assert r.status_code == 422 and "beat 1" in r.json()["detail"]
    assert (await statuses(api, pid))["script"] == "approved"
    assert (await api.patch(f"/api/projects/{pid}/steps/story", json={"result": STORY_RESULT})).status_code == 200
    assert (await statuses(api, pid))["script"] == "stale"


async def test_run_accepts_an_instruction_for_story_and_script_only(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea"], "approved")
    assert (await api.post(f"/api/projects/{pid}/steps/story/run", json={"instruction": "plus court"})).status_code == 202


def test_script_stale_names_keeps_reference_when_elements_unchanged():
    from app.services.flow import script_stale_names
    from app.state import dependents

    refs = {"references": [{"name": "Léo", "prompt": "p"}], "bible": "B"}
    names = script_stale_names(refs, {**refs, "bible": "B2"})
    assert "reference" not in names and set(names) == set(dependents("script")) - {"reference"}
    assert "reference" not in script_stale_names(None, {"bible": "B"})  # absents = listes vides


def test_script_stale_names_includes_reference_when_element_added():
    from app.services.flow import script_stale_names
    from app.state import dependents

    names = script_stale_names({"references": []}, {"references": [{"name": "Léo", "prompt": "p"}]})
    assert set(names) == set(dependents("script"))
    assert "reference" in script_stale_names(None, {"references": [{"name": "Léo"}]})


async def test_edit_script_text_keeps_reference_fresh(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script", "reference", "clips"], "approved")
    await session.execute(Step.__table__.update().where(Step.name == "reference").values(result={"asset_ids": [1]}))
    await session.commit()
    scenes = [{"voice_text": "nouveau texte", "visual_prompt": "b", "duration_s": 3}]
    assert (await api.patch(f"/api/projects/{pid}/steps/script", json={"scenes": scenes})).status_code == 200
    status = await statuses(api, pid)
    assert status["reference"] == "approved" and status["clips"] == "stale"


# --- Validation du script : images de référence manquantes lancées à ce moment ----------------------------------------

async def script_awaiting_with_references(session, pid, reference_status):
    await set_status(session, ["idea", "story"], "approved")
    await set_status(session, ["script"], "awaiting_validation")
    await set_status(session, ["reference"], reference_status)
    await session.execute(Step.__table__.update().where(Step.project_id == pid, Step.name == "script")
                          .values(result={"references": [{"id": "cat", "prompt": "a ginger cat"}]}))
    await session.commit()


@pytest.fixture
def published(monkeypatch):
    from app.api import steps as steps_api

    events = []

    async def publish(event):
        events.append(event)

    monkeypatch.setattr(steps_api, "publish_event", publish)
    return events


@pytest.mark.parametrize("reference_status", ["pending", "stale"])
async def test_approve_script_starts_missing_references(api, session, published, reference_status):
    pid = await new_project(api)
    await script_awaiting_with_references(session, pid, reference_status)
    assert (await api.post(f"/api/projects/{pid}/steps/script/approve")).status_code == 200
    status = await statuses(api, pid)
    assert status["script"] == "approved" and status["reference"] == "running"
    assert api.enqueued == [(pid, "reference", None)]
    assert published == [{"project_id": pid, "step": "reference", "status": "running", "error": None}]


@pytest.mark.parametrize("reference_status", ["awaiting_validation", "running", "failed"])
async def test_approve_script_keeps_references_already_started(api, session, published, reference_status):
    pid = await new_project(api)
    await script_awaiting_with_references(session, pid, reference_status)
    assert (await api.post(f"/api/projects/{pid}/steps/script/approve")).status_code == 200
    assert (await statuses(api, pid))["reference"] == reference_status
    assert api.enqueued == [] and published == []


async def test_approve_script_over_budget_leaves_references_pending(api, session, published):
    pid = await new_project(api)
    await script_awaiting_with_references(session, pid, "pending")
    await api.put("/api/settings", json={"project_budget_usd": "0.01"})
    await session.execute(ProviderCall.__table__.insert().values(project_id=pid, step="script", provider="gemini",
                                                                 model="m", cost_usd=1, status="ok"))
    await session.commit()
    assert (await api.post(f"/api/projects/{pid}/steps/script/approve")).status_code == 200
    status = await statuses(api, pid)
    assert status["script"] == "approved" and status["reference"] == "pending"
    assert api.enqueued == [] and published == []


async def test_clips_wait_in_queue_while_references_generate(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    await set_status(session, ["reference"], "running")
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={})
    assert r.status_code == 202 and r.json() == {"queued": True}
    assert api.enqueued == [] and (await statuses(api, pid))["clips"] == "pending"


async def test_start_image_choice_is_a_clips_launch_override_only(api, session):
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    assert (await api.post(f"/api/projects/{pid}/steps/voice/run", json={"start_image": "gemini"})).status_code == 422
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={"start_image": "dalle"})).status_code == 422
    assert (await api.post(f"/api/projects/{pid}/steps/voice/run", json={"reuse_start_image": True})).status_code == 422
    assert api.enqueued == []
    body = {"scene_id": 7, "start_image": "gemini"}
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json=body)).status_code == 202
    assert api.enqueued == [(pid, "clips", 7, {"start_image": "gemini"})]
