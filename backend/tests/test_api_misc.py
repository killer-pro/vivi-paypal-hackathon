import pathlib
import subprocess
import tempfile

import pytest

from app.models import Project, ProviderCall
from app.providers.fal import FAL_KEY_MISSING


async def test_music_upload_rejects_empty_and_non_audio(api):
    r = await api.post("/api/music", files={"file": ("a.mp3", b"", "audio/mpeg")}, data={"name": "n", "tags": ""})
    assert r.status_code == 400
    r = await api.post("/api/music", files={"file": ("a.txt", b"abc", "text/plain")}, data={"name": "n", "tags": ""})
    assert r.status_code == 400


async def test_music_upload_ok_stores_duration_and_tags(api):
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "a.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=2", str(p)], check=True)
        r = await api.post("/api/music", files={"file": ("a.mp3", p.read_bytes(), "audio/mpeg")},
                           data={"name": "Chill", "tags": "calme, lofi,, "})
    assert r.status_code == 201
    item = (await api.get("/api/music")).json()[0]
    assert item["tags"] == ["calme", "lofi"] and 1.5 < item["duration_s"] < 2.5
    assert item["url"] == f"http://mem/{next(iter(api.storage.files))}"

    assert (await api.delete(f"/api/music/{item['id']}")).status_code == 204
    assert (await api.get("/api/music")).json() == []
    assert (await api.delete(f"/api/music/{item['id']}")).status_code == 404


async def test_settings_mask_secrets_and_reject_unknown_keys(api):
    assert (await api.put("/api/settings", json={"fal_key": "abcdef1234"})).status_code == 200
    assert (await api.get("/api/settings")).json()["fal_key"] == "••••1234"
    assert (await api.put("/api/settings", json={"fal_key": "••••1234"})).status_code == 200
    assert (await api.put("/api/settings", json={"nope": "x"})).status_code == 400
    assert (await api.get("/api/settings")).json()["fal_key"] == "••••1234"


async def test_costs_aggregate(api, session):
    session.add_all([ProviderCall(step="clips", provider="fal", model="kling", cost_usd=1.5, status="ok"),
                     ProviderCall(step="voice", provider="elevenlabs", model="m", cost_usd=0.5, status="ok")])
    await session.commit()
    data = (await api.get("/api/costs")).json()
    assert data["total_usd"] == 2.0 and data["by_provider"] == {"fal": 1.5, "elevenlabs": 0.5}
    assert len(data["calls"]) == 2
    only_fal = (await api.get("/api/costs", params={"provider": "fal"})).json()
    assert only_fal["total_usd"] == 1.5 and len(only_fal["calls"]) == 1
    assert (await api.get("/api/costs", params={"since": "2999-01-01T00:00:00"})).json()["total_usd"] == 0


async def test_costs_filter_by_project(api, session, admin):
    p = Project(title="t", user_id=admin.id)
    session.add(p)
    await session.commit()
    session.add_all([ProviderCall(project_id=p.id, step="clips", provider="fal", model="k", cost_usd=1, status="ok"),
                     ProviderCall(step="voice", provider="elevenlabs", model="m", cost_usd=2, status="ok")])
    await session.commit()
    data = (await api.get("/api/costs", params={"project_id": p.id})).json()
    assert data["total_usd"] == 1 and data["by_project"] == {str(p.id): 1}


async def test_providers_health_in_fake_mode(api):
    assert all((await api.get("/api/providers/health")).json().values())


@pytest.fixture
def real_providers(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "fake_providers", False)


async def test_models_endpoint_returns_cards(api, real_providers, monkeypatch):
    from app.providers.base import Availability
    from app.providers.comfyui import ComfyUIProvider

    async def availability(self):
        return {"fast": Availability(True), "balanced": Availability(True), "precision": Availability(True),
                "max": Availability(False, "Modèle manquant : ESRGAN/4x-UltraSharp.pth")}

    monkeypatch.setattr(ComfyUIProvider, "availability", availability)
    r = await api.get("/api/providers/models")
    assert r.status_code == 200
    data = r.json()
    local = [c for c in data["video"] if c["provider"] == "comfyui"]
    assert [c["id"] for c in local] == ["fast", "balanced", "precision", "max"]
    assert local[0] == {"provider": "comfyui", "id": "fast", "name": "Rapide",
                        "description": "Wan 2.2 14B, 320×576 : le meilleur compromis.", "speed": 4,
                        "quality": 3.5, "minutes_per_clip": 5, "cost_usd_per_clip": None, "credits_per_clip": None, "available": True,
                        "reason": "", "recommended": True, "locked": False, "locked_reason": None}
    assert [c["id"] for c in data["video"] if c["recommended"]] == ["fast"]  # le profil par défaut seulement
    assert local[3]["available"] is False and local[3]["reason"] == "Modèle manquant : ESRGAN/4x-UltraSharp.pth"
    kling = next(c for c in data["video"] if c["provider"] == "fal" and c["id"] == "kling")
    assert kling == {"provider": "fal", "id": "kling", "name": "kling", "description": "", "speed": None,
                     "quality": None, "minutes_per_clip": None, "cost_usd_per_clip": 1.4, "credits_per_clip": None, "available": False,
                     "reason": FAL_KEY_MISSING, "recommended": False, "locked": False, "locked_reason": None}
    assert {c["id"] for c in data["video"] if c["provider"] == "fal"} == {"kling", "wan", "ltx"}
    assert ("fal", "flux") in [(c["provider"], c["id"]) for c in data["image"]] and "comfyui_workflows" not in data


