import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.app_settings import AppSettings
from app.models import CreditEntry, StripeEvent
from app.services import credits
from tests.test_billing_api import config_with
from tests.test_stripe_client import SECRET, sign

NEXT_MONTH = int((datetime.now(UTC) + timedelta(days=30)).timestamp())


@pytest.fixture(autouse=True)
async def webhook_secret(session):
    app_settings = AppSettings(session)
    await app_settings.set("stripe_webhook_secret", SECRET)
    await app_settings.set("billing_config", json.dumps(config_with(tier={"credits": 400})))


async def send(api_as, event: dict, *, secret: str = SECRET, at: float | None = None, header: str | None = None):
    body = json.dumps(event).encode()
    c = await api_as(None)
    return await c.post("/api/stripe/webhook", content=body, headers={
        "Stripe-Signature": header if header is not None else sign(body, secret, at), "Content-Type": "application/json"})


def topup_event(event_id, user_id, credits_sold=200, status="paid"):
    return {"id": event_id, "type": "checkout.session.completed", "data": {"object": {
        "mode": "payment", "payment_status": status, "client_reference_id": str(user_id), "customer": "cus_1",
        "metadata": {"credits": str(credits_sold), "pack_id": "pack200"}}}}


def invoice_event(event_id, customer="cus_1", period_end=NEXT_MONTH, subscription="sub_1", plan=None):
    return {"id": event_id, "type": "invoice.paid", "data": {"object": {
        "customer": customer, "subscription": subscription, "billing_reason": "subscription_cycle",
        "subscription_details": {"metadata": {"plan": plan} if plan else {}},
        "lines": {"data": [{"period": {"end": period_end}}]}}}}


def deleted_event(event_id, customer="cus_1"):
    return {"id": event_id, "type": "customer.subscription.deleted", "data": {"object": {"customer": customer}}}


async def customer(session, make_user, email="c@x.fr", customer_id="cus_1"):
    user = await make_user(email)
    user.stripe_customer_id = customer_id
    await session.commit()
    return user.id


async def balance(session, uid):
    return await credits.balance(session, uid)


async def test_signature_is_required(api_as, make_user, session):
    uid = await customer(session, make_user)
    event = topup_event("evt_1", uid)
    assert (await send(api_as, event, header="")).status_code == 400
    assert (await send(api_as, event, secret="whsec_autre")).status_code == 400
    assert (await send(api_as, event, at=time.time() - 3600)).status_code == 400
    body = json.dumps(event).encode()
    c = await api_as(None)
    forged = await c.post("/api/stripe/webhook", content=body.replace(b"200", b"999"), headers={"Stripe-Signature": sign(body)})
    assert forged.status_code == 400
    assert (await balance(session, uid)).total == 0 and await session.scalar(select(func.count()).select_from(StripeEvent)) == 0


async def test_webhook_refuses_everything_while_the_secret_is_not_configured(api_as, make_user, session):
    await AppSettings(session).set("stripe_webhook_secret", "")
    uid = await customer(session, make_user)
    assert (await send(api_as, topup_event("evt_1", uid), secret="")).status_code == 400


async def test_topup_grants_topup_credits(api_as, make_user, session):
    uid = await customer(session, make_user)
    assert (await send(api_as, topup_event("evt_1", uid, 500))).status_code == 200
    assert await balance(session, uid) == credits.Balance(0, 500)
    entry = (await session.scalars(select(CreditEntry).where(CreditEntry.user_id == uid))).one()
    assert (entry.kind, entry.bucket, entry.amount) == ("topup", "topup", 500) and "500" in entry.reason


async def test_same_event_twice_credits_once(api_as, make_user, session):
    uid = await customer(session, make_user)
    first = await send(api_as, topup_event("evt_1", uid))
    second = await send(api_as, topup_event("evt_1", uid))
    assert first.status_code == second.status_code == 200 and second.json()["duplicate"] is True
    assert (await balance(session, uid)).total == 200
    assert await session.scalar(select(func.count()).select_from(StripeEvent)) == 1


async def test_unpaid_checkout_grants_nothing(api_as, make_user, session):
    uid = await customer(session, make_user)
    assert (await send(api_as, topup_event("evt_1", uid, status="unpaid"))).status_code == 200
    assert (await balance(session, uid)).total == 0


async def test_invoice_paid_starts_the_subscription_and_grants_the_monthly_quota(api_as, make_user, session):
    uid = await customer(session, make_user)
    assert (await send(api_as, invoice_event("evt_1"))).status_code == 200
    assert await balance(session, uid) == credits.Balance(400, 0)
    user = await make_user("autre@x.fr")  # un autre compte n'est pas touché
    await session.refresh(user)
    from app.models import User
    ends = (await session.get(User, uid, populate_existing=True)).subscription_ends_at
    assert ends is not None and ends > datetime.now(UTC) + timedelta(days=29) and (await session.get(User, uid)).is_subscribed
    assert (await balance(session, user.id)).total == 0


