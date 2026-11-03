"""Chat du plan : l'IA répond, et modifie au besoin le plan (titre, fiche visuelle, scènes) avec instantané pour annuler."""
import json

import pytest
from sqlalchemy import select

from app.api.projects import get_registry
from app.main import app
from app.models import ProviderCall, Scene, Step
from app.providers.base import ProviderError, TextResult
from tests.test_api_steps import new_project, set_status, statuses


class ScriptedLLM:
    name = "scripted-llm"
    model = "s-1"

    def __init__(self):
        self.answer: object = {"reply": "Voilà."}
        self.error: ProviderError | None = None
        self.prompts: list[str] = []

    async def complete(self, system, prompt, *, max_tokens=4000, json_schema=None):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        text = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return TextResult(text, 0.002, self.model)


@pytest.fixture
def llm():
    scripted = ScriptedLLM()

    class Registry:
        async def llm(self):
            return scripted

    app.dependency_overrides[get_registry] = lambda: Registry()
    yield scripted
    app.dependency_overrides.pop(get_registry, None)


async def plan_project(api, session, count=3):
    """Projet dont le script est à valider : `count` scènes, fiche visuelle « B »."""
    pid = await new_project(api)
    await set_status(session, ["idea"], "approved")
    await set_status(session, ["script"], "awaiting_validation")
    step = await session.scalar(select(Step).where(Step.project_id == pid, Step.name == "script"))
    step.result = {"bible": "B"}
    session.add_all(Scene(project_id=pid, position=i, voice_text=f"voix {i}", visual_prompt=f"plan {i}", duration_s=5)
                    for i in range(1, count + 1))
    await session.commit()
    return pid


async def scenes_of(session, pid):
    rows = (await session.scalars(select(Scene).where(Scene.project_id == pid).order_by(Scene.position))).all()
    for row in rows:
        await session.refresh(row)
    return rows


def plan_of(scenes, changes=None):
    """Plan complet renvoyé par l'IA : les scènes existantes, `changes` : {position: champs modifiés}."""
    return {"title": "Nouveau titre", "bible": "B2", "scenes": [
        {"id": s.id, "voice_text": s.voice_text, "visual_prompt": s.visual_prompt, "duration_s": s.duration_s,
         **(changes or {}).get(s.position, {})} for s in scenes]}


async def chat(api, pid, message="Change la scène 2"):
    return await api.post(f"/api/projects/{pid}/plan/chat", json={"message": message})


async def messages(api, pid):
    return (await api.get(f"/api/projects/{pid}/plan/messages")).json()


async def test_chat_question_keeps_plan(api, session, llm):
    pid = await plan_project(api, session)
    llm.answer = {"reply": "Trois scènes de 5 s."}
    r = await chat(api, pid, "Combien de scènes ?")
    assert r.status_code == 200
    body = r.json()
    assert body["plan_changed"] is False
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][1]["content"] == "Trois scènes de 5 s."
    assert [s.voice_text for s in await scenes_of(session, pid)] == ["voix 1", "voix 2", "voix 3"]
    assert len(await messages(api, pid)) == 2


async def test_chat_edit_replaces_scene_text_and_keeps_ids(api, session, llm):
    pid = await plan_project(api, session)
    before = await scenes_of(session, pid)
    llm.answer = {"reply": "Fait.", "plan": plan_of(before, {2: {"voice_text": "nouvelle voix"}})}
    r = await chat(api, pid)
    assert r.json()["plan_changed"] is True
    after = await scenes_of(session, pid)
    assert [s.id for s in after] == [s.id for s in before]
    assert [s.voice_text for s in after] == ["voix 1", "nouvelle voix", "voix 3"]
    project = (await api.get(f"/api/projects/{pid}")).json()
    assert project["title"] == "Nouveau titre"
    assert next(s for s in project["steps"] if s["name"] == "script")["result"]["bible"] == "B2"


async def test_chat_can_add_and_remove_scenes(api, session, llm):
    pid = await plan_project(api, session)
    before = await scenes_of(session, pid)
    plan = plan_of(before)
    plan["scenes"] = [plan["scenes"][0], plan["scenes"][2],
                      {"id": None, "voice_text": "fin", "visual_prompt": "plan fin", "duration_s": 4}]
    llm.answer = {"reply": "Ok.", "plan": plan}
    assert (await chat(api, pid)).status_code == 200
    after = await scenes_of(session, pid)
    assert [s.voice_text for s in after] == ["voix 1", "voix 3", "fin"]
    assert after[0].id == before[0].id and after[1].id == before[2].id and after[2].id not in {s.id for s in before}


