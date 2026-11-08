import json

import httpx
import pytest
from sqlalchemy import select

from app.app_settings import AppSettings
from app.config import settings
from app.main import app
from app.models import CreditBalance
from app.services.paypal_client import FakePayPal, PayPalClient, PayPalError, get_paypal
from tests.test_billing_api import config_with

CONFIG = config_with(tier={"paypal_plan_id": "P-VIVI", "credits": 400}, tiers={"creator": {"paypal_plan_id": "P-CREATOR"}},
                     packs=[{"id": "pack200", "price_id": "", "credits": 200, "label": "10 $", "paypal_amount": "10.00"},
                            {"id": "pack500", "price_id": "", "credits": 500, "label": "24 $"}])


@pytest.fixture
async def paypal(session):
    fake = FakePayPal()
    app.dependency_overrides[get_paypal] = lambda: fake
    await AppSettings(session).set("billing_config", json.dumps(CONFIG))
    yield fake
    app.dependency_overrides.pop(get_paypal, None)


async def topup_balance(session, user) -> int:
    row = await session.scalar(select(CreditBalance).where(CreditBalance.user_id == user.id))
    return row.topup if row else 0


async def test_order_then_capture_credits_the_topup_once(api_as, make_user, paypal, session):
    user = await make_user("a@x.fr")
    c = await api_as(user)
    r = await c.post("/api/billing/paypal/order", json={"pack_id": "pack200"})
    assert r.status_code == 200 and r.json()["url"] == "https://www.paypal.test/checkoutnow?token=ORDER-1"
    assert paypal.calls[0] == ("order", "10.00", f"{user.id}:pack200")
    first = await c.post("/api/billing/paypal/capture", json={"order_id": "ORDER-1"})
    again = await c.post("/api/billing/paypal/capture", json={"order_id": "ORDER-1"})
    assert first.json() == {"credited": 200} and again.json() == {"credited": 0}
    assert await topup_balance(session, user) == 200


@pytest.mark.parametrize("body,status", [({"pack_id": "inconnu"}, 404), ({"pack_id": "pack500"}, 409)])
async def test_order_refuses_unknown_or_non_paypal_packs(api_as, make_user, paypal, body, status):
    c = await api_as(await make_user("a@x.fr"))
    assert (await c.post("/api/billing/paypal/order", json=body)).status_code == status


async def test_capture_of_someone_elses_order_is_refused(api_as, make_user, paypal, session):
    owner, thief = await make_user("a@x.fr"), await make_user("b@x.fr")
    await (await api_as(owner)).post("/api/billing/paypal/order", json={"pack_id": "pack200"})
    r = await (await api_as(thief)).post("/api/billing/paypal/capture", json={"order_id": "ORDER-1"})
    assert r.status_code == 403 and await topup_balance(session, owner) == 0


async def test_webhook_credits_once_and_dedupes_with_the_capture(api_as, make_user, paypal, session):
    user = await make_user("a@x.fr")
    c = await api_as(user)
    await c.post("/api/billing/paypal/order", json={"pack_id": "pack200"})
    event = {"event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": (await paypal.capture_order("ORDER-1"))[
        "purchase_units"][0]["payments"]["captures"][0]}
    anon = await api_as(None)
    assert (await anon.post("/api/paypal/webhook", json=event)).json() == {"received": True, "credited": 200}
    assert (await anon.post("/api/paypal/webhook", json=event)).json()["credited"] == 0
    assert (await c.post("/api/billing/paypal/capture", json={"order_id": "ORDER-1"})).json() == {"credited": 0}
    assert await topup_balance(session, user) == 200


async def test_webhook_with_a_bad_signature_is_rejected(api_as, paypal):
    paypal.webhook_valid = False
    r = await (await api_as(None)).post("/api/paypal/webhook", json={"event_type": "PAYMENT.CAPTURE.COMPLETED"})
    assert r.status_code == 400


