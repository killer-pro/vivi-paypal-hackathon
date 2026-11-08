import json
import logging
from datetime import date

import httpx
import pytest

from app.app_settings import AppSettings
from app.providers import gemini as gemini_mod
from app.providers import registry as registry_mod
from app.providers.base import ProviderError
from app.providers.claude import ClaudeLLM
from app.providers.gemini import DEFAULT_MODEL, PRICES, PRICES_VALID_UNTIL, THINKING_LEVELS, GeminiLLM
from app.providers.registry import ProviderRegistry

KEY = "AIza-secret-key-1234"


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def ok(text="Bonjour", usage=None, **candidate):
    return httpx.Response(200, json={
        "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP", **candidate}],
        "usageMetadata": usage if usage is not None else
        {"promptTokenCount": 1000, "candidatesTokenCount": 500, "thoughtsTokenCount": 200},
    })


async def test_gemini_contract_request_shape_and_cost():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(url=str(req.url), key=req.headers.get("x-goog-api-key"), body=json.loads(req.content))
        return ok()

    llm = GeminiLLM(KEY, client(handler), model="gemini-3.5-flash-lite")
    r = await llm.complete("tu es scénariste", "écris", max_tokens=123)
    assert llm.name == "gemini" and r.text == "Bonjour" and r.model == "gemini-3.5-flash-lite"
    assert seen["url"].endswith("/v1beta/models/gemini-3.5-flash-lite:generateContent")
    assert seen["key"] == KEY and KEY not in seen["url"]
    assert seen["body"]["systemInstruction"] == {"parts": [{"text": "tu es scénariste"}]}
    assert seen["body"]["contents"] == [{"role": "user", "parts": [{"text": "écris"}]}]
    assert seen["body"]["generationConfig"]["maxOutputTokens"] == 123
    price_in, price_out = PRICES["gemini-3.5-flash-lite"]
    # les tokens de réflexion sont facturés comme de la sortie
    assert r.cost_usd == pytest.approx((1000 * price_in + 700 * price_out) / 1_000_000)


async def test_gemini_health_checks_the_key_with_a_free_call():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.headers.get("x-goog-api-key")))
        return httpx.Response(200 if request.headers.get("x-goog-api-key") == KEY else 403)

    assert await GeminiLLM(KEY, client(handler)).health() is True
    assert await GeminiLLM("mauvaise", client(handler)).health() is False
    assert seen[0] == ("GET", "/v1beta/models", KEY)  # liste des modèles : gratuite, la clé reste dans l'en-tête


async def test_health_is_false_when_the_service_is_unreachable():
    def down(request):
        raise httpx.ConnectError("réseau coupé")

    assert await GeminiLLM(KEY, client(down)).health() is False


async def test_gemini_ignores_thought_parts_and_joins_text():
    body = {"candidates": [{"content": {"parts": [{"text": "pensée", "thought": True}, {"text": "A"}, {"text": "B"}]}}],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1}}
    r = await GeminiLLM(KEY, client(lambda req: httpx.Response(200, json=body))).complete("s", "p")
    assert r.text == "AB"


async def test_gemini_unknown_model_uses_fallback_price():
    r = await GeminiLLM(KEY, client(lambda req: ok()), model="gemini-futur").complete("s", "p")
    price_in, price_out = max(PRICES.values())
    assert r.cost_usd == pytest.approx((1000 * price_in + 700 * price_out) / 1_000_000)


@pytest.mark.parametrize("model", list(PRICES) + ["gemini-futur"])
async def test_gemini_thinking_level_per_model(model):
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content)["generationConfig"])
        return ok()

    await GeminiLLM(KEY, client(handler), model=model).complete("s", "p")
    if model in THINKING_LEVELS:
        assert seen["thinkingConfig"] == {"thinkingLevel": THINKING_LEVELS[model]}
        assert "thinkingBudget" not in seen["thinkingConfig"]
    else:  # niveau non documenté pour ce modèle : on ne l'envoie pas (évite un 400)
        assert "thinkingConfig" not in seen


