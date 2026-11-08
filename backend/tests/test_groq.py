import json

import httpx
import pytest

from app.providers.base import ProviderError
from app.providers.groq import GroqLLM


def llm(handler, key="gsk-test", model="openai/gpt-oss-120b") -> GroqLLM:
    return GroqLLM(key, httpx.AsyncClient(transport=httpx.MockTransport(handler)), model)


def answer(content="{}", finish="stop") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": finish}],
                                     "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}})


async def test_complete_sends_json_schema_and_prices_tokens():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(url=str(req.url), auth=req.headers["authorization"], body=json.loads(req.content))
        return answer('{"a": 1}')

    result = await llm(handler).complete("système", "idée", max_tokens=500,
                                         json_schema={"type": "OBJECT", "properties": {"id": {"type": "INTEGER", "nullable": True}}})
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions" and seen["auth"] == "Bearer gsk-test"
    assert seen["body"]["max_completion_tokens"] == 500 and seen["body"]["reasoning_effort"] == "low"
    assert seen["body"]["response_format"]["json_schema"]["schema"] == {
        "type": "object", "properties": {"id": {"type": ["integer", "null"]}}}
    assert (result.text, result.model, result.input_tokens, result.output_tokens) == ('{"a": 1}', "openai/gpt-oss-120b",
                                                                                      1_000_000, 1_000_000)
    assert result.cost_usd == pytest.approx(0.75)


async def test_without_key_no_request_is_sent():
    def handler(req):
        raise AssertionError("aucune requête attendue")

    with pytest.raises(ProviderError, match="Réglages → Groq"):
        await llm(handler, key="").complete("s", "p")


async def test_truncated_empty_and_invalid_json_answers_raise():
    with pytest.raises(ProviderError, match="tronquée"):
        await llm(lambda r: answer("{", finish="length")).complete("s", "p")
    with pytest.raises(ProviderError, match="vide"):
        await llm(lambda r: answer("  ")).complete("s", "p")
    invalid = httpx.Response(400, json={"error": {"code": "json_validate_failed"}})
    with pytest.raises(ProviderError, match="non conforme") as e:
        await llm(lambda r: invalid).complete("s", "p", json_schema={"type": "OBJECT"})
    assert e.value.retryable


async def test_health_checks_the_key_on_the_models_list():
    assert await llm(lambda r: httpx.Response(200, json={"data": []})).health()
    assert not await llm(lambda r: httpx.Response(401)).health()
    assert not await llm(lambda r: httpx.Response(200), key="").health()
