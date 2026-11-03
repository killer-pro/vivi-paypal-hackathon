"""Assistant de rédaction de l'admin : générer ou reformuler le texte d'un champ avec le LLM actif.

Le résultat n'est jamais enregistré ici : l'admin le place dans le brouillon du champ, que l'utilisateur enregistre
(ou annule). L'appel passe par `tracked_call` : coût et erreurs visibles dans `provider_calls` et `/costs`.
"""
import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, Scene, Step
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.services import langfuse, styles
from app.services.costs import tracked_call
from app.services.pipeline import ENGAGEMENT_RULE, VISUAL_PROMPT_GUIDE, WORDS_PER_SECOND, project_brief, word_budget

MODES = ("generate", "rewrite")
MAX_TEXT = 6000
MAX_INSTRUCTION = 300
MAX_CONTEXT = 2500  # caractères de contexte (angle, script) repris dans le prompt
MAX_TOKENS = 2000  # réflexion comprise (Gemini) ; les textes demandés sont courts
ATTEMPTS = 2
TIMEOUT_S = 90

ASSIST_SYSTEM = (
    "Tu es l'assistant de rédaction d'un studio de vidéos verticales virales (TikTok, Reels, Shorts). "
    "Tu réponds uniquement par le texte du champ demandé, prêt à être collé tel quel : ni guillemets, ni markdown, "
    "ni titre, ni préambule, ni commentaire, ni alternatives."
)


@dataclass(frozen=True)
class FieldKind:
    label: str
    guidance: str
    single_line: bool = False


FIELD_KINDS = {
    "project_title": FieldKind("titre de travail du projet",
                               "Court (3 à 8 mots), en français, qui résume le sujet.", single_line=True),
    "theme": FieldKind("thème (brief) de la vidéo",
                       "En français, 1 à 3 phrases : sujet, promesse, ton et public visé."),
    "hint": FieldKind("piste de départ pour trouver l'angle",
                      "En français, une phrase : une direction ou une intuition à explorer."),
    "angle": FieldKind("angle de la vidéo",
                       "En français, texte brut de 2 à 5 phrases : l'accroche des 2 premières secondes, le fil "
                       "conducteur et la chute. Original et précis, sans liste ni markdown."),
    "bible": FieldKind("fiche visuelle de la vidéo (personnages, produits et marques, décor, palette, style)",
                       "En anglais, texte brut : pour chaque personnage récurrent nom, âge, visage, coiffure, "
                       "vêtements, signe distinctif ; pour chaque marque ou produit son nom exact et son apparence "
                       "reconnaissable (forme, couleurs, logo : emplacement, typographie, couleurs) ; le décor "
                       "principal, la palette et le style d'image. 250 mots au plus, sans markdown."),
    "voice_text": FieldKind("texte de voix off d'une scène",
                            "En français parlé, uniquement les mots prononcés : phrases courtes et rythmées, "
                            "tutoiement si le ton s'y prête, ni didascalie, ni emoji, ni numéro de scène."),
    "visual_prompt": FieldKind("prompt visuel d'une scène (générateur texte-vers-vidéo)",
                               f"En anglais, {VISUAL_PROMPT_GUIDE}."),
    "reference_prompt": FieldKind("prompt de l'image de référence (style commun des clips)",
                                  "En anglais, un seul paragraphe : sujet, décor, palette, lumière, style visuel ; "
                                  "format vertical 9:16."),
    "title": FieldKind("titre de publication",
                       "En français, accrocheur, 70 caractères maximum, sans hashtag.", single_line=True),
    "description": FieldKind("description de publication",
                             "En français, 1 à 3 phrases qui donnent envie de regarder jusqu'au bout, peut finir par "
                             "une question ou un appel à l'action ; sans hashtag."),
    "hashtags": FieldKind("hashtags de publication",
                          "5 à 8 hashtags pertinents pour la plateforme, séparés par des espaces, chacun commençant "
                          "par #, sans autre texte.", single_line=True),
}
FINAL_KINDS = {"title", "description", "hashtags"}
SCENE_KINDS = {"voice_text", "visual_prompt"}
SCRIPT_CONTEXT_KINDS = SCENE_KINDS | FINAL_KINDS | {"reference_prompt", "bible"}
STYLED_KINDS = {"visual_prompt", "reference_prompt", "bible"}  # champs dont le rendu dépend du style visuel du projet