async def test_a_capture_for_the_wrong_amount_credits_nothing(api_as, make_user, paypal, session):
    user = await make_user("a@x.fr")
    capture = {"id": "CAP-X", "status": "COMPLETED", "custom_id": f"{user.id}:pack200",
               "amount": {"currency_code": "USD", "value": "1.00"}}
    r = await (await api_as(None)).post("/api/paypal/webhook", json={"event_type": "PAYMENT.CAPTURE.COMPLETED",
                                                                    "resource": capture})
    assert r.json()["credited"] == 0 and await topup_balance(session, user) == 0


async def test_paypal_is_offered_only_once_the_credentials_are_set(api_as, make_user, paypal, session, monkeypatch):
    monkeypatch.setattr(settings, "fake_providers", False)
    c = await api_as(await make_user("a@x.fr"))
    packs = lambda body: {p["id"]: p["paypal_purchasable"] for p in body["packs"]}  # noqa: E731
    assert packs((await c.get("/api/billing")).json()) == {"pack200": False, "pack500": False}
    app_settings = AppSettings(session)
    await app_settings.set("paypal_client_id", "id")
    await app_settings.set("paypal_client_secret", "secret")
    assert packs((await c.get("/api/billing")).json()) == {"pack200": True, "pack500": False}  # pack500 : pas de montant


@pytest.mark.parametrize("order_id", ["../../v1/identity/oauth2/userinfo", "ORDER 1", "A/B", "x" * 65])
async def test_capture_refuses_an_order_id_that_could_alter_the_request_path(api_as, make_user, paypal, order_id):
    c = await api_as(await make_user("a@x.fr"))
    assert (await c.post("/api/billing/paypal/capture", json={"order_id": order_id})).status_code == 422
    assert not [call for call in paypal.calls if call[0] == "capture"]


async def test_the_real_client_never_calls_paypal_with_a_malformed_order_id():
    client = PayPalClient("id", "secret", "")
    with pytest.raises(PayPalError):
        await client.capture_order("../x")


async def test_capturing_an_order_already_captured_is_not_an_error(api_as, make_user, paypal):
    async def already(order_id):
        raise PayPalError("Déjà capturée", "ORDER_ALREADY_CAPTURED")
    paypal.capture_order = already
    r = await (await api_as(await make_user("a@x.fr"))).post("/api/billing/paypal/capture", json={"order_id": "ORDER-1"})
    assert r.status_code == 200 and r.json() == {"credited": 0}


async def test_get_paypal_prefers_the_saved_credentials_then_a_shared_fake(session, monkeypatch):
    monkeypatch.setattr(settings, "fake_providers", True)
    assert await get_paypal(session) is await get_paypal(session)  # sans identifiants : même faux d'une requête à l'autre
    app_settings = AppSettings(session)
    await app_settings.set("paypal_client_id", "id")
    await app_settings.set("paypal_client_secret", "secret")
    assert isinstance(await get_paypal(session), PayPalClient)


async def test_fake_mode_has_a_default_voice_so_a_fresh_install_runs_end_to_end(session, monkeypatch):
    monkeypatch.setattr(settings, "fake_providers", True)
    assert await AppSettings(session).get("default_voice_id") == "fake-voice"
    monkeypatch.setattr(settings, "fake_providers", False)
    assert await AppSettings(session).get("default_voice_id") == ""


# --- Abonnement (PayPal Subscriptions) ---

async def subscription_balance(session, user) -> int:
    row = await session.scalar(select(CreditBalance).where(CreditBalance.user_id == user.id))
    return row.subscription if row else 0


async def subscribe(c, paypal, cycles: int = 1, tier_id: str = "starter") -> str:
    """Crée l'abonnement par l'API et simule l'approbation du client chez PayPal ; renvoie l'identifiant d'abonnement."""
    r = await c.post("/api/billing/paypal/subscription", json={"tier_id": tier_id})
    assert r.status_code == 200
    sub_id = r.json()["url"].rsplit("=", 1)[1]
    paypal.approve_subscription(sub_id, cycles)
    return sub_id


