import base64
import binascii
import logging
from collections.abc import Sequence
from datetime import date
from urllib.parse import quote

import httpx

from app.providers.base import (
    Availability,
    GenerationResult,
    ProviderError,
    TextResult,
    ensure_non_empty,
    key_is_valid,
    missing_key,
    raise_for_provider,
    require_key,
)

logger = logging.getLogger(__name__)

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"  # liste gratuite : sert au test de clé
DEFAULT_MODEL = "gemini-3.5-flash-lite"
KEY_MISSING = missing_key("gemini", "Gemini")
# USD par million de tokens (entrée, sortie), tarif payant standard relevé le 2026-10-17, ajustable.
# La sortie inclut les tokens de réflexion. Google annonce un doublement pour gemini-4-argon au 2026-12-01
# (4,00 / 20,00) et pour les deux Flash au 2027-01-01 (1,50 / 7,50) : mettre la table et PRICES_VALID_UNTIL à jour.
PRICES = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-4-argon": (2.00, 10.00),
}
# Images (image de référence), USD par million de tokens (entrée, sortie image), tarif payant relevé le 2026-10-22 sur
# ai.google.dev/gemini-api/docs/pricing (page mise à jour le 2026-10-19) : une image 1K ≈ 1120 tokens de sortie, soit
# ≈ 0,067 $ (3.1-flash-image), 0,034 $ (3.1-flash-lite-image), 0,134 $ (3-pro-image). Modèle absent : le plus cher.
IMAGE_PRICES = {
    "gemini-3.1-flash-image": (0.50, 60.00),
    "gemini-3.1-flash-lite-image": (0.25, 30.00),
    "gemini-3-pro-image": (2.00, 120.00),
}
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image"  # « Nano Banana 2 », vérifié le 2026-10-22 (JPEG 768×1376 en 9:16)
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAGIC_TYPES = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"RIFF": "image/webp"}
PRICES_VALID_UNTIL = date(2026, 11, 30)  # veille du premier changement de prix annoncé
FALLBACK_PRICE = max(PRICES.values())  # modèle inconnu : estimation prudente (le plus cher de la table)
# Réflexion minimale documentée par modèle : les étapes ne demandent que de l'écriture (texte / JSON), et
# `maxOutputTokens` est partagé avec la réflexion. Modèle absent = champ non envoyé (niveau non documenté → 400).
THINKING_LEVELS = {
    "gemini-3.5-flash-lite": "minimal",
    "gemini-3.6-flash": "minimal",
    "gemini-3.8-flash": "low",
    "gemini-4-argon": "low",
}
_stale_warned = False


def sniff_image_type(data: bytes, announced: str) -> str:
    """Type réel d'une image d'après ses premiers octets : Gemini annonce parfois image/png pour un JPEG."""
    return next((mime for magic, mime in MAGIC_TYPES.items() if data.startswith(magic)), announced)


def warn_if_prices_stale(today: date | None = None) -> None:
    """Avertit (une fois par processus) quand la table de prix a dépassé sa date de validité."""
    global _stale_warned
    if not _stale_warned and (today or date.today()) > PRICES_VALID_UNTIL:
        _stale_warned = True
        logger.warning("gemini: table PRICES périmée depuis le %s, coûts sous-estimés : la mettre à jour",
                       PRICES_VALID_UNTIL.isoformat())


def token_counts(usage: dict) -> tuple[int, int]:
    """(entrée, sortie) d'une réponse selon `usageMetadata`. Compteurs absents ou `null` comptés 0 ; sans
    `candidatesTokenCount`, sortie = total - entrée (le total inclut la réflexion)."""
    tokens_in = usage.get("promptTokenCount") or 0
    if usage.get("candidatesTokenCount") is not None:
        return tokens_in, usage["candidatesTokenCount"] + (usage.get("thoughtsTokenCount") or 0)
    return tokens_in, max((usage.get("totalTokenCount") or 0) - tokens_in, 0)


def tokens_cost(usage: dict, prices: tuple[float, float]) -> float:
    """Coût USD d'une réponse selon `usageMetadata` (voir `token_counts`)."""
    tokens_in, tokens_out = token_counts(usage)
    price_in, price_out = prices
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


IMAGE_OUTPUT_TOKENS = 1290  # jetons de sortie d'une image (≈ 1 Mpx), base de l'estimation avant l'appel


def estimate_image_cost(model: str) -> float:
    """Coût estimé d'une image avant de la générer (le coût réel vient de `usageMetadata`)."""
    return IMAGE_PRICES.get(model, max(IMAGE_PRICES.values()))[1] * IMAGE_OUTPUT_TOKENS / 1_000_000


def image_models(configured: str) -> list[str]:
    """Modèles d'image proposés : celui du réglage `gemini_image_model` d'abord, puis ceux de la table de prix."""
    return list(dict.fromkeys([configured, *IMAGE_PRICES]))


