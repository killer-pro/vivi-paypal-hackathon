import json

import pytest
from sqlalchemy import select

from app.api.projects import get_registry
from app.main import app
from app.models import CreditEntry
from app.providers.base import ProviderError
from app.services import credits
from tests.test_assist import RecordingLLM
from tests.test_launch_credits import client_project, movements, total

ASSIST_PRICE = 1  # 0,005 $ × 2,5 ÷ 0,05 = 0,25 → 1 crédit


def _use_llm(llm):
    class Registry:
        async def llm(self):
            return llm

    app.dependency_overrides[get_registry] = lambda: Registry()
    return llm


@pytest.fixture
def assist_llm():
    yield _use_llm(RecordingLLM())
    app.dependency_overrides.pop(get_registry, None)


@pytest.fixture
def chat_llm():
    yield _use_llm(RecordingLLM(answer=json.dumps({"reply": "Voilà."})))
    app.dependency_overrides.pop(get_registry, None)


async def assist(c, **body):
    return await c.post("/api/ai/assist", json={"field_kind": "title", **body})


async def test_assist_charges_client_and_not_admin(api, api_as, make_user, fund, session, assist_llm):
    user, c, pid = await client_project(api_as, make_user, fund, amount=10)
    assert (await assist(c, project_id=pid)).status_code == 200
    assert await total(session, user) == 10 - ASSIST_PRICE
    assert [(e.kind, e.step) for e in await movements(session)] == [("reserve", "assist")]
    before = len(await movements(session))
    assert (await assist(api)).status_code == 200
    assert len(await movements(session)) == before


async def test_assist_refused_without_credits_before_llm_call(api_as, make_user, fund, assist_llm):
    user, c, pid = await client_project(api_as, make_user, fund, amount=0)
    r = await assist(c, project_id=pid)
    assert r.status_code == 409 and "Crédits insuffisants" in r.json()["detail"] and assist_llm.calls == []


async def test_assist_failure_refunds(api_as, make_user, fund, session, assist_llm):
    user, c, pid = await client_project(api_as, make_user, fund, amount=10)
    assist_llm.error = ProviderError("claude: 529")
    uid = user.id
    r = await assist(c, project_id=pid)
    assert r.status_code == 502
    assert (await credits.balance(session, uid)).total == 10
    kinds = [e.kind for e in await session.scalars(select(CreditEntry).where(CreditEntry.kind.in_(["reserve", "refund"])))]
    assert kinds == ["reserve", "refund"]


async def test_assist_without_project_is_still_charged(api_as, make_user, fund, session, assist_llm):
    user = await make_user("n@x.fr")
    await fund(user, 5)
    c = await api_as(user)
    assert (await assist(c)).status_code == 200
    assert await total(session, user) == 5 - ASSIST_PRICE
    assert (await movements(session))[0].project_id is None


async def test_plan_chat_charges_project_owner(api, api_as, make_user, fund, session, chat_llm):
    user, c, pid = await client_project(api_as, make_user, fund, amount=10)
    r = await c.post(f"/api/projects/{pid}/plan/chat", json={"message": "Bonjour"})
    assert r.status_code == 200
    assert await total(session, user) == 10 - ASSIST_PRICE
    assert [(e.kind, e.step) for e in await movements(session)] == [("reserve", "plan_chat")]
    # l'administrateur qui discute sur le projet d'un client le facture à ce client
    assert (await api.post(f"/api/projects/{pid}/plan/chat", json={"message": "Encore"})).status_code == 200
    assert await total(session, user) == 10 - 2 * ASSIST_PRICE


async def test_plan_chat_refused_without_credits_and_ignores_dollar_budget(api, api_as, make_user, fund, chat_llm):
    user, c, pid = await client_project(api_as, make_user, fund, amount=0)
    r = await c.post(f"/api/projects/{pid}/plan/chat", json={"message": "Bonjour"})
    assert r.status_code == 409 and "Crédits insuffisants" in r.json()["detail"] and chat_llm.calls == []
    await fund(user, 5)
    await api.put("/api/settings", json={"project_budget_usd": "0.0001"})
    for _ in range(2):  # le premier échange dépasse déjà 0,0001 $ : le budget en dollars ne vaut que pour l'admin
        assert (await c.post(f"/api/projects/{pid}/plan/chat", json={"message": "Bonjour"})).status_code == 200