def sale_event(sub_id: str) -> dict:
    return {"id": f"WH-{sub_id}", "event_type": "PAYMENT.SALE.COMPLETED", "resource": {"id": "SALE-1", "billing_agreement_id": sub_id}}


async def test_subscribing_then_confirming_grants_the_monthly_quota_once(api_as, make_user, paypal, session):
    user = await make_user("a@x.fr")
    c = await api_as(user)
    sub_id = await subscribe(c, paypal)
    assert paypal.calls[0] == ("subscribe", "P-VIVI", str(user.id))
    first = await c.post("/api/billing/paypal/subscription/confirm", json={"subscription_id": sub_id})
    again = await c.post("/api/billing/paypal/subscription/confirm", json={"subscription_id": sub_id})
    assert first.json() == {"activated": True, "credited": 400} and again.json() == {"activated": True, "credited": 0}
    assert await subscription_balance(session, user) == 400
    assert (await c.get("/api/billing")).json()["subscribed"] is True


async def test_confirming_before_the_first_payment_credits_nothing(api_as, make_user, paypal, session):
    c = await api_as(user := await make_user("a@x.fr"))
    sub_id = await subscribe(c, paypal, cycles=0)
    r = await c.post("/api/billing/paypal/subscription/confirm", json={"subscription_id": sub_id})
    assert r.json() == {"activated": False, "credited": 0} and await subscription_balance(session, user) == 0


async def test_renewal_webhook_resets_the_quota_once_per_cycle_and_dedupes_with_the_confirm(api_as, make_user, paypal, session):
    c = await api_as(user := await make_user("a@x.fr"))
    sub_id = await subscribe(c, paypal)
    await c.post("/api/billing/paypal/subscription/confirm", json={"subscription_id": sub_id})
    anon = await api_as(None)
    assert (await anon.post("/api/paypal/webhook", json=sale_event(sub_id))).json()["credited"] == 0  # même cycle que la confirmation
    paypal.approve_subscription(sub_id, cycles=2)  # un mois plus tard
    assert (await anon.post("/api/paypal/webhook", json=sale_event(sub_id))).json()["credited"] == 400
    assert (await anon.post("/api/paypal/webhook", json=sale_event(sub_id))).json()["credited"] == 0
    assert await subscription_balance(session, user) == 400


async def test_the_webhook_alone_activates_a_client_who_closed_the_tab(api_as, make_user, paypal, session):
    c = await api_as(user := await make_user("a@x.fr"))
    sub_id = await subscribe(c, paypal)
    r = await (await api_as(None)).post("/api/paypal/webhook", json=sale_event(sub_id))
    assert r.json()["credited"] == 400 and await subscription_balance(session, user) == 400


async def test_cancelling_keeps_the_paid_period_and_frees_the_subscription(api_as, make_user, paypal, session):
    c = await api_as(await make_user("a@x.fr"))
    sub_id = await subscribe(c, paypal)
    await c.post("/api/billing/paypal/subscription/confirm", json={"subscription_id": sub_id})
    assert (await c.get("/api/billing")).json()["paypal_cancellable"] is True
    assert (await c.post("/api/billing/paypal/subscription/cancel")).json() == {"cancelled": True}
    assert ("cancel", sub_id) in paypal.calls
    cancelled = {"id": "WH-C", "event_type": "BILLING.SUBSCRIPTION.CANCELLED", "resource": {"id": sub_id}}
    await (await api_as(None)).post("/api/paypal/webhook", json=cancelled)
    body = (await c.get("/api/billing")).json()
    assert body["subscribed"] is True and body["paypal_cancellable"] is False  # période payée conservée, plus de renouvellement


