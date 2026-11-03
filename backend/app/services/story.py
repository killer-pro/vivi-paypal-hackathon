"""Histoire d'une vidéo (étape `story`) : beats, éléments suivis (personnages, accessoires, lieux) et contrôles du
scénario. Fonctions pures : les appels au LLM et la base restent dans `pipeline.py`."""
import re
from typing import Any

from app.app_settings import VOICE_ID
from app.providers.base import ProviderError
from app.services.llm_json import fill_durations, fit_durations, json_value, ref_id, scene_duration, scene_text

MAX_REFERENCES = 6  # éléments dont le script demande une image de référence
MAX_REFERENCES_TOTAL = 12  # avec ceux que l'utilisateur ajoute à la main (élément de l'histoire ou nouveau)
REFERENCE_KINDS = ("character", "prop")  # un lieu n'a pas d'image de référence
KINDS = ("character", "prop", "place")
CONTINUITIES = ("continue", "cut")  # « continue » : le beat suit directement le précédent (même lieu), « cut » : coupe
MAX_DESCRIPTOR_CHARS = 500
MAX_BIBLE_CHARS = 4000

_TEXT = {"type": "STRING"}
STORY_SCHEMA = {
    "type": "OBJECT",
    "properties": {"beats": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {"summary": _TEXT, "voice_text": _TEXT, "duration_s": {"type": "NUMBER"},
                       "continuity": {"type": "STRING", "enum": list(CONTINUITIES)}},
        "required": ["summary", "voice_text", "duration_s", "continuity"],
        "propertyOrdering": ["summary", "voice_text", "duration_s", "continuity"]}}},
    "required": ["beats"],
}
INVENTORY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "bible": _TEXT,
        "elements": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"id": _TEXT, "kind": {"type": "STRING", "enum": list(KINDS)}, "name": _TEXT,
                           "descriptor": _TEXT, "prompt": _TEXT},
            "required": ["id", "kind", "name", "descriptor", "prompt"],
            "propertyOrdering": ["id", "kind", "name", "descriptor", "prompt"]}},
        "beats": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"elements": {"type": "ARRAY", "items": {
                "type": "OBJECT", "properties": {"id": _TEXT, "state": _TEXT},
                "required": ["id", "state"], "propertyOrdering": ["id", "state"]}}, "speaker": _TEXT},
            "required": ["elements", "speaker"], "propertyOrdering": ["elements", "speaker"]}},
    },
    "required": ["bible", "elements", "beats"], "propertyOrdering": ["bible", "elements", "beats"],
}


def _element(raw) -> dict | None:
    """Élément normalisé (`id`, `kind`, `name`, `descriptor`, `prompt`), None s'il est inexploitable."""
    if not isinstance(raw, dict) or not (eid := ref_id(raw.get("id"))):
        return None
    kind = scene_text(raw.get("kind")).lower()
    voice = scene_text(raw.get("voice_id"))
    return {"id": eid, "kind": kind if kind in KINDS else "prop", "name": scene_text(raw.get("name")) or eid,
            "descriptor": scene_text(raw.get("descriptor"))[:MAX_DESCRIPTOR_CHARS], "prompt": scene_text(raw.get("prompt")),
            "voice_id": voice if VOICE_ID.fullmatch(voice) else ""}


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _continuity(raw, first: bool) -> str:
    """« continue » ou « cut » ; toute autre valeur vaut « cut », et le premier beat n'a rien à poursuivre."""
    value = scene_text(raw).lower()
    return "continue" if value == "continue" and not first else "cut"


def _states(raw) -> list[dict]:
    """Éléments visibles d'un beat : `[{"id", "state"}]`, sans id vide ni doublon."""
    found: dict[str, str] = {}
    for item in _list(raw):
        if isinstance(item, dict) and (eid := ref_id(item.get("id"))):
            found.setdefault(eid, scene_text(item.get("state")))
    return [{"id": eid, "state": state} for eid, state in found.items()]


def parse_story(beats_text: str, inventory_text: str, target_duration_s: float) -> dict:
    """Fusionne la passe histoire (beats : résumé, voix off, durée) et la passe inventaire (éléments, fiche visuelle,
    éléments visibles de chaque beat, dans le même ordre) en `{"elements", "beats", "bible"}`. Durée absente : part
    égale du reste de la cible. Résumé et voix off sont obligatoires."""
    data = json_value(beats_text)
    raw_beats = data.get("beats") if isinstance(data, dict) else data
    if not isinstance(raw_beats, list) or not raw_beats:
        raise ProviderError("story: JSON invalide ou aucun beat")
    beats: list[dict[str, Any]] = []
    problems: list[str] = []
    for i, raw in enumerate(raw_beats, 1):
        raw = raw if isinstance(raw, dict) else {}
        beat: dict[str, Any] = {"summary": scene_text(raw.get("summary")), "voice_text": scene_text(raw.get("voice_text")),
                "duration_s": scene_duration(raw.get("duration_s")),
                "continuity": _continuity(raw.get("continuity"), first=not beats)}
        missing = [k for k in ("summary", "voice_text") if not beat[k]]
        if missing:
            problems.append(f"beat {i} incomplet ({' et '.join(missing)} vide{'s' if len(missing) > 1 else ''})")
        beats.append(beat)
    if problems:
        raise ProviderError(f"story: {' ; '.join(problems)}")
    fill_durations(beats, target_duration_s)
    fit_durations(beats, target_duration_s)
    data = json_value(inventory_text)
    inventory = data if isinstance(data, dict) else {}
    seen = [b for b in _list(inventory.get("beats")) if isinstance(b, dict)]
    for i, beat in enumerate(beats):
        shown = seen[i] if i < len(seen) else {}
        beat["elements"] = _states(shown.get("elements"))
        beat["speaker"] = ref_id(shown.get("speaker"))
    elements: dict[str, dict] = {}
    for raw in _list(inventory.get("elements")):
        if element := _element(raw):
            elements.setdefault(element["id"], element)
    return {"elements": list(elements.values()), "beats": beats,
            "bible": scene_text(inventory.get("bible"))[:MAX_BIBLE_CHARS]}


