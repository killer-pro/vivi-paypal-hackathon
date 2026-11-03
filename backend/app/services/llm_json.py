"""Lecture tolérante des réponses JSON des LLM (script, story) : valeur JSON, texte, durée, identifiant d'élément."""
import json
import re
import unicodedata

MAX_PARSED_SCENE_S = 60  # au-delà, la durée lue est absurde pour une scène : traitée comme absente
SCENE_MIN_S = 2  # durée minimale d'une scène
SCENE_MAX_S = 5  # 5 s : durée maximale d'un clip Wan 2.2 (au-delà, la dernière image serait tenue)
DURATION_TOLERANCE = 0.1  # écart toléré entre la somme des durées et la cible
DEFAULT_SCENE_S = 4.0  # durée d'une scène rendue sans durée exploitable, faute de cible à répartir


def json_value(text: str):
    """Valeur JSON de la réponse : texte entier (sortie structurée), bloc ```, sinon premier objet ou tableau."""
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
    candidates = [stripped, fence.group(1) if fence else None]
    candidates += [m.group(0) if (m := re.search(pattern, stripped, re.DOTALL)) else None
                   for pattern in (r"\{.*\}", r"\[.*\]")]
    for candidate in filter(None, candidates):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def scene_text(value) -> str:
    if isinstance(value, list):
        value = " ".join(str(v) for v in value if v is not None)
    return "" if value is None or isinstance(value, (dict, bool)) else str(value).strip()


def scene_duration(value) -> float | None:
    """Durée en secondes : nombre, ou texte du type « 4 s », « 4,5 secondes ». Absente, nulle, au format horaire
    (« 00:04 »), en millisecondes ou supérieure à 60 s → None (traitée comme absente)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(s|sec|secs|seconde|secondes|seconds?)?\.?\s*", value, re.I)
        value = float(match.group(1).replace(",", ".")) if match else None
    return float(value) if isinstance(value, (int, float)) and 0 < value <= MAX_PARSED_SCENE_S else None


def ref_id(value) -> str:
    """Identifiant d'élément de référence normalisé (minuscules sans accents, `a-z0-9_-`, 30 caractères) ; vide si
    inexploitable."""
    text = unicodedata.normalize("NFKD", scene_text(value).lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9_-]+", "_", text).strip("_")[:30]


def fill_durations(items: list[dict], target_duration_s: float | None) -> None:
    """Les éléments sans `duration_s` (None) reçoivent une part égale du reste de la durée cible, jamais moins de
    `SCENE_MIN_S` (reste faible ou nul : durée par défaut)."""
    undefined = [i for i in items if i["duration_s"] is None]
    if undefined:
        remaining = (target_duration_s or 0) - sum(i["duration_s"] for i in items if i["duration_s"] is not None)
        share = max(round(remaining / len(undefined), 1), SCENE_MIN_S) if remaining > 0 else DEFAULT_SCENE_S
        for i in undefined:
            i["duration_s"] = share


def fit_durations(items: list[dict], target_duration_s: float) -> None:
    """Somme des durées à plus de 10 % de la cible : durées rééchelonnées (au demi-seconde) pour l'atteindre, chacune
    bornée entre `SCENE_MIN_S` et `SCENE_MAX_S` (le surplus ou le manque va aux scènes qui ont de la marge). Les LLM
    écrivent des histoires plus courtes que demandé (26 s pour 30 s mesurées)."""
    if not items or abs(sum(i["duration_s"] for i in items) - target_duration_s) <= DURATION_TOLERANCE * target_duration_s:
        return
    free = list(items)
    fixed = 0.0
    for _ in range(len(items)):
        scale = (target_duration_s - fixed) / sum(i["duration_s"] for i in free)
        clamped = [i for i in free if not SCENE_MIN_S <= i["duration_s"] * scale <= SCENE_MAX_S]
        if not clamped:
            break
        for i in clamped:
            i["duration_s"] = float(min(max(i["duration_s"] * scale, SCENE_MIN_S), SCENE_MAX_S))
            fixed += i["duration_s"]
            free.remove(i)
        if not free:
            return
    for i in free:
        i["duration_s"] = round(i["duration_s"] * scale * 2) / 2
