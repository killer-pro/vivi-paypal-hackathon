import httpx

from app.app_settings import IMAGE_PROVIDERS, LLM_PROVIDERS, AppSettings
from app.config import settings
from app.providers.base import ImageProvider, LLMProvider, ProviderError, VideoProvider, VoiceProvider
from app.providers.claude import ClaudeLLM
from app.providers.comfyui import ComfyUIProvider
from app.providers.elevenlabs import ElevenLabsVoice
from app.providers.fakes import FakeImage, FakeLLM, FakeVideo, FakeVoice
from app.providers.fal import IMAGE_MODELS, FalProvider
from app.providers.gemini import GeminiImage, GeminiLLM, image_models
from app.services import langfuse


class ProviderRegistry:
    """Providers configurés par les réglages ; `async with` ferme le client HTTP partagé."""

    VIDEO_PROVIDER_NAMES = ["fal", "comfyui"]
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
        return ClaudeLLM(await self._s.get("anthropic_api_key"))

    async def image(self, name: str) -> ImageProvider:
        """Provider de l'image de référence (`IMAGE_PROVIDER_NAMES`) ; `KeyError` s'il est inconnu."""
        if name not in self.IMAGE_PROVIDER_NAMES:
            raise KeyError(name)
        gemini_model = await self._s.get("gemini_image_model")
        if settings.fake_providers:
            return FakeImage(models=image_models(gemini_model) if name == "gemini" else list(IMAGE_MODELS))
        if name == "gemini":
            return GeminiImage(await self._s.get("gemini_api_key"), self._client, gemini_model)
        return FalProvider(await self._s.get("fal_key"), self._client)

    async def video(self, name: str) -> VideoProvider:
        if name not in self.VIDEO_PROVIDER_NAMES:
            raise KeyError(name)
        if settings.fake_providers:
            return FakeVideo(models=(FalProvider if name == "fal" else ComfyUIProvider).models)
        if name == "fal":
            return FalProvider(await self._s.get("fal_key"), self._client)
        return ComfyUIProvider(await self._s.get("comfyui_url"), self._client)

    async def voice(self) -> VoiceProvider:
        if settings.fake_providers:
            return FakeVoice()
        return ElevenLabsVoice(await self._s.get("elevenlabs_api_key"), self._client)

    async def health_report(self) -> dict[str, bool]:
        return {
            **{name: await (await self._llm(name)).health() for name in LLM_PROVIDERS},
            "fal": await (await self.video("fal")).health(),
            "comfyui": await (await self.video("comfyui")).health(),
            "elevenlabs": await (await self.voice()).health(),
            "langfuse": settings.fake_providers or await langfuse.healthy(await langfuse.load_config(self._s),
                                                                          self._client),
        }
