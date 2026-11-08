import httpx

from app.providers.base import (
    ProviderError,
    TextResult,
    key_is_valid,
    missing_key,
    raise_for_provider,
    require_key,
    standard_schema,
)

API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODELS_URL = "https://api.groq.com/openai/v1/models"  # liste gratuite : sert au test de clé
DEFAULT_MODEL = "openai/gpt-oss-120b"
KEY_MISSING = missing_key("groq", "Groq")
# USD par million de tokens (entrée, sortie), relevé le 2026-11-07 sur console.groq.com/docs/model. Seul gpt-oss-120b
# a passé le test du 2026-11-07 (script en 4 scènes, JSON imposé, en français) ; qwen3.8-27b échoue au JSON imposé.
PRICES = {
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
}
FALLBACK_PRICE = max(PRICES.values())  # modèle inconnu : estimation prudente


class GroqLLM:
    """Texte généré par Groq (API compatible OpenAI `chat/completions`). Pas de retry interne (tracked_call s'en charge) ;
    sans clé, aucune requête."""

    name = "groq"

    def __init__(self, api_key: str, client: httpx.AsyncClient, model: str = DEFAULT_MODEL):
        self._key = api_key
        self._c = client
        self.model = model or DEFAULT_MODEL

    async def complete(self, system, prompt, *, max_tokens=4000, json_schema=None):
        require_key(self._key, KEY_MISSING)
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "max_completion_tokens": max_tokens,
            "reasoning_effort": "low",  # la réflexion partage le budget de tokens : les étapes ne demandent que de l'écriture
        }
        if json_schema is not None:  # mode non strict : nos schémas n'exigent pas toutes leurs propriétés
            payload["response_format"] = {"type": "json_schema",
                                          "json_schema": {"name": "answer", "schema": standard_schema(json_schema)}}
        try:
            r = await self._c.post(API_URL, json=payload, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.TransportError as e:
            raise ProviderError(f"groq: réseau ({type(e).__name__})", retryable=True) from e
        if r.status_code == 400 and "json_validate_failed" in r.text:  # JSON non conforme au schéma : un nouvel essai suffit souvent
            raise ProviderError("groq: réponse JSON non conforme au schéma", retryable=True)
        raise_for_provider(r, "groq")
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        if choice.get("finish_reason") == "length":
            raise ProviderError(f"groq: réponse tronquée (limite de {max_tokens} tokens atteinte, réflexion comprise)")
        if not text.strip():
            raise ProviderError("groq: réponse vide")
        usage = data.get("usage") or {}
        tokens_in, tokens_out = usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0
        price_in, price_out = PRICES.get(self.model, FALLBACK_PRICE)
        return TextResult(text, (tokens_in * price_in + tokens_out * price_out) / 1_000_000, self.model, tokens_in, tokens_out)

    async def health(self) -> bool:
        return await key_is_valid(self._c, self._key, MODELS_URL, {"Authorization": f"Bearer {self._key}"})
