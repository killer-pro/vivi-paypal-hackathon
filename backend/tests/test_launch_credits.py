import json
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import CreditEntry, CreditReservation, Project, Scene, Step
from app.services import credits, steps
from app.services.flow import StepBusy
from app.services.pricing import DEFAULT_PRICING, Pricing
from tests.test_api_steps import new_project, set_status

PRICING = Pricing.from_json(json.loads(DEFAULT_PRICING), usd_per_credit=Decimal("0.05"),
                            margin=Decimal("2.5"))
CLIP_3S = PRICING.clip_credits(PRICING.local_clip_cost_usd("fast", 3))  # 3 crédits : 0,048 $ × 2,5 ÷ 0,05 = 2,4


async def client_project(api_as, make_user, fund, amount=1000, email="c@x.fr"):
    user = await make_user(email)
    if amount:
        await fund(user, amount)
    c = await api_as(user)
    return user, c, await new_project(c)


async def add_scenes(session, pid, count=3, duration=3.0):
    scenes = [Scene(project_id=pid, position=i, voice_text="texte", visual_prompt="plan", duration_s=duration)
              for i in range(count)]
    session.add_all(scenes)
    await session.commit()
    return [s.id for s in scenes]


async def entries(session, kind=None):
    query = select(CreditEntry).order_by(CreditEntry.id)
    if kind:
        query = query.where(CreditEntry.kind == kind)
    return list((await session.scalars(query)).all())


async def movements(session):
    """Mouvements de réservation et de remboursement (hors crédits accordés par `fund`)."""
    return [e for e in await entries(session) if e.kind in ("reserve", "refund")]


async def total(session, user) -> int:
    return (await credits.balance(session, user.id)).total


