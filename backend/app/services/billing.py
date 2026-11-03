"""Offre payante : abonnement et recharges (réglage `billing_config`). Les prix en argent vivent côté Stripe ; ici, les
identifiants de prix, les crédits vendus et le libellé affiché."""
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.app_settings import AppSettings

# Valeurs de la spec : 400 crédits par mois, packs de 200, 500 et 1 200 crédits. Les `price_id` sont à saisir (Stripe).
DEFAULT_BILLING = json.dumps({
    "subscription": {"price_id": "", "credits": 400, "label": "19 $ par mois"},
    "packs": [{"id": "pack200", "price_id": "", "credits": 200, "label": "10 $", "paypal_amount": "10.00"},
              {"id": "pack500", "price_id": "", "credits": 500, "label": "24 $", "paypal_amount": "24.00"},
              {"id": "pack1200", "price_id": "", "credits": 1200, "label": "55 $", "paypal_amount": "55.00"}],
})

PAYPAL_AMOUNT = re.compile(r"[1-9]\d{0,5}\.\d{2}")  # dollars avec deux décimales, exigé par PayPal


@dataclass(frozen=True)
class Plan:
    id: str
    price_id: str
    credits: int
    label: str
    paypal_amount: str = ""  # montant en dollars (« 10.00 ») facturé par PayPal ; vide : pas d'achat par PayPal

    @property
    def purchasable(self) -> bool:
        return bool(self.price_id)

    @property
    def paypal_purchasable(self) -> bool:
        return bool(self.paypal_amount)


@dataclass(frozen=True)
class BillingConfig:
    subscription: Plan
    packs: tuple[Plan, ...]

    @property
    def configured(self) -> bool:
        return self.subscription.purchasable or any(p.purchasable for p in self.packs)

    def pack(self, pack_id: str) -> Plan | None:
        return next((p for p in self.packs if p.id == pack_id), None)


def _plan(raw: Any, plan_id: str | None = None) -> Plan | None:
    if not isinstance(raw, dict) or not set(raw) <= {"id", "price_id", "credits", "label", "paypal_amount"}:
        return None
    credits, price_id, label = raw.get("credits"), raw.get("price_id", ""), raw.get("label", "")
    amount = raw.get("paypal_amount", "")
    if not isinstance(amount, str) or (amount.strip() and not PAYPAL_AMOUNT.fullmatch(amount.strip())):
        return None
    plan_id = plan_id or raw.get("id")
    if (isinstance(credits, bool) or not isinstance(credits, int) or credits <= 0 or not isinstance(price_id, str)
            or not isinstance(label, str) or not isinstance(plan_id, str) or not plan_id):
        return None
    return Plan(plan_id, price_id.strip(), credits, label.strip(), amount.strip())


def parse_billing(raw: str) -> BillingConfig | None:
    """Réglage `billing_config` ; `None` s'il est mal formé (JSON, crédits ≤ 0, identifiant de pack manquant ou en double)."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or not set(data) <= {"subscription", "packs"}:
        return None
    defaults = json.loads(DEFAULT_BILLING)
    subscription = _plan(data.get("subscription", defaults["subscription"]), "subscription")
    packs = [_plan(p) for p in data.get("packs", defaults["packs"])] if isinstance(data.get("packs", []), list) else [None]
    if subscription is None or None in packs or len({p.id for p in packs if p}) != len(packs):
        return None
    return BillingConfig(subscription, tuple(p for p in packs if p))


async def load_billing(app_settings: "AppSettings") -> BillingConfig:
    return parse_billing(await app_settings.get("billing_config")) or parse_billing(DEFAULT_BILLING)  # type: ignore[return-value]
