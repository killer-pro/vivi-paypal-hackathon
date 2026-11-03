import json
import uuid

import httpx
import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.app_settings import AppSettings
from app.config import settings
from app.models import Project
from app.providers.base import GenerationResult, ProviderError, TextResult
from app.services import langfuse
from app.services.costs import tracked_call
from tests.conftest import ensure_admin


@pytest.fixture(autouse=True)
def no_env_keys(monkeypatch):
    """Les clés du `.env` du poste ne doivent pas activer le journal dans les tests."""
    for name in ("langfuse_public_key", "langfuse_secret_key", "langfuse_base_url"):
        monkeypatch.setattr(settings, name, "")


@pytest.fixture
def config():
    """Clés propres à chaque test : le SDK ne garde qu'une instance par clé publique."""
    return langfuse.LangfuseConfig(f"pk-lf-{uuid.uuid4()}", "sk-lf-1", "https://lf.test")


@pytest.fixture
def spans(monkeypatch, config):
    """Observations produites par le vrai SDK, captées en mémoire (aucun réseau)."""
    exporter = InMemorySpanExporter()
    client = Langfuse(public_key=config.public_key, secret_key=config.secret_key, base_url=config.base_url,
                      span_exporter=exporter)
    monkeypatch.setitem(langfuse._clients, config, client)

    def finished() -> list:
        client.flush()
        return [(s.name, dict(s.attributes or {}), s) for s in exporter.get_finished_spans()]

    yield finished
    client.shutdown()  # libère l'instance : le SDK en garde une seule par clé publique


async def new_project(session) -> int:
    project = Project(title="t", user_id=(await ensure_admin(session)).id)
    session.add(project)
    await session.commit()
    return project.id


async def enable(session, config):
    await AppSettings(session).set_many({"langfuse_public_key": config.public_key, "langfuse_secret_key": config.secret_key,
                                         "langfuse_base_url": config.base_url + "/"})


def attr(attributes: dict, key: str):
    """Attribut d'observation ; les valeurs structurées et les métadonnées sont du JSON, les autres du texte."""
    value = attributes[f"langfuse.observation.{key}"]
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


async def test_no_keys_means_no_observation(session, spans, config):
    async def fn():
        return TextResult("ok", 0.01, "m")

    await tracked_call(session, project_id=await new_project(session), step="story", provider="p", model="m", fn=fn,
                       input=langfuse.messages("prompt"))
    assert spans() == []


async def test_success_is_a_generation_with_messages_usage_and_cost(session, spans, config):
    await enable(session, config)
    pid = await new_project(session)

    async def fn():
        return TextResult("réponse", 0.25, "m", 12, 7)

    await tracked_call(session, project_id=pid, step="story", provider="gemini", model="m", fn=fn,
                       input=langfuse.messages("prompt", "système"))
    (name, attributes, _), = spans()
    assert name == "write-story"  # nom stable, verbe d'abord : ni identifiant ni modèle
    assert attr(attributes, "type") == "generation" and attr(attributes, "model.name") == "m"
    assert attr(attributes, "input") == [{"role": "system", "content": "système"}, {"role": "user", "content": "prompt"}]
    assert attr(attributes, "output") == {"role": "assistant", "content": "réponse"}
    assert attr(attributes, "usage_details") == {"input": 12, "output": 7}
    assert attr(attributes, "cost_details") == {"total": 0.25}
    assert attributes["session.id"] == f"projet-{pid}" and attributes["langfuse.trace.tags"] == ("story",)
    assert attr(attributes, "metadata.provider") == "gemini" and attr(attributes, "metadata.attempt") == "1"


async def test_media_is_described_not_sent(session, spans, config):
    await enable(session, config)

    async def fn():
        return GenerationResult(b"x" * 10, "video/mp4", 0.5, "m")

    await tracked_call(session, project_id=None, step="clips", provider="p", model="m", fn=fn,
                       input=langfuse.messages("un plan"))
    (name, attributes, _), = spans()
    assert name == "generate-clip" and attr(attributes, "output") == {"content_type": "video/mp4", "bytes": 10}


async def test_each_failed_attempt_is_an_error_generation(session, spans, config):
    await enable(session, config)

    async def fn():
        raise ProviderError("503", retryable=True)

    with pytest.raises(ProviderError):
        await tracked_call(session, project_id=None, step="assist:rewrite", provider="p", model="m", fn=fn,
                           attempts=2, base_delay=0)
    attempts = [(a["langfuse.observation.level"], a["langfuse.observation.status_message"],
                 attr(a, "metadata.attempt")) for _, a, _ in spans()]
    assert attempts == [("ERROR", "503", "1"), ("ERROR", "503", "2")]
    assert spans()[0][0] == "assist-rewrite"


async def test_step_run_is_the_trace_root_of_its_generations(session, spans, config):
    await enable(session, config)
    pid = await new_project(session)

    async def fn():
        return TextResult("ok", 0.01, "m")

    with langfuse.step_run(config, project_id=pid, title="Mon projet", step="story") as root:
        await tracked_call(session, project_id=pid, step="story", provider="p", model="m", fn=fn)
        await tracked_call(session, project_id=pid, step="story", provider="p", model="m", fn=fn)
        root.update(output={"status": "awaiting_validation"})
    by_name = {}
    for name, attributes, span in spans():
        by_name.setdefault(name, []).append((attributes, span))
    (root_attrs, root_span), = by_name["run-story"]
    assert root_span.parent is None and root_attrs["langfuse.trace.name"] == "run-story"
    assert root_attrs["session.id"] == f"projet-{pid}"
    assert attr(root_attrs, "input") == {"project": "Mon projet", "step": "story"}
    assert [s.parent.span_id for _, s in by_name["write-story"]] == [root_span.context.span_id] * 2


def test_step_run_without_config_is_inert():
    with langfuse.step_run(None, project_id=1, title="t", step="story") as root:
        assert root is None


def test_names_are_stable_verbs():
    assert [langfuse.action(s) for s in ("story", "clips", "assist:rewrite", "plan_chat", "autre_etape")] == [
        "write-story", "generate-clip", "assist-rewrite", "chat-plan", "autre-etape"]


def test_long_text_is_clipped():
    assert langfuse.messages("x" * (langfuse.MAX_TEXT + 5))[0]["content"].endswith("(coupé)")


async def test_shutdown_flushes_and_forgets_the_clients(spans):
    langfuse.shutdown()
    assert langfuse._clients == {}


@pytest.mark.parametrize(("status", "keys", "expected"), [(200, True, True), (401, True, False), (200, False, False)])
async def test_healthy_checks_the_keys(config, status, keys, expected):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status))) as client:
        assert await langfuse.healthy(config if keys else None, client) is expected
