import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs

import httpx
import pytest

from app.app_settings import AppSettings
from app.services.billing import DEFAULT_BILLING, load_billing, parse_billing
from app.services.stripe_client import FakeStripe, StripeClient, StripeError, verify_signature

SECRET = "whsec_test"


def sign(payload: bytes, secret: str = SECRET, at: float | None = None) -> str:
    stamp = int(at if at is not None else time.time())
    mac = hmac.new(secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={stamp},v1={mac}"


def test_valid_signature_is_accepted():
    assert verify_signature(b'{"id":"evt_1"}', sign(b'{"id":"evt_1"}'), SECRET)


def test_two_v1_signatures_one_valid_is_accepted():
    header = sign(b"{}") + ",v1=" + "0" * 64
    assert verify_signature(b"{}", header, SECRET)


def test_tampered_payload_wrong_secret_old_or_malformed_header_are_refused():
    header = sign(b'{"id":"evt_1"}')
    assert not verify_signature(b'{"id":"evt_2"}', header, SECRET)
    assert not verify_signature(b'{"id":"evt_1"}', header, "whsec_autre")
    assert not verify_signature(b"{}", sign(b"{}", at=time.time() - 3600), SECRET)
    for bad in ("", "n'importe quoi", "t=abc,v1=00", "v1=00", "t=1"):
        assert not verify_signature(b"{}", bad, SECRET)
    assert not verify_signature(b"{}", sign(b"{}"), "")  # secret non configuré : tout est refusé


async def test_real_client_sends_form_encoded_requests_with_the_secret_key():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers["authorization"], parse_qs(request.content.decode())))
        return httpx.Response(200, json={"id": "cus_1", "url": "https://stripe.test/pay"})

    client = StripeClient("sk_test_x", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await client.create_customer("a@x.fr", 7) == "cus_1"
    url = await client.create_checkout(customer_id="cus_1", mode="payment", price_id="price_9", success_url="https://s",
                                       cancel_url="https://c", client_reference_id="7", metadata={"credits": "200"})
    assert url == "https://stripe.test/pay"
    assert await client.create_portal("cus_1", "https://r") == "https://stripe.test/pay"
    (c_path, c_auth, c_form), (k_path, _, k_form), (p_path, _, p_form) = seen
    assert (c_path, c_auth) == ("/v1/customers", "Bearer sk_test_x")
    assert c_form == {"email": ["a@x.fr"], "metadata[user_id]": ["7"]}
    assert k_path == "/v1/checkout/sessions"
    assert k_form["line_items[0][price]"] == ["price_9"] and k_form["line_items[0][quantity]"] == ["1"]
    assert k_form["mode"] == ["payment"] and k_form["metadata[credits]"] == ["200"] and k_form["customer"] == ["cus_1"]
    assert k_form["client_reference_id"] == ["7"]
    assert p_path == "/v1/billing_portal/sessions" and p_form == {"customer": ["cus_1"], "return_url": ["https://r"]}


async def test_subscription_checkout_copies_metadata_onto_the_subscription():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"url": "https://stripe.test/pay"})

    client = StripeClient("sk_test_x", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await client.create_checkout(customer_id="cus_1", mode="subscription", price_id="price_9", success_url="https://s",
                                 cancel_url="https://c", client_reference_id="7", metadata={"plan": "creator"})
    assert seen[0]["subscription_data[metadata][plan]"] == ["creator"]  # relu sur chaque facture (invoice.paid)


async def test_stripe_error_carries_a_readable_message():
    def handler(request):
        return httpx.Response(402, json={"error": {"message": "No such price: 'price_x'"}})

    client = StripeClient("sk_test_x", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(StripeError, match="No such price"):
        await client.create_portal("cus_1", "https://r")


async def test_fake_stripe_records_calls_and_returns_urls():
    fake = FakeStripe()
    assert await fake.create_customer("a@x.fr", 1) == "cus_fake_1"
    url = await fake.create_checkout(customer_id="cus_fake_1", mode="subscription", price_id="p", success_url="https://s",
                                     cancel_url="https://c", client_reference_id="1", metadata={})
    assert url.startswith("https://") and fake.calls[-1][0] == "checkout"


def test_default_billing_config_follows_the_spec():
    config = parse_billing(DEFAULT_BILLING)
    assert config and [t.credits for t in config.tiers] == [1200, 3000, 9000]
    assert [(p.id, p.credits, p.paypal_amount) for p in config.packs] == [("pack500", 500, "6.00"), ("pack1500", 1500, "15.00")]
    assert not config.configured  # price_id vides


@pytest.mark.parametrize("raw", [
    "pas du json", "[]", '{"tiers": [{"id": "a", "credits": -1}]}', '{"packs": [{"id": "a", "credits": 0}]}',
    '{"packs": [{"id": "a", "credits": 5}, {"id": "a", "credits": 6}]}', '{"packs": [{"credits": 5}]}',
    '{"subscription": {"price_id": "", "credits": 5}}', '{"autre": 1}',
])
async def test_billing_config_setting_rejects_invalid_values(session, raw):
    with pytest.raises(ValueError, match="billing_config"):
        await AppSettings(session).set("billing_config", raw)


async def test_load_billing_reads_the_setting(session):
    app_settings = AppSettings(session)
    assert (await load_billing(app_settings)).packs[0].id == "pack500"
    config = json.loads(DEFAULT_BILLING)
    config["tiers"][0].update(price_id="price_sub", credits=300)
    config["packs"] = [{"id": "p1", "price_id": "price_p1", "credits": 50, "label": "5 $"}]
    await app_settings.set("billing_config", json.dumps(config))
    config = await load_billing(app_settings)
    assert config.tiers[0].price_id == "price_sub" and config.tiers[0].credits == 300
    assert [p.id for p in config.packs] == ["p1"]
