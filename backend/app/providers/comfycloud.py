import asyncio

import httpx

from app.providers.base import (
    Availability,
    ProviderError,
    ensure_non_empty,
    key_is_valid,
    missing_key,
    raise_for_provider,
    require_key,
)
from app.providers.comfyui import ComfyUIImage, ComfyUIProvider, execution_error, first_output
from app.providers.profiles import ModelFile, get_profile
from app.providers.workflows import cloud_workflow

BASE_URL = "https://cloud.comfy.org/api"
KEY_MISSING = missing_key("Comfy Cloud", "Comfy Cloud")
# Les clés des comptes sans forfait lisent l'API mais ne peuvent rien lancer, même avec des crédits achetés.
NO_PLAN = "Comfy Cloud : l'API exige un abonnement payant, Standard ou plus (les crédits seuls ne suffisent pas)"
# Facturé au temps de calcul GPU (RTX PRO 6000 : 736 crédits par heure, 211 crédits par dollar sans abonnement), relevé
# le 2026-11-07 sur comfy.org/pricing ; ni la file d'attente ni la durée de la vidéo ne comptent.
USD_PER_GPU_S = 736 / 3600 / 211
# Secondes de calcul d'un clip de 3 s par profil, mesurées le 2026-11-07 (estimation du budget avant lancement).
# Image de départ Kontext comprise : elle s'exécute dans le même graphe que le clip (Rapide avec référence : ≈ 0,021 $).
GPU_S_PER_CLIP = {"fast": 22, "balanced": 26, "precision": 45, "max": 60}
ESTIMATE_CLIP_S = 3
# Pire cas : file d'attente du service et profil Maximum de 5 s (quelques minutes de calcul) ; le polling le couvre.
CLIP_TIMEOUT_S = 1200
IMAGE_TIMEOUT_S = 600
POLL_INTERVAL_S = 2.0
FAILED = {"error", "non_retryable_error", "lost", "cancelled"}  # états finaux d'échec de `GET /api/job/{id}/status`



def cloud_clip_usd(profile: str, duration_s: float) -> float:
    """Coût de revient d'un clip Comfy Cloud : temps de GPU mesuré du profil, proportionnel à la durée (référence 3 s)."""
    seconds = GPU_S_PER_CLIP[get_profile(profile).id] * max(duration_s, 1) / ESTIMATE_CLIP_S
    return round(seconds * USD_PER_GPU_S, 4)

class ComfyCloudProvider(ComfyUIProvider):
    """Mêmes profils et mêmes graphes que ComfyUI local, exécutés par Comfy Cloud (API v1, celle de ComfyUI plus le statut
    des jobs). Lancer un graphe exige un abonnement payant (`NO_PLAN`). Les chargeurs GGUF sont remplacés par
    leurs modèles fp8 du cloud."""

    name = "comfycloud"

    def __init__(self, api_key: str, client: httpx.AsyncClient, poll_interval: float = POLL_INTERVAL_S):
        super().__init__(BASE_URL, client, poll_interval)
        self._key = api_key
        self._headers = {"X-API-Key": api_key}

    def estimate_cost(self, model: str, duration_s: float) -> float:
        return cloud_clip_usd(model, duration_s)

    async def _run(self, workflow: dict, what: str, *, free: bool = True) -> bytes:
        require_key(self._key, KEY_MISSING)
        r = await self._post("prompt", json={"prompt": cloud_workflow(workflow)})
        if r.status_code in (402, 403) and '"FREE_TIER_' in r.text:  # FREE_TIER_NOT_ALLOWED, FREE_TIER_EXHAUSTED
            raise ProviderError(NO_PLAN)
        raise_for_provider(r, self.name)
        prompt_id = r.json()["prompt_id"]
        output = first_output(await self._wait_or_cancel(prompt_id))
        self._spent += await self._gpu_seconds(prompt_id) * USD_PER_GPU_S
        return ensure_non_empty(await self._view({k: output.get(k, "") for k in ("filename", "subfolder", "type")}), what)

    async def _gpu_seconds(self, prompt_id: str) -> float:
        """Durée d'exécution facturée (horodatages en millisecondes) ; 0 si le service ne la donne pas."""
        r = await self._get(f"jobs/{prompt_id}")
        if r.status_code != 200:
            return 0.0
        job = r.json()
        start, end = job.get("execution_start_time"), job.get("execution_end_time")
        return max(end - start, 0) / 1000 if start and end else 0.0

    async def _view(self, params: dict) -> bytes:
        """Fichier produit : le service répond par une redirection vers une URL signée, lue sans la clé (elle n'a pas à
        partir chez l'hébergeur du stockage)."""
        r = await self._get("view", params=params)
        if r.is_redirect:
            r = await self._c.get(r.headers["location"])
        raise_for_provider(r, self.name)
        return r.content

    async def _wait_history(self, prompt_id: str) -> dict:
        for _ in range(int(CLIP_TIMEOUT_S / self._poll)):
            r = await self._get(f"job/{prompt_id}/status")
            raise_for_provider(r, self.name)
            status = r.json().get("status")
            if status == "success":
                h = await self._get(f"history_v2/{prompt_id}")
                raise_for_provider(h, self.name)
                return h.json()[prompt_id]
            if status in FAILED:
                h = await self._get(f"history_v2/{prompt_id}")
                detail = execution_error(h.json().get(prompt_id) or {}) if h.status_code == 200 else None
                raise ProviderError(f"{self.name}: échec du workflow ({detail or status})")
            await asyncio.sleep(self._poll)
        raise ProviderError(f"{self.name}: timeout de polling")

    async def _cancel(self, prompt_id: str) -> None:
        """Retire le job de la file, ou l'interrompt s'il tourne déjà (le job désigné seulement)."""
        await self._post("queue", json={"delete": [prompt_id]})
        await self._post("interrupt", json={"prompt_id": prompt_id})

    async def _free(self) -> None:
        """Rien à décharger : les machines du service ne sont pas les nôtres."""

    async def availability_of(self, wanted: dict[str, list[ModelFile]]) -> dict[str, Availability]:
        """Disponible dès qu'une clé est saisie, comme fal : les modèles du cloud ont été vérifiés une fois pour toutes
        (`CLOUD_UNETS`), et interroger le service à chaque affichage coûterait une requête par carte."""
        return dict.fromkeys(wanted, Availability(True) if self._key else Availability(False, KEY_MISSING))

    async def health(self) -> bool:
        return await key_is_valid(self._c, self._key, f"{BASE_URL}/user", self._headers)


class ComfyCloudImage(ComfyUIImage):
    """Image de référence Flux dev générée par Comfy Cloud (même graphe que la version locale)."""

    name = "comfycloud"