# Préambule seul sur la première ligne (« Voici la proposition : ») ; une phrase qui continue après « : » est gardée.
_PREAMBLE = re.compile(r"^(voici|voilà|here is|here's)\b[^\n]*:\s*$", re.I)
# Libellé recopié en tête de réponse, retiré seulement s'il nomme le champ demandé (« Titre : » pour un titre).
LABELS = {
    "project_title": ("titre", "title"), "title": ("titre", "title"), "theme": ("thème", "theme"),
    "hint": ("piste",), "angle": ("angle",), "voice_text": ("voix off", "texte de la voix off"),
    "visual_prompt": ("prompt", "prompt visuel", "visual prompt"), "reference_prompt": ("prompt", "image prompt"),
    "description": ("description",), "hashtags": ("hashtags",), "bible": ("fiche visuelle", "bible"),
}
_QUOTES = (('"', '"'), ("«", "»"), ("“", "”"), ("'", "'"), ("`", "`"))


def clean_output(text: str, kind: str) -> str:
    """Retire l'habillage que les LLM ajoutent malgré la consigne : bloc ```, préambule, libellé, guillemets,
    gras markdown. Les hashtags sont normalisés (`#` devant, sans doublon)."""
    out = text.strip()
    fence = re.fullmatch(r"```[\w-]*\s*(.*?)\s*```", out, re.DOTALL)
    if fence:
        out = fence.group(1).strip()
    lines = out.splitlines()
    if len(lines) > 1 and _PREAMBLE.match(lines[0].strip()):
        out = "\n".join(lines[1:]).strip()
    labels = "|".join(re.escape(label) for label in LABELS[kind])
    out = re.sub(rf"^({labels})\s*:\s*", "", out, count=1, flags=re.I).strip()
    bold = re.fullmatch(r"\*\*([^*]+)\*\*", out)  # réponse entièrement en gras ; le gras interne est gardé
    if bold:
        out = bold.group(1).strip()
    for opening, closing in _QUOTES:
        inner = out[len(opening):-len(closing)]
        # Guillemets englobants seulement : « A » … « B » (citations internes) reste intact.
        if (len(out) >= 2 and out.startswith(opening) and out.endswith(closing)
                and opening not in inner and closing not in inner):
            out = inner.strip()
            break
    if kind == "hashtags":
        tags = [t.lstrip("#") for t in re.split(r"[\s,;]+", out)]
        return " ".join(dict.fromkeys(f"#{t}" for t in tags if t))
    if FIELD_KINDS[kind].single_line:
        out = " ".join(out.split())
    return out


def _clip(text: str) -> str:
    return text if len(text) <= MAX_CONTEXT else text[:MAX_CONTEXT] + " […]"


async def _last_position(session: AsyncSession, project: Project) -> int | None:
    return await session.scalar(select(func.max(Scene.position)).where(Scene.project_id == project.id))


