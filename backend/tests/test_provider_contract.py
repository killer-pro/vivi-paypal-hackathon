import httpx
import pytest

from app.providers.base import Availability, ProviderError, ensure_non_empty
from app.providers.fakes import FakeImage, FakeLLM, FakeVideo, FakeVoice
from app.providers.gemini import GeminiLLM


def gemini_ok(req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                                     "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})


@pytest.mark.parametrize("make_llm", [
    FakeLLM,
    lambda: GeminiLLM("k", httpx.AsyncClient(transport=httpx.MockTransport(gemini_ok))),
], ids=["fake", "gemini"])
async def test_llms_respect_contract(make_llm):
    provider = make_llm()
    llm = await provider.complete("sys", "hi", max_tokens=100)
    assert provider.name and llm.text and llm.cost_usd >= 0 and llm.model
    assert await provider.health() is True


async def test_fakes_respect_contract():
    img = await FakeImage().generate("p", model="m")
    vid = await FakeVideo().generate("p", model="fake-video", duration_s=5)
    voice = await FakeVoice().synthesize("bonjour", voice_id="v")
    for r in (img, vid, voice):
        assert len(r.data) > 0 and r.cost_usd >= 0 and r.content_type
    assert FakeVideo().estimate_cost("fake-video", 5) > 0
    assert await FakeVideo().health() is True
    assert await FakeVideo().availability() == {"fake-video": Availability(True)}


def test_ensure_non_empty_rejects_zero_bytes():
    with pytest.raises(ProviderError, match="vide"):
        ensure_non_empty(b"", "clip")
    assert ensure_non_empty(b"x", "clip") == b"x"


async def test_fake_video_can_fail():
    with pytest.raises(ProviderError):
        await FakeVideo(fail_with=ProviderError("boom", retryable=False)).generate("p", model="fake-video", duration_s=5)


async def test_fake_llm_accepts_json_schema():
    r = await FakeLLM().complete("sys", "Découpe en scènes", json_schema={"type": "OBJECT"})
    assert '"scenes"' in r.text
