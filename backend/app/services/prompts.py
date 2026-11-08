"""Textes envoyés aux LLM : consignes système, prompts de l'idée, de la story, du script et des scènes."""
import json
import math

from app.models import Project
from app.services import styles
from app.services.llm_json import SCENE_MAX_S, SCENE_MIN_S
from app.services.story import MAX_REFERENCES

IDEA_SYSTEM = "Tu es stratège de contenus viraux pour TikTok, Reels et Shorts."
SCRIPT_SYSTEM = "Tu es scénariste de vidéos verticales virales. Réponds uniquement en JSON."
FINAL_SYSTEM = "Tu rédiges les métadonnées de publication de vidéos virales. Réponds uniquement en JSON."
WORDS_PER_SECOND = 2.5  # débit d'une voix off française naturelle
# Style de prompt visuel de Wan 2.2 (mesuré, Tâche 20A) : un prompt long qui commence par le sujet et son action, avec une
# phrase de caméra explicite, donne un sujet net et une caméra qui bouge ; un prompt court donne un sujet minuscule et un
# plan fixe. Règles de composition (benchmark des profils, 2026-10-21) : sujet de taille modérée avec de la marge, action
# visible, intérieur/extérieur séparés. Le prompt a deux paragraphes car trois modèles le lisent : Flux/Kontext dessinent
# l'image de départ (paragraphe 1 seul : la caméra y est inutile), Wan I2V anime cette image (paragraphe « Motion: » seul :
# redécrire l'image concurrence l'image fournie), Wan T2V lit les deux (`providers.base.split_prompt`). Partagé par le
# script, le chat du plan et l'assistant IA.
VISUAL_PROMPT_GUIDE = (
    "deux paragraphes séparés par une ligne vide. "
    "Premier paragraphe, l'image de départ (80 à 130 mots), dans cet ordre : le sujet principal dans sa pose de départ, "
    "avec des détails physiques ; le décor ; la lumière (moment, direction, couleurs) ; le style d'image de la fiche "
    "visuelle, repris tel quel, avec « sharp focus on the subject, shallow depth of field ». "
    "Il est autonome : le générateur ne connaît ni les autres scènes ni la fiche visuelle, donc chaque personnage, "
    "objet et marque présent y est redécrit en entier, mot pour mot comme dans la fiche ; une marque est nommée et son "
    "logo décrit par sa forme, ses couleurs et son emplacement, jamais par les lettres qu'il porte (le générateur ne "
    "sait pas écrire : ex. « a red aluminium can with a flowing white script logo across its front »). "
    "Composition : le sujet est de taille modérée, avec de la marge autour, jamais remplissant le conteneur ; "
    "l'intérieur et l'extérieur sont séparés explicitement (« derrière le verre », vue de côté fixe). "
    "Second paragraphe, qui commence par « Motion: » (30 à 60 mots) : le sujet en quelques mots, puis son action "
    "principale, faite de 2 ou 3 gestes enchaînés qui remplissent toute la durée de la scène et décrits par ce qu'on "
    "voit (« un bras pousse le dessous du couvercle », pas « dévisser »), puis une phrase de caméra explicite (ex. « "
    "low-angle tracking shot, the camera smoothly dollies backward following the subject », « slow dolly in », « slow "
    "pan left »). Le sujet et la caméra bougent dès la première seconde, à vitesse naturelle (jamais de ralenti). "
    "Format vertical 9:16. Les deux paragraphes ne contiennent aucune négation (« no », « without », « don't ») ni "
    "demande de texte à l'écran : ils décrivent ce qu'on voit, jamais ce qu'on évite (le générateur ne lit pas les "
    "négations)")
# Dernière scène : appel à l'engagement (liker, commenter, partager). Partagée par le script, le chat du plan et l'assistant.
ENGAGEMENT_RULE = (
    "La dernière scène est toujours l'appel à l'engagement : elle dure 4 à 5 secondes et sa voix off (10 mots au plus) contient obligatoirement les trois "
    "gestes, « like », « commente » et « partage », avec une question précise sur le sujet pour déclencher les "
    "commentaires (ex. « Quelle est ta pire habitude du soir ? Dis-le en commentaire, mets un like et partage à "
    "quelqu'un qui dort mal ! », à adapter au sujet). "
    "L'avant-dernière scène porte la chute ou l'idée forte ; le visuel de la dernière scène prolonge cette chute avec "
    "le sujet principal qui regarde la caméra, sans texte à l'écran"
)


