"""Client PayPal minimal (REST par httpx, sans SDK) : recharges par Orders v2 et vérification des webhooks par l'API PayPal.
Le faux client sert aux tests et à `FAKE_PROVIDERS=true` : aucun appel réseau, aucune clé."""
import re
import time
from typing import Protocol

import httpx
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import AppSettings
from app.config import settings
from app.db import get_session

PAYPAL_API = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}
TIMEOUT_S = 20
ORDER_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")  # un identifiant de commande finit dans une URL appelée avec nos identifiants
TOKEN_MARGIN_S = 60  # on renouvelle le jeton un peu avant son expiration


class PayPalError(Exception):
    """Refus ou panne de PayPal ; le message est celui de PayPal, affichable tel quel. `issue` : code d'erreur de PayPal
    (« ORDER_ALREADY_CAPTURED »...), vide s'il n'y en a pas."""

    def __init__(self, message: str, issue: str = ""):
        super().__init__(message)
        self.issue = issue


class PayPalAPI(Protocol):
    async def create_order(self, *, amount: str, custom_id: str, description: str, return_url: str,
                           cancel_url: str) -> tuple[str, str]:
        """Crée une commande en dollars ; renvoie `(order_id, url d'approbation)`."""
        ...

    async def capture_order(self, order_id: str) -> dict: ...

    async def verify_webhook(self, headers: dict[str, str], event: dict) -> bool: ...


class PayPalClient:
    def __init__(self, client_id: str, secret: str, webhook_id: str, mode: str = "sandbox",
                 http: httpx.AsyncClient | None = None):
        self._auth, self._webhook_id = (client_id, secret), webhook_id
        self._base, self._http = PAYPAL_API.get(mode, PAYPAL_API["sandbox"]), http or httpx.AsyncClient(timeout=TIMEOUT_S)
        self._token, self._expires_at = "", 0.0

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self._http.request(method, f"{self._base}{path}", **kwargs)
        except httpx.HTTPError as e:
            raise PayPalError(f"PayPal injoignable : {e}") from e
        body = response.json() if response.content else {}
        if response.status_code >= 400:
            issue = ((body.get("details") or [{}])[0] or {}).get("issue") or ""
            raise PayPalError(body.get("message") or body.get("error_description") or f"PayPal : erreur {response.status_code}",
                              issue)
        return body

    async def _headers(self) -> dict[str, str]:
        if time.monotonic() >= self._expires_at:
            body = await self._request("POST", "/v1/oauth2/token", auth=self._auth, data={"grant_type": "client_credentials"})
            self._token, self._expires_at = body["access_token"], time.monotonic() + int(body["expires_in"]) - TOKEN_MARGIN_S
        return {"Authorization": f"Bearer {self._token}"}

    async def create_order(self, *, amount: str, custom_id: str, description: str, return_url: str,
                           cancel_url: str) -> tuple[str, str]:
        body = await self._request("POST", "/v2/checkout/orders", headers=await self._headers(), json={
            "intent": "CAPTURE",
            "purchase_units": [{"custom_id": custom_id, "description": description,
                                "amount": {"currency_code": "USD", "value": amount}}],
            "payment_source": {"paypal": {"experience_context": {
                "return_url": return_url, "cancel_url": cancel_url, "user_action": "PAY_NOW", "brand_name": "Vivi"}}}})
        approve = next((link["href"] for link in body.get("links", []) if link.get("rel") in ("payer-action", "approve")), None)
        if approve is None:
            raise PayPalError("PayPal n'a pas renvoyé de page de paiement")
        return body["id"], approve

    async def capture_order(self, order_id: str) -> dict:
        if not ORDER_ID.fullmatch(order_id):
            raise PayPalError("Commande invalide")
        return await self._request("POST", f"/v2/checkout/orders/{order_id}/capture", headers=await self._headers(),
                                   json={})

    async def verify_webhook(self, headers: dict[str, str], event: dict) -> bool:
        """Signature vérifiée par PayPal lui-même (`verify-webhook-signature`) : refusée si la réponse n'est pas SUCCESS."""
        keys = ("paypal-auth-algo", "paypal-cert-url", "paypal-transmission-id", "paypal-transmission-sig",
                "paypal-transmission-time")
        if not self._webhook_id or any(k not in headers for k in keys):
            return False
        body = await self._request("POST", "/v1/notifications/verify-webhook-signature", headers=await self._headers(), json={
            "auth_algo": headers["paypal-auth-algo"], "cert_url": headers["paypal-cert-url"],
            "transmission_id": headers["paypal-transmission-id"], "transmission_sig": headers["paypal-transmission-sig"],
            "transmission_time": headers["paypal-transmission-time"], "webhook_id": self._webhook_id, "webhook_event": event})
        return body.get("verification_status") == "SUCCESS"


class FakePayPal:
    """Garde les appels en mémoire ; une commande « approuvée » se capture avec le montant et le `custom_id` créés."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.orders: dict[str, dict] = {}
        self.webhook_valid = True

    async def create_order(self, *, amount: str, custom_id: str, description: str, return_url: str,
                           cancel_url: str) -> tuple[str, str]:
        order_id = f"ORDER-{len(self.orders) + 1}"
        self.orders[order_id] = {"amount": amount, "custom_id": custom_id}
        self.calls.append(("order", amount, custom_id))
        return order_id, f"https://www.paypal.test/checkoutnow?token={order_id}"

    async def capture_order(self, order_id: str) -> dict:
        self.calls.append(("capture", order_id))
        order = self.orders.get(order_id)
        if order is None:
            raise PayPalError("Commande inconnue")
        return {"id": order_id, "status": "COMPLETED", "purchase_units": [{"payments": {"captures": [{
            "id": f"CAP-{order_id}", "status": "COMPLETED", "custom_id": order["custom_id"],
            "amount": {"currency_code": "USD", "value": order["amount"]}}]}}]}

    async def verify_webhook(self, headers: dict[str, str], event: dict) -> bool:
        return self.webhook_valid


async def get_paypal(session: AsyncSession = Depends(get_session)) -> PayPalAPI:
    if settings.fake_providers:
        return FakePayPal()
    app_settings = AppSettings(session)
    client_id, secret = await app_settings.get("paypal_client_id"), await app_settings.get("paypal_client_secret")
    if not (client_id and secret):
        raise HTTPException(503, "PayPal n'est pas configuré (identifiants absents des Réglages)")
    return PayPalClient(client_id, secret, await app_settings.get("paypal_webhook_id"), await app_settings.get("paypal_mode"))
