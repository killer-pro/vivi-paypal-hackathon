import pytest

from app.app_settings import AppSettings
from app.providers.registry import ProviderRegistry


async def test_set_then_get(session):
    s = AppSettings(session)
    await s.set("comfyui_url", "http://x")
    assert await s.get("comfyui_url") == "http://x"


async def test_get_falls_back_to_defaults(session):
    assert await AppSettings(session).get("default_video_provider") == "comfyui"


async def test_secrets_are_masked(session):
    s = AppSettings(session)
    await s.set("fal_key", "abcdef1234")
    masked = await s.all_masked()
    assert masked["fal_key"] == "••••1234"
    assert masked["default_video_provider"] == "comfyui"


async def test_set_unknown_key_rejected(session):
    with pytest.raises(KeyError):
        await AppSettings(session).set("hack", "x")


async def test_registry_fake_mode(session):
    reg = ProviderRegistry(AppSettings(session))
    assert (await reg.llm()).name == "fake-llm"
    for name in reg.IMAGE_PROVIDER_NAMES:
        assert (await reg.image(name)).name == "fake-image"
    assert (await reg.voice()).name == "fake-voice"
    for name in reg.VIDEO_PROVIDER_NAMES:
        assert (await reg.video(name)).name == "fake-video"
    report = await reg.health_report()
    assert set(report) == {"claude", "gemini", "fal", "comfyui", "elevenlabs", "langfuse"} and all(report.values())


async def test_registry_unknown_video_provider(session):
    with pytest.raises(KeyError):
        await ProviderRegistry(AppSettings(session)).video("nope")


async def test_registry_builds_comfyui_from_its_url_only(session, monkeypatch):
    from app.config import settings
    from app.providers.comfyui import ComfyUIProvider

    monkeypatch.setattr(settings, "fake_providers", False)
    await AppSettings(session).set("comfyui_url", "http://comfy:8188/")
    provider = await ProviderRegistry(AppSettings(session)).video("comfyui")
    assert isinstance(provider, ComfyUIProvider) and provider.models == ["fast", "balanced", "precision", "max"]


async def test_start_image_provider_setting_defaults_to_kontext_and_rejects_unknown_values(session):
    settings = AppSettings(session)
    assert await settings.get("start_image_provider") == "comfyui"
    await settings.set("start_image_provider", "gemini")
    assert (await settings.all_masked())["start_image_provider"] == "gemini"
    with pytest.raises(ValueError):
        await settings.set("start_image_provider", "dalle")
