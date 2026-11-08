"""Offre payante : forfaits mensuels (crédits et avantages), niveau gratuit et recharges (réglage `billing_config`). Les
prix en argent vivent côté Stripe et PayPal ; ici, les identifiants de prix, les crédits vendus, le libellé affiché et
les avantages de chaque forfait (`docs/abonnement.md`)."""
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.providers.profiles import PROFILES

if TYPE_CHECKING:
    from app.app_settings import AppSettings

ALL_PROFILES = [p.id for p in PROFILES]


def _perks(queue: int, references: int, profiles: list[str], duration: int, parallel: int, styles: bool) -> dict:
    return {"queue_max": queue, "references_max": references, "profiles": profiles, "max_duration_s": duration,
            "parallel_clips": parallel, "styles": styles}


def _tier(tier_id: str, name: str, amount: str, credits: int, perks: dict) -> dict:
    return {"id": tier_id, "name": name, "label": f"{amount.removesuffix('.00')} $ par mois", "credits": credits,
            "price_id": "", "paypal_amount": amount, "paypal_plan_id": "", "perks": perks}


# Valeurs de la spec (2026-11-07). Les `price_id` (Stripe) et `paypal_plan_id` sont à renseigner.
DEFAULT_BILLING = json.dumps({
    "tiers": [_tier("starter", "Starter", "9.00", 1200, _perks(2, 4, ["fast", "balanced", "precision"], 60, 1, True)),
              _tier("creator", "Créateur", "19.00", 3000, _perks(4, 8, ALL_PROFILES, 90, 2, True)),
              _tier("pro", "Pro", "49.00", 9000, _perks(8, 16, ALL_PROFILES, 180, 3, True))],
    "free": _perks(1, 2, ["fast", "balanced"], 30, 1, False),
    # crédit plus cher qu'en forfait (1,2 et 1 ¢ contre 0,75 à 0,54 ¢), et sans les avantages
    "packs": [{"id": "pack500", "price_id": "", "credits": 500, "label": "6 $", "paypal_amount": "6.00"},
              {"id": "pack1500", "price_id": "", "credits": 1500, "label": "15 $", "paypal_amount": "15.00"}],
})

PAYPAL_AMOUNT = re.compile(r"[1-9]\d{0,5}\.\d{2}")  # dollars avec deux décimales, exigé par PayPal
PAYPAL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")  # identifiant PayPal (commande, abonnement, plan) : il finit dans une URL
TIER_ID = re.compile(r"[a-z0-9_-]{1,20}")  # identifiant de forfait : tient dans `users.plan_id` (String(20))
PERK_KEYS = {"queue_max", "references_max", "profiles", "max_duration_s", "parallel_clips", "styles"}


@dataclass(frozen=True)
class Perks:
    """Avantages d'un forfait : limites (file par projet, éléments de référence par projet, durée de vidéo, clips
    générés en même temps par compte) et fonctions débloquées (profils de génération, styles visuels)."""
    queue_max: int
    references_max: int
    profiles: frozenset[str]
    max_duration_s: int
    parallel_clips: int
    styles: bool

    def to_json(self) -> dict:
        return {"queue_max": self.queue_max, "references_max": self.references_max, "profiles": sorted(self.profiles),
                "max_duration_s": self.max_duration_s, "parallel_clips": self.parallel_clips, "styles": self.styles}


UNLIMITED = Perks(1000, 1000, frozenset(ALL_PROFILES), 1000, 1000, True)  # compte administrateur


@dataclass(frozen=True)
class Pack:
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
class Tier(Pack):
    """Forfait mensuel : ses crédits sont remis au quota à chaque mois payé."""
    name: str = ""
    paypal_plan_id: str = ""  # plan PayPal (« P-… ») de l'abonnement mensuel ; vide : pas d'abonnement par PayPal
    perks: Perks = field(default=UNLIMITED)

    @property
    def paypal_subscribable(self) -> bool:
        return bool(self.paypal_plan_id)


