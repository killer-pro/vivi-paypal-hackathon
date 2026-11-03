# Histoire (étape `story`)

Code : `backend/app/services/story.py` (fonctions pures : schémas, lecture, contrôles) et `pipeline.py` (`_story`, `_script`).
Admin : `admin/src/story.ts`, `hooks/useStoryDraft.ts`, `components/plan/StoryView.tsx`, `panels/StoryPanel.tsx`.

## Pourquoi
Un seul appel LLM qui écrivait tout (fiche visuelle, références, scènes, voix, `Motion:`) laissait des accessoires
disparaître ou changer de forme d'une scène à l'autre, et des objets annoncés ne servaient jamais. L'histoire est
maintenant une étape à part : écrite d'abord, relue et modifiée par l'utilisateur, puis transformée en scènes.

## Position dans le flow
`idea` → **`story`** → `script` → `reference` → … La génération du plan s'arrête sur `story` (borne `plan_until`,
`services/flow.py`) : l'utilisateur relit l'histoire sur l'écran Plan, puis « Écrire les scènes » valide `story` et lance
`script`. Modifier ou régénérer `story` périme `script` et tout l'aval. `reference` démarre automatiquement dès que le
script est écrit (pendant sa relecture) quand il liste des éléments récurrents : voir `references.md`.

## Projets existants
La migration `0012` ajoute à chaque projet une étape `story` **validée et vide** : `_script` prend alors l'ancien chemin
(un seul appel), `mark_stale` ignore cette story vide et la génération du plan s'arrête sur `script`. Aucune donnée n'est
migrée.

## `result` de l'étape
```
{"bible": "style, décor, palette (anglais)",
 "elements": [{"id", "kind": "character|prop|place", "name", "descriptor", "prompt"}],
 "beats": [{"summary", "voice_text", "duration_s", "continuity": "continue|cut", "elements": [{"id", "state"}]}],
 "warnings": [...]}
```
`descriptor` : apparence figée (anglais, 40 mots au plus). `prompt` : image de référence (vide pour un lieu). `state` :
condition physique visible de l'élément dans ce beat (« dry », « zipper jammed »), jamais l'action en cours.

## Passes
1. **Histoire** (`story_prompt`, `STORY_SCHEMA`) : beats avec résumé, voix off, durée ; causalité, accroche, appel à
   l'engagement (`ENGAGEMENT_RULE`). Contrôle : `script_problems` (durée ±20 %, voix trop longue, engagement). Une relance
   ciblée.
2. **Inventaire** (`inventory_prompt`, `INVENTORY_SCHEMA`) : fiche de style, éléments, éléments visibles de chaque beat avec
   leur état. Contrôle : `story_problems`. Une relance ciblée de cette passe seule.
Au plus 4 appels (2 passes + une relance chacune). Défauts restants : `result.warnings`. L'appel à l'engagement est garanti
(`ENGAGEMENT_FALLBACK`).

