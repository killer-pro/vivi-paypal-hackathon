from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_user
from app.app_settings import AppSettings
from app.db import get_session
from app.models import User
from app.services import access

router = APIRouter(tags=["access"])


@router.get("/access")
async def get_access(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """Ce que l'abonnement débloque pour le compte connecté : fonctions encore verrouillées (`locked`, vide si abonné) et
    motif à afficher pour la référence et les styles (`reasons`) ; les profils portent le leur dans `/providers/models`."""
    app_settings = AppSettings(session)
    locked = await access.locked_for(app_settings, user)
    return {
        "subscribed": user.is_subscribed, "subscription_ends_at": user.subscription_ends_at,
        "locked": {"profiles": sorted(locked.profiles), "reference": locked.reference, "styles": sorted(locked.styles)},
        "reasons": {"reference": await access.reason(app_settings, user, "reference"),
                    "style": await access.reason(app_settings, user, "style", "anime" if locked.styles else "")},
    }
