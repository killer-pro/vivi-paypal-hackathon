import pytest
from sqlalchemy import select

from app.api.projects import get_registry
from app.main import app
from app.models import Project, ProviderCall, Scene, Step
from app.providers.base import ProviderError, TextResult
from app.providers.fakes import FAKE_ASSIST
from app.services.assist import FIELD_KINDS, MAX_INSTRUCTION, MAX_TEXT, clean_output
from app.services.prompts import VISUAL_PROMPT_GUIDE
from app.state import STEP_NAMES
from tests.conftest import ensure_admin


class RecordingLLM:
    name = "recording-llm"
    model = "rec-1"

    def __init__(self, answer="Texte proposé", error: ProviderError | None = None):
        self.answer, self.error = answer, error
        self.calls = []

    async def complete(self, system, prompt, *, max_tokens=4000, json_schema=None):
        self.calls.append({"system": system, "prompt": prompt, "json_schema": json_schema})
        if self.error:
            raise self.error
        return TextResult(self.answer, 0.002, self.model)


@pytest.fixture
def llm():
    """LLM enregistreur injecté à la place du registre (le mode FAKE_PROVIDERS reste testé à part)."""
    recorder = RecordingLLM()

    class Registry:
        async def llm(self):
            return recorder

    app.dependency_overrides[get_registry] = lambda: Registry()
    yield recorder
    app.dependency_overrides.pop(get_registry, None)


async def seed(session, target=30):
    p = Project(title="Sommeil", theme="3 erreurs du soir", target_duration_s=target,
                user_id=(await ensure_admin(session)).id)
    session.add(p)
    await session.flush()
    angle = {"angle": "Le téléphone n'est pas coupable"}
    session.add_all(Step(project_id=p.id, name=n, status="approved" if n == "idea" else "pending",
                         result=angle if n == "idea" else {}) for n in STEP_NAMES)
    scene = Scene(project_id=p.id, position=1, voice_text="Tu dors mal ?", visual_prompt="woman awake in bed",
                  duration_s=4)
    session.add(scene)
    await session.commit()
    return p, scene


async def assist(api, **body):
    return await api.post("/api/ai/assist", json={"mode": "generate", "text": "", **body})


async def test_fake_mode_generates_and_rewrites_deterministically(api, session):
    p, scene = await seed(session)
    r = await assist(api, field_kind="voice_text", project_id=p.id, scene_id=scene.id)
    assert r.status_code == 200 and r.json()["text"]
    again = await assist(api, field_kind="voice_text", project_id=p.id, scene_id=scene.id)
    assert again.json() == r.json()
    rw = await assist(api, field_kind="angle", mode="rewrite", text="Un angle à reprendre", instruction="plus court")
    assert rw.status_code == 200 and "Un angle à reprendre" in rw.json()["text"]
    tags = await assist(api, field_kind="hashtags")
    assert all(t.startswith("#") for t in tags.json()["text"].split())


async def test_every_field_kind_works_in_fake_mode(api):
    assert set(FAKE_ASSIST) == set(FIELD_KINDS)  # un exemple plausible par champ pour le walkthrough
    for kind in FIELD_KINDS:
        r = await assist(api, field_kind=kind)
        assert r.status_code == 200 and r.json()["text"].strip(), kind


async def test_call_is_tracked_with_project_and_counted_in_costs(api, session, llm):
    p, scene = await seed(session)
    assert (await assist(api, field_kind="title", project_id=p.id)).status_code == 200
    call = await session.scalar(select(ProviderCall))
    assert (call.project_id, call.step, call.provider, call.model, call.status) == (
        p.id, "assist:title", "recording-llm", "rec-1", "ok")
    costs = (await api.get("/api/costs", params={"project_id": p.id})).json()
    assert costs["total_usd"] == pytest.approx(0.002)


async def test_voice_text_prompt_has_word_budget_context_and_instruction(api, session, llm):
    p, scene = await seed(session)
    await assist(api, field_kind="voice_text", mode="rewrite", text="Tu dors mal ?", instruction="plus punchy",
                 project_id=p.id, scene_id=scene.id)
    prompt, system = llm.calls[0]["prompt"], llm.calls[0]["system"]
    assert "10 mots" in prompt and "4 s" in prompt  # 4 s × 2,5 mots/s
    assert "3 erreurs du soir" in prompt and "Le téléphone n'est pas coupable" in prompt
    assert "Tu dors mal ?" in prompt and "plus punchy" in prompt and "woman awake in bed" in prompt
    assert "uniquement" in system.lower() and llm.calls[0]["json_schema"] is None


async def test_duration_override_wins_for_unsaved_scene_drafts(api, session, llm):
    p, _ = await seed(session)
    await assist(api, field_kind="voice_text", project_id=p.id, duration_s=6)
    assert "15 mots" in llm.calls[0]["prompt"]


async def test_visual_prompt_is_asked_in_english(api, llm):
    await assist(api, field_kind="visual_prompt")
    assert "anglais" in llm.calls[0]["prompt"] and VISUAL_PROMPT_GUIDE in llm.calls[0]["prompt"]  # même guide que le script


@pytest.mark.parametrize("kind,styled", [("visual_prompt", True), ("reference_prompt", True), ("bible", True), ("voice_text", False)])
async def test_project_style_reaches_visual_fields_only(api, session, llm, kind, styled):
    p, _ = await seed(session)
    p.style = "anime"
    await session.commit()
    await assist(api, field_kind=kind, project_id=p.id)
    assert ("Style visuel imposé : Japanese anime style" in llm.calls[0]["prompt"]) is styled