def story_problems(story: dict) -> list[str]:
    """Défauts de cohérence du scénario, un message français chacun : inventaire vide, beat sans aucun élément visible, id cité par un beat mais absent des éléments,
    élément que aucun beat ne cite, accessoire vu dans un seul beat (hors les deux derniers, où il peut être résolu),
    état qui revient à une valeur déjà quittée."""
    elements, beats = story["elements"], story["beats"]
    if not elements:
        return ["l'inventaire est vide ou illisible : aucun élément suivi"]
    known = {e["id"]: e for e in elements}
    problems: list[str] = []
    seen: dict[str, list[tuple[int, str]]] = {}
    for n, beat in enumerate(beats, 1):
        speaker = beat.get("speaker", "")
        if speaker and (speaker not in known or known[speaker]["kind"] != "character"):
            problems.append(f"beat {n} : le locuteur « {speaker} » n'est pas un personnage de la liste des éléments")
        if not beat["elements"]:
            problems.append(f"beat {n} : aucun élément visible dans l'inventaire")
        for item in beat["elements"]:
            if item["id"] in known:
                seen.setdefault(item["id"], []).append((n, item["state"].strip().lower()))
            else:
                problems.append(f"beat {n} cite l'élément « {item['id']} » absent de la liste des éléments")
    for element in elements:
        appearances = seen.get(element["id"], [])
        if not appearances:
            problems.append(f"l'élément « {element['id']} » n'apparaît dans aucun beat")
        elif element["kind"] == "prop" and len(appearances) == 1 and appearances[0][0] <= len(beats) - 2:
            problems.append(f"l'accessoire « {element['id']} » n'apparaît qu'au beat {appearances[0][0]} : "
                            "à reprendre plus tard ou à résoudre")
        states = [(n, state) for n, state in appearances if state]
        for k in range(2, len(states)):
            n, state = states[k]
            if state != states[k - 1][1] and state in {s for _, s in states[:k - 1]}:
                problems.append(f"l'état de « {element['id']} » revient à « {state} » au beat {n} sans raison")
    return problems


def elements_in(beat: dict, elements: list[dict]) -> list[dict]:
    """Éléments présents dans un beat (`id`, `kind`, `name`, `descriptor`, `state`), ceux dont l'id est inconnu exclus."""
    known = {e["id"]: e for e in elements}
    return [{**{k: known[i["id"]][k] for k in ("id", "kind", "name", "descriptor")}, "state": i["state"]}
            for i in beat["elements"] if i["id"] in known]


def descriptor_head(present: list[dict]) -> str:
    """Tête du prompt visuel d'une scène : le descripteur de chaque élément présent, suivi de son état ; un personnage dont
    le descripteur ne dit pas son nom est nommé (le prompt le reprend ensuite par son nom)."""
    def line(e: dict) -> str:
        text = e["descriptor"].rstrip(". ")
        if e.get("kind") == "character" and e["name"].lower() not in text.lower():
            text = f"{e['name']}, {text}"
        return f"{text} ({e['state']})" if e["state"] else text

    return ". ".join(line(e) for e in present if e["descriptor"])


def references_from(elements: list[dict], limit: int = MAX_REFERENCES) -> list[dict]:
    """Éléments qui reçoivent une image de référence (`id`, `prompt`, `descriptor`) : personnages et accessoires avec un
    prompt, `limit` au plus."""
    return [{"id": e["id"], "prompt": e["prompt"], **({"descriptor": e["descriptor"]} if e["descriptor"] else {})}
            for e in elements if e["kind"] in REFERENCE_KINDS and e["prompt"]][:limit]


def build_bible(style: str, elements: list[dict]) -> str:
    """Fiche visuelle d'un projet à story : style, décor et palette, puis le descripteur de chaque élément, assemblés par le
    serveur (le LLM n'a pas à les recopier)."""
    lines = [style.strip(), *(f"{e['name']}: {e['descriptor']}" for e in elements if e["descriptor"])]
    return "\n".join(lines)[:MAX_BIBLE_CHARS]