async def test_chat_marks_downstream_stale(api, session, llm):
    pid = await plan_project(api, session)
    await set_status(session, ["script", "reference", "clips", "voice"], "approved")
    llm.answer = {"reply": "Ok.", "plan": plan_of(await scenes_of(session, pid), {1: {"voice_text": "autre"}})}
    assert (await chat(api, pid)).status_code == 200
    status = await statuses(api, pid)
    assert status["clips"] == status["voice"] == "stale"


async def test_chat_visual_sheet_change_keeps_reference_fresh(api, session, llm):
    pid = await plan_project(api, session)
    await set_status(session, ["script", "reference", "clips"], "approved")
    await session.execute(Step.__table__.update().where(Step.name == "reference").values(result={"asset_ids": [1]}))
    await session.commit()
    llm.answer = {"reply": "Ok.", "plan": plan_of(await scenes_of(session, pid))}  # bible B -> B2, éléments inchangés
    assert (await chat(api, pid)).status_code == 200
    status = await statuses(api, pid)
    assert status["reference"] == "approved" and status["clips"] == "stale"


@pytest.mark.parametrize("answer", [
    "pas du json",
    {"reply": "x", "plan": {"scenes": []}},
    {"reply": "x", "plan": {"scenes": [{"id": None, "voice_text": " ", "visual_prompt": "p", "duration_s": 3}]}},
    {"reply": "x", "plan": {"scenes": [{"id": None, "voice_text": "v", "visual_prompt": "p", "duration_s": 0}]}},
    {"reply": "x", "plan": {"scenes": [{"id": None, "voice_text": "v", "visual_prompt": "p", "duration_s": 3}] * 31}},
    {"reply": "x", "plan": {"scenes": [{"id": 1, "voice_text": "v", "visual_prompt": "p", "duration_s": 3}] * 2}},
    {"plan": {"scenes": [{"id": None, "voice_text": "v", "visual_prompt": "p", "duration_s": 3}]}},
])
async def test_chat_invalid_plan_is_502_and_nothing_changes(api, session, llm, answer):
    pid = await plan_project(api, session)
    llm.answer = answer
    r = await chat(api, pid)
    assert r.status_code == 502 and r.json()["detail"]
    assert [s.voice_text for s in await scenes_of(session, pid)] == ["voix 1", "voix 2", "voix 3"]
    assert await messages(api, pid) == []


async def test_chat_provider_error_is_502(api, session, llm):
    pid = await plan_project(api, session)
    llm.error = ProviderError("panne", retryable=False)
    assert (await chat(api, pid)).status_code == 502
    assert await messages(api, pid) == []


async def test_chat_refused_when_downstream_running(api, session, llm):
    pid = await plan_project(api, session)
    await set_status(session, ["script"], "approved")
    await set_status(session, ["reference"], "running")
    r = await chat(api, pid)
    assert r.status_code == 409 and llm.prompts == []


async def test_chat_refused_when_budget_reached(api, session, llm):
    pid = await plan_project(api, session)
    assert (await api.put("/api/settings", json={"project_budget_usd": "1"})).status_code == 200
    session.add(ProviderCall(project_id=pid, step="clips", provider="fal", model="k", cost_usd=2, status="ok"))
    await session.commit()
    r = await chat(api, pid)
    assert r.status_code == 409 and "Budget" in r.json()["detail"] and llm.prompts == []


async def test_chat_logs_cost(api, session, llm):
    pid = await plan_project(api, session)
    await chat(api, pid)
    call = await session.scalar(select(ProviderCall).where(ProviderCall.project_id == pid))
    assert call.step == "plan_chat" and call.status == "ok"


async def test_chat_prompt_carries_plan_with_ids_and_history(api, session, llm):
    pid = await plan_project(api, session)
    scenes = await scenes_of(session, pid)
    await chat(api, pid, "Première question")
    await chat(api, pid, "Seconde question")
    prompt = llm.prompts[-1]
    assert f'"id": {scenes[0].id}' in prompt and "voix 2" in prompt
    assert "Première question" in prompt and "Seconde question" in prompt