async def test_models_endpoint_survives_comfyui_down(api, real_providers):
    assert (await api.put("/api/settings", json={"comfyui_url": "http://127.0.0.1:9"})).status_code == 200
    r = await api.get("/api/providers/models")
    assert r.status_code == 200
    local = [c for c in r.json()["video"] if c["provider"] == "comfyui"]
    assert len(local) == 4 and all(not c["available"] and c["reason"] == "ComfyUI injoignable" for c in local)


async def test_settings_have_no_workflow_path(api):
    settings = (await api.get("/api/settings")).json()
    assert "comfyui_workflow_path" not in settings
    assert settings["default_video_provider"] == "comfyui" and settings["default_video_model"] == "fast"
    r = await api.put("/api/settings", json={"comfyui_workflow_path": "wan22-14b-t2v"})
    assert r.status_code == 400 and "comfyui_workflow_path" in r.json()["detail"]


async def test_misc_routes_require_auth(api):
    api.cookies.clear()
    for path in ("/api/music", "/api/settings", "/api/providers/health", "/api/costs"):
        assert (await api.get(path)).status_code == 401


async def test_music_upload_rejects_oversized_file(api, monkeypatch):
    monkeypatch.setattr("app.api.music.MAX_UPLOAD_BYTES", 10)
    r = await api.post("/api/music", files={"file": ("a.mp3", b"x" * 11, "audio/mpeg")}, data={"name": "n", "tags": ""})
    assert r.status_code == 413


async def test_settings_write_is_atomic(api, session, monkeypatch):
    async def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(session, "commit", boom)
    with pytest.raises(RuntimeError):
        await api.put("/api/settings", json={"fal_key": "abcdef1234", "comfyui_url": "http://x"})
    await session.rollback()
    assert (await api.get("/api/settings")).json()["comfyui_url"] != "http://x"


async def test_settings_reject_unsafe_default_voice_id(api):
    r = await api.put("/api/settings", json={"default_voice_id": "../v1/user"})
    assert r.status_code == 400 and "default_voice_id" in r.json()["detail"]
    assert (await api.put("/api/settings", json={"default_voice_id": "Rachel_01-ab"})).status_code == 200


async def test_legacy_default_video_model_is_read_and_written_as_max(api, session):
    """Ancien réglage `workflow` (d'avant les profils) : lu `max` partout (API, lancements), et réécrit `max`."""
    from app.app_settings import AppSettings
    from app.models import Setting

    session.add(Setting(key="default_video_model", value="workflow"))
    await session.commit()
    assert (await api.get("/api/settings")).json()["default_video_model"] == "max"
    assert await AppSettings(session).get("default_video_model") == "max"
    assert (await api.put("/api/settings", json={"default_video_model": "workflow"})).status_code == 200
    row = await session.get(Setting, "default_video_model", populate_existing=True)
    assert row.value == "max"


async def test_voice_catalog_is_stored_validated_and_voices_come_from_the_provider(api):
    catalog = '[{"id": "voix_a", "name": "Camille"}, {"id": "voix-b", "name": "Hugo"}]'
    assert (await api.put("/api/settings", json={"voice_catalog": catalog})).json()["voice_catalog"] == catalog
    for bad in ('[{"id": "../x", "name": "A"}]', '[{"id": "a", "name": " "}]', "pas du json",
                '[{"id": "a", "name": "A"}, {"id": "a", "name": "B"}]'):
        r = await api.put("/api/settings", json={"voice_catalog": bad})
        assert r.status_code == 400 and "voice_catalog" in r.json()["detail"]
    assert (await api.get("/api/settings")).json()["voice_catalog"] == catalog  # un refus ne touche à rien
    r = await api.get("/api/providers/voices")
    assert r.status_code == 200 and r.json()[0] == {"id": "voix_a", "name": "Camille"}
