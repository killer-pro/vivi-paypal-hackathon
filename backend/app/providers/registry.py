import httpx

from app.app_settings import IMAGE_PROVIDERS, LLM_PROVIDERS, AppSettings
from app.config import settings
from app.providers.base import ImageProvider, LLMProvider, ProviderError, VideoProvider, VoiceProvider
from app.providers.claude import ClaudeLLM
from app.providers.comfycloud import ComfyCloudImage, ComfyCloudProvider, cloud_clip_usd, cloud_talk_usd
from app.providers.comfyui import ComfyUIImage, ComfyUIProvider
from app.providers.elevenlabs import ElevenLabsVoice
from app.providers.fakes import FakeImage, FakeLLM, FakeVideo, FakeVoice
from app.providers.fal import IMAGE_MODELS, FalProvider
from app.providers.gemini import GeminiImage, GeminiLLM, image_models
from app.providers.groq import GroqLLM
from app.providers.ollama import OllamaLLM
from app.providers.profiles import TALK_MODELS
from app.services import langfuse

# Providers qui exécutent nos graphes ComfyUI : mêmes profils Wan 2.2, image de départ par Flux Kontext, image de
# référence par Flux dev.
COMFY_PROVIDERS = ("comfyui", "comfycloud")


def image_model_ids(provider: str, gemini_model: str) -> list[str]:
    """Modèles d'un provider d'image, le modèle par défaut en premier (le réglage `gemini_image_model` pour Gemini)."""
    if provider == "gemini":
        return image_models(gemini_model)
    return [ComfyUIImage.MODEL] if provider in COMFY_PROVIDERS else list(IMAGE_MODELS)


class ProviderRegistry:
    """Providers configurés par les réglages ; `async with` ferme le client HTTP partagé."""

    VIDEO_PROVIDER_NAMES = ["fal", "comfyui", "comfycloud"]
    IMAGE_PROVIDER_NAMES = list(IMAGE_PROVIDERS)

    def __init__(self, app_settings: AppSettings):
        self._s = app_settings
        self._client = httpx.AsyncClient(timeout=120)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ProviderRegistry":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def llm(self) -> LLMProvider:
        """Provider de texte choisi par le réglage `llm_provider` (scripts, idées, métadonnées)."""
        return await self._llm(await self._s.get("llm_provider"))

    async def _llm(self, name: str) -> LLMProvider:
        if name not in LLM_PROVIDERS:
            raise ProviderError(f"llm_provider inconnu : « {name} » (attendu : {', '.join(LLM_PROVIDERS)})")
        if settings.fake_providers:
            return FakeLLM()
        if name == "gemini":
            return GeminiLLM(await self._s.get("gemini_api_key"), self._client, await self._s.get("gemini_model"))
        if name == "groq":
            return GroqLLM(await self._s.get("groq_api_key"), self._client, await self._s.get("groq_model"))
        if name == "ollama":
            return OllamaLLM(await self._s.get("ollama_url"), self._client, await self._s.get("ollama_model"))
        return ClaudeLLM(await self._s.get("anthropic_api_key"))

    async def image(self, name: str) -> ImageProvider:
        """Provider de l'image de référence (`IMAGE_PROVIDER_NAMES`) ; `KeyError` s'il est inconnu."""
        if name not in self.IMAGE_PROVIDER_NAMES:
            raise KeyError(name)
        gemini_model = await self._s.get("gemini_image_model")
        if settings.fake_providers:
            return FakeImage(models=image_model_ids(name, gemini_model))
        if name == "gemini":
            return GeminiImage(await self._s.get("gemini_api_key"), self._client, gemini_model)
        if name == "comfyui":
            return ComfyUIImage(ComfyUIProvider(await self._s.get("comfyui_url"), self._client))
        if name == "comfycloud":
            return ComfyCloudImage(ComfyCloudProvider(await self._s.get("comfy_cloud_api_key"), self._client))
        return FalProvider(await self._s.get("fal_key"), self._client)

    async def video(self, name: str) -> VideoProvider:
        if name not in self.VIDEO_PROVIDER_NAMES:
            raise KeyError(name)
        if settings.fake_providers:
            # même coût annoncé que le vrai provider : le devis du mode factice ressemble à celui du serveur
            return FakeVideo(models=(FalProvider if name == "fal" else ComfyUIProvider).models,
                             cost=cloud_clip_usd if name == "comfycloud" else None)
        if name == "fal":
            return FalProvider(await self._s.get("fal_key"), self._client)
        if name == "comfycloud":
            return ComfyCloudProvider(await self._s.get("comfy_cloud_api_key"), self._client)
        return ComfyUIProvider(await self._s.get("comfyui_url"), self._client)

    async def talker(self) -> ComfyCloudProvider | FakeVideo:
        """Générateur des avatars parlants (lip-sync) : Comfy Cloud seulement (modèles absents du ComfyUI local)."""
        if settings.fake_providers:
            return FakeVideo(models=list(TALK_MODELS), cost=cloud_talk_usd)
        return ComfyCloudProvider(await self._s.get("comfy_cloud_api_key"), self._client)

    async def voice(self) -> VoiceProvider:
        if settings.fake_providers:
            return FakeVoice()
        return ElevenLabsVoice(await self._s.get("elevenlabs_api_key"), self._client)

    async def health_report(self) -> dict[str, bool]:
        return {
            **{name: await (await self._llm(name)).health() for name in LLM_PROVIDERS},
            "fal": await (await self.video("fal")).health(),
            "comfyui": await (await self.video("comfyui")).health(),
            "comfycloud": await (await self.video("comfycloud")).health(),
            "elevenlabs": await (await self.voice()).health(),
            "langfuse": settings.fake_providers or await langfuse.healthy(await langfuse.load_config(self._s),
                                                                          self._client),
        }