async def test_undo_restores_plan_and_only_last_message_is_undoable(api, session, llm):
    pid = await plan_project(api, session)
    llm.answer = {"reply": "A.", "plan": plan_of(await scenes_of(session, pid), {1: {"voice_text": "A1"}})}
    await chat(api, pid, "premier")
    llm.answer = {"reply": "B.", "plan": plan_of(await scenes_of(session, pid), {1: {"voice_text": "B1"}})}
    await chat(api, pid, "second")
    llm.answer = {"reply": "Sans changement."}
    await chat(api, pid, "question")
    listed = await messages(api, pid)
    assistants = [m for m in listed if m["role"] == "assistant"]
    assert [m["can_undo"] for m in assistants] == [False, True, False]
    first, second = assistants[0], assistants[1]
    assert (await api.post(f"/api/projects/{pid}/plan/messages/{first['id']}/undo")).status_code == 409
    assert (await api.post(f"/api/projects/{pid}/plan/messages/{second['id']}/undo")).status_code == 204
    assert (await scenes_of(session, pid))[0].voice_text == "A1"
    assert (await api.post(f"/api/projects/{pid}/plan/messages/{second['id']}/undo")).status_code == 409
    assert not any(m["can_undo"] for m in await messages(api, pid))


async def test_undo_restores_removed_scene_and_title(api, session, llm):
    pid = await plan_project(api, session)
    scenes = await scenes_of(session, pid)
    plan = plan_of(scenes)
    plan["scenes"] = plan["scenes"][:2]
    llm.answer = {"reply": "Retirée.", "plan": plan}
    await chat(api, pid)
    mid = next(m["id"] for m in await messages(api, pid) if m["can_undo"])
    assert (await api.post(f"/api/projects/{pid}/plan/messages/{mid}/undo")).status_code == 204
    assert [s.voice_text for s in await scenes_of(session, pid)] == ["voix 1", "voix 2", "voix 3"]
    data = (await api.get(f"/api/projects/{pid}")).json()
    assert data["title"] == "t"
    assert next(s for s in data["steps"] if s["name"] == "script")["result"]["bible"] == "B"


async def test_undo_refused_when_downstream_running(api, session, llm):
    pid = await plan_project(api, session)
    llm.answer = {"reply": "A.", "plan": plan_of(await scenes_of(session, pid), {1: {"voice_text": "A1"}})}
    await chat(api, pid)
    mid = next(m["id"] for m in await messages(api, pid) if m["can_undo"])
    await set_status(session, ["clips"], "running")
    assert (await api.post(f"/api/projects/{pid}/plan/messages/{mid}/undo")).status_code == 409
    assert (await scenes_of(session, pid))[0].voice_text == "A1"


async def test_messages_listed_in_order_with_can_undo(api, session, llm):
    pid = await plan_project(api, session)
    await chat(api, pid, "un")
    await chat(api, pid, "deux")
    listed = await messages(api, pid)
    assert [m["content"] for m in listed if m["role"] == "user"] == ["un", "deux"]
    assert [m["role"] for m in listed] == ["user", "assistant", "user", "assistant"]
    assert all(set(m) == {"id", "role", "content", "can_undo", "created_at"} for m in listed)


@pytest.mark.parametrize("message", ["", "   ", "x" * 2001])
async def test_chat_message_length_validation(api, session, llm, message):
    pid = await plan_project(api, session)
    assert (await chat(api, pid, message)).status_code == 422
    assert llm.prompts == []


async def test_chat_unknown_project_is_404(api, llm):
    assert (await chat(api, 999)).status_code == 404
    assert (await api.get("/api/projects/999/plan/messages")).status_code == 404


@pytest.mark.parametrize("bible", [None, 3])
async def test_chat_plan_with_unusable_bible_keeps_current_one(api, session, llm, bible):
    pid = await plan_project(api, session)
    plan = plan_of(await scenes_of(session, pid), {1: {"voice_text": "autre"}})
    plan["bible"] = bible
    llm.answer = {"reply": "Ok.", "plan": plan}
    assert (await chat(api, pid)).status_code == 200
    script = next(s for s in (await api.get(f"/api/projects/{pid}")).json()["steps"] if s["name"] == "script")
    assert script["result"]["bible"] == "B"