## Enchaînement des scènes (`continuity`)
Chaque beat dit s'il **suit directement le précédent** (`continue` : même lieu, l'action et le décor continuent, le cadrage
change) ou s'il **coupe** (`cut` : changement de lieu, ellipse). `parse_story` normalise : valeur absente ou inconnue →
`cut`, premier beat toujours `cut` (l'admin applique la même règle à l'enregistrement). Le script copie la valeur sur
`Scene.continuity` (migration `0013`, `cut` par défaut : un projet existant n'est jamais enchaîné). Modifiable dans l'écran
Plan (« Enchaînement » de chaque beat à partir du deuxième).

À la génération des clips, une scène `continue` part de la **dernière image du clip précédent** (`montage.last_frame`, ffmpeg) :
c'est l'image que le provider reçoit déjà dans `image=`, donc Kontext replace personnages, tenue, style et décor de cette
image dans le nouveau plan, puis Wan I2V l'anime. Les scènes sont alors générées **une à la fois dans l'ordre des positions**
(sans scène `continue` à générer, la concurrence habituelle du provider reste en vigueur). La scène précédente est
le clip produit pendant ce lancement, sinon son clip sélectionné ; sans clip précédent, la scène retombe sur son élément de
référence. Spike du 2026-10-26 (projet 52, scènes 3 → 4) : personnage, blazer, style et décor conservés, alors que le clip
généré sans chaînage changeait de style et perdait le personnage ; les détails fins d'un accessoire (la chaîne dorée du sac)
se perdent encore, ce que doit corriger l'envoi de plusieurs images à Kontext (chantier suivant).

## Voix par personnage (`speaker`, `voice_id`)
Chaque beat a un **locuteur** (`speaker`) : l'id du personnage qui prononce sa voix off (réplique, pensée à la première
personne), vide pour le narrateur ; la passe inventaire le décide (`INVENTORY_SCHEMA`). `story_problems` refuse un locuteur qui n'est pas un
personnage de la liste. Chaque personnage a une voix (`voice_id`, identifiant du catalogue ElevenLabs des réglages) :
`assign_voices` donne à chaque personnage qui parle et n'en a pas une voix distincte du catalogue, autre que celle du
narrateur (`default_voice_id`) ; sans voix disponible, `voice_id` reste vide (voix par défaut). Tout se corrige dans l'écran Plan (« Qui
parle » de chaque beat, « Voix quand il parle » de chaque personnage). Le script copie le locuteur sur `Scene.speaker`
(migration `0014`, vide par défaut : un projet existant garde sa voix unique) ; l'étape Voix choisit la voix scène par scène
(`_voice`). Un `PATCH /steps/story` refuse un identifiant de voix invalide ou un locuteur absent des éléments.

## Plusieurs images pour Kontext
Le prompt envoyé est allégé (`compact_prompt`) : le descripteur d'un élément dont l'image part avec le clip, quand il est recopié mot pour mot, est remplacé par son nom. Le prompt stocké et affiché ne change pas.

Une scène envoie à Kontext jusqu'à **2 images** (`MAX_KONTEXT_IMAGES` ; à 3 sujets Kontext en perd toujours un, mesuré sur la scène « chauffeur, assassin, voiture ») : l'image principale (dernière image du clip précédent
pour une scène `continue`, sinon l'image de son élément principal `Scene.reference`), puis les images des **autres éléments
visibles** dans la scène (`Scene.elements`) qui ont une image de référence, personnages d'abord puis accessoires dans l'ordre
de la scène (`extra_references`). Le workflow (`kontext_workflow`) enchaîne un `ReferenceLatent` par image
(LoadImage → ImageScale 576×1008 → VAEEncode → ReferenceLatent) avant le guidage ; le provider ComfyUI envoie chaque image sous
un nom distinct (`vv_reference.png`, `vv_reference_2.png`…). `generate(..., references=[...])` n'est passé au provider que
s'il y a des images en plus : un provider qui n'en fait rien (fal) les ignore. Spike du 2026-10-26 (projet 54, scène 2 : dernière
image + personnage + sac) : le personnage reprend la tenue et les cheveux de son image de référence, au prix d'un calcul
nettement plus long (≈ 10 minutes de Kontext pour 3 images contre ≈ 5 pour une, **mesure indicative** : la machine servait
aussi à autre chose, à refaire à vide), d'où le plafond. Si l'image principale et une référence se
contredisent (sac différent), l'image principale l'emporte ; en pratique les références existent avant les clips.

## Contrôles (`story_problems`)
Inventaire vide ; beat sans aucun élément visible ; id cité par un beat et absent des éléments ; élément cité par aucun beat ; accessoire vu dans un seul beat (hors les deux
derniers, où il peut être résolu) ; état qui revient à une valeur déjà quittée.

## Étape `script` à partir de la story
Un appel court par beat (4 en parallèle, `SCENE_CALLS`) : `scene_prompt` donne le style, le beat, la voix off, la scène
précédente et, pour chaque élément présent, son descripteur et son état. Le serveur ajoute en tête du `visual_prompt`
les descripteurs absents (`with_descriptors` : un personnage y est nommé), voix off et durées sont copiées du beat. Les
scènes ne sont remplacées qu'une fois tous les prompts reçus. `Scene.elements` garde `[{"id", "state"}]` ;
`Scene.reference` vaut le premier personnage présent, sinon le premier accessoire qui a une image. `result.references`
vient des éléments `character` et `prop` (au plus 6), ce qui laisse `reference` et `clips` inchangés ; `result.bible` est la
fiche de style suivie des descripteurs, assemblée par le serveur.

## Consigne et enregistrement manuel
Une consigne de l'utilisateur (`POST …/steps/{story|script}/run {"instruction"}`) s'applique à la réécriture de l'histoire, et
à chaque prompt de scène lors de l'écriture des scènes. `PATCH /steps/story` refuse (`422`) un `result` non vide mal formé
(`story_result_errors` : au moins un beat, résumé et voix off non vides, durée > 0, ids de beats présents dans les éléments).

## Écran Plan et éditeur
Phase « histoire » de l'écran Plan (`StoryView`, une colonne centrée) : avertissements, puis trois sections titrées
comme celles du plan prêt (`plan-section`) : **Style** (fiche de style), **Éléments suivis** (compteur par type,
`elementCounts` : « 1 personnage, 1 accessoire, 1 lieu » ; cartes avec le nom et une pastille de type, puis nom, type,
apparence, voix d'un personnage, prompt de référence hors lieux) et **Beats** (compteur « 4 beats, 30 s sur 30 s visées » ;
cartes avec numéro et durée, puis résumé, voix off, durée, qui parle, enchaînement, éléments visibles et leur état).
Une section vide le dit dans un cadre en pointillés (`.empty`) avec ce qu'il faut ajouter. « Écrire les scènes » est
dans la barre d'action du bas commune à « Valider le plan et générer » (`PlanFoot` : ce qui va se passer à gauche,
masqué sur mobile, l'action à droite). Génération en cours, échec et plan jamais généré (`PlanProgress`, logique
`planProgress` dans `planChat.ts`) : les trois étapes du plan (Idée, Histoire, Scènes) avec leur état écrit (« Prête »,
« En cours », « Échec », « À venir ») et teinté, le temps écoulé de l'étape en cours, l'erreur sous l'étape en échec,
puis « Arrêter », « Réessayer » ou « Générer le plan ». Enregistrer (`PATCH /steps/story`) ; « Écrire les
scènes » (qui ne valide l'histoire que si elle ne l'est pas déjà) est bloqué tant que le brouillon n'est pas enregistré. Un id de beat absent des éléments, ou un beat sans résumé
ni voix off, empêche l'enregistrement. Dans l'éditeur, l'outil Script contient le panneau Histoire (`StoryPanel`).