async def test_subscribe_to_creator_sets_plan_and_quota(api_as, make_user, paypal, session):
    user = await make_user("a@x.fr")
    c = await api_as(user)
    sub_id = await subscribe(c, paypal, tier_id="creator")
    assert paypal.calls[0] == ("subscribe", "P-CREATOR", str(user.id))
    r = await c.post("/api/billing/paypal/subscription/confirm", json={"subscription_id": sub_id})
    assert r.json() == {"activated": True, "credited": 3000}
    await session.refresh(user)
    assert user.plan_id == "creator" and await subscription_balance(session, user) == 3000
    body = (await c.get("/api/billing")).json()
    assert body["current_tier"] == "creator" and body["subscribed"] is True


async def test_renewal_keeps_tier_quota(api_as, make_user, paypal, session):
    c = await api_as(user := await make_user("a@x.fr"))
    sub_id = await subscribe(c, paypal, tier_id="creator")
    await c.post("/api/billing/paypal/subscription/confirm", json={"subscription_id": sub_id})
    paypal.approve_subscription(sub_id, cycles=2)
    assert (await (await api_as(None)).post("/api/paypal/webhook", json=sale_event(sub_id))).json()["credited"] == 3000
    await session.refresh(user)
    assert user.plan_id == "creator" and await subscription_balance(session, user) == 3000


async def test_unknown_paypal_plan_ignored(api_as, make_user, paypal, session):
    from app.services import payments
    user = await make_user("a@x.fr")
    subscription = {"id": "I-X", "plan_id": "P-AUTRE", "custom_id": str(user.id), "status": "ACTIVE",
                    "billing_info": {"cycle_executions": [{"tenure_type": "REGULAR", "cycles_completed": 1}]}}
    assert await payments.apply_paypal_subscription(session, subscription, AppSettings(session)) == 0
    assert user.plan_id is None and await subscription_balance(session, user) == 0


async def test_unknown_tier_404(api_as, make_user, paypal):
    r = await (await api_as(await make_user("a@x.fr"))).post("/api/billing/paypal/subscription", json={"tier_id": "gold"})
    assert r.status_code == 404 and paypal.calls == []


async def test_tier_without_paypal_plan_409(api_as, make_user, paypal):
    c = await api_as(await make_user("a@x.fr"))
    assert (await c.post("/api/billing/paypal/subscription", json={"tier_id": "pro"})).status_code == 409  # Pro n'a pas de plan PayPal


async def test_resubscribing_to_the_renewing_tier_409(api_as, make_user, paypal):
    c = await api_as(await make_user("a@x.fr"))
    await c.post("/api/billing/paypal/subscription/confirm", json={"subscription_id": await subscribe(c, paypal)})
    assert (await c.post("/api/billing/paypal/subscription", json={"tier_id": "starter"})).status_code == 409


async def test_switching_tier_replaces_the_subscription_once_the_new_one_is_paid(api_as, make_user, paypal, session):
    c = await api_as(user := await make_user("a@x.fr"))
    old = await subscribe(c, paypal)
    await c.post("/api/billing/paypal/subscription/confirm", json={"subscription_id": old})
    new = await subscribe(c, paypal, tier_id="creator")
    r = await c.post("/api/billing/paypal/subscription/confirm", json={"subscription_id": new})
    assert r.json() == {"activated": True, "credited": 3000} and ("cancel", old) in paypal.calls
    await session.refresh(user)
    assert user.plan_id == "creator" and user.paypal_subscription_id == new
    assert await subscription_balance(session, user) == 3000  # le quota du nouveau forfait remplace l'ancien
    cancelled = {"id": "WH-C", "event_type": "BILLING.SUBSCRIPTION.CANCELLED", "resource": {"id": old}}
    await (await api_as(None)).post("/api/paypal/webhook", json=cancelled)
    await session.refresh(user)
    assert user.paypal_subscription_id == new and (await c.get("/api/billing")).json()["paypal_cancellable"] is True


async def test_abandoned_switch_keeps_the_current_subscription(api_as, make_user, paypal, session):
    c = await api_as(user := await make_user("a@x.fr"))
    old = await subscribe(c, paypal)
    await c.post("/api/billing/paypal/subscription/confirm", json={"subscription_id": old})
    assert (await c.post("/api/billing/paypal/subscription", json={"tier_id": "creator"})).status_code == 200  # jamais approuvé
    await session.refresh(user)
    assert user.paypal_subscription_id == old and user.plan_id == "starter" and ("cancel", old) not in paypal.calls


