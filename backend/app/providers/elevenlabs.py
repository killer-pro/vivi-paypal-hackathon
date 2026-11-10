import re

import httpx

from app.providers.base import (
    GenerationResult,
    ProviderError,
    ensure_non_empty,
    key_is_valid,
    missing_key,
    raise_for_provider,
    require_key,
)

PRICE_PER_CHAR = 0.00018
MODEL_ID = "eleven_multilingual_v2"
TAGGED_MODEL_ID = "eleven_v3"  # seul modèle qui joue les balises d'émotion ([excited], [laughs]…) au lieu de les lire
AUDIO_TAG = re.compile(r"\[[^\[\]\n]{1,40}\]")
KEY_MISSING = missing_key("elevenlabs", "ElevenLabs")


def model_for(text: str) -> str:
    return TAGGED_MODEL_ID if AUDIO_TAG.search(text) else MODEL_ID


def spoken(text: str) -> str:
    """Le texte sans ses balises d'émotion : ce qui s'entend, donc ce qui se sous-titre."""
    return re.sub(r"\s+", " ", AUDIO_TAG.sub(" ", text)).strip()


class ElevenLabsVoice:
    name = "elevenlabs"

    def __init__(self, api_key: str, client: httpx.AsyncClient):
        self._key = api_key
        self._c = client

    async def synthesize(self, text, *, voice_id):
        require_key(self._key, KEY_MISSING)
        model = model_for(text)
        try:
            r = await self._c.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": self._key}, json={"text": text, "model_id": model},
            )
        except httpx.TransportError as e:
            raise ProviderError(f"elevenlabs: réseau ({e})", retryable=True) from e
        raise_for_provider(r, "elevenlabs")
        return GenerationResult(ensure_non_empty(r.content, "voix"), "audio/mpeg", len(text) * PRICE_PER_CHAR, model)

    async def voices(self) -> list[dict[str, str]]:
        """Voix disponibles sur le compte (les siennes et celles de la bibliothèque qu'il a ajoutées)."""
        require_key(self._key, KEY_MISSING)
        try:
            r = await self._c.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": self._key})
        except httpx.TransportError as e:
            raise ProviderError(f"elevenlabs: réseau ({e})", retryable=True) from e
        raise_for_provider(r, "elevenlabs")
        return [{"id": v["voice_id"], "name": v["name"]} for v in r.json().get("voices", [])]

    async def health(self) -> bool:
        return await key_is_valid(self._c, self._key, "https://api.elevenlabs.io/v1/user", {"xi-api-key": self._key})