def project_brief(project: Project) -> str:
    return (f"Thème : {project.theme}\nPlateforme : {project.platform}\n"
            f"Durée totale cible : {project.target_duration_s} secondes")


def word_budget(duration_s: float) -> int:
    return round(duration_s * WORDS_PER_SECOND)


def scene_count(target_duration_s: float, scene_length_s: float | None = None) -> tuple[str, str]:
    """(nombre de scènes, durée de chacune) tels que le prompt les demande : « 6 à 15 », « de 2 à 5 secondes »."""
    if scene_length_s:  # durée de scène imposée : nombre de scènes ≈ durée cible / durée de scène
        fewest = most = max(1, round(target_duration_s / scene_length_s))
        length = f"d'environ {scene_length_s:g} secondes chacune"
    else:
        fewest = max(1, math.ceil(target_duration_s / SCENE_MAX_S))
        most = max(fewest, int(target_duration_s // SCENE_MIN_S))
        length = f"de {SCENE_MIN_S} à {SCENE_MAX_S} secondes"
    return (f"{fewest}" if fewest == most else f"{fewest} à {most}"), length


def script_prompt(project: Project, angle: str, scene_length_s: float | None = None, instruction: str = "") -> str:
    target = project.target_duration_s
    count, length = scene_count(target, scene_length_s)
    rate = str(WORDS_PER_SECOND).replace(".", ",")
    return (f"{project_brief(project)}\n"
            "Angle retenu (matière de travail ; ne reprends pas sa mise en forme markdown) :\n"
            f"<<<\n{angle}\n>>>\n"
            + (f"Consigne de l'utilisateur, à appliquer en priorité : {instruction.strip()}\n" if instruction.strip() else "")
            + style_line(project)
            + "Commence par `bible`, la fiche visuelle de la vidéo, en anglais : pour chaque personnage récurrent (nom, "
            "âge, visage, coiffure, vêtements, signe distinctif), chaque objet ou produit clé, le décor principal, la "
            "palette de couleurs et le style d'image. Si le sujet est une marque ou un produit réel, nomme-le "
            "exactement et décris son apparence reconnaissable (forme, couleurs, logo : emplacement, typographie, "
            "couleurs). Elle sert de référence unique à toutes les scènes.\n"
            f"Puis `references` : au plus {MAX_REFERENCES} éléments RÉCURRENTS dont l'apparence doit rester identique d'une "
            "scène à l'autre (personnage qui revient, produit ou marque réels), chacun avec `id` (court, minuscules, sans "
            "espace, ex. « kroc », « coca_can »), `prompt` : image de référence en anglais, sujet seul sur fond neutre "
            "uni, plein cadre vertical, mêmes mots que la fiche (marque nommée, logo décrit), et `descriptor` : "
            "l'apparence physique de l'élément en anglais, 40 mots au plus, sans décor, fond ni action (le premier "
            "paragraphe de chaque visual_prompt de scène qui l'utilise commence par ce descripteur, mot pour mot). "
            "Aucun élément qui n'apparaît qu'une fois. Dans chaque scène, `reference` = id de l'élément principal "
            "visible dans la scène, ou \"\" s'il n'y en a pas. Le visual_prompt nomme toujours le personnage ou la marque "
            "par son nom (« Ray Kroc », « Coca-Cola »), même quand une référence existe.\n"
            f"Découpe ensuite la vidéo en {count} scènes {length} : la somme des "
            f"duration_s doit faire {target} secondes (à 10 % près).\n"
            f"Voix off en français, au débit d'environ {rate} mots par seconde : "
            f"environ {word_budget(target)} mots au total, et pour chaque scène environ "
            f"{rate} × duration_s mots (ex. {word_budget(4)} mots pour 4 s). "
            "voice_text ne contient que le texte prononcé (ni didascalie, ni markdown, ni numéro de scène). "
            "La première scène est l'accroche : une phrase choc ou une question qui retient le spectateur dès les 2 "
            f"premières secondes. {ENGAGEMENT_RULE}.\n"
            f"visual_prompt est en anglais, pour un générateur texte-vers-vidéo : {VISUAL_PROMPT_GUIDE}.\n"
            "Continuité : les scènes qui se suivent gardent les mêmes personnages, le même décor et la même lumière "
            "(mêmes mots que la fiche), mais changent de cadrage (plan large, moyen, gros plan, plongée, travelling…) "
            "pour ne jamais ressembler à un doublon ; une scène qui prolonge la précédente commence là où celle-ci "
            "s'arrête.\n"
            'Réponds avec {"bible": "fiche visuelle", "references": [{"id": "kroc", "prompt": "image de référence", "descriptor": "apparence physique"}], '
            '"scenes": [{"voice_text": "texte de la voix off", "visual_prompt": "description visuelle en anglais", '
            '"duration_s": 4, "reference": "kroc"}]}.')


def style_line(project: Project) -> str:
    return (f"Style visuel imposé : {style}. Applique-le à la fiche visuelle et à chaque prompt visuel.\n"
            if (style := styles.directive(project.style)) else "")


def story_prompt(project: Project, angle: str, scene_length_s: float | None = None, instruction: str = "") -> str:
    """Passe histoire : les beats (une scène chacun), sans rien de visuel, avec une causalité vérifiable."""
    target = project.target_duration_s
    count, length = scene_count(target, scene_length_s)
    rate = str(WORDS_PER_SECOND).replace(".", ",")
    return (f"{project_brief(project)}\n"
            "Angle retenu (matière de travail ; ne reprends pas sa mise en forme markdown) :\n"
            f"<<<\n{angle}\n>>>\n"
            + (f"Consigne de l'utilisateur, à appliquer en priorité : {instruction.strip()}\n" if instruction.strip() else "")
            + f"Écris l'histoire de la vidéo en {count} beats (un beat = une scène) {length} : la somme des duration_s "
            f"doit faire {target} secondes (à 10 % près).\n"
            "Chaque beat a `summary` (1 à 2 phrases en français : qui fait quoi, quel objet est touché et ce qui change "
            "pour lui), `voice_text` (voix off en français, texte prononcé seulement, au débit d'environ "
            f"{rate} mots par seconde, soit {word_budget(4)} mots pour 4 s), `duration_s` et `continuity` : « continue » "
            "si le beat se passe au même endroit, dans la suite immédiate du précédent (la caméra change de cadrage mais "
            "l'action et le décor continuent), « cut » pour un changement de lieu ou une ellipse ; le premier beat est "
            "toujours « cut ».\n"
            "Causalité : chaque beat découle du précédent. Tout objet introduit est repris dans un beat suivant ou "
            "résolu dans l'un des deux derniers beats (une histoire où un objet annoncé n'a aucune suite est refusée) ; "
            "aucun élément n'apparaît sans avoir été amené. Le premier beat est l'accroche : une phrase choc ou une "
            f"question dès les 2 premières secondes. {ENGAGEMENT_RULE}.\n"
            'Réponds avec {"beats": [{"summary": "...", "voice_text": "...", "duration_s": 4, "continuity": "cut"}]}.')


def inventory_prompt(project: Project, beats: list[dict]) -> str:
    """Passe inventaire : fiche visuelle, éléments suivis et, pour chaque beat, les éléments visibles avec leur état."""
    summaries = json.dumps([{"beat": i, "summary": b["summary"]} for i, b in enumerate(beats, 1)], ensure_ascii=False)
    return (f"{project_brief(project)}\nVoici les beats de l'histoire :\n<<<\n{summaries}\n>>>\n"
            + style_line(project)
            + "Dresse l'inventaire, en anglais. `bible` : style d'image, décor principal et palette de couleurs, 80 mots "
            "au plus, sans décrire les personnages. `elements` : chaque personnage récurrent, chaque accessoire qui "
            "compte dans l'histoire (objet touché, abîmé, déplacé) et chaque lieu, avec `id` (court, minuscules, sans "
            "espace), `kind` (character, prop ou place), `name`, `descriptor` (apparence figée, 40 mots au plus : forme, "
            "matière, couleurs, détails distinctifs, jamais de décor ni d'action ; pour une marque réelle, son nom "
            "exact ; un personnage est un humain ordinaire et original, jamais le visage, le nom ou le sosie d'une "
            "personnalité réelle, politique ou célèbre) et `prompt` (image de référence : sujet seul sur fond neutre uni, plein cadre vertical, mêmes mots "
            "que le descripteur ; vide pour un lieu).\n"
            f"Puis `beats` : exactement {len(beats)} objets, dans l'ordre, chacun avec `elements` : les éléments visibles "
            "dans ce beat, chacun avec son `state` : sa condition physique visible, courte et en anglais (objet : « dry », "
            "« wet with a visible spill », « zipper jammed » ; personnage : tenue ou apparence qui change, « hair messy », "
            "« lipstick smeared on cheek »), jamais l'action en cours, qui est dans `summary`, ni un lieu ; vide si rien "
            "ne change. L'état change quand un événement le modifie et ne revient jamais en arrière sans événement. Tout accessoire est visible dans au moins deux beats, ou dans l'un des deux derniers. Chaque beat a aussi "
            "`speaker` : l'id du personnage qui prononce la voix off de ce beat quand c'est sa réplique ou sa pensée à la "
            "première personne, sinon vide (le narrateur) ; la plupart des beats d'une voix off racontée restent vides.\n"
            'Réponds avec {"bible": "...", "elements": [{"id": "sac", "kind": "prop", "name": "...", "descriptor": "...", '
            '"prompt": "..."}], "beats": [{"elements": [{"id": "sac", "state": "dry"}], "speaker": ""}]}.')


def corrected(prompt: str, answer: str, problems: str, ask: str) -> str:
    """Prompt de la relance ciblée : la demande, la réponse précédente et ses défauts."""
    return (f"{prompt}\n\nTa réponse précédente est à corriger : {problems}.\nRéponse précédente :\n<<<\n"
            f"{answer[:3000]}\n>>>\nCorrige-la : {ask}")


def scene_prompt(project: Project, bible: str, beat: dict, present: list[dict], previous: str, index: int,
                 count: int, instruction: str = "") -> str:
    """Prompt visuel d'une scène à partir de son beat : fiche de style, éléments présents avec leur état, scène précédente."""
    looks = "\n".join(f"- {e['name']} : {e['descriptor']}" + (f" ; état dans cette scène : {e['state']}" if e["state"] else "")
                      for e in present)
    return (style_line(project) + (f"Fiche visuelle (style, décor, palette) : {bible}\n" if bible else "")
            + (f"Consigne de l'utilisateur, à appliquer en priorité : {instruction.strip()}\n" if instruction.strip() else "")
            + f"Scène {index} sur {count}, {beat['duration_s']:g} secondes. Ce qui se passe : {beat['summary']}\n"
            f"Voix off de la scène : {beat['voice_text']}\n"
            + (f"Scène précédente : {previous} Cette scène continue la même action avec un autre cadrage.\n" if previous else "")
            + (f"Éléments visibles, avec leur apparence figée et leur état (reprends chaque descripteur mot pour mot, "
               f"état compris) :\n{looks}\n" if looks else "")
            + f"visual_prompt est en anglais, pour un générateur texte-vers-vidéo : {VISUAL_PROMPT_GUIDE}.\n"
            'Réponds avec {"visual_prompt": "..."}.')


def reference_look(project: Project) -> str:
    """Style des images de référence : celui du projet, « cinematic » sans style choisi."""
    return styles.directive(project.style) or "cinematic"


def reference_suffix(project: Project) -> str:
    return f"Vertical 9:16, {reference_look(project)}, the subject alone on a plain neutral background."