@dataclass(frozen=True)
class BillingConfig:
    tiers: tuple[Tier, ...]
    free: Perks
    packs: tuple[Pack, ...]

    @property
    def configured(self) -> bool:
        return any(p.purchasable for p in (*self.tiers, *self.packs))

    def tier(self, tier_id: str | None) -> Tier | None:
        return next((t for t in self.tiers if t.id == tier_id), None)

    def tier_by_paypal_plan(self, plan_id: str | None) -> Tier | None:
        return next((t for t in self.tiers if t.paypal_plan_id and t.paypal_plan_id == plan_id), None)

    def pack(self, pack_id: str) -> Pack | None:
        return next((p for p in self.packs if p.id == pack_id), None)


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _parse_perks(raw: Any) -> Perks | None:
    if not isinstance(raw, dict) or set(raw) != PERK_KEYS:
        return None
    profiles = raw["profiles"]
    if (not all(_count(raw[k]) for k in PERK_KEYS - {"profiles", "styles"}) or not isinstance(raw["styles"], bool)
            or not isinstance(profiles, list) or not set(profiles) <= set(ALL_PROFILES)):
        return None
    return Perks(raw["queue_max"], raw["references_max"], frozenset(profiles), raw["max_duration_s"],
                 raw["parallel_clips"], raw["styles"])


def _offer(raw: Any, extra: set[str]) -> dict | None:
    """Champs communs d'un pack ou d'un forfait, nettoyés ; `None` si l'un est mal formé."""
    if not isinstance(raw, dict) or not set(raw) <= {"id", "price_id", "credits", "label", "paypal_amount"} | extra:
        return None
    fields = {k: raw.get(k, "") for k in ("id", "price_id", "label", "paypal_amount", *(extra - {"perks"}))}
    if not all(isinstance(v, str) for v in fields.values()) or not _count(raw.get("credits")):
        return None
    fields = {k: v.strip() for k, v in fields.items()}
    if (not fields["id"] or (fields["paypal_amount"] and not PAYPAL_AMOUNT.fullmatch(fields["paypal_amount"]))
            or (fields.get("paypal_plan_id") and not PAYPAL_ID.fullmatch(fields["paypal_plan_id"]))):
        return None
    return {**fields, "credits": raw["credits"]}


def _pack(raw: Any) -> Pack | None:
    fields = _offer(raw, set())
    return Pack(**fields) if fields else None


def _parse_tier(raw: Any) -> Tier | None:
    fields = _offer(raw, {"name", "paypal_plan_id", "perks"})
    perks = _parse_perks(raw.get("perks")) if fields else None
    if fields is None or perks is None or not TIER_ID.fullmatch(fields["id"]):
        return None
    return Tier(**{**fields, "name": fields["name"] or fields["id"]}, perks=perks)


def _unique(items: list[Any]) -> bool:
    return None not in items and len({i.id for i in items}) == len(items)


def parse_billing(raw: str) -> BillingConfig | None:
    """Réglage `billing_config` ; `None` s'il est mal formé (JSON, ancien format à abonnement unique, crédits ≤ 0,
    avantage manquant ou inconnu, aucun forfait, identifiant manquant ou en double)."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or not set(data) <= {"tiers", "free", "packs"}:
        return None
    defaults = json.loads(DEFAULT_BILLING)
    raw_tiers, raw_packs = data.get("tiers", defaults["tiers"]), data.get("packs", defaults["packs"])
    if not isinstance(raw_tiers, list) or not raw_tiers or not isinstance(raw_packs, list):
        return None
    tiers, packs = [_parse_tier(t) for t in raw_tiers], [_pack(p) for p in raw_packs]
    free = _parse_perks(data.get("free", defaults["free"]))
    if free is None or not _unique(tiers) or not _unique(packs):
        return None
    return BillingConfig(tuple(tiers), free, tuple(packs))  # type: ignore[arg-type]


async def load_billing(app_settings: "AppSettings") -> BillingConfig:
    return parse_billing(await app_settings.get("billing_config")) or parse_billing(DEFAULT_BILLING)  # type: ignore[return-value]
