import anthropic

from app.providers.base import HEALTH_TIMEOUT_S, ProviderError, TextResult, missing_key, require_key

PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0
KEY_MISSING = missing_key("claude", "Claude")


class ClaudeLLM:
    name = "claude"

    def __init__(self, api_key: str, model: str = "claude-sonnet-5-5", client: anthropic.AsyncAnthropic | None = None):
        self.model = model
        self._c = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)  # retries : tracked_call
        self._key = api_key

    async def complete(self, system, prompt, *, max_tokens=4000, json_schema=None):
        # json_schema ignoré : le prompt demande déjà du JSON et l'appelant valide la réponse.
        require_key(self._key, KEY_MISSING)  # sans clé, le SDK lèverait un TypeError
        try:
            msg = await self._c.messages.create(
                model=self.model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"claude: réseau ({e})", retryable=True) from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"claude: HTTP {e.status_code}", retryable=e.status_code >= 500 or e.status_code == 429) from e
        text = "".join(b.text for b in msg.content if b.type == "text")
        if not text.strip():
            raise ProviderError("claude: réponse vide")
        cost = (msg.usage.input_tokens * PRICE_IN_PER_M + msg.usage.output_tokens * PRICE_OUT_PER_M) / 1_000_000
        return TextResult(text, cost, self.model, msg.usage.input_tokens, msg.usage.output_tokens)

    async def health(self) -> bool:
        """Clé valide : la liste des modèles (gratuite) répond. Faux sans clé, clé refusée ou service injoignable."""
        if not self._key:
            return False
        try:
            await self._c.models.list(limit=1, timeout=HEALTH_TIMEOUT_S)
        except anthropic.APIError:
            return False
        return True
