import asyncio
from dataclasses import dataclass

import httpx

from app.providers.base import (
    Availability,
    GenerationResult,
    ProviderError,
    ensure_non_empty,
    missing_key,
    plain_prompt,
    raise_for_provider,
    require_key,
)


@dataclass(frozen=True)
class VideoModel:
    endpoint: str
    price_per_second: float  # estimation USD, ajustable
    durations: tuple[int, ...]  # durées (s) produites par le modèle ; une seule = longueur fixe, pas de paramètre
    aspect_ratio: bool = True  # le modèle accepte `aspect_ratio`


VIDEO_MODELS = {
    # Kling v2 sur fal : `duration` n'accepte que "5" ou "10".
    "kling": VideoModel("fal-ai/kling-video/v2/master/text-to-video", 0.28, (5, 10)),
    # Wan et LTX n'ont pas de paramètre de durée : clip de longueur fixe (~5 s par défaut).
    "wan": VideoModel("fal-ai/wan/v2.2-a14b/text-to-video", 0.10, (5,)),
    "ltx": VideoModel("fal-ai/ltx-video", 0.04, (5,), aspect_ratio=False),
}
IMAGE_MODELS = {"flux": "fal-ai/flux/dev"}
IMAGE_PRICE = 0.025
MAX_POLLS = 600
TRANSIENT_RETRIES = 5  # erreurs réseau/5xx tolérées par requête après soumission, réessayées sur place
FAL_KEY_MISSING = missing_key("fal", "fal.ai")


def clip_duration(model: str, duration_s: float) -> int:
    """Durée réellement générée (et facturée) : plus petite durée autorisée couvrant la scène, sinon la plus longue.
    Le montage coupe le clip à la durée de la voix, ou tient sa dernière image s'il est plus court."""
    allowed = VIDEO_MODELS[model].durations
    return next((d for d in allowed if d >= duration_s), allowed[-1])


class FalProvider:
    name = "fal"
    models = list(VIDEO_MODELS)

    def __init__(self, key: str, client: httpx.AsyncClient, poll_interval: float = 3.0):
        self._key = key
        self._h = {"Authorization": f"Key {key}"}
        self._c = client
        self._poll = poll_interval

    def estimate_cost(self, model: str, duration_s: float) -> float:
        return round(VIDEO_MODELS[model].price_per_second * clip_duration(model, duration_s), 4)

    async def _submit(self, endpoint: str, payload: dict) -> dict:
        """Seule requête qu'un échec transitoire autorise à rejouer (via tracked_call) : rien n'est encore facturé.
        Première requête de toute génération (image ou clip) : sans clé, rien n'est envoyé."""
        require_key(self._key, FAL_KEY_MISSING)
        try:
            r = await self._c.post(f"https://queue.fal.run/{endpoint}", json=payload, headers=self._h)
        except httpx.TransportError as e:
            raise ProviderError(f"fal: réseau ({e})", retryable=True) from e
        raise_for_provider(r, "fal")
        return r.json()

    async def _get(self, url: str, what: str, headers: dict | None = None) -> httpx.Response:
        """GET après soumission : le job est déjà payé, les erreurs transitoires sont réessayées ici (bornées) sur la
        même URL ; un échec définitif n'est pas relançable, pour que tracked_call ne resoumette pas le job."""
        for attempt in range(TRANSIENT_RETRIES + 1):
            try:
                r = await self._c.get(url, headers=headers)
                raise_for_provider(r, what)
                return r
            except httpx.TransportError as e:
                error = ProviderError(f"{what}: réseau ({e})", retryable=True)
            except ProviderError as e:
                error = e
            if not error.retryable or attempt == TRANSIENT_RETRIES:
                raise ProviderError(f"{error} (job fal déjà soumis, non relancé)") from error
            await asyncio.sleep(self._poll)
        raise AssertionError("unreachable")  # pragma: no cover

    async def _wait(self, job: dict) -> dict:
        for _ in range(MAX_POLLS):
            status = (await self._get(job["status_url"], "fal", self._h)).json()["status"]
            if status == "COMPLETED":
                return (await self._get(job["response_url"], "fal", self._h)).json()
            if status in ("FAILED", "ERROR"):
                raise ProviderError("fal: génération échouée")
            await asyncio.sleep(self._poll)
        raise ProviderError("fal: timeout de polling")

    async def _generate(self, endpoint: str, payload: dict, output_url, what: str) -> bytes:
        out = await self._wait(await self._submit(endpoint, payload))
        return ensure_non_empty((await self._get(output_url(out), what)).content, what)

    async def generate(self, prompt, *, model, duration_s=5, image=None, references=()):
        prompt = plain_prompt(prompt)
        if model in IMAGE_MODELS:
            data = await self._generate(IMAGE_MODELS[model], {"prompt": prompt},
                                        lambda out: out["images"][0]["url"], "image")
            return GenerationResult(data, "image/png", IMAGE_PRICE, model)
        spec = VIDEO_MODELS[model]
        payload = {"prompt": prompt}
        if len(spec.durations) > 1:
            payload["duration"] = str(clip_duration(model, duration_s))
        if spec.aspect_ratio:
            payload["aspect_ratio"] = "9:16"
        data = await self._generate(spec.endpoint, payload, lambda out: out["video"]["url"], "clip")
        return GenerationResult(data, "video/mp4", self.estimate_cost(model, duration_s), model)

    def _state(self) -> Availability:
        return Availability(True) if self._key else Availability(False, FAL_KEY_MISSING)

    async def availability(self) -> dict[str, Availability]:
        return dict.fromkeys(self.models, self._state())

    async def reference_availability(self, model: str) -> Availability:
        return self._state()  # les modèles fal ignorent l'image de référence en V1

    async def image_availability(self) -> dict[str, Availability]:
        return dict.fromkeys(IMAGE_MODELS, self._state())

    async def health(self) -> bool:
        return bool(self._key)  # fal n'a pas de point d'entrée gratuit pour tester une clé : présence seulement
