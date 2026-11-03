# Assistant IA de rédaction

Sur la ligne de chaque champ texte de l'admin, « Générer » et « Améliorer » (avec une consigne facultative) proposent un
texte rédigé par le LLM actif (réglage `llm_provider` : Claude ou Gemini). La proposition remplace le texte du
brouillon du champ ; elle n'est enregistrée que si l'utilisateur enregistre le formulaire, et « Annuler la
proposition » rétablit le texte précédent.

## Champs couverts
| `field_kind` | Champ de l'admin | Règles données au LLM |
|---|---|---|
| `project_title` | Titre du projet (création, brief) | 3 à 8 mots, français |
| `theme` | Thème (création, brief) | 1 à 3 phrases : sujet, promesse, ton, public |
| `hint` | Piste de départ (Idée) | Une phrase, une direction à explorer |
| `angle` | Angle proposé (Idée) | 2 à 5 phrases, accroche, fil conducteur, chute, sans markdown |
| `voice_text` | Voix off d'une scène (Script) | Français parlé, uniquement les mots prononcés, budget de mots ≈ 2,5 × durée |
| `visual_prompt` | Prompt visuel d'une scène (Script) | Anglais, guide `VISUAL_PROMPT_GUIDE` partagé avec l'étape script (80 à 120 mots : sujet + action, décor, phrase de caméra explicite, lumière, style ; 9:16, sans texte à l'écran ; règles de composition, voir plus bas) |
| `reference_prompt` | Prompt de l'image de référence | Anglais, style commun des clips, 9:16 |
| `title` | Titre de publication (Final) | Accrocheur, 70 caractères maximum, sans hashtag |
| `description` | Description (Final) | 1 à 3 phrases, question ou appel à l'action possible, sans hashtag |
| `hashtags` | Hashtags (Final) | 5 à 8, séparés par des espaces, chacun avec `#` |

## Règles de composition du prompt visuel
Issues du benchmark des profils de génération (`docs/profils-generation.md`) et incluses dans `VISUAL_PROMPT_GUIDE`
(`services/pipeline.py`), donc appliquées à la fois par l'étape script (génération initiale des scènes) et par
l'assistant (`visual_prompt`) :
- un sujet de taille modérée avec de la marge autour, jamais un sujet qui remplit le conteneur ;
- une action décrite par ce qu'on voit (« un bras pousse le dessous du couvercle »), pas par un verbe abstrait
  (« dévisser », que le modèle anime en geste humain) ;
- intérieur et extérieur séparés explicitement (« derrière le verre », vue de côté fixe) ;
- une seule action continue par scène.

Reformulation d'un `visual_prompt` **avec consigne** : la tâche donnée au LLM autorise à changer la composition (cadrage,
taille du sujet, action) en gardant le sens de la voix off de la scène, pour corriger réellement une scène défectueuse
au lieu de la paraphraser. Sans consigne, ou pour un autre champ, la reformulation garde le sens et les informations du
texte actuel.

## Où il est utilisé
Sujet de l'accueil, panneaux Idée, Script, Clips (volet « Préciser le prompt de cette scène », `kind = visual_prompt`
avec `projectId` et `sceneId` : la scène donne le contexte), Image de référence et Export.

## Fonctionnement
- API : `POST /api/ai/assist` (`backend/app/api/assist.py`), détails et codes d'erreur dans `api.md`.
- Service : `backend/app/services/assist.py`. `build_prompt` assemble les lignes `Champ :` / `Mode :`, les règles du
  champ (`FIELD_KINDS`), le contexte (`_context` : brief, angle validé, script actuel, métadonnées, scène, budget de
  mots), le texte actuel entre `<<<`/`>>>`, la consigne et la tâche (générer ou reformuler). Prompt système
  `ASSIST_SYSTEM` : répondre uniquement par le texte du champ. `clean_output` retire l'habillage restant, de façon
  conservatrice (libellé du seul champ demandé, guillemets seulement englobants, gras seulement global : voir `api.md`).
- Coût : `tracked_call` (2 tentatives, 90 s), journal `provider_calls` avec `step = "assist:<champ>"` et le projet (une
  réponse vide une fois nettoyée garde son coût réel et donne une erreur `502`) ;
  visible dans l'écran Coûts (« Assistant IA (voix off) ») et dans le coût du projet.
- Mode `FAKE_PROVIDERS=true` : `FakeLLM` reconnaît les lignes `Champ :` / `Mode :` et répond de façon déterministe
  (`FAKE_ASSIST` : un exemple plausible par champ ; reformulation = texte actuel suivi de « (version reformulée) »).
- Admin : composant `AssistField` et logique pure `src/assist.ts` (voir `admin.md`, section « Assistant IA »).
  Inactif pendant une génération de l'étape ou d'une étape en aval, pendant un enregistrement et pendant l'appel ; une
  réponse tardive n'écrase ni les autres champs ni un champ modifié entre-temps (voir `admin.md`).

## Chat du plan
Sur l'écran Plan, l'utilisateur discute avec l'IA (`app/services/plan_chat.py`). Le prompt contient le brief, le style, le plan courant en JSON (avec l'`id` de chaque scène) et les 10 derniers messages. La réponse est structurée (`reply` et, si le plan change, `plan` complet : l'`id` d'une scène gardée est conservé, `null` pour une nouvelle). Le serveur la valide (scènes non vides, durées > 0, 1 à 30 scènes, ids sans doublon), applique le plan et garde l'instantané précédent sur le message de l'IA pour l'annuler. L'appel est journalisé (`provider_calls`, étape `plan_chat`) et refusé si le budget est atteint ou si une étape tourne.

## Règles partagées (2026-10-25)
- Le style visuel du projet (`Project.style`) est ajouté au contexte des champs `visual_prompt`, `reference_prompt` et `bible`.
- Pour la voix off et le prompt visuel de la **dernière scène**, le contexte rappelle la règle d'engagement (liker, commenter, partager).
