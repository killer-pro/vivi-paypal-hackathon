import json

import pytest
from sqlalchemy import select

from app.app_settings import AppSettings
from app.config import settings
from app.main import app
from app.models import CreditBalance
from app.services.paypal_client import FakePayPal, PayPalClient, PayPalError, get_paypal

CONFIG = {"subscription": {"price_id": "", "credits": 400, "label": "19 $ par mois"},
          "packs": [{"id": "pack200", "price_id": "", "credits": 200, "label": "10 $", "paypal_amount": "10.00"},
                    {"id": "pack500", "price_id": "", "credits": 500, "label": "24 $"}]}


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
