import httpx

from app.providers.base import HEALTH_TIMEOUT_S, ProviderError, TextResult, raise_for_provider

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma4"
TIMEOUT_S = 600  # un modèle local froid met du temps à se charger, puis à écrire un script entier


def lower_types(schema):
    """Le schéma de sortie structurée est écrit au format Gemini (types en majuscules) ; Ollama attend du JSON Schema."""
    if isinstance(schema, dict):
        return {k: v.lower() if k == "type" and isinstance(v, str) else lower_types(v) for k, v in schema.items()}
    if isinstance(schema, list):
        return [lower_types(v) for v in schema]
    return schema


class OllamaLLM:
    """Texte généré sur votre machine par Ollama (`/api/chat`) : sans clé, sans coût. Pas de retry interne
    (tracked_call s'en charge)."""

    name = "ollama"

    def __init__(self, url: str, client: httpx.AsyncClient, model: str = DEFAULT_MODEL):
        self._url = (url or DEFAULT_URL).rstrip("/")
        self._c = client
        self.model = model or DEFAULT_MODEL

    async def complete(self, system, prompt, *, max_tokens=4000, json_schema=None):
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "stream": False,
            "keep_alive": 0,  # décharge le modèle dès la réponse : la RAM revient à ComfyUI (Flux, Wan)
            "think": False,  # la réflexion des modèles qui en ont une mangerait le budget de tokens
            "options": {"num_predict": max_tokens},
        }
        if json_schema is not None:
            payload["format"] = lower_types(json_schema)
        try:
            r = await self._c.post(f"{self._url}/api/chat", json=payload, timeout=TIMEOUT_S)
        except httpx.TransportError as e:
            raise ProviderError(f"ollama: injoignable ({type(e).__name__}), lancez « ollama serve »", retryable=True) from e
        if r.status_code == 404:
            raise ProviderError(f"ollama: modèle « {self.model} » absent, lancez « ollama pull {self.model} »")
        raise_for_provider(r, "ollama")
        data = r.json()
        text = (data.get("message") or {}).get("content") or ""
        if data.get("done_reason") == "length":
            raise ProviderError(f"ollama: réponse tronquée (limite de {max_tokens} tokens atteinte)")
        if not text.strip():
            raise ProviderError("ollama: réponse vide")
        return TextResult(text, 0.0, self.model, data.get("prompt_eval_count") or 0, data.get("eval_count") or 0)

    async def installed_models(self) -> list[str]:
        """Modèles déjà téléchargés ; vide si Ollama ne répond pas."""
        try:
            r = await self._c.get(f"{self._url}/api/tags", timeout=HEALTH_TIMEOUT_S)
            return [m["name"] for m in r.json().get("models", [])] if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            return []

    async def health(self) -> bool:
        """Ollama répond et le modèle choisi est téléchargé."""
        installed = await self.installed_models()
        return self.model in installed or f"{self.model}:latest" in installed  # « gemma4 » = « gemma4:latest »
