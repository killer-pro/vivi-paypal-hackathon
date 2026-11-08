"""Cartes des modèles vidéo et d'image (`GET /providers/models`) et contrôle du modèle d'un lancement des étapes clips et
reference, partagé par l'API et l'autopilot (`launch_step`)."""
from fastapi import HTTPException

from app.providers.base import Availability
from app.providers.profiles import DEFAULT_PROFILE, LEGACY_NAMES, PROFILES
from app.providers.registry import ProviderRegistry

PROFILES_BY_ID = {p.id: p for p in PROFILES}
CARD_DURATION_S = 3  # coût affiché d'un modèle cloud : celui d'un clip de 3 s


class ModelRefused(HTTPException):
    """Modèle vidéo ou d'image inconnu (400) ou indisponible (409) : l'autopilot affiche la raison sur l'étape."""


async def video_cards(registry: ProviderRegistry, providers: list[str] | None = None) -> list[dict]:
    """Cartes des modèles vidéo (de `providers`, par défaut tous), dans l'ordre des providers puis de leurs modèles :
    profil (notes vitesse/qualité), avec sa durée par clip en local ou son coût d'un clip sur Comfy Cloud, ou modèle
    cloud (coût d'un clip), avec sa disponibilité ; `recommended` : le profil local par défaut (`DEFAULT_PROFILE`). Ne
    lève pas si un service est injoignable (ses cartes sont grisées)."""
    cards = []
    for name in providers or registry.VIDEO_PROVIDER_NAMES:
        video = await registry.video(name)
        availability = await video.availability()
        for model in video.models:
            profile = PROFILES_BY_ID.get(model)
            local = profile if name == "comfyui" else None  # profil exécuté chez nous : chiffré en durée, pas en dollars
            state = availability[model]
            cards.append({
                "provider": name, "id": model,
                "name": profile.name if profile else model,
                "description": profile.description if profile else "",
                "speed": profile and profile.speed, "quality": profile and profile.quality,
                "minutes_per_clip": local and local.minutes_per_clip,
                "cost_usd_per_clip": None if local else video.estimate_cost(model, CARD_DURATION_S),
                "available": state.available, "reason": state.reason,
                "recommended": local is not None and local.id == DEFAULT_PROFILE,
            })
    return cards


async def image_cards(registry: ProviderRegistry) -> list[dict]:
    """Modèles d'image (image de référence) de chaque provider, dans l'ordre de `IMAGE_PROVIDER_NAMES`, avec leur
    disponibilité (clé du provider), comme les cartes vidéo ; ne lève pas."""
    cards = []
    for name in registry.IMAGE_PROVIDER_NAMES:
        availability = await (await registry.image(name)).image_availability()
        cards += [{"provider": name, "id": model, "name": model, "available": state.available, "reason": state.reason}
                  for model, state in availability.items()]
    return cards


def ensure_usable(availability: dict[str, Availability], model: str, unknown: str) -> None:
    """400 (`unknown`) si `model` n'est pas au catalogue, 409 (raison de sa carte) s'il est indisponible."""
    state = availability.get(model)
    if state is None:
        raise ModelRefused(400, unknown)
    if not state.available:
        raise ModelRefused(409, state.reason)


async def ensure_image_model_usable(registry: ProviderRegistry, provider: str, model: str) -> None:
    """Image de référence : 400 si le provider ou le modèle n'existe pas, 409 s'il est indisponible (clé manquante)."""
    if provider not in registry.IMAGE_PROVIDER_NAMES:
        raise ModelRefused(400, f"Provider d'image inconnu : {provider}")
    image = await registry.image(provider)
    ensure_usable(await image.image_availability(), model, f"Modèle d'image inconnu pour {provider} : {model}")


async def ensure_clip_model_usable(registry: ProviderRegistry, provider: str, model: str, *,
                                   has_reference: bool = False) -> None:
    """400 si le provider ou le modèle n'existe pas, 409 (raison de sa carte) s'il est indisponible pour de bon : clé
    manquante, ComfyUI injoignable (connexion refusée, URL invalide), fichier absent. Un ComfyUI qui ne répond pas dans
    le délai (occupé) reste disponible, avec un avertissement : le job attend son tour. L'ancien nom `workflow` vaut le profil Maximum."""
    if provider not in ProviderRegistry.VIDEO_PROVIDER_NAMES:
        raise ModelRefused(400, f"Provider vidéo inconnu : {provider}")
    video = await registry.video(provider)
    model = LEGACY_NAMES.get(model, model)
    ensure_usable(await video.availability(), model, f"Modèle vidéo inconnu pour {provider} : {model}")
    if has_reference:  # ComfyUI enchaîne alors Kontext puis Wan I2V : d'autres fichiers de modèle à vérifier
        state = await video.reference_availability(model)
        if not state.available:
            raise ModelRefused(409, f"Image de référence présente : {state.reason}")
