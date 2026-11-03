from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import ADMIN_ONLY, current_user
from app.api.projects import get_registry
from app.app_settings import EDITABLE_KEYS, EDITOR_KEYS, MASK, AppSettings
from app.db import get_session
from app.models import User
from app.providers.base import ProviderError
from app.providers.gemini import PRICES as GEMINI_PRICES
from app.providers.registry import ProviderRegistry
from app.services import access
from app.services.video_models import image_cards, video_cards

router = APIRouter(tags=["providers"])  # réglages et voix du compte : admin ; santé et modèles : tout compte


@router.get("/settings", dependencies=ADMIN_ONLY)
async def get_settings(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    return await AppSettings(session).all_masked()


@router.get("/settings/editor")
async def get_editor_settings(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """Réglages par défaut dont l'éditeur a besoin, pour tout compte connecté (`/settings` est réservé à l'admin)."""
    app_settings = AppSettings(session)
    return {key: await app_settings.get(key) for key in sorted(EDITOR_KEYS)}


@router.put("/settings", dependencies=ADMIN_ONLY)
async def put_settings(body: dict[str, str], session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    unknown = sorted(set(body) - EDITABLE_KEYS)
    if unknown:
        raise HTTPException(400, f"Clés non modifiables : {', '.join(unknown)}")
    app_settings = AppSettings(session)
    # valeur masquée renvoyée telle quelle : on garde le secret
    try:
        await app_settings.set_many({k: v for k, v in body.items() if not v.startswith(MASK)})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return await app_settings.all_masked()


@router.get("/providers/health")
async def providers_health(registry: ProviderRegistry = Depends(get_registry)) -> dict[str, bool]:
    return await registry.health_report()


@router.get("/providers/voices", dependencies=ADMIN_ONLY)
async def providers_voices(registry: ProviderRegistry = Depends(get_registry)) -> list[dict[str, str]]:
    """Voix du compte du fournisseur de voix, à ajouter au catalogue des réglages."""
    try:
        return await (await registry.voice()).voices()
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e


@router.get("/providers/models")
async def providers_models(registry: ProviderRegistry = Depends(get_registry), user: User = Depends(current_user),
                           session: AsyncSession = Depends(get_session)) -> dict:
    """Cartes des modèles. `locked` / `locked_reason` : profil réservé à l'abonnement pour ce compte, distinct de la
    disponibilité technique (`available`) ; l'interface l'affiche avec son motif au lieu de le masquer."""
    app_settings = AppSettings(session)
    video = await video_cards(registry)
    for card in video:
        card["locked_reason"] = (await access.reason(app_settings, user, "profile", card["id"])
                                 if card["provider"] == "comfyui" else None)
        card["locked"] = card["locked_reason"] is not None
    return {"video": video, "image": await image_cards(registry), "llm": {"gemini": list(GEMINI_PRICES)}}
