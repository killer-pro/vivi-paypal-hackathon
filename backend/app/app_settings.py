import json
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import decrypt, encrypt
from app.models import Setting
from app.providers.gemini import DEFAULT_IMAGE_MODEL as GEMINI_DEFAULT_IMAGE_MODEL
from app.providers.gemini import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from app.providers.groq import DEFAULT_MODEL as GROQ_DEFAULT_MODEL
from app.providers.ollama import DEFAULT_MODEL as OLLAMA_DEFAULT_MODEL
from app.providers.ollama import DEFAULT_URL as OLLAMA_DEFAULT_URL
from app.providers.profiles import DEFAULT_PROFILE, LEGACY_NAMES
from app.services.billing import DEFAULT_BILLING, parse_billing
from app.services.pricing import DEFAULT_PRICING, parse_pricing, positive_decimal

MASK = "••••"
CREDIT_KEYS = ("credits_usd_per_credit", "credits_margin", "credits_signup_grant", "credits_reservation_timeout_min",
               "credits_pricing", "billing_config")
SECRET_KEYS = {"anthropic_api_key", "gemini_api_key", "groq_api_key", "fal_key", "comfy_cloud_api_key", "elevenlabs_api_key", "langfuse_secret_key", "smtp_password",
                "stripe_secret_key", "stripe_webhook_secret", "paypal_client_secret"}
EDITABLE_KEYS = SECRET_KEYS | {"comfyui_url", "default_voice_id", "voice_catalog", "default_video_provider", "default_video_model",
                               "llm_provider", "gemini_model", "groq_model", "ollama_url", "ollama_model", "project_budget_usd", "image_provider",
                               "start_image_provider", "gemini_image_model", "langfuse_public_key", "langfuse_base_url",
                               "smtp_host", "smtp_port", "smtp_user", "smtp_sender", "paypal_client_id", "paypal_webhook_id", "paypal_mode",
                               *CREDIT_KEYS}
# Choix par défaut que l'éditeur affiche (voix, modèles) : lisibles par tout compte, aucun secret ni adresse de service.
EDITOR_KEYS = {"default_voice_id", "voice_catalog", "default_video_provider", "default_video_model", "image_provider",
               "start_image_provider"}
DEFAULTS = {"default_voice_id": "", "voice_catalog": "[]", "default_video_provider": "comfyui", "default_video_model": DEFAULT_PROFILE,
            "llm_provider": "claude", "gemini_model": GEMINI_DEFAULT_MODEL, "groq_model": GROQ_DEFAULT_MODEL,
            "ollama_url": OLLAMA_DEFAULT_URL, "ollama_model": OLLAMA_DEFAULT_MODEL, "project_budget_usd": "10",
            "image_provider": "gemini", "start_image_provider": "comfyui", "gemini_image_model": GEMINI_DEFAULT_IMAGE_MODEL,
            "smtp_port": "587", "credits_usd_per_credit": "0.01", "credits_margin": "3", "credits_signup_grant": "200",
            "credits_reservation_timeout_min": "30", "credits_pricing": DEFAULT_PRICING,
            "billing_config": DEFAULT_BILLING, "paypal_mode": "sandbox"}