## Banc d'essai
`backend/scripts/eval_script.py [modèle] [--pipeline old|new|both]` (clé `GEMINI_API_KEY`). Mesure du 2026-10-26 (modèle
Gemini par défaut, une réponse par thème, **sans relance**) : le nouveau pipeline n'a aucun accessoire orphelin ni id inconnu
sur 4 thèmes sur 6 (le thème du projet 52 : 18 beats, 0 défaut ; « McDonald's » : 3 accessoires orphelins ; « œufs brouillés » :
2). Descripteurs absents des prompts écrits par le LLM avant l'ajout du serveur : 7 sur 18 scènes pour le thème du projet 52,
d'où la garantie côté serveur. Objectif du design : zéro orphelin sur 4 thèmes sur 5 ; la relance automatique de
l'inventaire, non mesurée par le banc, vise les cas restants.

## Limites connues
- La story ne se rouvre pas depuis l'éditeur une fois validée (seulement quand elle est périmée, via l'écran Plan).
- Le chat du plan et l'assistant IA agissent sur les scènes, pas sur la story.
- Au-delà de 2 images, les accessoires en trop sont ignorés (un accessoire clé peut manquer si la scène en montre beaucoup).
- Régénérer le clip d'une scène ne périme pas les scènes enchaînées qui la suivent : leur image de départ vient de l'ancien clip.
- `continuity` se modifie dans la story (puis « Écrire les scènes ») ou scène par scène via la case « Enchaîner » de Clips (voir `references.md`).

## Durée totale
Les LLM écrivent des histoires plus courtes que demandé (26 s pour 30 s mesurées). Quand la somme des `duration_s` s'écarte de plus de 10 % de la durée cible, `fit_durations` (`services/llm_json.py`) rééchelonne les beats (au demi-seconde, entre 2 s et 5 s, le maximum d'un clip Wan) ; la voix off garde son texte.
