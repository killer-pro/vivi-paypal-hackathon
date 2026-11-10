"""Lecture et contrôle des réponses des LLM : scènes, fiche visuelle, références, défauts de qualité du script."""
import math
import re
from typing import Any

from app.providers.base import ProviderError
from app.providers.elevenlabs import spoken
from app.services.llm_json import (
    fill_durations,
    json_value,
    ref_id,
    scene_duration,
    scene_text,
)
from app.services.prompts import word_budget
from app.services.story import MAX_BIBLE_CHARS, MAX_DESCRIPTOR_CHARS, MAX_REFERENCES, descriptor_head

ENGAGEMENT_FALLBACK = "Si ça t'a plu, like, commente et partage !"
# Un appel à l'engagement nomme les trois gestes (« liker », « commenter », « partager » et leurs formes courantes).
ENGAGEMENT_WORDS = (r"\b(like\w*|aim\w*)", r"\bcomment\w*", r"\bpartag\w*")
DURATION_TOLERANCE = 0.2  # écart toléré entre la somme des durées et la cible (le prompt demande 10 %)
WORDS_TOLERANCE = 1.5  # voix off au plus 1,5 fois le budget de mots de sa scène, plus 3 mots
SCENE_KEYS = ("voice_text", "visual_prompt", "duration_s")
MAX_SCRIPT_TOKENS = 16000  # plafond du budget de sortie du script, quels que soient les paramètres
# Noms rencontrés dans les réponses des LLM pour les champs d'une scène (le premier non vide l'emporte).
SCENE_ALIASES = {
    "voice_text": ("voice_text", "voiceover", "voice_over", "voice", "narration", "text"),
    "visual_prompt": ("visual_prompt", "visual", "visual_description", "video_prompt", "prompt"),
    "duration_s": ("duration_s", "duration", "seconds", "duree_s", "duree"),
}
# Sorties structurées (schéma OpenAPI au format Gemini) des étapes qui attendent du JSON.
SCENES_SCHEMA = {
    "type": "OBJECT",
    "properties": {"bible": {"type": "STRING"}, "scenes": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {"voice_text": {"type": "STRING"}, "visual_prompt": {"type": "STRING"},
                       "duration_s": {"type": "NUMBER"}, "reference": {"type": "STRING"}},
        "required": list(SCENE_KEYS), "propertyOrdering": [*SCENE_KEYS, "reference"]}},
        "references": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"id": {"type": "STRING"}, "prompt": {"type": "STRING"}, "descriptor": {"type": "STRING"}},
            "required": ["id", "prompt", "descriptor"], "propertyOrdering": ["id", "prompt", "descriptor"]}}},
    "required": ["bible", "scenes"], "propertyOrdering": ["bible", "references", "scenes"],
}
FINAL_SCHEMA = {
    "type": "OBJECT",
    "properties": {"title": {"type": "STRING"}, "description": {"type": "STRING"},
                   "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}}},
    "required": ["title", "description", "hashtags"], "propertyOrdering": ["title", "description", "hashtags"],
}


SCENE_SCHEMA = {"type": "OBJECT", "properties": {"visual_prompt": {"type": "STRING"}}, "required": ["visual_prompt"]}


def extract_json(text: str, what: str) -> dict:
    """Objet JSON de la réponse ; tolère les blocs ``` et le texte autour."""
    data = json_value(text)
    if not isinstance(data, dict):
        raise ProviderError(f"{what}: JSON invalide (réponse du LLM non exploitable)")
    return data


def _scene_field(scene: dict, key: str):
    return next((scene[k] for k in SCENE_ALIASES[key] if scene.get(k) not in (None, "", [])), None)


def parse_bible(text: str) -> str:
    """Fiche visuelle (personnages, marques, décor, style) d'une réponse de script ; vide si la réponse n'en a pas."""
    data = json_value(text)
    bible = scene_text(data.get("bible")) if isinstance(data, dict) else ""
    return bible[:MAX_BIBLE_CHARS]


def parse_references(text: str) -> list[dict]:
    """Éléments de référence du script (`id`, `prompt`, `descriptor` s'il y en a un) : sans doublon ni entrée incomplète,
    `MAX_REFERENCES` au plus."""
    data = json_value(text)
    raw = data.get("references") if isinstance(data, dict) else None
    found: dict[str, dict] = {}
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and (rid := ref_id(item.get("id"))) and (prompt := scene_text(item.get("prompt"))):
            descriptor = scene_text(item.get("descriptor"))[:MAX_DESCRIPTOR_CHARS]
            found.setdefault(rid, {"id": rid, "prompt": prompt, **({"descriptor": descriptor} if descriptor else {})})
    return list(found.values())[:MAX_REFERENCES]


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())


