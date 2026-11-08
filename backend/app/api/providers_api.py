from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import ADMIN_ONLY, current_user
from app.api.projects import get_registry
from app.app_settings import EDITABLE_KEYS, EDITOR_KEYS, MASK, AppSettings
from app.db import get_session
from app.models import User
from app.providers.base import ProviderError
from app.providers.gemini import PRICES as GEMINI_PRICES
from app.providers.groq import PRICES as GROQ_PRICES
from app.providers.registry import COMFY_PROVIDERS, ProviderRegistry
from app.services import access
from app.services.pricing import Pricing, load_pricing
from app.services.video_models import CARD_DURATION_S, image_cards, video_cards

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


UNAVAILABLE = "Indisponible pour le moment"


def _client_price(card: dict, pricing: Pricing | None) -> None:
    """Prix d'un clip de la carte : en crédits pour un client (ni dollars ni durée de calcul), inchangé pour l'admin
    (`pricing` absent). Le même calcul que le devis du lancement (forfait local de ComfyUI, coût cloud sinon)."""
    if pricing is None:
        card["credits_per_clip"] = None
        return
    local = card["provider"] == "comfyui"
    cost = pricing.local_clip_cost_usd(card["id"], CARD_DURATION_S) if local else card["cost_usd_per_clip"]
    card.update(credits_per_clip=None if cost is None else pricing.clip_credits(cost), cost_usd_per_clip=None,
                minutes_per_clip=None)


@router.get("/providers/models")
async def providers_models(registry: ProviderRegistry = Depends(get_registry), user: User = Depends(current_user),
                           session: AsyncSession = Depends(get_session)) -> dict:
    """Cartes des modèles. `locked` / `locked_reason` : profil réservé à un forfait pour ce compte, distinct de la
    disponibilité technique (`available`) ; l'interface l'affiche avec son motif au lieu de le masquer. Un client voit
    le prix d'un clip en crédits (`credits_per_clip`), jamais en dollars ; l'admin garde dollars et durées."""
    app_settings = AppSettings(session)
    video = await video_cards(registry)
    pricing = None if user.is_admin else await load_pricing(app_settings)
    for card in video:
        _client_price(card, pricing)
        card["locked_reason"] = (await access.reason(app_settings, user, "profile", card["id"])
                                 if card["provider"] in COMFY_PROVIDERS else None)
        card["locked"] = card["locked_reason"] is not None
    image = await image_cards(registry)
    if not user.is_admin:  # le motif technique (« clé manquante, à saisir dans Réglages ») ne parle qu'à l'admin
        for card in (*video, *image):
            if not card["available"]:
                card["reason"] = UNAVAILABLE
    return {"video": video, "image": image, "llm": {"gemini": list(GEMINI_PRICES), "groq": list(GROQ_PRICES)}}
