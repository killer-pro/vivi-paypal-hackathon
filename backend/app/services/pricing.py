import json
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from app.providers.comfycloud import cloud_clip_usd
from app.providers.profiles import PROFILES

if TYPE_CHECKING:
    from app.app_settings import AppSettings

# Actions à prix forfaitaire (le prix des clips vient du coût de revient de chaque scène).
ACTIONS = ("idea", "story", "script", "reference", "voice", "final", "assist")
# Durée de référence d'un clip local : celle de `Profile.minutes_per_clip`.
REFERENCE_CLIP_S = Decimal(3)
# Coûts mesurés (`provider_calls`, 2026-11-07) : texte Groq / Gemini, image de référence Comfy Cloud, voix ElevenLabs
# (≈ 0,011 $ par scène). `local_clip_usd` : forfait des clips ComfyUI local (×0,6 / ×1 / ×1,5 / ×2,5).
DEFAULT_PRICING = json.dumps({
    "margin_overrides": {},
    "flat_usd": {"idea": 0.002, "story": 0.006, "script": 0.005, "reference": 0.04, "voice": 0.012, "final": 0.002,
                 "assist": 0.003},
    "local_clip_usd": {"fast": 0.048, "balanced": 0.08, "precision": 0.12, "max": 0.20},
})
_SECTIONS = {  # section → clés admises
    "margin_overrides": ACTIONS + ("clips",),
    "flat_usd": ACTIONS,
    "local_clip_usd": tuple(p.id for p in PROFILES),
}
_MICRO_USD = Decimal("0.000001")  # les flottants (0,1 + 0,2) sont ramenés au micro-dollar avant le calcul


def _decimal(value: Any) -> Decimal | None:
    """Nombre fini positif ou nul ; `None` sinon (texte, booléen, infini, négatif)."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number >= 0 else None


def credits_for(cost_usd: float | Decimal, margin: Decimal, usd_per_credit: Decimal) -> int:
    """Prix en crédits : coût de revient × marge ÷ valeur du crédit, arrondi au crédit supérieur (calcul exact)."""
    cost = Decimal(str(cost_usd)).quantize(_MICRO_USD)
    if cost <= 0:
        return 0
    return int((cost * margin / usd_per_credit).to_integral_value(rounding=ROUND_CEILING))


def parse_pricing(raw: str) -> dict[str, dict[str, Decimal]] | None:
    """Table `credits_pricing` ; `None` si le JSON est mal formé, une clé inconnue, un montant négatif ou non fini."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or not set(data) <= set(_SECTIONS):
        return None
    parsed: dict[str, dict[str, Decimal]] = {}
    for section, table in data.items():
        if not isinstance(table, dict) or not set(table) <= set(_SECTIONS[section]):
            return None
        values = {key: _decimal(amount) for key, amount in table.items()}
        if any(v is None or (section == "margin_overrides" and v == 0) for v in values.values()):
            return None
        parsed[section] = {key: v for key, v in values.items() if v is not None}
    return parsed


def positive_decimal(value: str) -> Decimal | None:
    """Nombre fini strictement positif (virgule acceptée) ; `None` sinon."""
    number = _decimal(value.replace(",", ".")) if isinstance(value, str) else None
    return number if number else None


@dataclass(frozen=True)
class Pricing:
    usd_per_credit: Decimal
    margin: Decimal
    margin_overrides: dict[str, Decimal]
    flat_usd: dict[str, Decimal]
    local_clip_usd: dict[str, Decimal]

    @classmethod
    def from_json(cls, table: dict[str, Any], *, usd_per_credit: Decimal, margin: Decimal) -> "Pricing":
        """Table du réglage `credits_pricing` (sections absentes = valeurs initiales)."""
        defaults = parse_pricing(DEFAULT_PRICING) or {}
        stored = parse_pricing(json.dumps(table)) or {}
        merged = {section: {**defaults.get(section, {}), **stored.get(section, {})} for section in _SECTIONS}
        return cls(usd_per_credit, margin, merged["margin_overrides"], merged["flat_usd"], merged["local_clip_usd"])

    def _credits(self, action: str, cost_usd: float | Decimal) -> int:
        return credits_for(cost_usd, self.margin_overrides.get(action, self.margin), self.usd_per_credit)

    def action_credits(self, action: str) -> int:
        """Prix d'une action forfaitaire (voix : par scène)."""
        return self._credits(action, self.flat_usd[action])

    def clip_credits(self, scene_cost_usd: float) -> int:
        """Prix d'un clip, d'après son coût de revient."""
        return self._credits("clips", scene_cost_usd)

    def local_clip_cost_usd(self, profile: str, duration_s: float) -> float:
        """Coût de revient d'un clip ComfyUI : forfait du profil, proportionnel à la durée (référence 3 s)."""
        return float(self.local_clip_usd[profile] * Decimal(str(duration_s)) / REFERENCE_CLIP_S)


async def load_pricing(app_settings: "AppSettings") -> Pricing:
    """Tarifs courants : réglages `credits_*` (la base prime sur l'environnement)."""
    usd = positive_decimal(await app_settings.get("credits_usd_per_credit"))
    margin = positive_decimal(await app_settings.get("credits_margin"))
    assert usd and margin  # validés à l'écriture ; les défauts du code sont valides
    try:
        table = json.loads(await app_settings.get("credits_pricing"))
    except ValueError:
        table = {}
    return Pricing.from_json(table, usd_per_credit=usd, margin=margin)


def video_credits(pricing: Pricing, scenes: int = 10, profile: str = "fast") -> int:
    """Crédits d'une vidéo de 30 s (`scenes` scènes de 3 s, clips Comfy Cloud du profil) : idée, histoire, script, image
    de référence, métadonnées, et voix et clip de chaque scène. Sert à dire combien de vidéos paie un forfait."""
    once = sum(pricing.action_credits(a) for a in ("idea", "story", "script", "reference", "final"))
    return once + scenes * (pricing.action_credits("voice") + pricing.clip_credits(cloud_clip_usd(profile, float(REFERENCE_CLIP_S))))