LLM_PROVIDERS = ("claude", "gemini", "groq", "ollama")
START_IMAGE_PROVIDERS = ("comfyui", "gemini")  # image de départ de chaque scène : Flux Kontext (local) ou Gemini
IMAGE_PROVIDERS = ("gemini", "fal", "comfyui", "comfycloud")  # image de référence ; Gemini par défaut (même clé que la rédaction)
# Réglages à valeurs fermées : une autre valeur est refusée à l'écriture.
CHOICES = {"paypal_mode": ("sandbox", "live"), "llm_provider": LLM_PROVIDERS, "image_provider": IMAGE_PROVIDERS, "start_image_provider": START_IMAGE_PROVIDERS}
# Réglages au format contraint (vide = retour au défaut) : un identifiant de modèle finit dans une URL.
PATTERNS = {**{key: re.compile(r"[A-Za-z0-9._-]+") for key in ("gemini_model", "gemini_image_model", "ollama_model")},
            "groq_model": re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?")}  # Groq préfixe l'éditeur : « openai/gpt-oss-120b »
# Anciennes valeurs remplacées : lues et écrites sous leur nouveau nom (`workflow` d'avant les profils → `max`).
RENAMED = {"default_video_model": LEGACY_NAMES}
# Identifiant de voix : inséré dans l'URL du provider, donc limité à des caractères sûrs (ni « / » ni « . »).
VOICE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAX_VOICES = 100


def parse_voice_catalog(raw: str) -> list[dict[str, str]] | None:
    """Catalogue `[{"id", "name"}]` d'un réglage JSON ; `None` s'il est mal formé (id invalide, doublon, trop long)."""
    try:
        voices = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(voices, list) or len(voices) > MAX_VOICES:
        return None
    ids = set()
    for v in voices:
        if not (isinstance(v, dict) and isinstance(v.get("id"), str) and VOICE_ID.fullmatch(v["id"])
                and isinstance(v.get("name"), str) and 0 < len(v["name"].strip()) <= 80) or v["id"] in ids:
            return None
        ids.add(v["id"])
    return [{"id": v["id"], "name": v["name"].strip()} for v in voices]


def _port(value: str) -> int | None:
    """Port TCP (1–65535) ; `None` si la valeur n'en est pas un."""
    return int(value) if value.isascii() and value.isdigit() and 0 < int(value) <= 65535 else None


def _budget(value: str) -> float | None:
    """Montant en dollars (virgule acceptée) ; `None` si ce n'est pas un nombre fini positif ou nul."""
    try:
        amount = float(value.replace(",", "."))
    except ValueError:
        return None
    return amount if 0 <= amount < float("inf") else None


def _integer_from(minimum: int):
    """Règle « entier ≥ minimum »."""
    return lambda value: value.isascii() and value.isdigit() and int(value) >= minimum


# Règles de valeur par réglage : (valeur acceptée ?, message de refus). Une valeur vide (retour au défaut) n'est jamais contrôlée.
RULES = {
    "project_budget_usd": (lambda v: _budget(v) is not None, "project_budget_usd : montant invalide (nombre de dollars, 0 = sans limite)"),
    **{key: (lambda v: positive_decimal(v) is not None, f"{key} : nombre strictement positif attendu")
       for key in ("credits_usd_per_credit", "credits_margin")},
    **{key: (_integer_from(minimum), f"{key} : entier supérieur ou égal à {minimum} attendu")
       for key, minimum in (("credits_signup_grant", 0), ("credits_reservation_timeout_min", 1))},
    "credits_pricing": (lambda v: parse_pricing(v) is not None,
                        "credits_pricing : table de tarifs invalide (JSON {margin_overrides, flat_usd, local_clip_usd}, "
                        "montants finis ≥ 0, actions et profils connus)"),
    "billing_config": (lambda v: parse_billing(v) is not None,
                       "billing_config : offre invalide (JSON {tiers, free, packs} : au moins un forfait, crédits et limites "
                       "entiers > 0, avantages complets, profils connus, identifiants uniques, forfait en minuscules de 20 caractères au plus)"),
    "smtp_port": (lambda v: _port(v) is not None, "smtp_port : port invalide (entier entre 1 et 65535)"),
    "default_voice_id": (lambda v: VOICE_ID.fullmatch(v) is not None,
                         "default_voice_id : identifiant invalide (lettres, chiffres, _ et - uniquement, 64 max)"),
    "voice_catalog": (lambda v: parse_voice_catalog(v) is not None,
                      f"voice_catalog : liste de voix invalide (nom 80 caractères max, identifiant unique, {MAX_VOICES} voix au plus)"),
}


def _validation_error(key: str, value: str) -> str | None:
    """Raison du refus de `value` pour `key` (valeurs fermées, format contraint, règle propre au réglage) ; `None` si elle est valide."""
    allowed = CHOICES.get(key)
    if allowed and value not in allowed:
        return f"{key} : valeur « {value} » invalide (attendu : {', '.join(allowed)})"
    if not value:
        return None
    pattern = PATTERNS.get(key)
    if pattern and not pattern.fullmatch(value):
        return f"{key} : valeur « {value} » invalide (lettres, chiffres, . _ - uniquement{', un / au plus' if key == 'groq_model' else ''})"
    rule = RULES.get(key)
    if rule and not rule[0](value):
        return rule[1]
    return None


class AppSettings:
    def __init__(self, session: AsyncSession):
        self._s = session

    async def get(self, key: str) -> str:
        row = await self._s.get(Setting, key)
        value = row.value if row and row.value else self._fallback(key)
        if key in SECRET_KEYS:  # clé collée avec un espace ou un retour à la ligne : en-tête HTTP invalide
            value = decrypt(value).strip()
        return RENAMED.get(key, {}).get(value, value)

    async def budget_usd(self) -> float:
        """Budget maximum par vidéo, en dollars ; 0 = sans limite."""
        return _budget(await self.get("project_budget_usd")) or 0.0

    @staticmethod
    def _fallback(key: str) -> str:
        """Valeur hors base : environnement, ou défaut du code si elle est vide (ex. `COMFYUI_URL=`)."""
        value = str(getattr(settings, key, "") or DEFAULTS.get(key, ""))
        if key == "default_voice_id" and not value and settings.fake_providers:
            return "fake-voice"  # sans clé ElevenLabs, le mode factice doit quand même aller jusqu'au bout
        return value

    async def set_many(self, values: dict[str, str]) -> None:
        """Écrit toutes les clés en une seule transaction (tout ou rien)."""
        for key in values:
            if key not in EDITABLE_KEYS:
                raise KeyError(key)
        for key, value in values.items():
            error = _validation_error(key, value)
            if error:
                raise ValueError(error)
        for key, value in values.items():
            value = RENAMED.get(key, {}).get(value, value)
            await self._s.merge(Setting(key=key, value=encrypt(value) if key in SECRET_KEYS else value))
        await self._s.commit()

    async def set(self, key: str, value: str) -> None:
        await self.set_many({key: value})

    async def all_masked(self) -> dict[str, str]:
        out = {}
        for key in sorted(EDITABLE_KEYS):
            v = await self.get(key)
            out[key] = (MASK + v[-4:]) if key in SECRET_KEYS and v else v
        return out
