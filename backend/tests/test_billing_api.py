import json
from datetime import UTC, datetime, timedelta

import pytest

from app.app_settings import AppSettings
from app.config import settings
from app.main import app
from app.services.stripe_client import FakeStripe, StripeError, get_stripe

CONFIG = {"subscription": {"price_id": "price_sub", "credits": 400, "label": "19 $ par mois"},
          "packs": [{"id": "pack200", "price_id": "price_200", "credits": 200, "label": "10 $"},
                    {"id": "pack500", "price_id": "", "credits": 500, "label": "24 $"}]}


@pytest.fixture
async def stripe(session):
    fake = FakeStripe()
    app.dependency_overrides[get_stripe] = lambda: fake
    await AppSettings(session).set("billing_config", json.dumps(CONFIG))
    yield fake
    app.dependency_overrides.pop(get_stripe, None)


async def test_billing_lists_the_offer_and_the_subscription_state(api_as, make_user, stripe):
    c = await api_as(await make_user("a@x.fr"))
    body = (await c.get("/api/billing")).json()
    assert body["subscription"] == {"credits": 400, "label": "19 $ par mois", "purchasable": True,
                                    "paypal_purchasable": False}
    assert body["packs"] == [{"id": "pack200", "credits": 200, "label": "10 $", "purchasable": True,
                              "paypal_purchasable": False},
                             {"id": "pack500", "credits": 500, "label": "24 $", "purchasable": False,
                              "paypal_purchasable": False}]
    assert body["subscribed"] is False and body["manageable"] is False


async def test_billing_requires_login(api_as):
    assert (await (await api_as(None)).get("/api/billing")).status_code == 401
    assert (await (await api_as(None)).post("/api/billing/checkout", json={"kind": "subscription"})).status_code == 401


async def test_subscription_checkout_creates_the_customer_once(api_as, make_user, stripe, session):
    user = await make_user("a@x.fr")
    c = await api_as(user)
    r = await c.post("/api/billing/checkout", json={"kind": "subscription"})
    assert r.status_code == 200 and r.json()["url"] == "https://checkout.stripe.test/subscription/price_sub"
    await c.post("/api/billing/checkout", json={"kind": "subscription"})
    assert [call[0] for call in stripe.calls] == ["customer", "checkout", "checkout"]  # un seul client Stripe
    await session.refresh(user)
    assert user.stripe_customer_id == f"cus_fake_{user.id}"


async def test_topup_checkout_carries_the_credits_sold(api_as, make_user, stripe):
    c = await api_as(await make_user("a@x.fr"))
    r = await c.post("/api/billing/checkout", json={"kind": "topup", "pack_id": "pack200"})
    assert r.status_code == 200
    kind, _, mode, price, metadata = stripe.calls[-1]
    assert (kind, mode, price) == ("checkout", "payment", "price_200") and metadata["credits"] == "200"


@pytest.mark.parametrize("body,status", [
    ({"kind": "topup", "pack_id": "inconnu"}, 404), ({"kind": "topup"}, 422), ({"kind": "autre"}, 422),
    ({"kind": "topup", "pack_id": "pack500"}, 409),  # pack sans prix Stripe
])
async def test_checkout_refuses_unknown_or_unconfigured_offers(api_as, make_user, stripe, body, status):
    assert (await (await api_as(await make_user("a@x.fr"))).post("/api/billing/checkout", json=body)).status_code == status
    assert stripe.calls == []


async def test_unconfigured_subscription_is_refused_with_a_clear_message(api_as, make_user, stripe, session):
    await AppSettings(session).set("billing_config", json.dumps({"subscription": {"price_id": "", "credits": 400}}))
    r = await (await api_as(await make_user("a@x.fr"))).post("/api/billing/checkout", json={"kind": "subscription"})
    assert r.status_code == 409 and "pas encore" in r.json()["detail"]


async def test_unverified_account_cannot_buy(api_as, make_user, stripe):
    r = await (await api_as(await make_user("a@x.fr", verified=False))).post("/api/billing/checkout", json={"kind": "topup", "pack_id": "pack200"})
    assert r.status_code == 403 and "adresse e-mail" in r.json()["detail"]


async def test_active_subscriber_is_sent_to_the_portal_not_a_second_checkout(api_as, make_user, stripe, session):
    user = await make_user("a@x.fr")
    user.subscription_ends_at = datetime.now(UTC) + timedelta(days=10)
    await session.commit()
    c = await api_as(user)
    r = await c.post("/api/billing/checkout", json={"kind": "subscription"})
    assert r.status_code == 409 and "déjà abonné" in r.json()["detail"]
    assert (await c.post("/api/billing/checkout", json={"kind": "topup", "pack_id": "pack200"})).status_code == 200  # recharge libre


async def test_portal_opens_the_accounts_own_customer_only(api_as, make_user, stripe, session):
    a, b = await make_user("a@x.fr"), await make_user("b@x.fr")
    a.stripe_customer_id, b.stripe_customer_id = "cus_a", "cus_b"
    await session.commit()
    r = await (await api_as(a)).post("/api/billing/portal")
    assert r.status_code == 200 and r.json()["url"] == "https://billing.stripe.test/cus_a"
    assert stripe.calls == [("portal", "cus_a")]


async def test_portal_without_any_purchase_is_refused(api_as, make_user, stripe):
    r = await (await api_as(await make_user("a@x.fr"))).post("/api/billing/portal")
    assert r.status_code == 409 and "Aucun" in r.json()["detail"]


async def test_stripe_failure_becomes_a_502_with_its_message(api_as, make_user, stripe, monkeypatch):
    async def refuse(*args, **kwargs):
        raise StripeError("No such price: 'price_sub'")

    monkeypatch.setattr(stripe, "create_checkout", refuse)
    r = await (await api_as(await make_user("a@x.fr"))).post("/api/billing/checkout", json={"kind": "subscription"})
    assert r.status_code == 502 and "No such price" in r.json()["detail"]


async def test_urls_come_from_public_url(api_as, make_user, stripe, monkeypatch):
    sent = {}

    async def capture(**kwargs):
        sent.update(kwargs)
        return "https://x"

    monkeypatch.setattr(stripe, "create_checkout", capture)
    await (await api_as(await make_user("a@x.fr"))).post("/api/billing/checkout", json={"kind": "subscription"})
    assert sent["success_url"] == f"{settings.public_url}/credits?checkout=success"
    assert sent["cancel_url"] == f"{settings.public_url}/credits?checkout=cancelled"