async def test_confirming_someone_elses_subscription_is_refused(api_as, make_user, paypal, session):
    owner, thief = await make_user("a@x.fr"), await make_user("b@x.fr")
    sub_id = await subscribe(await api_as(owner), paypal)
    r = await (await api_as(thief)).post("/api/billing/paypal/subscription/confirm", json={"subscription_id": sub_id})
    assert r.status_code == 403 and await subscription_balance(session, owner) == 0 == await subscription_balance(session, thief)


@pytest.mark.parametrize("sub_id", ["../../v1/x", "I 1", "A/B", "x" * 65])
async def test_subscription_ids_that_could_alter_the_request_path_are_refused(api_as, make_user, paypal, sub_id):
    c = await api_as(await make_user("a@x.fr"))
    assert (await c.post("/api/billing/paypal/subscription/confirm", json={"subscription_id": sub_id})).status_code == 422


async def test_paypal_subscription_is_offered_only_with_a_plan_and_credentials(api_as, make_user, paypal, session, monkeypatch):
    monkeypatch.setattr(settings, "fake_providers", False)
    c = await api_as(await make_user("a@x.fr"))
    assert [t["paypal_purchasable"] for t in (await c.get("/api/billing")).json()["tiers"]] == [False, False, False]
    app_settings = AppSettings(session)
    await app_settings.set("paypal_client_id", "id")
    await app_settings.set("paypal_client_secret", "secret")
    assert [t["paypal_purchasable"] for t in (await c.get("/api/billing")).json()["tiers"]] == [True, True, False]


async def test_the_real_client_creates_a_product_then_a_monthly_plan():
    seen: list[tuple[str, dict]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content and request.url.path != "/v1/oauth2/token" else {}
        seen.append((request.url.path, body))
        answers = {"/v1/oauth2/token": {"access_token": "T", "expires_in": 3600}, "/v1/catalogs/products": {"id": "PROD-1"},
                   "/v1/billing/plans": {"id": "P-NEW"}}
        return httpx.Response(201, json=answers[request.url.path])

    client = PayPalClient("id", "secret", "", http=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    assert await client.create_monthly_plan(name="Vivi mensuel", amount="19.00") == "P-NEW"
    plan = dict(seen)["/v1/billing/plans"]
    assert plan["product_id"] == "PROD-1"
    assert plan["billing_cycles"][0]["pricing_scheme"]["fixed_price"] == {"value": "19.00", "currency_code": "USD"}


def legacy_subscription(user, status="ACTIVE", cycles=2) -> dict:
    """Abonnement au plan unique d'avant les forfaits : son plan n'est plus dans `billing_config`."""
    return {"id": "I-OLD", "plan_id": "P-ANCIEN", "custom_id": str(user.id), "status": status,
            "billing_info": {"cycle_executions": [{"tenure_type": "REGULAR", "cycles_completed": cycles}],
                             "next_billing_time": "2030-01-01T00:00:00Z"}}


async def test_legacy_subscriber_renewal_is_credited(make_user, paypal, session):
    from app.services import payments
    user = await make_user("a@x.fr")
    user.paypal_subscription_id = "I-OLD"
    await session.commit()
    assert await payments.apply_paypal_subscription(session, legacy_subscription(user), AppSettings(session)) == 400
    assert user.plan_id == "starter" and user.subscription_ends_at.year == 2030


async def test_legacy_subscription_cancellation_frees_it(make_user, paypal, session):
    from app.services import payments
    user = await make_user("a@x.fr")
    user.paypal_subscription_id = "I-OLD"
    await session.commit()
    await payments.apply_paypal_subscription(session, legacy_subscription(user, "CANCELLED"), AppSettings(session))
    assert user.paypal_subscription_id is None
