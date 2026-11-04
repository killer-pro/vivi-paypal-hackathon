import json
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import decrypt, encrypt
from app.models import Setting
from app.providers.gemini import DEFAULT_IMAGE_MODEL as GEMINI_DEFAULT_IMAGE_MODEL
from app.providers.gemini import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from app.providers.ollama import DEFAULT_MODEL as OLLAMA_DEFAULT_MODEL
from app.providers.ollama import DEFAULT_URL as OLLAMA_DEFAULT_URL
from app.providers.profiles import DEFAULT_PROFILE, LEGACY_NAMES
from app.services.access import DEFAULT_LOCKED, parse_locked
from app.services.billing import DEFAULT_BILLING, parse_billing
from app.services.pricing import DEFAULT_PRICING, parse_pricing, positive_decimal

MASK = "••••"
CREDIT_KEYS = ("credits_usd_per_credit", "credits_margin", "credits_signup_grant", "credits_reservation_timeout_min",
               "credits_max_parallel_clips", "credits_pricing", "subscription_locked", "billing_config")
SECRET_KEYS = {"anthropic_api_key", "gemini_api_key", "fal_key", "elevenlabs_api_key", "langfuse_secret_key", "smtp_password",
                "stripe_secret_key", "stripe_webhook_secret", "paypal_client_secret"}
EDITABLE_KEYS = SECRET_KEYS | {"comfyui_url", "default_voice_id", "voice_catalog", "default_video_provider", "default_video_model",
                               "llm_provider", "gemini_model", "ollama_url", "ollama_model", "project_budget_usd", "image_provider",
                               "start_image_provider", "gemini_image_model", "langfuse_public_key", "langfuse_base_url",
                               "smtp_host", "smtp_port", "smtp_user", "smtp_sender", "paypal_client_id", "paypal_webhook_id", "paypal_mode",
                               *CREDIT_KEYS}
# Choix par défaut que l'éditeur affiche (voix, modèles) : lisibles par tout compte, aucun secret ni adresse de service.
EDITOR_KEYS = {"default_voice_id", "voice_catalog", "default_video_provider", "default_video_model", "image_provider",
               "start_image_provider"}
DEFAULTS = {"default_voice_id": "", "voice_catalog": "[]", "default_video_provider": "comfyui", "default_video_model": DEFAULT_PROFILE,
            "llm_provider": "claude", "gemini_model": GEMINI_DEFAULT_MODEL,
            "ollama_url": OLLAMA_DEFAULT_URL, "ollama_model": OLLAMA_DEFAULT_MODEL, "project_budget_usd": "10",
            "image_provider": "gemini", "start_image_provider": "comfyui", "gemini_image_model": GEMINI_DEFAULT_IMAGE_MODEL,
            "smtp_port": "587", "credits_usd_per_credit": "0.05", "credits_margin": "2.5", "credits_signup_grant": "100",
            "credits_reservation_timeout_min": "30", "credits_max_parallel_clips": "1", "credits_pricing": DEFAULT_PRICING,
            "subscription_locked": DEFAULT_LOCKED, "billing_config": DEFAULT_BILLING, "paypal_mode": "sandbox"}
LLM_PROVIDERS = ("claude", "gemini", "ollama")
START_IMAGE_PROVIDERS = ("comfyui", "gemini")  # image de départ de chaque scène : Flux Kontext (local) ou Gemini
IMAGE_PROVIDERS = ("gemini", "fal", "comfyui")  # image de référence ; Gemini par défaut (même clé que la rédaction)
# Réglages à valeurs fermées : une autre valeur est refusée à l'écriture.
CHOICES = {"paypal_mode": ("sandbox", "live"), "llm_provider": LLM_PROVIDERS, "image_provider": IMAGE_PROVIDERS, "start_image_provider": START_IMAGE_PROVIDERS}
# Réglages au format contraint (vide = retour au défaut) : un identifiant de modèle finit dans une URL.
PATTERNS = {key: re.compile(r"[A-Za-z0-9._-]+") for key in ("gemini_model", "gemini_image_model", "ollama_model")}
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
        for key, allowed in CHOICES.items():
            if key in values and values[key] not in allowed:
                raise ValueError(f"{key} : valeur « {values[key]} » invalide (attendu : {', '.join(allowed)})")
        if "project_budget_usd" in values and values["project_budget_usd"] and _budget(values["project_budget_usd"]) is None:
            raise ValueError("project_budget_usd : montant invalide (nombre de dollars, 0 = sans limite)")
        for key in ("credits_usd_per_credit", "credits_margin"):
            if values.get(key) and positive_decimal(values[key]) is None:
                raise ValueError(f"{key} : nombre strictement positif attendu")
        for key, minimum in (("credits_signup_grant", 0), ("credits_reservation_timeout_min", 1), ("credits_max_parallel_clips", 1)):
            if values.get(key) and not (values[key].isascii() and values[key].isdigit() and int(values[key]) >= minimum):
                raise ValueError(f"{key} : entier supérieur ou égal à {minimum} attendu")
        if "credits_pricing" in values and values["credits_pricing"] and parse_pricing(values["credits_pricing"]) is None:
            raise ValueError("credits_pricing : table de tarifs invalide (JSON {margin_overrides, flat_usd, local_clip_usd}, "
                             "montants finis ≥ 0, actions et profils connus)")
        if values.get("subscription_locked") and parse_locked(values["subscription_locked"]) is None:
            raise ValueError("subscription_locked : liste invalide (JSON {profiles, reference, styles} : profils et styles "
                             "connus, reference vrai ou faux)")
        if values.get("billing_config") and parse_billing(values["billing_config"]) is None:
            raise ValueError("billing_config : offre invalide (JSON {subscription, packs} : crédits entiers > 0, "
                             "identifiants de pack uniques)")
        if values.get("smtp_port") and _port(values["smtp_port"]) is None:
            raise ValueError("smtp_port : port invalide (entier entre 1 et 65535)")
        if values.get("default_voice_id") and not VOICE_ID.fullmatch(values["default_voice_id"]):
            raise ValueError("default_voice_id : identifiant invalide (lettres, chiffres, _ et - uniquement, 64 max)")
        if "voice_catalog" in values and parse_voice_catalog(values["voice_catalog"] or "[]") is None:
            raise ValueError(f"voice_catalog : liste de voix invalide (nom 80 caractères max, identifiant unique, "
                             f"{MAX_VOICES} voix au plus)")
        for key, pattern in PATTERNS.items():
            if values.get(key) and not pattern.fullmatch(values[key]):
                raise ValueError(f"{key} : valeur « {values[key]} » invalide (lettres, chiffres, . _ - uniquement)")
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
