"""Délais d'une étape : timeout d'un appel provider et timeout du job Arq qui l'enveloppe."""
from app.providers.comfycloud import CLIP_TIMEOUT_S as CLOUD_CLIP_TIMEOUT_S
from app.providers.comfycloud import IMAGE_TIMEOUT_S as CLOUD_IMAGE_TIMEOUT_S
from app.providers.comfyui import CLIP_TIMEOUT_S as COMFYUI_CLIP_TIMEOUT_S
from app.providers.comfyui import IMAGE_TIMEOUT_S as COMFYUI_IMAGE_TIMEOUT_S
from app.services.costs import DEFAULT_ATTEMPTS
from app.services.flow import RUN_ASSET_KIND

STEP_TIMEOUTS = {"clips": 900, "montage": 600}
# ComfyUI local (lent) et Comfy Cloud (file d'attente du service) : timeout d'un appel des clips (provider vidéo) et de
# reference (provider d'image).
PROVIDER_TIMEOUTS = {"clips": {"comfyui": COMFYUI_CLIP_TIMEOUT_S, "comfycloud": CLOUD_CLIP_TIMEOUT_S},
                     "reference": {"comfyui": COMFYUI_IMAGE_TIMEOUT_S, "comfycloud": CLOUD_IMAGE_TIMEOUT_S}}
DEFAULT_TIMEOUT = 300
PER_ITEM_STEPS = {*RUN_ASSET_KIND, "reference"}  # un appel provider par scène (clips, voix) ou par élément récurrent
LLM_CALLS = {"script": 10, "story": 4}  # appels LLM possibles par lancement (dont ceux d'une scène à la fois pour un script à partir de la story)
JOB_MARGIN_S = 120  # téléchargements, stockage, écritures en base
MAX_JOB_TIMEOUT = 24 * 3600  # un projet long de clips ComfyUI séquentiels (un GPU) dépasse 6 h


def step_timeout(step: str, provider: str | None = None) -> int:
    """Timeout d'un appel provider ; pour les clips et les images de référence, il dépend du provider (ComfyUI local :
    plus long)."""
    return PROVIDER_TIMEOUTS.get(step, {}).get(provider or "") or STEP_TIMEOUTS.get(step, DEFAULT_TIMEOUT)


def job_timeout(step: str, item_count: int, provider: str | None = None) -> int:
    """Timeout du job Arq : chaque appel (un par scène pour clips/voix, un par élément pour reference) peut durer jusqu'à
    son timeout à chaque tentative de tracked_call, plus le backoff ; borné par MAX_JOB_TIMEOUT."""
    calls = max(item_count, 1) if step in PER_ITEM_STEPS else LLM_CALLS.get(step, 1)
    per_call = step_timeout(step, provider) * DEFAULT_ATTEMPTS + 2**DEFAULT_ATTEMPTS
    return min(calls * per_call + JOB_MARGIN_S, MAX_JOB_TIMEOUT)