async def _context(session: AsyncSession, kind: str, project: Project | None, scene: Scene | None,
                   duration_s: float | None) -> list[str]:
    """Lignes de contexte : brief, angle, script et métadonnées selon le champ, pour rester cohérent avec le projet."""
    parts = []
    if project is not None:
        parts.append(f"Projet « {project.title} »\n{project_brief(project)}")
        if kind not in {"theme", "project_title", "hint", "angle"}:
            idea = await session.scalar(select(Step).where(Step.project_id == project.id, Step.name == "idea"))
            angle = (idea.result or {}).get("angle", "") if idea else ""
            if angle:
                parts.append(f"Angle retenu :\n<<<\n{_clip(angle)}\n>>>")
        if kind in SCRIPT_CONTEXT_KINDS:
            scenes = (await session.scalars(select(Scene).where(Scene.project_id == project.id)
                                            .order_by(Scene.position))).all()
            script_step = await session.scalar(select(Step).where(Step.project_id == project.id, Step.name == "script"))
            bible = (script_step.result or {}).get("bible", "") if script_step else ""
            if bible and kind != "bible":
                parts.append(f"Fiche visuelle (à respecter mot pour mot pour les personnages et marques) :\n<<<\n"
                             f"{_clip(bible)}\n>>>")
            if scenes:
                script = "\n".join(f"{s.position}. ({s.duration_s:g} s) {s.voice_text} | visuel : {s.visual_prompt}"
                                   for s in scenes)
                parts.append(f"Script actuel (voix off | visuel) :\n<<<\n{_clip(script)}\n>>>")
        if kind in STYLED_KINDS and (style := styles.directive(project.style)):
            parts.append(f"Style visuel imposé : {style}. Applique-le.")
        if kind in FINAL_KINDS and project.metadata_json:
            meta = project.metadata_json
            parts.append(f"Métadonnées actuelles : titre « {meta.get('title', '')} », description "
                         f"« {meta.get('description', '')} », hashtags {' '.join(meta.get('hashtags') or [])}")
    if scene is not None:
        if kind in SCENE_KINDS and project is not None and scene.position == await _last_position(session, project):
            parts.append(f"Cette scène est la dernière. {ENGAGEMENT_RULE}.")
        parts.append(f"Scène concernée : n° {scene.position}, voix off « {scene.voice_text} », "
                     f"prompt visuel « {scene.visual_prompt} »")
    duration = duration_s or (scene.duration_s if scene else None)
    if kind == "voice_text" and duration:
        rate = str(WORDS_PER_SECOND).replace(".", ",")
        parts.append(f"Durée de la scène : {duration:g} s, soit environ {word_budget(duration)} mots "
                     f"(débit de {rate} mots par seconde) : ne dépasse pas ce budget.")
    return parts


def build_prompt(kind: str, mode: str, text: str, instruction: str, context: list[str]) -> str:
    """Prompt de l'assistant. Les lignes `Champ :` et `Mode :` servent aussi au FakeLLM (réponses déterministes)."""
    spec = FIELD_KINDS[kind]
    lines = [f"Champ : {kind}", f"Mode : {mode}", f"Champ à rédiger : {spec.label}.", f"Règles du champ : {spec.guidance}"]
    lines += context
    if text.strip():
        lines.append(f"Texte actuel :\n<<<\n{text.strip()}\n>>>")
    if instruction.strip():
        lines.append(f"Consigne de l'utilisateur : {instruction.strip()}")
    if mode == "rewrite" and kind == "visual_prompt" and instruction.strip():
        lines.append("Tâche : réécris le prompt visuel en appliquant la consigne et les règles du champ ; tu peux "
                     "changer la composition de la scène (cadrage, taille du sujet, action) en gardant le sens de la "
                     "voix off de la scène.")
    elif mode == "rewrite":
        lines.append("Tâche : reformule le texte actuel en gardant son sens et ses informations, en appliquant la "
                     "consigne s'il y en a une et les règles du champ.")
    else:
        lines.append("Tâche : rédige une nouvelle proposition pour ce champ, cohérente avec le contexte"
                     + (" (le texte actuel peut servir d'inspiration)" if text.strip() else "") + ".")
    return "\n\n".join(lines)


async def assist(session: AsyncSession, registry: ProviderRegistry, *, kind: str, mode: str, text: str,
                 instruction: str = "", project: Project | None = None, scene: Scene | None = None,
                 duration_s: float | None = None) -> str:
    prompt = build_prompt(kind, mode, text, instruction, await _context(session, kind, project, scene, duration_s))
    llm = await registry.llm()

    result = await tracked_call(session, project_id=project.id if project else None, step=f"assist:{kind}",
                                provider=llm.name, model=getattr(llm, "model", llm.name),
                                fn=lambda: llm.complete(ASSIST_SYSTEM, prompt, max_tokens=MAX_TOKENS),
                                attempts=ATTEMPTS, timeout=TIMEOUT_S, input=langfuse.messages(prompt, ASSIST_SYSTEM))
    # Contrôlé après tracked_call : une réponse facturée mais vide une fois nettoyée garde son coût réel au journal.
    text = clean_output(result.text, kind)
    if not text:
        raise ProviderError(f"{llm.name}: réponse vide une fois nettoyée")
    return text
