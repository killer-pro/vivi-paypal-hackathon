from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_user
from app.app_settings import AppSettings
from app.db import get_session
from app.models import User
from app.services import access
from app.services.billing import ALL_PROFILES
from app.services.styles import STYLES

router = APIRouter(tags=["access"])


@router.get("/access")
async def get_access(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """Forfait du compte connecté (`tier`, `null` sans abonnement), ses avantages (`perks`), ce qu'il laisse verrouillé
    (`locked`) et le motif à afficher pour les styles (`reasons`) ; les profils portent le leur dans `/providers/models`."""
    app_settings = AppSettings(session)
    perks, tier = await access.perks_for(app_settings, user), await access.current_tier(app_settings, user)
    return {
        "subscribed": user.is_subscribed, "subscription_ends_at": user.subscription_ends_at,
        "tier": {"id": tier.id, "name": tier.name} if tier else None, "perks": perks.to_json(),
        "locked": {"profiles": sorted(set(ALL_PROFILES) - perks.profiles), "styles": [] if perks.styles else sorted(STYLES)},
        "reasons": {"style": await access.reason(app_settings, user, "style", next(iter(STYLES)))},
    }
