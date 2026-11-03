"""Accès par abonnement : le point d'accroche unique qui décide si un compte peut utiliser une fonction réservée (profil
de génération, image de référence, style). La liste des fonctions réservées est le réglage `subscription_locked`, pas
du code d'écran ; l'état d'abonnement est `User.subscription_ends_at` (écrit par le paiement, lot 4)."""
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.providers.profiles import PROFILES, get_profile
from app.services.styles import STYLES

if TYPE_CHECKING:
    from app.app_settings import AppSettings

Feature = Literal["profile", "reference", "style"]
DEFAULT_LOCKED = json.dumps({"profiles": ["precision", "max"], "reference": True, "styles": list(STYLES)})
REASON_PREFIX = "Réservé à l'abonnement"


class SubscriptionRequired(HTTPException):
    """403 : la fonction demandée est réservée à l'abonnement ; le détail est le motif affiché tel quel."""

    def __init__(self, what: str):
        super().__init__(status_code=403, detail=f"{REASON_PREFIX} : {what}")


@dataclass(frozen=True)
class Locked:
    profiles: frozenset[str]
    reference: bool
    styles: frozenset[str]


def parse_locked(raw: str) -> Locked | None:
    """Réglage `subscription_locked` ; `None` s'il est mal formé (JSON, clé ou profil/style inconnu, mauvais type)."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or not set(data) <= {"profiles", "reference", "styles"}:
        return None
    profiles, styles = data.get("profiles", []), data.get("styles", [])
    if (not isinstance(profiles, list) or not set(profiles) <= {p.id for p in PROFILES}
            or not isinstance(styles, list) or not set(styles) <= set(STYLES)
            or not isinstance(data.get("reference", False), bool)):
        return None
    return Locked(frozenset(profiles), data.get("reference", False), frozenset(styles))


async def load_locked(app_settings: "AppSettings") -> Locked:
    return parse_locked(await app_settings.get("subscription_locked")) or Locked(frozenset(), False, frozenset())


async def locked_for(app_settings: "AppSettings", user: User) -> Locked:
    """Ce qui est verrouillé pour ce compte : rien s'il est abonné (ou admin)."""
    return Locked(frozenset(), False, frozenset()) if user.is_subscribed else await load_locked(app_settings)


def _reason(locked: Locked, feature: Feature, value: str) -> str | None:
    if feature == "profile":
        profile = get_profile(value)  # KeyError : profil inconnu, refusé ailleurs (provider cloud : pas de profil)
        return f"le profil {profile.name}" if profile.id in locked.profiles else None
    if feature == "reference":
        return "les images de référence" if locked.reference else None
    return "les styles visuels" if value and value in locked.styles else None


async def reason(app_settings: "AppSettings", user: User, feature: Feature, value: str = "") -> str | None:
    """Motif du refus (« Réservé à l'abonnement : … ») si le compte ne peut pas utiliser la fonction, `None` sinon."""
    if user.is_subscribed:
        return None
    try:
        what = _reason(await load_locked(app_settings), feature, value)
    except KeyError:
        return None
    return f"{REASON_PREFIX} : {what}" if what else None


async def require(app_settings: "AppSettings", user: User, feature: Feature, value: str = "") -> None:
    """Lève `SubscriptionRequired` si le compte ne peut pas utiliser la fonction."""
    what = await reason(app_settings, user, feature, value)
    if what:
        raise SubscriptionRequired(what.removeprefix(f"{REASON_PREFIX} : "))


async def set_subscription_end(session: AsyncSession, user: User, ends_at: datetime | None) -> None:
    """Fixe la fin de la période d'abonnement (`None` : plus abonné). Écrit par le paiement (lot 4) et le script d'essai."""
    user.subscription_ends_at = ends_at
    await session.commit()