def test_thinking_levels_are_minimal_where_supported():
    assert THINKING_LEVELS[DEFAULT_MODEL] == "minimal"
    assert set(THINKING_LEVELS) <= set(PRICES) and set(THINKING_LEVELS.values()) <= {"minimal", "low"}


@pytest.mark.parametrize("reason,match", [
    ("MAX_TOKENS", "tronquée"), ("SAFETY", "interrompue.*SAFETY"), ("RECITATION", "interrompue.*RECITATION"),
])
async def test_gemini_truncated_text_is_never_success(reason, match):
    """Texte partiel + finishReason anormal : erreur non relançable, jamais un succès tronqué."""
    with pytest.raises(ProviderError, match=match) as e:
        await GeminiLLM(KEY, client(lambda req: ok(text='{"scenes": [', finishReason=reason))).complete("s", "p")
    assert not e.value.retryable


@pytest.mark.parametrize("usage,tokens_out", [
    ({"promptTokenCount": 1000, "totalTokenCount": 1700}, 700),  # candidatesTokenCount absent
    ({"promptTokenCount": 1000, "candidatesTokenCount": None, "thoughtsTokenCount": None, "totalTokenCount": 1700}, 700),
    ({"promptTokenCount": None, "candidatesTokenCount": 500, "thoughtsTokenCount": None}, 500),
    ({}, 0),
])
async def test_gemini_usage_fallbacks_are_none_safe(usage, tokens_out):
    r = await GeminiLLM(KEY, client(lambda req: ok(usage=usage)), model="gemini-3.5-flash-lite").complete("s", "p")
    price_in, price_out = PRICES["gemini-3.5-flash-lite"]
    tokens_in = usage.get("promptTokenCount") or 0
    assert r.cost_usd == pytest.approx((tokens_in * price_in + tokens_out * price_out) / 1_000_000)


async def test_gemini_model_is_url_quoted():
    seen = {}

    def handler(req):
        seen["path"] = req.url.raw_path.decode()
        return ok()

    await GeminiLLM(KEY, client(handler), model="x/../y?z").complete("s", "p")
    assert seen["path"].endswith("/models/x%2F..%2Fy%3Fz:generateContent")


def test_stale_price_table_warns(caplog, monkeypatch):
    monkeypatch.setattr(gemini_mod, "_stale_warned", False)
    with caplog.at_level(logging.WARNING):
        gemini_mod.warn_if_prices_stale(PRICES_VALID_UNTIL)
        assert "PRICES" not in caplog.text
        gemini_mod.warn_if_prices_stale(date(2027, 1, 2))
        gemini_mod.warn_if_prices_stale(date(2027, 1, 3))
    assert caplog.text.count("PRICES") == 1  # une seule fois par processus


@pytest.mark.parametrize("status,retryable", [(500, True), (503, True), (429, True), (400, False), (403, False)])
async def test_gemini_http_errors(status, retryable):
    with pytest.raises(ProviderError) as e:
        await GeminiLLM(KEY, client(lambda req: httpx.Response(status, json={"error": {"message": "x"}}))).complete("s", "p")
    assert e.value.retryable is retryable and str(status) in str(e.value)


async def test_gemini_network_error_is_retryable():
    def handler(req):
        raise httpx.ConnectError("down")

    with pytest.raises(ProviderError, match="réseau") as e:
        await GeminiLLM(KEY, client(handler)).complete("s", "p")
    assert e.value.retryable


@pytest.mark.parametrize("body", [
    {"promptFeedback": {"blockReason": "SAFETY"}},
    {"candidates": [{"finishReason": "SAFETY"}]},
    {"candidates": [{"content": {"parts": [{"text": "  "}]}, "finishReason": "STOP"}]},
    {},
])
async def test_gemini_empty_or_blocked_is_error(body):
    with pytest.raises(ProviderError) as e:
        await GeminiLLM(KEY, client(lambda req: httpx.Response(200, json=body))).complete("s", "p")
    assert not e.value.retryable


async def test_gemini_key_never_in_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    errors = []
    for handler in (lambda r: httpx.Response(401, text="bad key"), lambda r: httpx.Response(200, json={})):
        with pytest.raises(ProviderError) as e:
            await GeminiLLM(KEY, client(handler)).complete("s", "p")
        errors.append(str(e.value))
    assert all(KEY not in err for err in errors)
    assert KEY not in caplog.text


