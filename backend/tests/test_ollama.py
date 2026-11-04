import json

import httpx
import pytest

from app.providers.base import ProviderError
from app.providers.ollama import OllamaLLM, lower_types


def llm(handler, model="qwen3:14b") -> OllamaLLM:
    return OllamaLLM("http://ollama:11434/", httpx.AsyncClient(transport=httpx.MockTransport(handler)), model)


def chat(content="{}", **extra) -> httpx.Response:
    return httpx.Response(200, json={"message": {"content": content}, "prompt_eval_count": 7, "eval_count": 3, **extra})


def test_lower_types_converts_gemini_schema():
    schema = {"type": "OBJECT", "properties": {"scenes": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["scenes"]}
    assert lower_types(schema) == {"type": "object", "properties": {"scenes": {"type": "array", "items": {"type": "string"}}},
                                   "required": ["scenes"]}


async def test_complete_sends_schema_and_returns_free_text():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(url=str(req.url), body=json.loads(req.content))
        return chat('{"a": 1}')

    result = await llm(handler).complete("système", "idée", max_tokens=500, json_schema={"type": "OBJECT"})
    assert seen["url"] == "http://ollama:11434/api/chat"
    assert seen["body"]["format"] == {"type": "object"} and seen["body"]["think"] is False
    assert seen["body"]["keep_alive"] == 0
    assert seen["body"]["options"] == {"num_predict": 500} and seen["body"]["stream"] is False
    assert (result.text, result.cost_usd, result.input_tokens, result.output_tokens) == ('{"a": 1}', 0.0, 7, 3)


async def test_truncated_and_empty_answers_raise():
    with pytest.raises(ProviderError, match="tronquée"):
        await llm(lambda r: chat("{", done_reason="length")).complete("s", "p")
    with pytest.raises(ProviderError, match="vide"):
        await llm(lambda r: chat("  ")).complete("s", "p")


async def test_missing_model_and_unreachable_server_are_explicit():
    with pytest.raises(ProviderError, match="ollama pull qwen3:14b"):
        await llm(lambda r: httpx.Response(404, json={"error": "not found"})).complete("s", "p")

    def down(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderError, match="ollama serve") as e:
        await llm(down).complete("s", "p")
    assert e.value.retryable


async def test_health_requires_the_chosen_model_to_be_installed():
    tags = lambda r: httpx.Response(200, json={"models": [{"name": "qwen3:14b"}]})  # noqa: E731
    assert await llm(tags).health()
    assert not await llm(tags, model="gemma4").health()
    latest = lambda r: httpx.Response(200, json={"models": [{"name": "gemma4:latest"}]})  # noqa: E731
    assert await llm(latest, model="gemma4").health()
    assert not await llm(lambda r: httpx.Response(500)).health()


async def test_reference_choice_defaults_to_flux_dev_on_comfyui(session):
    from app.app_settings import AppSettings
    from app.services.pipeline import reference_choice

    s = AppSettings(session)
    await s.set("image_provider", "comfyui")
    assert await reference_choice({}, s) == ("comfyui", "flux-dev")
    assert await reference_choice({"model": "flux"}, s) == ("fal", "flux")