class _Gemini:
    """API REST `generateContent`. Pas de retry interne (tracked_call s'en charge) ; la clé passe uniquement par
    l'en-tête `x-goog-api-key`, jamais dans l'URL (qui peut finir dans les logs) ; sans clé, aucune requête."""

    name = "gemini"

    def __init__(self, api_key: str, client: httpx.AsyncClient):
        self._key = api_key
        self._c = client

    async def _generate(self, model: str, payload: dict) -> dict:
        require_key(self._key, KEY_MISSING)
        try:
            r = await self._c.post(API_URL.format(model=quote(model, safe="")), json=payload,
                                   headers={"x-goog-api-key": self._key})
        except httpx.TransportError as e:
            raise ProviderError(f"gemini: réseau ({type(e).__name__})", retryable=True) from e
        raise_for_provider(r, "gemini")
        return r.json()

    async def health(self) -> bool:
        return await key_is_valid(self._c, self._key, MODELS_URL, {"x-goog-api-key": self._key})


class GeminiLLM(_Gemini):
    def __init__(self, api_key: str, client: httpx.AsyncClient, model: str = DEFAULT_MODEL):
        super().__init__(api_key, client)
        self.model = model or DEFAULT_MODEL

    async def complete(self, system, prompt, *, max_tokens=4000, json_schema=None):
        config: dict = {"maxOutputTokens": max_tokens}
        if json_schema is not None:  # sortie structurée : JSON valide conforme au schéma, sans bloc ``` ni texte autour
            config["responseMimeType"] = "application/json"
            config["responseSchema"] = json_schema
        if self.model in THINKING_LEVELS:
            config["thinkingConfig"] = {"thinkingLevel": THINKING_LEVELS[self.model]}
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": config,
        }
        data = await self._generate(self.model, payload)
        candidate = (data.get("candidates") or [{}])[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text") or "" for p in parts if not p.get("thought"))
        reason = candidate.get("finishReason")
        if reason == "MAX_TOKENS":
            raise ProviderError(f"gemini: réponse tronquée (limite de {max_tokens} tokens atteinte, réflexion comprise)")
        if reason not in (None, "STOP", "FINISH_REASON_UNSPECIFIED"):
            raise ProviderError(f"gemini: réponse interrompue ({reason})")
        if not text.strip():
            blocked = (data.get("promptFeedback") or {}).get("blockReason")
            raise ProviderError(f"gemini: réponse vide{f' ({blocked})' if blocked else ''}")
        usage = data.get("usageMetadata") or {}
        return TextResult(text, self._cost(usage), self.model, *token_counts(usage))

    def _cost(self, usage: dict) -> float:
        warn_if_prices_stale()
        return tokens_cost(usage, PRICES.get(self.model, FALLBACK_PRICE))


class GeminiImage(_Gemini):
    """Image de référence (sortie image de `generateContent`, base64 dans `inlineData`), en 9:16 par défaut.
    `models` : le modèle du réglage `gemini_image_model` puis ceux de `IMAGE_PRICES`."""

    def __init__(self, api_key: str, client: httpx.AsyncClient, model: str = DEFAULT_IMAGE_MODEL):
        super().__init__(api_key, client)
        self.models = image_models(model or DEFAULT_IMAGE_MODEL)

    async def generate(self, prompt: str, *, model: str, aspect_ratio: str = "9:16",
                       references: Sequence[bytes] = ()) -> GenerationResult:
        """`references` : images d'entrée (personnages, produit) que le modèle replace dans la scène du prompt."""
        parts = [*({"inlineData": {"mimeType": sniff_image_type(r, "image/png"), "data": base64.b64encode(r).decode()}}
                   for r in references), {"text": prompt}]
        data = await self._generate(model, {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect_ratio}},
        })
        candidate = (data.get("candidates") or [{}])[0]
        image = next((p["inlineData"] for p in (candidate.get("content") or {}).get("parts") or []
                      if p.get("inlineData")), None)
        if image is None:  # refus (sécurité) ou réponse texte seule
            reason = candidate.get("finishReason") or (data.get("promptFeedback") or {}).get("blockReason")
            raise ProviderError(f"gemini: aucune image dans la réponse ({reason or 'réponse vide'})")
        if image.get("mimeType") not in IMAGE_TYPES:
            raise ProviderError(f"gemini: type d'image inattendu ({image.get('mimeType')})")
        try:
            content = base64.b64decode(image.get("data") or "", validate=True)
        except binascii.Error as e:
            raise ProviderError("gemini: image illisible (base64 invalide)") from e
        cost = tokens_cost(data.get("usageMetadata") or {}, IMAGE_PRICES.get(model, max(IMAGE_PRICES.values())))
        return GenerationResult(ensure_non_empty(content, "image"), sniff_image_type(content, image["mimeType"]), cost, model)

    async def image_availability(self) -> dict[str, Availability]:
        state = Availability(True) if self._key else Availability(False, KEY_MISSING)
        return dict.fromkeys(self.models, state)