@pytest.fixture
def real_providers(monkeypatch):
    monkeypatch.setattr(registry_mod.settings, "fake_providers", False)


async def test_registry_picks_llm_by_setting(session, real_providers):
    s = AppSettings(session)
    reg = ProviderRegistry(s)
    assert isinstance(await reg.llm(), ClaudeLLM)  # défaut
    await s.set_many({"llm_provider": "gemini", "gemini_api_key": KEY})
    llm = await reg.llm()
    assert isinstance(llm, GeminiLLM) and llm.model == DEFAULT_MODEL
    await s.set("gemini_model", "gemini-3.6-flash")
    assert (await reg.llm()).model == "gemini-3.6-flash"
    await reg.aclose()


async def test_registry_unknown_llm_provider_is_clear_error(session, real_providers, monkeypatch):
    s = AppSettings(session)
    real_get = s.get

    async def get(key):
        return "mistral" if key == "llm_provider" else await real_get(key)

    monkeypatch.setattr(s, "get", get)
    with pytest.raises(ProviderError, match="mistral"):
        await ProviderRegistry(s).llm()


async def test_registry_fake_mode_stays_fake_for_gemini(session):
    s = AppSettings(session)
    await s.set("llm_provider", "gemini")
    reg = ProviderRegistry(s)
    assert (await reg.llm()).name == "fake-llm"
    assert (await reg.health_report())["gemini"] is True


async def test_settings_llm_provider_validated(api):
    assert (await api.put("/api/settings", json={"llm_provider": "mistral"})).status_code == 400
    r = await api.put("/api/settings", json={"llm_provider": "gemini", "gemini_api_key": KEY})
    assert r.status_code == 200
    data = r.json()
    assert data["llm_provider"] == "gemini" and data["gemini_api_key"] == "••••1234"
    assert data["gemini_model"] == DEFAULT_MODEL


@pytest.mark.parametrize("model", ["a/b", "x?y", "x#y", "gemini 3", " gemini", "../x"])
async def test_settings_gemini_model_validated(api, model):
    assert (await api.put("/api/settings", json={"gemini_model": model})).status_code == 400


async def test_settings_gemini_model_accepts_ids(api):
    r = await api.put("/api/settings", json={"gemini_model": "gemini-3.6-flash"})
    assert r.status_code == 200 and r.json()["gemini_model"] == "gemini-3.6-flash"


async def test_providers_models_lists_gemini_models(api):
    data = (await api.get("/api/providers/models")).json()
    assert data["llm"]["gemini"] == list(PRICES) and data["llm"]["groq"][0] == "openai/gpt-oss-120b"


async def test_gemini_structured_output_only_when_schema_given():
    """Étapes JSON : `responseMimeType` + `responseSchema` ; texte libre : aucun des deux (rétrocompatible)."""
    seen = []
    schema = {"type": "OBJECT", "properties": {"a": {"type": "STRING"}}, "required": ["a"]}

    def handler(req):
        seen.append(json.loads(req.content)["generationConfig"])
        return ok(text='{"a": "x"}')

    llm = GeminiLLM(KEY, client(handler))
    await llm.complete("s", "p", json_schema=schema)
    await llm.complete("s", "p")
    assert seen[0]["responseMimeType"] == "application/json" and seen[0]["responseSchema"] == schema
    assert "responseMimeType" not in seen[1] and "responseSchema" not in seen[1]


async def test_claude_accepts_json_schema_and_keeps_request_unchanged():
    seen = {}

    class Messages:
        async def create(self, **kwargs):
            seen.update(kwargs)
            block = type("B", (), {"type": "text", "text": '{"a": 1}'})()
            usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()
            return type("M", (), {"content": [block], "usage": usage})()

    fake_client = type("C", (), {"messages": Messages()})()
    r = await ClaudeLLM("k", client=fake_client).complete("s", "p", json_schema={"type": "OBJECT"})
    assert r.text == '{"a": 1}' and "json_schema" not in seen and seen["system"] == "s"