@pytest.mark.parametrize("body,status", [
    ({"field_kind": "angle", "mode": "rewrite", "text": "   "}, 422),
    ({"field_kind": "angle", "mode": "rewrite"}, 422),
    ({"field_kind": "inconnu"}, 422),
    ({"field_kind": "angle", "mode": "traduire"}, 422),
    ({"field_kind": "angle", "text": "x" * (MAX_TEXT + 1)}, 422),
    ({"field_kind": "angle", "instruction": "x" * (MAX_INSTRUCTION + 1)}, 422),
    ({"field_kind": "angle", "project_id": 999999}, 404),
    ({"field_kind": "voice_text", "scene_id": 1}, 422),  # scène sans projet
])
async def test_invalid_input(api, llm, body, status):
    r = await api.post("/api/ai/assist", json={"mode": "generate", **body})
    assert r.status_code == status and isinstance(r.json()["detail"], str)  # message français lisible
    assert llm.calls == []


async def test_scene_of_another_project_is_404(api, session, llm):
    p, scene = await seed(session)
    other, _ = await seed(session)
    r = await assist(api, field_kind="voice_text", project_id=other.id, scene_id=scene.id)
    assert r.status_code == 404


async def test_provider_error_is_502_with_clear_message_and_tracked(api, session, llm):
    llm.error = ProviderError("gemini: HTTP 400 clé invalide")
    r = await assist(api, field_kind="angle")
    assert r.status_code == 502 and "Assistant IA indisponible" in r.json()["detail"] and "HTTP 400" in r.json()["detail"]
    call = await session.scalar(select(ProviderCall))
    assert call.status == "error" and call.step == "assist:angle"


async def test_empty_answer_after_cleanup_is_502_and_logged_at_its_real_cost(api, session, llm):
    llm.answer = '```\n""\n```'
    r = await assist(api, field_kind="angle")
    assert r.status_code == 502 and "vide" in r.json()["detail"]
    calls = (await session.scalars(select(ProviderCall))).all()
    assert len(calls) == 1 and calls[0].cost_usd == pytest.approx(0.002)  # réponse facturée par le provider


async def test_requires_auth(api):
    api.cookies.clear()
    assert (await assist(api, field_kind="angle")).status_code == 401


@pytest.mark.parametrize("kind,raw,expected", [
    ("angle", '```\n"Un angle"\n```', "Un angle"),
    ("angle", "Voici une proposition :\n« Un angle percutant »", "Un angle percutant"),
    ("title", "**3 erreurs du soir**\n", "3 erreurs du soir"),
    ("title", "Titre : 3 erreurs\nqui ruinent", "3 erreurs qui ruinent"),
    ("voice_text", "“Tu dors mal ?”", "Tu dors mal ?"),
    ("hashtags", "astuce, #viral  fyp #viral", "#astuce #viral #fyp"),
    ("visual_prompt", "Prompt: close-up of a cat", "close-up of a cat"),
    ("description", "Here is the text:\nTu dors mal ?", "Tu dors mal ?"),
])
def test_clean_output(kind, raw, expected):
    assert clean_output(raw, kind) == expected


@pytest.mark.parametrize("kind,raw", [
    ("voice_text", "«Dors» dit le médecin, puis «lève-toi»"),
    ("voice_text", '"Bonjour" et "merci" : les deux mots magiques'),
    ("angle", "Titre : un faux titre qui fait partie de l'angle"),
    ("description", "Prompt: écris ton rêve en commentaire"),
    ("voice_text", "C'est **vraiment** important, et **maintenant**."),
    ("angle", "Version courte : on démonte trois mythes.\nPuis on conclut."),
])
def test_clean_output_preserves_legit_text(kind, raw):
    assert clean_output(raw, kind) == raw


RECOMPOSE = "changer la composition"


async def test_rewrite_with_instruction_may_recompose_visual_prompt(api, session, llm):
    p, scene = await seed(session)
    await assist(api, field_kind="visual_prompt", mode="rewrite", text="woman awake in bed",
                 instruction="le sujet est trop grand", project_id=p.id, scene_id=scene.id)
    prompt = llm.calls[0]["prompt"]
    assert RECOMPOSE in prompt and "taille du sujet" in prompt and "sens de la voix off" in prompt
    assert "Tu dors mal ?" in prompt and "gardant son sens et ses informations" not in prompt


@pytest.mark.parametrize("kind,instruction", [("voice_text", "plus punchy"), ("visual_prompt", "")])
async def test_rewrite_of_other_fields_still_keeps_meaning(api, session, llm, kind, instruction):
    p, scene = await seed(session)
    await assist(api, field_kind=kind, mode="rewrite", text="Tu dors mal ?", instruction=instruction,
                 project_id=p.id, scene_id=scene.id)
    prompt = llm.calls[0]["prompt"]
    assert "gardant son sens et ses informations" in prompt and RECOMPOSE not in prompt


async def test_last_scene_voice_asks_for_the_engagement_call(api, session, llm):
    p, scene = await seed(session)
    await assist(api, field_kind="voice_text", project_id=p.id, scene_id=scene.id)
    assert "« commente »" in llm.calls[0]["prompt"]
    session.add(Scene(project_id=p.id, position=2, voice_text="Fin", visual_prompt="x", duration_s=4))
    await session.commit()
    await assist(api, field_kind="voice_text", project_id=p.id, scene_id=scene.id)
    assert "« commente »" not in llm.calls[1]["prompt"]  # plus la dernière scène
