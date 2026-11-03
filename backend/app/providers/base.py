import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True)
class GenerationResult:
    data: bytes
    content_type: str
    cost_usd: float
    model: str
    keyframe: bytes | None = None  # image de départ (PNG) d'un profil `keyframe`, à conserver avec le clip


# Un prompt visuel peut finir par un paragraphe « Motion: … » (action et caméra) : l'image fixe (Flux, Kontext) n'en a que
# faire, et l'animation à partir d'une image (Wan I2V) n'a besoin que de lui. Sans ce paragraphe, un seul texte sert partout.
_MOTION = re.compile(r"\n\s*Motion\s*:\s*", re.I)


def split_prompt(prompt: str) -> tuple[str, str]:
    """(image fixe, mouvement) d'un prompt visuel ; mouvement vide s'il n'a pas de paragraphe « Motion: »."""
    still, found, motion = _MOTION.split(prompt, maxsplit=1)[0], _MOTION.search(prompt), ""
    if found:
        motion = prompt[found.end():].strip()
    return still.strip(), motion


def plain_prompt(prompt: str) -> str:
    """Prompt d'un générateur texte-vers-vidéo : image et mouvement ensemble, sans l'étiquette « Motion: »."""
    return " ".join(part for part in split_prompt(prompt) if part)


@dataclass(frozen=True)
class Availability:
    """Modèle vidéo utilisable ou non ; `reason` (texte affiché) explique pourquoi il ne l'est pas, ou, s'il reste
    utilisable, avertit (ex. ComfyUI occupé : le job attendra son tour). Seule source de la carte et du contrôle au
    lancement."""

    available: bool
    reason: str = ""


@dataclass(frozen=True)
class TextResult:
    text: str
    cost_usd: float
    model: str
    input_tokens: int = 0  # 0 = inconnu ; journalisés par Langfuse
    output_tokens: int = 0


class ProviderError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def missing_key(provider: str, card: str) -> str:
    """Raison d'un provider sans clé API (erreur d'étape, carte grisée, refus au lancement) : où la saisir."""
    return f"Clé API {provider} manquante, à saisir dans Réglages → {card}"


def require_key(key: str, reason: str) -> None:
    """Sans clé, aucune requête (un en-tête « Key  » est refusé par httpx, une clé vide par le service) : erreur claire,
    non relançable."""
    if not key:
        raise ProviderError(reason)


def ensure_non_empty(data: bytes, what: str) -> bytes:
    if not data:
        raise ProviderError(f"{what}: réponse vide")
    return data


class LLMProvider(Protocol):
    name: str
    async def complete(self, system: str, prompt: str, *, max_tokens: int = 4000,
                       json_schema: dict | None = None) -> TextResult:
        """`json_schema` (facultatif, schéma OpenAPI au format Gemini : types en majuscules) : réponse JSON attendue.
        Gemini l'impose (sortie structurée) ; un provider qui ne sait pas le faire l'ignore (le prompt demande déjà
        du JSON et l'appelant valide la réponse)."""
        ...
    async def health(self) -> bool: ...


class ImageProvider(Protocol):
    name: str
    async def generate(self, prompt: str, *, model: str) -> GenerationResult: ...
    async def image_availability(self) -> dict[str, Availability]:
        """Disponibilité de chaque modèle d'image, comme `VideoProvider.availability` ; ne lève pas."""
        ...
    async def health(self) -> bool: ...


class VideoProvider(Protocol):
    name: str
    models: list[str]
    def estimate_cost(self, model: str, duration_s: float) -> float: ...
    async def generate(self, prompt: str, *, model: str, duration_s: float, image: bytes | None = None,
                       references: Sequence[bytes] = ()) -> GenerationResult:
        """`image` : entrée principale (dernière image du clip précédent ou référence de la scène) ; `references` : images
        des autres éléments visibles, que les fournisseurs qui n'en font rien ignorent."""
        ...
    async def availability(self) -> dict[str, Availability]:
        """Disponibilité de chaque modèle de `models` ; ne lève pas (service injoignable = tous indisponibles)."""
        ...
    async def reference_availability(self, model: str) -> Availability:
        """Disponibilité de `model` quand le projet a une image de référence (la même que sans, si le fournisseur n'en
        fait rien). Point d'accroche d'une offre payante « image de référence »."""
        ...
    async def health(self) -> bool: ...


class VoiceProvider(Protocol):
    name: str
    async def synthesize(self, text: str, *, voice_id: str) -> GenerationResult: ...
    async def voices(self) -> list[dict[str, str]]: ...
    async def health(self) -> bool: ...


HEALTH_TIMEOUT_S = 10


async def key_is_valid(client: httpx.AsyncClient, key: str, url: str, headers: dict) -> bool:
    """Contrôle de santé d'un provider à clé : requête gratuite authentifiée (liste de modèles, profil…). Faux sans clé,
    sur clé refusée ou si le service ne répond pas."""
    if not key:
        return False
    try:
        return (await client.get(url, headers=headers, timeout=HEALTH_TIMEOUT_S)).status_code == 200
    except httpx.HTTPError:
        return False


def raise_for_provider(resp: httpx.Response, what: str) -> None:
    if resp.status_code >= 500 or resp.status_code == 429:
        raise ProviderError(f"{what}: HTTP {resp.status_code}", retryable=True)
    if resp.status_code >= 400:
        raise ProviderError(f"{what}: HTTP {resp.status_code} {resp.text[:200]}")