def main_reference(present: list[dict], elements: list[dict]) -> str:
    """Id de l'élément dont l'image de référence sert la scène : un personnage présent d'abord, sinon un accessoire, parmi
    ceux qui ont une image ; vide s'il n'y en a pas."""
    with_image = {r["id"] for r in references_from(elements)}
    return next((e["id"] for kind in REFERENCE_KINDS for e in present if e["kind"] == kind and e["id"] in with_image), "")


def story_result_errors(result: dict) -> list[str]:
    """Défauts de forme d'un `result` de story enregistré à la main (le script en dépend) : un message français chacun.
    Vide si le résultat est exploitable."""
    beats, elements = result.get("beats"), result.get("elements", [])
    if not isinstance(beats, list) or not beats:
        return ["l'histoire doit avoir au moins un beat"]
    if not isinstance(elements, list) or not all(isinstance(e, dict) and ref_id(e.get("id")) for e in elements):
        return ["éléments illisibles : chacun doit avoir un id"]
    known = {ref_id(e["id"]) for e in elements}
    errors: list[str] = [f"élément « {e['id']} » : identifiant de voix invalide" for e in elements
                         if e.get("voice_id") and not (isinstance(e["voice_id"], str) and VOICE_ID.fullmatch(e["voice_id"]))]
    for n, beat in enumerate(beats, 1):
        if not isinstance(beat, dict):
            errors.append(f"beat {n} illisible")
            continue
        if not all(isinstance(beat.get(k), str) and beat[k].strip() for k in ("summary", "voice_text")):
            errors.append(f"beat {n} : le résumé et la voix off sont obligatoires")
        if beat.get("continuity", "cut") not in CONTINUITIES:
            errors.append(f"beat {n} : continuité inconnue (« continue » ou « cut »)")
        duration = beat.get("duration_s")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
            errors.append(f"beat {n} : durée invalide")
        shown = beat.get("elements")
        if not isinstance(shown, list) or not all(isinstance(i, dict) for i in shown):
            errors.append(f"beat {n} : éléments visibles illisibles")
            continue
        speaker = ref_id(beat.get("speaker"))
        if speaker and speaker not in known:
            errors.append(f"beat {n} : locuteur « {speaker} » absent de la liste des éléments")
        errors += [f"beat {n} cite l'élément « {i.get('id')} » absent de la liste des éléments"
                   for i in shown if ref_id(i.get("id")) not in known]
    return errors


# Images d'entrée de Kontext par scène : chacune alourdit le calcul (≈ +5 min mesurées, machine chargée : indicatif), et au-delà
# de deux sujets il en perd un (essais sur la scène « chauffeur, assassin, voiture » : l'un des trois disparaît toujours).
MAX_KONTEXT_IMAGES = 2


def extra_references(shown: list[str], kinds: dict[str, str], available: set[str], exclude: set[str], limit: int) -> list[str]:
    """Ids des éléments visibles dont l'image s'ajoute en entrée de Kontext : ceux qui ont une image et ne sont pas
    déjà l'entrée principale, sans doublon, personnages d'abord (l'identité d'un visage est ce qui se voit le plus),
    `limit` au plus."""
    wanted = list(dict.fromkeys(i for i in shown if i in available and i not in exclude))
    wanted.sort(key=lambda i: kinds.get(i) != "character")  # tri stable : l'ordre de la scène est conservé
    return wanted[:max(limit, 0)]


def compact_prompt(prompt: str, shown: list[dict]) -> str:
    """Prompt d'une scène dont les éléments `shown` (`name`, `descriptor`) partent en image : leur descripteur recopié mot
    pour mot (état compris) est remplacé par leur nom, l'image porte déjà leur apparence et un long texte noie l'action."""
    for e in shown:
        descriptor = (e.get("descriptor") or "").rstrip(". ")
        if descriptor and e.get("name"):
            name = e["name"].replace("\\", r"\\")  # remplacement littéral : seul `\` est spécial pour re.sub
            prompt = re.sub(re.escape(descriptor) + r"(?: \([^)]*\))?", name, prompt, flags=re.IGNORECASE)
    return prompt


def assign_voices(story: dict, catalog: list[dict], narrator: str = "") -> None:
    """Donne à chaque personnage qui parle (locuteur d'un beat) et n'a pas de voix une voix du catalogue, distincte de
    celles déjà prises et de la voix du narrateur ; sans voix disponible, `voice_id` reste vide (voix par défaut)."""
    taken = {e["voice_id"] for e in story["elements"] if e.get("voice_id")}
    pool = [v["id"] for v in catalog if v["id"] != narrator and v["id"] not in taken]
    by_id = {e["id"]: e for e in story["elements"]}
    for speaker in dict.fromkeys(b.get("speaker", "") for b in story["beats"] if b.get("speaker")):
        element = by_id.get(speaker)
        if element and element["kind"] == "character" and not element.get("voice_id"):
            element["voice_id"] = pool.pop(0) if pool else ""
