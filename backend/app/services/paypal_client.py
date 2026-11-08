"""Client PayPal minimal (REST par httpx, sans SDK) : recharges par Orders v2, abonnements par Subscriptions et vérification
des webhooks par l'API PayPal. Le faux client sert aux tests et à `FAKE_PROVIDERS=true` : aucun appel réseau, aucune clé."""
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import AppSettings
from app.config import settings
from app.db import get_session
from app.services.billing import PAYPAL_ID

PAYPAL_API = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}
TIMEOUT_S = 20
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

    async def create_subscription(self, *, plan_id: str, custom_id: str, return_url: str, cancel_url: str) -> tuple[str, str]:
        """Crée un abonnement au plan PayPal ; renvoie `(subscription_id, url d'approbation)`."""
        ...

    async def get_subscription(self, subscription_id: str) -> dict: ...

    async def cancel_subscription(self, subscription_id: str, reason: str) -> None: ...

    async def verify_webhook(self, headers: dict[str, str], event: dict) -> bool: ...


def _safe_id(value: str) -> str:
    """Un identifiant PayPal finit dans une URL appelée avec nos identifiants : jamais de `/`, de `..` ni d'espace."""
    if not PAYPAL_ID.fullmatch(value):
        raise PayPalError("Identifiant PayPal invalide")
    return value


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
        return await self._request("POST", f"/v2/checkout/orders/{_safe_id(order_id)}/capture", headers=await self._headers(),
                                   json={})

    async def create_subscription(self, *, plan_id: str, custom_id: str, return_url: str, cancel_url: str) -> tuple[str, str]:
        body = await self._request("POST", "/v1/billing/subscriptions", headers=await self._headers(), json={
            "plan_id": _safe_id(plan_id), "custom_id": custom_id,
            "application_context": {"brand_name": "Vivi", "user_action": "SUBSCRIBE_NOW", "return_url": return_url,
                                    "cancel_url": cancel_url}})
        approve = next((link["href"] for link in body.get("links", []) if link.get("rel") == "approve"), None)
        if approve is None:
            raise PayPalError("PayPal n'a pas renvoyé de page d'abonnement")
        return body["id"], approve

    async def get_subscription(self, subscription_id: str) -> dict:
        return await self._request("GET", f"/v1/billing/subscriptions/{_safe_id(subscription_id)}", headers=await self._headers())

    async def cancel_subscription(self, subscription_id: str, reason: str) -> None:
        await self._request("POST", f"/v1/billing/subscriptions/{_safe_id(subscription_id)}/cancel",
                            headers=await self._headers(), json={"reason": reason})

    async def create_monthly_plan(self, *, name: str, amount: str) -> str:
        """Mise en route (une fois, par `scripts/paypal_create_plan.py`) : crée le produit et son plan mensuel en dollars
        chez PayPal ; renvoie l'identifiant du plan (« P-… »), à saisir dans `billing_config`."""
        headers = await self._headers()
        product = await self._request("POST", "/v1/catalogs/products", headers=headers,
                                      json={"name": name, "type": "SERVICE", "category": "SOFTWARE"})
        plan = await self._request("POST", "/v1/billing/plans", headers=headers, json={
            "product_id": product["id"], "name": name, "status": "ACTIVE",
            "billing_cycles": [{"frequency": {"interval_unit": "MONTH", "interval_count": 1}, "tenure_type": "REGULAR",
                                "sequence": 1, "total_cycles": 0,
                                "pricing_scheme": {"fixed_price": {"value": amount, "currency_code": "USD"}}}],
            "payment_preferences": {"auto_bill_outstanding": True, "payment_failure_threshold": 3}})
        return plan["id"]

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
    """Garde les appels en mémoire ; une commande « approuvée » se capture avec le montant et le `custom_id` créés, un
    abonnement s'active avec `approve_subscription` (le client a approuvé et PayPal a prélevé `cycles` mois)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.orders: dict[str, dict] = {}
        self.subscriptions: dict[str, dict] = {}
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

    async def create_subscription(self, *, plan_id: str, custom_id: str, return_url: str, cancel_url: str) -> tuple[str, str]:
        sub_id = f"I-SUB{len(self.subscriptions) + 1}"
        self.subscriptions[sub_id] = {"plan_id": plan_id, "custom_id": custom_id, "status": "APPROVAL_PENDING", "cycles": 0}
        self.calls.append(("subscribe", plan_id, custom_id))
        return sub_id, f"https://www.paypal.test/webapps/billing/subscriptions?ba_token={sub_id}"

    def approve_subscription(self, subscription_id: str, cycles: int = 1) -> None:
        self.subscriptions[subscription_id].update(status="ACTIVE", cycles=cycles)

    async def get_subscription(self, subscription_id: str) -> dict:
        sub = self.subscriptions.get(subscription_id)
        if sub is None:
            raise PayPalError("Abonnement inconnu")
        next_billing = datetime.now(UTC) + timedelta(days=30)
        return {"id": subscription_id, "status": sub["status"], "plan_id": sub["plan_id"], "custom_id": sub["custom_id"],
                "billing_info": {"next_billing_time": next_billing.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "cycle_executions": [{"tenure_type": "REGULAR", "cycles_completed": sub["cycles"]}]}}

    async def cancel_subscription(self, subscription_id: str, reason: str) -> None:
        self.calls.append(("cancel", subscription_id))
        self.subscriptions[subscription_id]["status"] = "CANCELLED"

    async def verify_webhook(self, headers: dict[str, str], event: dict) -> bool:
        return self.webhook_valid


_FAKE = FakePayPal()  # un seul faux pour tout le processus : une commande créée par une requête se capture dans la suivante


async def get_paypal(session: AsyncSession = Depends(get_session)) -> PayPalAPI:
    """Les identifiants saisis dans les Réglages priment ; sans eux, le faux n'est servi qu'en mode `FAKE_PROVIDERS`."""
    app_settings = AppSettings(session)
    client_id, secret = await app_settings.get("paypal_client_id"), await app_settings.get("paypal_client_secret")
    if client_id and secret:
        return PayPalClient(client_id, secret, await app_settings.get("paypal_webhook_id"), await app_settings.get("paypal_mode"))
    if settings.fake_providers:
        return _FAKE
    raise HTTPException(503, "PayPal n'est pas configuré (identifiants absents des Réglages)")
