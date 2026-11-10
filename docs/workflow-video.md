# Workflow vidéo (pipeline d'étapes)

Service : `backend/app/services/pipeline.py` (contexte, exécuteurs, `run_step`), avec `prompts.py` (textes envoyés aux LLM, dont `VISUAL_PROMPT_GUIDE`), `script_parsing.py` (lecture et contrôle des réponses), `timeouts.py` (`step_timeout`, `job_timeout`) et `choices.py` (provider et modèle d'un lancement). Point d'entrée : `run_step(ctx, project_id, step_name, scene_id=None)`.

## Parcours de création
Trois temps : **Nouvelle vidéo** (`/new` : idée, style, durée) → **Plan** (`/projects/:id/plan` : `idea` puis `story`
générées d'un trait ; l'histoire (beats et éléments suivis) est relue et modifiée ; « Écrire les scènes » lance `script`, dont
les scènes sont relues avec le chat de l'IA) → **éditeur** (`/projects/:id`, étapes suivantes). « Créer le plan » lance un
autopilot borné à `story` (`POST /projects/{id}/plan/generate`, voir `autopilot.md` ; borné à `script` pour un projet
existant sans story) : `idea` est validée automatiquement, `story` reste à valider. « Valider le plan et générer » valide `script`
et ouvre l'éditeur. Voir `story.md`.
Le **style** du projet (`Project.style` : `realistic`, `anime`, `illustration`, vide = aucun ; `services/styles.py`) ajoute
au prompt du script la ligne « Style visuel imposé : <directive> » (directive en anglais, reprise dans la fiche visuelle
et chaque prompt visuel). Changer le style rend les étapes produites périmées, comme le thème ou la durée.

## Les 9 étapes
`idea` → `story` → `script` → `reference` (optionnelle) → `clips` → `voice` → `music` → `montage` → `final`.

## États d'une étape
`pending`, `running`, `awaiting_validation`, `approved`, `failed`, `stale` (voir `app/state.py`).
L'API passe l'étape à `running` puis enfile le job ; `run_step` exécute l'exécuteur puis :
- succès → `awaiting_validation`, `result` enregistré, `error` vidé ;
- échec → `failed` avec un message lisible dans `error` (`ProviderError` tel quel, sinon `TypeErreur: message`). L'étape est relançable.
Après chaque changement, un événement `{project_id, step, status, error}` est publié via `ctx.publish`.
Si la session est en état d'erreur (erreur DB), elle est rollback avant d'enregistrer l'échec.

## Exécuteurs
| Étape | Action | `result` |
|---|---|---|
| `idea` | Le LLM développe un angle à partir du thème, de la plateforme, de la durée cible (et `params.hint`) : une seule proposition directe, 2 à 4 phrases, sans introduction ni markdown. | `{"angle"}` |
| `story` | L'histoire en deux passes (beats : résumé, voix off, durée ; puis éléments suivis et leur état dans chaque beat), contrôlée mécaniquement (`story_problems`, `script_problems`), une relance ciblée par passe. Voir `story.md`. | `{"bible", "elements", "beats", "warnings"?}` |
| `script` | **Avec une story écrite** : un appel court par beat (descripteurs et états des éléments présents, voix off et durées copiées de la story) ; sans story (projet existant, story validée et vide) : ancien chemin ci-dessous. Le LLM découpe en scènes (JSON, sortie structurée `SCENES_SCHEMA`). Prompt (`script_prompt`) : brief, angle entre `<<<`/`>>>` (sa mise en forme markdown n'est pas à reproduire), nombre de scènes de 2 à 6 s dont la somme vaut la durée cible (±10 %) ; `params.scene_length_s` (nombre, défaut `null` = libre) impose des scènes d'environ cette durée, le nombre de scènes valant alors environ durée cible / `scene_length_s` (`parse_scenes` inchangé), voix off française à environ 2,5 mots par seconde (budget total et par scène), `visual_prompt` en anglais selon `VISUAL_PROMPT_GUIDE` : **deux paragraphes**, l'image de départ (80 à 130 mots : sujet dans sa pose, décor, lumière, style) puis `Motion: …` (30 à 60 mots : action en 2 ou 3 gestes, phrase de caméra explicite comme « low-angle tracking shot, the camera smoothly dollies backward ») ; voir « Style de prompt » dans `providers.md`. Réponse lue par `parse_scenes` (voir ci-dessous) ; scène invalide → **une** relance ciblée avec l'erreur et la réponse précédente renvoyées au LLM (appel tracé et facturé), puis échec « script: scène N incomplète (champ vide) (après une relance automatique) ». Les `Scene` du projet sont supprimées puis recréées (positions 1..n) ; les assets existants sont conservés (scène détachée). Échec → scènes intactes. **Fiche visuelle** (`bible`, texte en anglais, ≤ 4000 car., stocké dans `result.bible`, éditable dans le panneau et via `PATCH …/steps/script` `result`) : personnages récurrents, marques (nom exact, forme, logo décrit), décor, palette, style ; chaque `visual_prompt` la reprend mot pour mot car le générateur vidéo ne voit ni les autres scènes ni la fiche. La **première scène est l'accroche** (2 premières secondes) et la **dernière scène est toujours l'appel à l'engagement** (`ENGAGEMENT_RULE` : 4 à 5 s, voix off de 10 mots au plus qui contient « like », « commente » et « partage » avec une question précise sur le sujet, exemple fourni au LLM ; l'avant-dernière porte la chute). Le chat du plan et l'assistant IA (voix off de la dernière scène) appliquent la même règle. **Validation** (`script_problems`) : somme des durées à ±20 % de la cible, voix off ≤ 1,5 × le budget de mots de la scène + 3, dernière scène nommant liker/commenter/partager (`has_engagement`) ; sinon **une** relance ciblée avec ces défauts. Après la relance, l'appel à l'engagement est garanti (`ENGAGEMENT_FALLBACK` ajouté à la voix off de la dernière scène) et les autres défauts restants sont listés dans `result.warnings` sans bloquer. Le prompt demande de la continuité entre scènes voisines avec un cadrage différent, et accepte une **consigne** de l'utilisateur (`POST …/steps/script/run` `{"instruction"}`, ≤ 1000 car., pour ce lancement seulement). La fiche sert aussi de prompt par défaut à l'image de référence et de contexte à l'assistant IA (champ `bible`). Limite connue : avec ComfyUI en texte-vers-vidéo (profils Rapide, Équilibré, Maximum), l'image de référence n'est pas transmise au modèle ; seul le texte (la fiche) assure la ressemblance. | `{"scene_count", "bible"}` |
| `reference` | Image de référence (`params.prompt`, `params.provider` et `params.model`, défaut réglage `image_provider` = Gemini et son modèle `gemini_image_model`, ou fal/`flux`, ou `comfyui`/`flux-dev` : Flux dev local, gratuit, ≈ 3 min par image, modèles gardés en mémoire entre deux images puis déchargés en fin d'étape) → `Asset(kind="reference")`. Modèle inconnu (`400`) ou indisponible (`409`, ex. clé fal manquante) refusé au lancement, avant tout job. | `{"asset_id"}` |
| `clips` | Un clip par scène (ou la scène `scene_id`). Provider/modèle : `ctx.overrides` (choix ponctuel passé au lancement, non enregistré), sinon `params.provider`/`params.model`, sinon réglages `default_video_provider`/`default_video_model` (défauts `comfyui` / `fast`). Modèle ComfyUI = id d'un profil de génération (`fast`, `balanced`, `precision`, `max` ; `docs/profils-generation.md`). L'image passée en `image=` est la référence de la scène (ou la dernière image du projet) ; pour une scène `continue` (voir `story.md`), c'est la dernière image du clip précédent, et les scènes sont alors générées une à la fois dans l'ordre. Les images des autres éléments visibles de la scène (personnages d'abord, 2 images au plus) sont passées en `references=` et toutes envoyées à Kontext (`ReferenceLatent` enchaînés). Profil `precision` : l'image de départ Flux est aussi stockée (`Asset(kind="keyframe")`, `meta.clip_asset_id` = id du clip, coût 0), l'admin l'affiche en `poster` de la variante. Mode avatar parlant (`Project.lipsync`) : une scène dont le personnage qui parle est visible est générée en lip-sync sur sa voix (`avatar-parlant.md`). Un clip généré pour une scène sans `selected_clip_asset_id` est sélectionné d'office (première variante) ; un choix existant n'est jamais écrasé. | `{"asset_ids"}` |
| `voice` | Voix off par scène : la voix du personnage qui parle (`Scene.speaker`, voix choisie dans la story : `voice_id` de l'élément), sinon la voix du narrateur (`params.voice_id`, sinon réglage `default_voice_id`) ; une scène sans aucune voix → échec avant tout appel (voir `story.md`). Chaque voix garde `meta.text` et `meta.voice_id` (réutilisée par le lip-sync). | `{"asset_ids"}` |
| `music` | Valide `params.track_id` dans la bibliothèque (aucun appel provider). Sans `track_id` : pas de musique. | `{"track_id"}` |
| `montage` | (Segments mis en cache par scène : voir « Montage incrémental » plus bas.) Télécharge pour chaque scène le clip sélectionné (`selected_clip_asset_id`) et la dernière voix (pour un clip lip-sync : la voix de `meta.voice_asset_id`, sans changement de vitesse), plus la musique éventuelle, dans un dossier temporaire ; rendu FFmpeg (`montage.render`) → `Asset(kind="render")`. | `{"asset_id", "duration_s"}` |
| `final` | Le LLM propose (sortie structurée `FINAL_SCHEMA`) titre, description, hashtags → `Project.metadata_json` (clés manquantes : titre du projet, description vide, aucun hashtag). Une édition du `result` via l'API met aussi à jour `metadata_json`. | métadonnées |

## Règles communes
- Un LLM est appelé avec `json_schema` seulement pour les étapes JSON (`script`, `final`) : un provider à l'ancienne
  signature (sans ce paramètre) reste utilisable pour les étapes texte.
- `clips` et `voice` génèrent plusieurs scènes en parallèle (`_per_scene`) : `CLIP_CONCURRENCY` (fal : 3, ComfyUI : 1,
  inconnu : 1) et `VOICE_CONCURRENCY` (2). Le résultat suit l'ordre des scènes. Les appels provider sont concurrents ;
  les écritures en base (journal des coûts, asset, clip sélectionné d'office) passent une à une par `ctx.writes`
  (`WriteGate`, `services/costs.py`) car la session est partagée, et sont à l'abri de l'annulation. À la première erreur,
  les scènes pas encore lancées sont abandonnées, les appels en cours annulés, `writes.settle()` attend les écritures
  engagées, puis l'erreur d'origine (pas un groupe d'erreurs) est enregistrée sur l'étape : un clip déjà payé et reçu
  est conservé.
- **Reprise après un échec** (`clips`, `voix`). Chaque lancement complet reçoit un `Step.run_id` (migration `0004`) que
  portent les assets qu'il produit (`meta["run"]`) ; une variante isolée (`scene_id`) remet `run_id` à `NULL`. Quand
  l'étape est `failed` et que son dernier lancement a produit des scènes, `GET /projects/{id}` expose
  `resume: {done, total}`. `run {resume: true}` génère seulement les scènes restantes : `launch_step` passe à l'exécuteur
  la liste `skip_scenes` (via les paramètres du lancement, `ctx.overrides`), l'exécuteur reprend leur dernier asset tel
  quel, génère les autres et renvoie `asset_ids` dans l'ordre des scènes. Le budget et le timeout du job ne comptent que
  les scènes restantes.
- **Scènes manquantes** : `run {only_missing: true}` fait pareil dans n'importe quel état, pour les scènes qui n'ont
  aucun clip (aucune voix) : utile après des variantes isolées sur une étape incomplète.
- **Une scène = une requête.** `run {scene_id}` ne génère que cette scène : un seul appel au provider (un seul clip
  ComfyUI), jamais la vidéo entière (testé avec un compteur d'appels). Le lancement d'une scène porte `run_id =
  "scene:<id>:<aléa>"` : s'il échoue, `GET /projects/{id}` expose `target_scene` et « Relancer » ne refait que cette scène ;
  `resume` est refusé (`409`) pour un tel lancement.
- **Arrêter une génération** : `POST /projects/{id}/steps/{name}/cancel` passe l'étape `running` en `failed`
  (« Arrêtée par l'utilisateur », `STOPPED_BY_USER`) et coupe l'autopilot ; ce qui est déjà produit est gardé et se reprend
  (`resume`). `run_step_job` surveille son étape toutes les 5 s (`STOP_POLL_S`) : dès qu'elle n'est plus `running` pour son
  `run_id` (arrêtée, ou arrêtée puis relancée), il annule la génération en cours (ComfyUI : `/interrupt` du clip en
  cours), n'enregistre plus rien, n'écrase pas le message et n'enchaîne pas l'autopilot.
- **Périmètre visible** : pendant une génération, `GET /projects/{id}` donne `target_scene` (une seule scène visée) ou
  `progress: {done, total}` (toutes les scènes) ; l'interface le dit (« Régénération de la scène 5 en cours : cette scène
  seulement » ou « Génération de toutes les scènes en cours : 3 sur 10 »).
- **Nouveau prompt d'une scène** : `run {scene_id, visual_prompt}` (clips) enregistre le prompt sur la scène puis
  régénère son clip seulement ; les autres scènes ne changent pas. Le nouveau clip est choisi d'office pour la scène
  (`select_new`), alors qu'une « Nouvelle variante » simple laisse le choix de l'utilisateur.
- Avant d'être lancée, une étape payante passe le contrôle de budget (`services/budget.py`, `docs/costs.md`).
- Appels provider via `tracked_call` (journal des coûts, retries), timeout 900 s pour `clips` (5700 s avec ComfyUI, génération locale lente : `step_timeout`), 600 s pour `montage`, 300 s sinon (1800 s pour `reference` avec ComfyUI). Le timeout du job compte un appel par scène (clips, voix) ou par élément récurrent (reference).
- Une réponse provider vide est une erreur : pas d'asset créé, coût non facturé.
- Réponses LLM : la valeur JSON est lue sur le texte entier (sortie structurée), sinon dans un bloc ```` ``` ````, sinon
  le premier objet ou tableau du texte (`_json_value`, `_extract_json`).
- `parse_scenes(text, target_duration_s)` (tolérant) : accepte `{"scenes": [...]}` ou un tableau seul, les noms de champs
  courants (`voiceover`, `narration`, `visual`, `duration`…), un texte en liste, une durée en texte (« 4 s », « 4,5
  secondes ») ; ignore les champs en trop. Une durée absente, nulle, absurde (format horaire « 00:04 », millisecondes,
  plus de 60 s) reçoit une part égale du reste de la durée cible, jamais moins de 2 s (4 s sans reste ni cible). Voix off et prompt visuel restent obligatoires : l'erreur nomme chaque scène et champ vide.
- Bug corrigé le 2026-10-18 : avec Gemini et un angle markdown long, l'étape échouait (« scène incomplète ») sur des
  réponses exploitables (durée « 4 s », clés différentes) ; la sortie structurée, le parse tolérant et la relance
  ciblée le règlent.
- Stockage : `projects/{project_id}/{kind}/{uuid}.{ext}` ; chaque nouvel asset prend la variante `max(variant)+1` pour (projet, type, scène).

## Validation manuelle, régénération et invalidation
- Une étape produite passe en `awaiting_validation` ; l'utilisateur la valide (`approve` → `approved`) ou la relance (`run`). Une étape ne peut démarrer que si les étapes dont elle dépend (`REQUIRES`, `app/state.py`) sont `approved` (`can_start`) : voix et musique ne dépendent que du script, donc se génèrent pendant les clips, et seul le montage attend clips, voix et musique. Une régénération ne périme que ses dépendants (`dependents` : les clips périment le montage et le rendu, pas la voix) ; `reference` est optionnelle : l'ignorer = l'approuver sans résultat.
- Relancer ou éditer (`PATCH`) une étape fait passer toutes les étapes aval déjà produites (approuvées ou à valider) en `stale` (`downstream`), sans supprimer leurs assets. Une étape `stale` peut être relancée ou approuvée telle quelle. L'étape optionnelle ignorée n'est pas marquée `stale`.
- Changer le brief du projet (`PATCH /projects/{id}`) ou le clip choisi d'une scène (`select-clip`) rend périmées les étapes concernées (voir `api.md`).
- Chaque régénération crée une nouvelle variante d'asset (`variant`), les précédentes restent consultables et sélectionnables (clips).
- Une étape `running` ne peut être ni éditée ni relancée (409).
- Mode automatique : le worker valide chaque étape terminée et lance la suivante, jusqu'au rendu final ; arrêt sur la première erreur (voir `autopilot.md`).

## Montage incrémental
Chaque scène montée (clip recadré 9:16 à la durée de la voix, voix calée) est un **segment** stocké sous
`projects/{id}/segments/{empreinte}-{clip}-{voix}.mp4|.wav` (`montage.segment_key`). Il ne dépend que de son clip et de
sa voix, qui ne changent jamais (une régénération crée un nouvel asset), et de l'empreinte des réglages d'encodage
(`montage.SEGMENT_VERSION` : taille, cadence, filtres, marge). Au montage, `_montage` réutilise les segments existants et
n'encode que les scènes nouvelles : après la régénération d'une scène sur dix, un seul segment est encodé, puis
`montage.assemble` produit la vidéo (sous-titres, mixage, normalisation). `result` du montage porte
`segments_rendered` et `segments_reused`. Les segments sont supprimés avec le projet (`delete_prefix`) ; ceux des
variantes abandonnées restent jusque-là.

## Banc d'essai du script
`backend/scripts/eval_script.py [modèle Gemini]` (clé `GEMINI_API_KEY`, `PYTHONPATH=.`) : idée puis script sur 5 thèmes fixes
(styles réaliste, anime, illustration, aucun ; 20 à 45 s), sans base de données. Il affiche par thème : JSON valide,
`script_problems` (durée, voix trop longue, engagement), éléments de référence, descripteurs ajoutés par le serveur,
scènes avec paragraphe `Motion:`, longueur des prompts. À relancer après toute modification des prompts pour comparer
deux versions. Mesure du 2026-10-25 (`gemini-3.5-flash-lite`, une réponse par thème, sans relance) : 5 JSON valides sur 5,
paragraphe `Motion:` dans toutes les scènes, descripteurs recopiés tels quels, appel à l'engagement correct 4 fois sur 5
(le 5e : voix off trop longue, que la relance automatique corrige) ; avant l'exemple dans `ENGAGEMENT_RULE`, le modèle
écrivait « commente et abonne-toi » sans like ni partage (0 sur 5). Budget de sortie : `script_max_tokens`.