async def test_invoice_paid_takes_the_tier_from_the_subscription_metadata(api_as, make_user, session):
    from app.models import User
    uid = await customer(session, make_user)
    await send(api_as, invoice_event("evt_1", plan="creator"))
    assert (await session.get(User, uid, populate_existing=True)).plan_id == "creator"
    assert await balance(session, uid) == credits.Balance(3000, 0)


async def test_renewal_resets_the_subscription_lot_and_the_leftover_expires(api_as, make_user, session):
    uid = await customer(session, make_user)
    await send(api_as, invoice_event("evt_1"))
    await credits.grant(session, uid, 50, bucket="topup", kind="topup", reason="x")
    r = await credits.reserve(session, uid, 150, project_id=None, step="clips", reason="t")  # 150 d'abonnement
    await credits.close(session, r, 150)
    await session.commit()
    assert await balance(session, uid) == credits.Balance(250, 50)
    await send(api_as, invoice_event("evt_2", period_end=NEXT_MONTH + 86400 * 30))
    assert await balance(session, uid) == credits.Balance(400, 50)  # 250 restants expirés, quota remis à 400
    kinds = [e.kind for e in await session.scalars(select(CreditEntry).where(CreditEntry.user_id == uid).order_by(CreditEntry.id))]
    assert kinds.count("subscription_grant") == 2 and "expire" in kinds
    sums = {b: await session.scalar(select(func.sum(CreditEntry.amount)).where(CreditEntry.user_id == uid, CreditEntry.bucket == b))
            for b in ("subscription", "topup")}
    assert (sums["subscription"], sums["topup"]) == (400, 50)


async def test_reservation_open_at_renewal_refunds_into_the_topup_lot(api_as, make_user, session):
    uid = await customer(session, make_user)
    await send(api_as, invoice_event("evt_1"))
    r = await credits.reserve(session, uid, 100, project_id=None, step="clips", reason="t")  # 100 d'abonnement retenus
    await session.commit()
    await send(api_as, invoice_event("evt_2", period_end=NEXT_MONTH + 86400 * 30))
    assert await balance(session, uid) == credits.Balance(400, 0)
    await session.refresh(r)
    assert await credits.close(session, r, 0) == 100  # rendu : sur le lot rechargé, jamais en négatif
    await session.commit()
    assert await balance(session, uid) == credits.Balance(400, 100)


async def test_subscription_deleted_ends_access_and_expires_the_subscription_lot(api_as, make_user, session):
    from app.models import User
    uid = await customer(session, make_user)
    await credits.grant(session, uid, 30, bucket="topup", kind="topup", reason="x")
    await session.commit()
    await send(api_as, invoice_event("evt_1"))
    await send(api_as, deleted_event("evt_2"))
    user = await session.get(User, uid, populate_existing=True)
    assert not user.is_subscribed and await balance(session, uid) == credits.Balance(0, 30)  # les recharges restent acquises


async def test_cancellation_keeps_access_until_the_period_ends(api_as, make_user, session):
    from app.models import User
    uid = await customer(session, make_user)
    await send(api_as, invoice_event("evt_1"))
    # l'annulation en cours de période n'envoie pas `deleted` : l'accès court jusqu'à la date enregistrée
    assert (await session.get(User, uid, populate_existing=True)).is_subscribed


async def test_older_invoice_never_shortens_the_period(api_as, make_user, session):
    from app.models import User
    uid = await customer(session, make_user)
    await send(api_as, invoice_event("evt_2", period_end=NEXT_MONTH + 86400 * 30))
    await send(api_as, invoice_event("evt_1", period_end=NEXT_MONTH))
    ends = (await session.get(User, uid, populate_existing=True)).subscription_ends_at
    assert int(ends.timestamp()) == NEXT_MONTH + 86400 * 30


async def test_unknown_customer_and_unknown_events_are_acknowledged_without_effect(api_as, make_user, session):
    uid = await customer(session, make_user)
    assert (await send(api_as, invoice_event("evt_1", customer="cus_inconnu"))).status_code == 200
    assert (await send(api_as, {"id": "evt_2", "type": "charge.refunded", "data": {"object": {}}})).status_code == 200
    assert (await send(api_as, topup_event("evt_3", 999999))).status_code == 200
    assert (await balance(session, uid)).total == 0


async def test_failure_after_the_event_is_recorded_lets_stripe_retry(api_as, make_user, session, monkeypatch):
    from app.services import payments
    uid = await customer(session, make_user)

    async def boom(*args, **kwargs):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(payments, "grant_topup", boom)
    c = await api_as(None)
    body = json.dumps(topup_event("evt_1", uid)).encode()
    with pytest.raises(RuntimeError):
        await c.post("/api/stripe/webhook", content=body, headers={"Stripe-Signature": sign(body)})
    monkeypatch.undo()
    assert await session.scalar(select(func.count()).select_from(StripeEvent)) == 0  # pas marqué : Stripe rejoue
    assert (await send(api_as, topup_event("evt_1", uid))).status_code == 200
    assert (await balance(session, uid)).total == 200