def with_descriptors(visual_prompt: str, present: list[dict]) -> str:
    """Garantit la cohérence des personnages et produits : le prompt visuel commence par le descripteur (et l'état) de
    chaque élément présent, mot pour mot. Le LLM est prié de le faire ; quand il l'a paraphrasé ou oublié, le serveur
    l'ajoute (on ne compte pas sur la recopie par un modèle léger)."""
    missing = [e for e in present if e.get("descriptor") and _plain(e["descriptor"]) not in _plain(visual_prompt)]
    return f"{descriptor_head(missing)}. {visual_prompt}" if missing else visual_prompt


def apply_descriptors(scenes: list[dict], references: list[dict]) -> None:
    """Ancien chemin du script : le descripteur de l'élément de référence de chaque scène ouvre son prompt visuel."""
    descriptors = {r["id"]: r["descriptor"] for r in references if r.get("descriptor")}
    for scene in scenes:
        if descriptor := descriptors.get(scene["reference"]):
            scene["visual_prompt"] = with_descriptors(scene["visual_prompt"], [{"descriptor": descriptor, "state": ""}])


def parse_scenes(text: str, target_duration_s: float | None = None) -> list[dict]:
    """Scènes normalisées (`voice_text`, `visual_prompt`, `duration_s`, `reference`) d'une réponse de LLM. Tolère les noms
    de champs courants, les champs en trop, une durée en texte ; une durée absente reçoit une part égale du reste de
    la durée cible. Voix off et prompt visuel sont obligatoires : l'erreur nomme chaque scène et champ manquant."""
    data = json_value(text)
    scenes = data.get("scenes") if isinstance(data, dict) else data
    if not isinstance(scenes, list) or not scenes:
        raise ProviderError("script: JSON invalide ou aucune scène")
    parsed: list[dict[str, Any]] = []
    problems: list[str] = []
    for i, raw in enumerate(scenes, 1):
        if not isinstance(raw, dict):
            problems.append(f"scène {i} n'est pas un objet JSON")
            continue
        scene = {"voice_text": scene_text(_scene_field(raw, "voice_text")),
                 "visual_prompt": scene_text(_scene_field(raw, "visual_prompt")),
                 "duration_s": scene_duration(_scene_field(raw, "duration_s")),
                 "reference": ref_id(raw.get("reference"))}
        missing = [k for k in ("voice_text", "visual_prompt") if not scene[k]]
        if missing:
            problems.append(f"scène {i} incomplète ({' et '.join(missing)} vide{'s' if len(missing) > 1 else ''})")
        parsed.append(scene)
    if problems:
        raise ProviderError(f"script: {' ; '.join(problems)}")
    fill_durations(parsed, target_duration_s)
    return parsed


def has_engagement(text: str) -> bool:
    return all(re.search(word, text, re.I) for word in ENGAGEMENT_WORDS)


def script_problems(scenes: list[dict], target_duration_s: float, noun: str = "scène",
                    last: str = "la dernière scène") -> list[str]:
    """Défauts de qualité d'un script structurellement valide : durée totale loin de la cible, voix off trop longue pour
    sa scène (le montage étirerait le clip), dernière scène sans appel à l'engagement."""
    problems = []
    total = sum(s["duration_s"] for s in scenes)
    if abs(total - target_duration_s) > DURATION_TOLERANCE * target_duration_s:
        problems.append(f"la somme des duration_s vaut {total:g} s au lieu de {target_duration_s:g} s")
    for i, s in enumerate(scenes, 1):
        words, budget = len(spoken(s["voice_text"]).split()), word_budget(s["duration_s"])
        if words > budget * WORDS_TOLERANCE + 3:
            problems.append(f"{noun} {i} : {words} mots de voix off pour {s['duration_s']:g} s (maximum {budget})")
    if not has_engagement(scenes[-1]["voice_text"]):
        problems.append(f"{last} doit inviter à liker, commenter et partager")
    return problems


def script_max_tokens(target_duration_s: float, scene_length_s: float | None = None) -> int:
    """Budget de sortie du script, réflexion comprise. Environ 330 tokens par scène (prompt visuel de ~190 mots anglais et
    voix off) plus la fiche et les références (~1500) : le défaut de 4000 tronquait les vidéos de 30 s et plus."""
    length = scene_length_s if isinstance(scene_length_s, (int, float)) and scene_length_s >= 1 else 3.5  # params non typés
    return min(3000 + 400 * math.ceil(target_duration_s / length), MAX_SCRIPT_TOKENS)
