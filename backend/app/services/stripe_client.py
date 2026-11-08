"""Client Stripe minimal (REST par httpx, sans SDK) et vérification de la signature des webhooks. Le faux client sert aux
tests et à `FAKE_PROVIDERS=true` : aucun appel réseau, aucune clé."""
import hashlib
import hmac
import time
from typing import Protocol

import httpx
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import AppSettings
from app.config import settings
from app.db import get_session

STRIPE_API = "https://api.stripe.com/v1"
SIGNATURE_TOLERANCE_S = 300  # un webhook plus ancien est refusé (rejeu)
TIMEOUT_S = 20


class StripeError(Exception):
    """Refus ou panne de Stripe ; le message est celui de Stripe, affichable tel quel."""


class StripeAPI(Protocol):
    async def create_customer(self, email: str, user_id: int) -> str: ...

    async def create_checkout(self, *, customer_id: str, mode: str, price_id: str, success_url: str, cancel_url: str,
                              client_reference_id: str, metadata: dict[str, str]) -> str: ...

    async def create_portal(self, customer_id: str, return_url: str) -> str: ...


def verify_signature(payload: bytes, header: str, secret: str, *, now: float | None = None) -> bool:
    """`Stripe-Signature: t=<horodatage>,v1=<HMAC-SHA256 de « t.payload »>` : valide si une signature v1 correspond
    (comparaison à temps constant) et si l'horodatage est récent. Sans secret configuré, tout est refusé."""
    if not secret:
        return False
    parts = [item.partition("=") for item in header.split(",")]
    stamps = [value for key, _, value in parts if key == "t"]
    if len(stamps) != 1 or not stamps[0].isascii() or not stamps[0].isdigit():
        return False
    stamp = int(stamps[0])
    if abs((time.time() if now is None else now) - stamp) > SIGNATURE_TOLERANCE_S:
        return False
    expected = hmac.new(secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, value) for key, _, value in parts if key == "v1")


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    """Formulaire imbriqué de Stripe : `metadata[user_id]`, `line_items[0][price]`."""
    out: dict[str, str] = {}
    for key, value in data.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten(value, name))
        elif isinstance(value, list):
            out.update(_flatten(dict(enumerate(value)), name))
        else:
            out[name] = str(value)
    return out


class StripeClient:
    def __init__(self, secret_key: str, http: httpx.AsyncClient | None = None):
        self._key, self._http = secret_key, http or httpx.AsyncClient(timeout=TIMEOUT_S)

    async def _post(self, path: str, data: dict) -> dict:
        try:
            response = await self._http.post(f"{STRIPE_API}{path}", data=_flatten(data),
                                             headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as e:
            raise StripeError(f"Stripe injoignable : {e}") from e
        body = response.json() if response.content else {}
        if response.status_code >= 400:
            raise StripeError((body.get("error") or {}).get("message") or f"Stripe : erreur {response.status_code}")
        return body

    async def create_customer(self, email: str, user_id: int) -> str:
        return (await self._post("/customers", {"email": email, "metadata": {"user_id": user_id}}))["id"]

    async def create_checkout(self, *, customer_id: str, mode: str, price_id: str, success_url: str, cancel_url: str,
                              client_reference_id: str, metadata: dict[str, str]) -> str:
        data: dict = {"mode": mode, "customer": customer_id, "line_items": [{"price": price_id, "quantity": 1}],
                      "success_url": success_url, "cancel_url": cancel_url, "client_reference_id": client_reference_id,
                      "metadata": metadata}
        if mode == "subscription":  # recopiées sur l'abonnement, donc sur chaque facture (`invoice.paid`)
            data["subscription_data"] = {"metadata": metadata}
        return (await self._post("/checkout/sessions", data))["url"]

    async def create_portal(self, customer_id: str, return_url: str) -> str:
        return (await self._post("/billing_portal/sessions", {"customer": customer_id, "return_url": return_url}))["url"]


class FakeStripe:
    """Garde les appels en mémoire et renvoie des URL factices (tests, `FAKE_PROVIDERS=true`)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def create_customer(self, email: str, user_id: int) -> str:
        self.calls.append(("customer", email, user_id))
        return f"cus_fake_{user_id}"

    async def create_checkout(self, *, customer_id: str, mode: str, price_id: str, success_url: str, cancel_url: str,
                              client_reference_id: str, metadata: dict[str, str]) -> str:
        self.calls.append(("checkout", customer_id, mode, price_id, metadata))
        return f"https://checkout.stripe.test/{mode}/{price_id}"

    async def create_portal(self, customer_id: str, return_url: str) -> str:
        self.calls.append(("portal", customer_id))
        return f"https://billing.stripe.test/{customer_id}"


async def get_stripe(session: AsyncSession = Depends(get_session)) -> StripeAPI:
    if settings.fake_providers:
        return FakeStripe()
    key = await AppSettings(session).get("stripe_secret_key")
    if not key:
        raise HTTPException(503, "Le paiement n'est pas configuré (clé secrète Stripe absente des Réglages)")
    return StripeClient(key)
