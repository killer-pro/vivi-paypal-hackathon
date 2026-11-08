"""Choix du provider et du modèle d'un lancement : paramètres de l'étape, sinon réglages."""
from app.app_settings import AppSettings
from app.providers.fal import IMAGE_MODELS
from app.providers.registry import COMFY_PROVIDERS, image_model_ids


async def reference_choice(params: dict, app_settings: AppSettings) -> tuple[str, str]:
    """(provider, modèle) de l'image de référence : paramètres de l'étape, sinon réglage `image_provider` et son modèle
    par défaut (`gemini_image_model`, ou Flux pour fal). Un ancien paramètre `model: flux` sans provider vaut fal."""
    provider = params.get("provider") or ("fal" if params.get("model") in IMAGE_MODELS
                                          else await app_settings.get("image_provider"))
    return provider, params.get("model") or image_model_ids(provider, await app_settings.get("gemini_image_model"))[0]


async def clip_provider_name(params: dict, app_settings: AppSettings) -> str:
    """Provider vidéo d'un lancement de l'étape clips : choix ponctuel/paramètres, sinon réglage par défaut."""
    return params.get("provider") or await app_settings.get("default_video_provider")


async def start_image_provider(params: dict, app_settings: AppSettings, video_provider: str) -> str:
    """Générateur de l'image de départ des scènes qui ont des images de référence : choix du lancement, sinon réglage
    `start_image_provider` (`comfyui` = Flux Kontext, sur le provider des clips, `gemini`). Seuls ComfyUI et Comfy Cloud
    ont cette étape : fal anime sa propre image."""
    choice = params.get("start_image") or await app_settings.get("start_image_provider")
    return choice if video_provider in COMFY_PROVIDERS else "comfyui"


async def clip_model(params: dict, app_settings: AppSettings) -> str:
    """Modèle vidéo (profil ComfyUI ou modèle fal) d'un lancement de l'étape clips, résolu comme le provider."""
    return params.get("model") or await app_settings.get("default_video_model")
