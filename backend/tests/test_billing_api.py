import json
from datetime import UTC, datetime, timedelta

import pytest

from app.app_settings import AppSettings
from app.config import settings
from app.main import app
from app.models import Setting
from app.services.billing import DEFAULT_BILLING
from app.services.pricing import load_pricing, video_credits
from app.services.stripe_client import FakeStripe, StripeError, get_stripe


def config_with(*, tier: dict | None = None, tiers: dict[str, dict] | None = None, packs: list | None = None) -> dict:
    """Offre par défaut, premier forfait (`tier`) ou forfaits par identifiant (`tiers`) et packs modifiés."""
    config = json.loads(DEFAULT_BILLING)
    config["tiers"][0].update(tier or {})
    for t in config["tiers"]:
        t.update((tiers or {}).get(t["id"], {}))
    if packs is not None:
        config["packs"] = packs
    return config


CONFIG = config_with(tier={"price_id": "price_sub"},
                     packs=[{"id": "pack200", "price_id": "price_200", "credits": 200, "label": "10 $"},
                            {"id": "pack500", "price_id": "", "credits": 500, "label": "24 $"}])


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
    starter = body["tiers"][0]
    assert {k: starter[k] for k in ("id", "name", "label", "credits", "purchasable", "paypal_purchasable")} == {
        "id": "starter", "name": "Starter", "label": "9 $ par mois", "credits": 1200, "purchasable": True,
        "paypal_purchasable": False}  # pas encore de plan PayPal
    assert starter["perks"]["queue_max"] == 2 and "videos_30s" in starter
    assert [t["id"] for t in body["tiers"]] == ["starter", "creator", "pro"] and body["free"]["perks"]["queue_max"] == 1
    assert body["current_tier"] is None
    assert body["packs"] == [{"id": "pack200", "credits": 200, "label": "10 $", "purchasable": True,
                              "paypal_purchasable": False},
                             {"id": "pack500", "credits": 500, "label": "24 $", "purchasable": False,
                              "paypal_purchasable": False}]
    assert body["subscribed"] is False and body["manageable"] is False


async def test_old_billing_setting_does_not_break_the_offer(api_as, make_user, session):
    old = {"subscription": {"price_id": "price_sub", "credits": 400, "label": "19 $ par mois"}, "packs": []}
    session.add(Setting(key="billing_config", value=json.dumps(old)))  # écrit avant les forfaits : jamais revalidé
    await session.commit()
    r = await (await api_as(await make_user("a@x.fr"))).get("/api/billing")
    assert r.status_code == 200 and r.json()["tiers"][0]["credits"] == 1200


async def test_billing_requires_login(api_as):
    assert (await (await api_as(None)).get("/api/billing")).status_code == 401
    assert (await (await api_as(None)).post("/api/billing/checkout", json={"kind": "subscription", "tier_id": "starter"})).status_code == 401


async def test_subscription_checkout_creates_the_customer_once(api_as, make_user, stripe, session):
    user = await make_user("a@x.fr")
    c = await api_as(user)
    r = await c.post("/api/billing/checkout", json={"kind": "subscription", "tier_id": "starter"})
    assert r.status_code == 200 and r.json()["url"] == "https://checkout.stripe.test/subscription/price_sub"
    await c.post("/api/billing/checkout", json={"kind": "subscription", "tier_id": "starter"})
    assert [call[0] for call in stripe.calls] == ["customer", "checkout", "checkout"]  # un seul client Stripe
    await session.refresh(user)
    assert user.stripe_customer_id == f"cus_fake_{user.id}"


async def test_subscription_checkout_needs_a_known_tier(api_as, make_user, stripe):
    c = await api_as(await make_user("a@x.fr"))
    assert (await c.post("/api/billing/checkout", json={"kind": "subscription"})).status_code == 422
    assert (await c.post("/api/billing/checkout", json={"kind": "subscription", "tier_id": "gold"})).status_code == 404
    assert (await c.post("/api/billing/checkout", json={"kind": "subscription", "tier_id": "pro"})).status_code == 409


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
    await AppSettings(session).set("billing_config", json.dumps(config_with(tier={"price_id": ""})))
    r = await (await api_as(await make_user("a@x.fr"))).post("/api/billing/checkout", json={"kind": "subscription", "tier_id": "starter"})
    assert r.status_code == 409 and "pas encore" in r.json()["detail"]


async def test_unverified_account_cannot_buy(api_as, make_user, stripe):
    r = await (await api_as(await make_user("a@x.fr", verified=False))).post("/api/billing/checkout", json={"kind": "topup", "pack_id": "pack200"})
    assert r.status_code == 403 and "adresse e-mail" in r.json()["detail"]


async def test_active_subscriber_is_sent_to_the_portal_not_a_second_checkout(api_as, make_user, stripe, session):
    user = await make_user("a@x.fr")
    user.subscription_ends_at = datetime.now(UTC) + timedelta(days=10)
    await session.commit()
    c = await api_as(user)
    r = await c.post("/api/billing/checkout", json={"kind": "subscription", "tier_id": "starter"})
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
    r = await (await api_as(await make_user("a@x.fr"))).post("/api/billing/checkout", json={"kind": "subscription", "tier_id": "starter"})
    assert r.status_code == 502 and "No such price" in r.json()["detail"]


async def test_urls_come_from_public_url(api_as, make_user, stripe, monkeypatch):
    sent = {}

    async def capture(**kwargs):
        sent.update(kwargs)
        return "https://x"

    monkeypatch.setattr(stripe, "create_checkout", capture)
    await (await api_as(await make_user("a@x.fr"))).post("/api/billing/checkout", json={"kind": "subscription", "tier_id": "starter"})
    assert sent["success_url"] == f"{settings.public_url}/plans?checkout=success"
    assert sent["cancel_url"] == f"{settings.public_url}/plans?checkout=cancelled"


async def test_billing_reports_videos_per_tier(api_as, make_user, session):
    pricing = await load_pricing(AppSettings(session))
    tiers = (await (await api_as(await make_user("a@x.fr"))).get("/api/billing")).json()["tiers"]
    assert [t["videos_30s"] for t in tiers] == [t["credits"] // video_credits(pricing) for t in tiers]
    assert tiers[0]["videos_30s"] >= 6  # Starter : 1 200 crédits
