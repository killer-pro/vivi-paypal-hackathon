"""Accès par forfait : le point d'accroche unique qui décide ce qu'un compte peut utiliser. Les avantages de chaque forfait
(profils, styles, limites de file, de références, de durée et de clips en parallèle) sont le réglage `billing_config`,
pas du code d'écran ; le forfait d'un compte est `User.plan_id` tant que `User.subscription_ends_at` est dans le futur
(écrits par le paiement). Un refus porte un motif lisible qui nomme le forfait qui débloque la fonction."""
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.providers.profiles import get_profile
from app.services.billing import UNLIMITED, Perks, Tier, load_billing

if TYPE_CHECKING:
    from app.app_settings import AppSettings

Feature = Literal["profile", "style"]
Limit = Literal["queue_max", "references_max", "max_duration_s"]


class SubscriptionRequired(HTTPException):
    """403 : la fonction ou la quantité demandée dépasse le forfait du compte ; le détail est le motif affiché tel quel."""

    def __init__(self, reason: str):
        super().__init__(status_code=403, detail=reason)


async def current_tier(app_settings: "AppSettings", user: User) -> Tier | None:
    """Forfait de l'abonné : celui de `plan_id`, ou le premier si `plan_id` est absent ou inconnu (abonnement d'avant
    les forfaits) ; `None` sans abonnement en cours (et pour l'admin, qui n'a pas besoin de forfait)."""
    if user.is_admin or not user.is_subscribed:
        return None
    config = await load_billing(app_settings)
    return config.tier(user.plan_id) or config.tiers[0]


async def perks_for(app_settings: "AppSettings", user: User) -> Perks:
    """Avantages du compte : illimités pour l'admin, ceux de son forfait s'il est abonné, du niveau gratuit sinon."""
    if user.is_admin:
        return UNLIMITED
    tier = await current_tier(app_settings, user)
    return tier.perks if tier else (await load_billing(app_settings)).free


def _feature(perks: Perks, feature: Feature, value: str) -> tuple[bool, str]:
    """(fonction permise par ces avantages ?, ce qu'elle est en clair). `KeyError` : profil inconnu."""
    if feature == "profile":
        profile = get_profile(value)
        return profile.id in perks.profiles, f"le profil {profile.name}"
    return not value or perks.styles, "les styles visuels"


async def reason(app_settings: "AppSettings", user: User, feature: Feature, value: str = "") -> str | None:
    """Motif du refus (« Réservé au forfait Créateur : le profil Maximum ») si le compte ne peut pas utiliser la fonction,
    `None` sinon. Un profil inconnu n'est pas refusé ici (provider cloud sans profil, ou refusé ailleurs)."""
    try:
        allowed, what = _feature(await perks_for(app_settings, user), feature, value)
    except KeyError:
        return None
    if allowed:
        return None
    unlocking = next((t for t in (await load_billing(app_settings)).tiers if _feature(t.perks, feature, value)[0]), None)
    return f"Réservé au forfait {unlocking.name} : {what}" if unlocking else f"Indisponible : {what}"


def _amount(perk: Limit, n: int) -> str:
    if perk == "max_duration_s":
        return f"{n} s"
    plural = "s" if n > 1 else ""
    return f"{n} demande{plural} en file" if perk == "queue_max" else f"{n} image{plural} de référence"


async def limit_reason(app_settings: "AppSettings", user: User, perk: Limit, wanted: int) -> str | None:
    """Motif du refus si `wanted` dépasse la limite `perk` du compte (« Limite de votre forfait : 30 s (forfait Starter :
    60 s) », la parenthèse nommant le premier forfait qui suffit), `None` sinon."""
    allowed = getattr(await perks_for(app_settings, user), perk)
    if wanted <= allowed:
        return None
    text = f"Limite de votre forfait : {_amount(perk, allowed)}"
    enough = next((t for t in (await load_billing(app_settings)).tiers if getattr(t.perks, perk) >= wanted), None)
    return f"{text} (forfait {enough.name} : {_amount(perk, getattr(enough.perks, perk))})" if enough else text


async def require(app_settings: "AppSettings", user: User, feature: Feature, value: str = "") -> None:
    """Lève `SubscriptionRequired` si le compte ne peut pas utiliser la fonction."""
    if why := await reason(app_settings, user, feature, value):
        raise SubscriptionRequired(why)


async def require_limit(app_settings: "AppSettings", user: User, perk: Limit, wanted: int) -> None:
    """Lève `SubscriptionRequired` si `wanted` dépasse la limite `perk` du compte."""
    if why := await limit_reason(app_settings, user, perk, wanted):
        raise SubscriptionRequired(why)


async def set_subscription_end(session: AsyncSession, user: User, ends_at: datetime | None,
                               plan_id: str | None = None) -> None:
    """Fixe la fin de la période d'abonnement (`None` : plus abonné) et le forfait. Écrit par le script d'essai."""
    user.subscription_ends_at, user.plan_id = ends_at, plan_id
    await session.commit()