async def test_client_launch_reserves_quote_and_price_endpoint_matches(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    price = (await c.post(f"/api/projects/{pid}/steps/idea/price", json={})).json()
    assert price == {"credits": 1, "balance": 1000, "sufficient": True, "unlimited": False}
    assert (await c.post(f"/api/projects/{pid}/steps/idea/run", json={})).status_code == 202
    reserved = await entries(session, "reserve")
    assert [-e.amount for e in reserved] == [price["credits"]] and reserved[0].step == "idea"
    assert await total(session, user) == 1000 - price["credits"]


async def test_clips_price_endpoint_matches_reservation(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    await add_scenes(session, pid, 3)
    await set_status(session, ["idea", "story", "script", "reference"], "approved")
    price = (await c.post(f"/api/projects/{pid}/steps/clips/price", json={})).json()
    assert price["credits"] == 3 * CLIP_3S
    assert (await c.post(f"/api/projects/{pid}/steps/clips/run", json={})).status_code == 202
    reservation = (await session.scalars(select(CreditReservation))).one()
    assert reservation.amount == price["credits"] and len(reservation.scene_prices) == 3
    assert list(reservation.scene_prices.values()) == [CLIP_3S] * 3


async def test_insufficient_credits_409_before_any_job(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund, amount=0)
    r = await c.post(f"/api/projects/{pid}/steps/idea/run", json={})
    assert r.status_code == 409 and "Crédits insuffisants" in r.json()["detail"]
    assert "1 crédits" in r.json()["detail"] and "0" in r.json()["detail"]
    assert c.enqueued == [] and await movements(session) == []
    assert (await session.scalar(select(Step.status).where(Step.project_id == pid, Step.name == "idea"))) == "pending"
    price = (await c.post(f"/api/projects/{pid}/steps/idea/price", json={})).json()
    assert price["sufficient"] is False


async def test_second_launch_refused_when_balance_pays_only_one(api_as, make_user, fund, session):
    user, c, first = await client_project(api_as, make_user, fund, amount=1)
    second = await new_project(c)
    assert (await c.post(f"/api/projects/{first}/steps/idea/run", json={})).status_code == 202
    r = await c.post(f"/api/projects/{second}/steps/idea/run", json={})
    assert r.status_code == 409 and "Crédits insuffisants" in r.json()["detail"]
    assert await total(session, user) == 0 and len(c.enqueued) == 1


async def test_stepbusy_after_reserve_refunds(api_as, make_user, fund, session, monkeypatch):
    user, c, pid = await client_project(api_as, make_user, fund)

    async def lost_race(*args, **kwargs):
        await session.commit()
        return False

    monkeypatch.setattr(steps, "claim_step", lost_race)
    with pytest.raises(StepBusy):
        await steps.launch_step(session, pid, "idea", c.enqueued.append)
    assert await total(session, user) == 1000
    reservation = (await session.scalars(select(CreditReservation))).one()
    assert reservation.status == "closed" and reservation.used == 0


async def test_enqueue_failure_refunds(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)

    async def broken(*args, **kwargs):
        raise RuntimeError("redis down")

    with pytest.raises(Exception, match="File d'attente indisponible"):
        await steps.launch_step(session, pid, "idea", broken)
    assert await total(session, user) == 1000
    assert (await session.scalars(select(CreditReservation))).one().status == "closed"


async def test_music_and_montage_are_free(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    await set_status(session, ["idea", "story", "script", "reference", "clips", "voice"], "approved")
    price = (await c.post(f"/api/projects/{pid}/steps/music/price", json={})).json()
    assert price["credits"] == 0 and price["sufficient"] is True
    assert (await c.post(f"/api/projects/{pid}/steps/music/run", json={})).status_code == 202
    assert await movements(session) == [] and await total(session, user) == 1000


async def test_admin_owner_not_charged_and_keeps_dollar_budget(api, session, admin):
    pid = await new_project(api)
    assert (await api.post(f"/api/projects/{pid}/steps/idea/run", json={})).status_code == 202
    assert await entries(session) == [] and (await session.scalars(select(CreditReservation))).first() is None
    await add_scenes(session, pid, 2)
    await set_status(session, ["idea", "story", "script", "reference"], "approved")
    await api.put("/api/settings", json={"project_budget_usd": "0.0001"})
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={})
    assert r.status_code == 409 and "Budget" in r.json()["detail"]


async def test_client_ignores_dollar_budget(api_as, make_user, fund, session, api):
    user, c, pid = await client_project(api_as, make_user, fund)
    await add_scenes(session, pid, 2)
    await set_status(session, ["idea", "story", "script", "reference"], "approved")
    await api.put("/api/settings", json={"project_budget_usd": "0.0001"})
    assert (await c.post(f"/api/projects/{pid}/steps/clips/run", json={})).status_code == 202


async def test_second_clips_run_refused_by_parallel_limit(api_as, make_user, fund, session):
    user, c, first = await client_project(api_as, make_user, fund)
    uid = user.id  # le refus annule la transaction, ce qui expire les objets de la session
    second = await new_project(c)
    for pid in (first, second):
        await add_scenes(session, pid, 1)
        await set_status(session, ["idea", "story", "script", "reference"], "approved")
    assert (await c.post(f"/api/projects/{first}/steps/clips/run", json={})).status_code == 202
    before = (await credits.balance(session, uid)).total
    r = await c.post(f"/api/projects/{second}/steps/clips/run", json={})
    assert r.status_code == 409 and "déjà en cours" in r.json()["detail"]
    assert (await credits.balance(session, uid)).total == before and len(c.enqueued) == 1


async def test_autopilot_stops_with_reason_on_insufficient_credits(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund, amount=0)
    await set_status(session, ["idea"], "awaiting_validation")
    project = await session.get(Project, pid)
    project.autopilot = True
    await session.commit()
    events = []

    async def publish(e):
        events.append(e)

    await steps.advance(session, pid, "idea", c.enqueued.append, publish)
    story = await session.scalar(select(Step).where(Step.project_id == pid, Step.name == "story"))
    await session.refresh(project)
    assert story.status == "failed" and "Crédits insuffisants" in story.error and project.autopilot is False
    assert events[-1]["status"] == "failed" and "Crédits insuffisants" in events[-1]["error"]


async def test_clips_reservation_is_sum_of_missing_scenes_only(api_as, make_user, fund, session):
    from app.models import Asset
    user, c, pid = await client_project(api_as, make_user, fund)
    ids = await add_scenes(session, pid, 3)
    await set_status(session, ["idea", "story", "script", "reference"], "approved")
    session.add(Asset(project_id=pid, scene_id=ids[0], kind="clip", key="k", content_type="video/mp4"))
    await session.commit()
    price = (await c.post(f"/api/projects/{pid}/steps/clips/price", json={"only_missing": True})).json()
    assert price["credits"] == 2 * CLIP_3S
    assert (await c.post(f"/api/projects/{pid}/steps/clips/run", json={"only_missing": True})).status_code == 202
    reservation = (await session.scalars(select(CreditReservation))).one()
    assert reservation.amount == 2 * CLIP_3S and set(reservation.scene_prices) == {str(ids[1]), str(ids[2])}


async def test_single_scene_price_is_one_scene(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    ids = await add_scenes(session, pid, 3)
    await set_status(session, ["idea", "story", "script", "reference"], "approved")
    price = (await c.post(f"/api/projects/{pid}/steps/clips/price", json={"scene_id": ids[1]})).json()
    assert price["credits"] == CLIP_3S


async def test_price_endpoint_for_unlimited_admin(api):
    pid = await new_project(api)
    price = (await api.post(f"/api/projects/{pid}/steps/idea/price", json={})).json()
    assert price == {"credits": 0, "balance": None, "sufficient": True, "unlimited": True}


async def test_price_endpoint_has_no_side_effect(api_as, make_user, fund, session):
    user, c, pid = await client_project(api_as, make_user, fund)
    await c.post(f"/api/projects/{pid}/steps/idea/price", json={})
    assert await movements(session) == [] and c.enqueued == []
    assert (await session.scalar(select(Step.status).where(Step.project_id == pid, Step.name == "idea"))) == "pending"
