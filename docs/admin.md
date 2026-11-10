# Admin (React)

Code : `admin/` (Vite + React + TypeScript, react-router). Interface en français, thème sombre.

## Lancer
```bash
cd backend && .venv/bin/alembic upgrade head && FAKE_PROVIDERS=true .venv/bin/uvicorn app.main:app --port 8000 --timeout-graceful-shutdown 2
cd admin && npm install && npm run dev   # http://localhost:5173
```
Le serveur Vite relaie `/api` vers `http://localhost:8000` (`vite.config.ts`) : le cookie `session` reste sur la même origine.
Tests : `npm test` (vitest). Build : `npm run build`. Lint : `npm run lint`.

## Écrans
- **Connexion, inscription, vérification, mot de passe oublié** (`/login`, `/register`, `/verify`, `/forgot`, `/reset`) :
  voir `docs/comptes.md`.
- **Projets** (`/`, `pages/Projects.tsx`) : la bibliothèque, avec un bouton « Nouvelle vidéo » vers `/new`.
  - **Vos vidéos** : recherche (titre et sujet, délai de saisie de 250 ms), filtre « Toutes / En cours / Terminées » et tri
    (plus récentes, plus anciennes, titre A→Z, plus coûteuses) : `GET /projects?q=&status=&sort=&limit=` (`libraryPath`,
    `home.ts`). Pagination par « Voir plus (N restantes) » : la liste est rechargée avec `limit` augmenté de 24, ce qui
    reste cohérent avec les rafraîchissements SSE. Sans résultat : « Aucune vidéo ne correspond à cette recherche » et
    « Effacer la recherche et les filtres ». Grille de cartes 9:16 (plus récentes d'abord par défaut ; 2 colonnes sous 720 px). Les cartes qui ont un rendu affichent un lien « Exporter » (`render_asset_id`, téléchargement depuis MinIO). Vignette : `thumbnail_url`
    de `GET /projects` (dernier rendu, sinon clip choisi de la première scène, `<video preload="metadata">`), sinon aplat
    teinté par l'état. Titre (lien vers l'éditeur, cible de clic sur toute la carte), avancement en 8 segments (validées
    en gris clair, courante à la couleur de l'état, libellé accessible « Étape 4 sur 8 : Clips »), état et coût.
    État (`cardState`, `home.ts`) : « Terminée », « Échec : <étape> », « En génération… » (autopilot actif, pastille et
    segment courant pulsés, sans animation si `prefers-reduced-motion`), sinon « <statut> : <étape> » (« À valider :
    Clips »). Bouton corbeille sur la vignette (au survol ou au focus, toujours visible sur écran tactile) →
    « Supprimer la vidéo ? » (`ConfirmDialog`) → `DELETE /projects/{id}` ; échec affiché au-dessus de la grille.
    Liste rechargée à chaque événement SSE ; liste vide : « Pas encore de vidéo : choisissez « Nouvelle vidéo » pour décrire une idée. »
  - Logique pure dans `home.ts` (tests `home.test.ts`) : `progress(current_step)`, `cardState`, `libraryPath`.
- **Nouvelle vidéo** (`/new`, `pages/NewVideo.tsx`, logique pure `newVideo.ts`) : premier temps du parcours en trois temps
  (idée → plan → éditeur). « Partir d'un modèle » (`src/templates.ts`) : six formats ; un clic remplit l'idée, la durée et la
  durée des scènes (non affichée, envoyée en `params.scene_length_s`) ; le marqueur `[sujet]` est sélectionné pour être
  remplacé en tapant (bande défilante sous 720 px). « Votre idée » (devient le thème ; assistant IA), **style** en choix
  unique (« Aucun » puis les styles de `GET /styles` : Réaliste, Anime, Illustration), **durée** en pastilles (15, 30, 45,
  60 s) ou saisie libre de 5 à 180 s (`parseDuration`). Un seul bouton, « Créer le plan » (désactivé sans idée ni durée
  valide) : `POST /projects` (titre tiré de l'idée par `titleFromSubject`), `PATCH …/steps/script` si une durée de scène
  est imposée, `POST …/plan/generate`, puis ouverture de `/projects/:id/plan`. Si la création réussit mais pas le
  lancement, le message et un lien « Ouvrir le plan » s'affichent ; un nouvel essai ne recrée pas le projet.
- **Plan** (`/projects/:id/plan`, `pages/Plan.tsx`, `components/plan/`, logique pure `planChat.ts`) : deuxième temps.
  Disposition en trois colonnes : chat à gauche (≈ 26 %), plan au centre, panneau **Apparence** à droite (≈ 24 %) ; sous
  860 px : plan, Apparence puis chat. États (`planPhase`) : génération en cours (« L'IA
  prépare votre plan », étapes Idée / Histoire / Scènes avec leur état et le temps écoulé, « Arrêter »), échec ou plan
  jamais généré (mêmes étapes, erreur sous l'étape en échec, « Réessayer » / « Générer le plan », jamais un écran vide),
  histoire à relire (voir `story.md`), plan prêt. Barre d'action du bas commune (`PlanFoot`). Plan prêt (`PlanView`) : **Casting** (`CastStrip` sur `castOf`, une vignette 9:16 par
  personnage / accessoire / lieu, son type et son nombre de scènes ; les vignettes passent de « Génération… » à l'image
  sans recharger, au fil des événements SSE relayés par `useProject` ; « À générer » si le lancement automatique a été refusé (budget, générateur) ou pour un élément ajouté, sans bloquer la validation ; « Générer » / « Réessayer » relancent un seul
  élément : `run("reference", undefined, { overrides: { reference_id } })`), puis **Scènes** en cartes dépliées et
  repliables (`SceneCard collapsible` avec `cast`) : vignette de l'élément principal de la scène (`Scene.reference`),
  pastilles des éléments visibles avec leur état et ligne d'enchaînement (`SceneChips`), case « Enchaîner avec la scène
  précédente » (`setSceneContinuity`, même action que la case « Enchaîner » des Clips) ; une scène enchaînée est reliée
  à la précédente par un filet d'accent. Pastilles, vignette et enchaînement viennent de la scène enregistrée (une scène
  ajoutée au brouillon n'en a pas avant l'enregistrement) ; tant que l'ordre du brouillon diffère de l'ordre enregistré,
  la ligne d'enchaînement, le filet et la case sont masqués (ils seraient faux). **Verrous** (`planLocks`,
  `planChat.ts`) : les images de référence qui se génèrent ne gèlent pas l'écran (validation, case « Enchaîner »,
  assistants restent actifs) ; seuls « Enregistrer le plan » (l'API refuse, 409 : le job lit les scènes, raison affichée
  devant le bouton) et le chat (409 tant qu'une étape tourne) attendent leur fin. Toute autre étape en cours ou une action
  en vol verrouille l'écran. « Ajouter une scène », « Enregistrer le plan » (collé en bas
  de la colonne) quand le brouillon change (`usePlanDraft`, partagé avec l'onglet Script), et « Valider le plan et
  générer » (confirmation : le plan est figé, les images du casting manquantes sont lancées par l'API à la validation, clips, voix, musique et montage se lancent ensuite depuis la page projet ; `approve("script")` puis page projet). Panneau Apparence (`AppearancePanel`) : fiche visuelle (`AssistField`,
  enregistrée avec le plan), style du projet, modèle des images de référence (celui de l'étape, sinon le défaut
  `image_provider`) et dépense de la vidéo (`CostSummary`). Le chat (`ChatPanel`) : Entrée
  envoie, Maj+Entrée saute une ligne ; « Plan modifié · Annuler » sous le dernier changement de l'IA ; refusé avec un
  message si des modifications ne sont pas enregistrées ou si une étape tourne (`chatBlockedReason`). **Redirection** :
  l'éditeur renvoie ici tant que l'idée ou le script n'est pas validé (`needsPlanScreen`, y compris pour les anciens
  projets) ; l'écran Plan renvoie vers l'éditeur dès que le script est validé : les deux règles s'excluent, pas de boucle.
- **Éditeur « Studio »** (`/projects/:id`) : voir ci-dessous.
- **Musique** (`/music`), **Réglages** (`/providers`, page « Réglages »), **Coûts** (`/costs`) : voir ci-dessous.

Barre latérale fine (`components/Layout.tsx`, 72 px) : repère 9:16 à l'accent, puis icône SVG inline (`components/icons.tsx`)
+ libellé court : Projets, Musique, Réglages (`/providers`), Coûts (Musique, Réglages et Coûts : administrateur seulement) ; masquée dans l'éditeur et l'écran Plan (plein cadre) ;
« Sortir » (déconnexion) en bas. Sous 720 px, elle devient une barre horizontale en haut.
La garde d'auth (`components/Layout.tsx`) appelle `GET /api/auth/me` ; toute réponse `401` renvoie vers `/login` (sauf
sur les écrans de compte) ; bandeau « Confirmez votre adresse e-mail » tant que l'adresse n'est pas vérifiée.
Backend injoignable (réseau, proxy sans backend, 5xx sans réponse JSON de l'API) : écran « Serveur injoignable » avec « Réessayer ».
La liste des projets affiche « Chargement… » puis, en cas d'échec, le même message avec « Réessayer ».
« Se déconnecter » appelle `POST /api/auth/logout` ; en cas d'échec, le message s'affiche sous le bouton.

## Éditeur « Studio » (`/projects/:id`)
Code : `pages/Studio.tsx` (+ `Studio.css`), `components/studio/` (`Pipeline`, `SceneList`, `Preview`, `Timeline`),
`components/StepPanel.tsx`, `components/panels/*Panel.tsx`, `hooks/useProject.ts`, `hooks/useDraft.ts`,
`hooks/usePlayer.ts`, logique pure `src/studio.ts` (tests `studio.test.ts`).

- **Mise en page** (plein cadre, sans la barre latérale de l'admin) : en-tête, frise des étapes (`Pipeline`), puis
  `[scènes 252 px] [aperçu 9:16 centré] [panneau de l'étape 380 px]`, timeline pleine largeur en bas ; seuls la liste des
  scènes et le panneau défilent. Sans scène (avant le script), la colonne des scènes disparaît. Sous 900 px : l'éditeur
  tient dans l'écran (`100dvh`). En-tête compact et frise des étapes restent en haut, un seul volet occupe le milieu et
  la barre d'onglets `MobileTabs` (Aperçu, Scènes, Étape) est en bas : « Aperçu » = aperçu + timeline (28 px par seconde
  au minimum), « Scènes » = liste verticale, « Étape » = panneau. Choisir une scène ramène à l'aperçu, ouvrir une étape
  (frise, « Reprendre », régénérer un clip ou une voix) ouvre l'onglet Étape. État `pane` dans `Studio.tsx`, attribut
  `data-pane` sur `.studio`. Les détails de libellé (`.hide-narrow`) disparaissent sur petit écran.
- **Scènes** (`SceneList`) : storyboard, une ligne par scène (vignette 9:16 du clip choisi, texte dit, durée, repères
  « Clip » et « Voix » à la couleur de piste, creux tant que le média manque), puis, sous la ligne, les pastilles des
  éléments visibles avec leur état et, pour une scène enchaînée, « Enchaînée : part de la dernière image de la scène N »
  (`SceneChips`, comme à l'écran Plan ; une coupe n'est pas écrite). Un trait d'accent vertical dans la marge du rail
  relie les scènes d'une même suite enchaînée (classes `is-chained` / `chains-next`). Cliquer sélectionne la scène
  (partagée par l'aperçu, la timeline et les panneaux) ; flèches et espace fonctionnent depuis la liste.
- **En-tête** : retour aux projets (icône), titre éditable en place (Entrée ou sortie du champ → `PATCH /projects/{id}`,
  Échap annule, titre vide refusé), coût cumulé (libellé « Dépensé » ; le détail par étape et le plafond s'affichent au survol ou au focus, sans clic), état de l'autopilot si actif (« Génération automatique : Clips 4/10 »,
  pastille pulsée, « Arrêter » → `DELETE /projects/{id}/autopilot`), « Exporter » (téléchargement du dernier rendu
  `/api/projects/{id}/assets/{asset_id}/download`) tant que le rendu est à jour (montage validé ou à valider) ; « Exporter » reste grisé sans rendu ou avec un rendu périmé (clip modifié depuis), l'infobulle dit quoi faire (`exportBlockedReason`, `studio.ts`) ; « Reprendre : étape » s'affiche dans ce cas. Erreurs de ces
  actions (portée `studio` de `useProject`) affichées sous l'en-tête.
- **Frise des étapes** (`Pipeline`) : Idée, Script, Clips (regroupe l'image de référence facultative et les clips), Voix,
  Musique, Montage, Export (rendu final), dans l'ordre de production ; pastille + libellé (`toolState` : à faire =
  creuse, en cours = accent pulsée, à valider = moitié pleine ambre, validé = pleine verte avec coche, en échec = pleine
  rouge avec « ! » ; la référence ne compte que si elle a été lancée ; `stale` = à valider). L'étape affichée est
  soulignée. Un outil à plusieurs étapes affiche un sélecteur en tête de panneau (« Image de référence » /
  « Clips » avec leur statut).
- **Étape affichée** : par défaut l'étape courante (`currentStep`) ; un clic sur un outil ouvre l'étape courante s'il la
  contient, sinon son étape principale (`toolStep`). Après une validation réussie, l'éditeur suit de nouveau l'étape
  courante, sauf si un brouillon est modifié. La route remonte l'éditeur à chaque changement de projet (`key={id}`).
- **Aperçu 9:16** (`Preview`, `usePlayer`) : le dernier rendu s'il existe (une vidéo pour toute la timeline ; son temps
  est ramené à l'échelle de la timeline, le montage calant chaque scène sur sa voix ; pendant la lecture, la scène
  sélectionnée suit la tête de lecture) ; sinon le clip choisi de la scène sélectionnée (muet) joué avec sa voix et la musique de fond choisie, texte
  de la voix off en sous-titre superposé, puis enchaînement sur la scène suivante. Chaque scène est jouée comme le montage la calera (`montage.ts`, miroir de `converge` : durée = voix et clip convergés + 0,3 s, voix accélérée ou ralentie, clip étiré ; durées lues dans les métadonnées des médias, `useMediaDurations`) : la voix n'est jamais coupée, la timeline reflète la durée réelle de chaque scène, et une horloge (pas la fin du clip) décide du passage à la suivante, en attendant un média qui charge encore. La musique joue en continu sur le temps
  de la timeline (elle ne redémarre pas à chaque scène, boucle si la piste est plus courte que la vidéo, se recale en cas de
  dérive de plus de 0,5 s) au niveau 0,15 du montage (`MUSIC_VOLUME`) ; elle s'arrête à la fin de la dernière scène. Barre : lecture/pause, temps
  `m:ss / m:ss`, source (« Rendu final » / « Scène N »). Sans clip : cadre pointillé explicatif.
- **Timeline** (`Timeline`) : règle (graduation par seconde, libellé toutes les 5 s ; par 5 s / 10 s au-delà d'une
  minute ; clic = placement de la tête de lecture), piste Clips (un bloc par scène, largeur ∝ durée, vignette vidéo,
  numéro), piste Voix (un bloc par scène, premiers mots du texte), piste Musique (un bloc sur toute la durée avec le nom
  de la piste choisie, sinon « Sans musique »), tête de lecture. Couleurs de piste : clips violet, voix turquoise,
  musique ambre. Bloc en cours de génération (étape `running` et média absent) : rayures animées ; bloc vide :
  pointillé « + » qui sélectionne la scène et ouvre l'étape qui le remplit. Cliquer un bloc sélectionne la scène
  (aperçu placé au début de la scène, panneau). Script vide : « La timeline se remplit dès que le script découpe la
  vidéo en scènes. »
- **Raccourcis** : espace = lecture/pause, ← → = scène précédente/suivante (`shortcutFor` : ignorés dans les champs de
  saisie, listes, lecteurs audio/vidéo, groupes radio et modales ; l'espace reste aux boutons et liens, sauf sur les
  blocs de la timeline).
- **URL stables** : chaque rechargement du projet renvoie des URL présignées nouvellement signées ; `stableUrls` garde
  l'URL déjà vue d'un asset tant qu'elle a été signée moins de 30 min avant la nouvelle (`X-Amz-Date`), pour que les
  lecteurs ne repartent pas de zéro à chaque événement SSE.
- **Brouillons protégés** : `useDraft` signale ses modifications non enregistrées (brouillon différent de la source) à
  `DirtyDraftsContext` ; changer d'étape ou revenir aux « Projets » avec un brouillon modifié ouvre « Modifications non
  enregistrées » (« Annuler » / « Quitter sans enregistrer », `ConfirmDialog`) ; fermer ou recharger l'onglet demande
  confirmation au navigateur.
- **`useProject(id)`** : `{project, loadError, refresh, busy, actionError, run, approve, patch, selectClip, updateProject,
  rename, stopAutopilot}` (`rename` et `stopAutopilot` rattachent leur erreur à l'en-tête, portée `studio`).
  Rechargé à chaque événement SSE du projet, après chaque action (succès ou échec) et toutes les 5 s tant qu'une étape est
  `running` (filet si un événement de fin est perdu). `run(step, sceneId?, {params?, overrides?})` : `params` sont
  fusionnés dans les paramètres enregistrés de l'étape (`PATCH`) s'ils changent (champ vide = paramètre absent) ;
  `overrides` (provider/modèle) partent dans le corps de `/run` et ne valent que pour ce lancement. Une action à la fois :
  un second clic dans le même instant est ignoré (garde synchrone). L'erreur d'action est rattachée à l'étape et
  affichée dans son panneau.
- **`StepPanel`** (commun) : en-tête (libellé + badge de statut), bandeaux « Génération en cours », « La génération a
  échoué » + `step.error` + « Relancer », « À régénérer » (`stale`), « Validez d'abord les étapes précédentes » ; pied
  avec actions propres au panneau, « Générer »/« Régénérer » (ou libellé du panneau) et « Valider ». Boutons désactivés
  si `locked` (action en cours, étape `running` ou étape en aval `running`, calculé une fois par l'éditeur et transmis
  aux panneaux). Quand une étape en aval tourne (`downstreamRunning`, via `runningDownstream(steps, name)`), un bandeau
  « Génération en cours : … » explique que l'étape ne peut être ni modifiée ni relancée avant la fin (l'API répondrait
  `409`). Le pied reste collé en bas du panneau qui défile ; une seule action principale à la fois (« Générer » tant
  que l'étape n'a jamais été lancée, puis « Valider »). Options :
  `runBlocked` (génération bloquée, raison affichée), `confirmRun` (précise ce qui est perdu dans la confirmation, toujours demandée avant de remplacer un résultat existant),
  `approveBlocked`. Logique pure dans `steps.ts` (tests `actions.test.ts`) :
  - `availableActions(step, previousApproved)` : `canRun` si l'amont obligatoire est validé et l'étape pas `running` ;
    `canApprove` si l'amont est validé et l'étape `awaiting_validation` ou `stale` (valider tel quel, sauf `RERUN_WHEN_STALE` :
    un montage périmé se relance) ; `showRetry` si
    `failed` et relançable ; `stale`.
  - `previousApproved(steps, name)` (miroir de `can_start`, dépendances `REQUIRES`), `dependents(name)`, `hasResult(step)` (le backend crée `result = {}`),
    `statusLabel(step)` (« Facultative » / « Ignorée » pour la référence).
- **Panneaux** (contenu propre uniquement ; reçoivent aussi `scene`, la scène sélectionnée dans la timeline). Le jargon
  technique (providers, modèles, identifiant de voix) est rangé dans un volet « Avancé » replié (`Advanced`, `ui.tsx`) :
  - **Assistant IA** sur chaque champ texte (titre et thème du brief, piste, angle, voix off et prompt visuel de chaque
    scène, prompt de l'image de référence, titre/description/hashtags de publication ; aussi le sujet de l'accueil) : voir « Assistant IA » ci-dessous.
  - *Idée* : brief (titre, thème, plateforme, durée ; « Enregistrer le brief » → `PATCH /projects/{id}`), piste de départ
    (`params.hint`), « Développer l'angle », angle éditable (« Enregistrer l'angle » → `PATCH` `result.angle`). Une fois
    l'idée validée, seuls le titre, la plateforme et la durée restent affichés : le thème (« Idée de départ ») et l'angle
    (« Angle retenu ») sont repliés, la piste de départ et le bouton de génération disparaissent.
  - *Script* : ouvre sur le casting (`CastStrip`, le même bandeau que l'écran Plan), puis toutes les scènes en cartes
    `SceneCard` avec casting (vignette de l'élément principal, pastilles, enchaînement, case « Enchaîner avec la scène
    précédente »), éditables (voix off, prompt visuel, durée), monter/descendre/supprimer, « Ajouter une
    scène » ; la scène sélectionnée est encadrée et amenée à l'écran. « Enregistrer les scènes » → `PATCH` `scenes` (les
    étapes aval passent « à régénérer ») ; « Générer le script », puis « Régénérer le script » avec confirmation (scènes
    et clips choisis remplacés) ; bloqué tant que des modifications ne sont pas enregistrées. Enregistrement bloqué
    (message « Scène N : … obligatoires ») tant qu'une scène a un texte de voix off ou un prompt visuel vide ou fait
    d'espaces (l'API répondrait `422`).
  - *Référence* (volet « Image de référence » du panneau Clips, `ReferenceSection`, replié) : édition seulement, les
    images étant dans le bandeau du casting qui ouvre le panneau Clips (`CastStrip`) : prompt et Importer / Générer par
    élément (nom et scènes tirés de `castOf`), ajout d'un élément ; sans élément, prompt, « Générer l'image », « Ignorer
    cette étape » (→ `approve`), image de style générée ; « Générateur d'image » : modèles de `/providers/models` (clé `image`)
    avec leur provider en clair, « (indisponible) » si sa carte l'est. Choix par défaut (`imageChoice`) : celui de
    l'étape s'il est disponible, sinon Gemini (réglage `image_provider`) s'il l'est, sinon le premier disponible ; envoyé
    en `params {prompt, provider, model}`. Modèle indisponible (clé manquante) ou modèles pas encore chargés : « Générer » désactivé, raison affichée (`imageBlocked`, `models.ts`)
    avec un lien « Ouvrir les Réglages » ; étape en échec : la même raison s'affiche sous l'erreur, au-dessus de
    « Relancer » désactivé (`StepPanel`, vaut aussi pour les clips).
  - *Clips* : cartes « Profil de génération, toutes les scènes » (`ModelCards`, voir `docs/profils-generation.md` ;
    défauts : `params`, sinon réglages `/settings`, ramenés sur une carte disponible par `pickable` ; enregistré dans
    `params` au lancement global) ; ligne d'estimation : durée totale (profil local, `totalEstimate`) ou coût
    (`/estimate`, modèle cloud). Scène sélectionnée (`SceneFocus` : « Scène N sur M » + texte) : variantes
    (`<video>` 9:16, image de départ `keyframe` en `poster` si le profil en produit une), « Choisir » → `select-clip`,
    « Nouvelle variante » (`run` avec `scene_id` et le profil de la scène en `overrides` : le choix global n'est pas
    modifié). « Avancé » : cartes « Nouvelle variante, scène N ». Validation bloquée tant qu'une scène n'a pas de clip choisi. Avancé (profil ComfyUI) : « Image de départ des scènes avec images de référence » (préférence, Flux Kontext ou Gemini, voir `profils-generation.md`) ; la préférence se règle dans Providers.
  - *Voix* : scène sélectionnée : `<audio>`, « Générer / Régénérer cette voix » ; « Générer les voix » pour toutes ;
    sélecteur « Voix » (catalogue des Réglages ; « Voix par défaut » suit `default_voice_id`) et texte de la voix off de la
    scène éditable (`VoiceTextEditor`, assistant IA compris) : l'enregistrer périme la voix, le montage et l'export
    (`PUT /projects/{id}/scenes/{scene_id}/voice-text`, refusé pendant la voix ou le montage).
  - *Réglages → ElevenLabs* : « Voix par défaut » (liste du catalogue) et **catalogue de voix** (`VoiceCatalog`) : ajout
    nom + identifiant, retrait, « Importer depuis ElevenLabs » (`GET /providers/voices`, voix du compte ajoutées sans
    doublon) ; enregistré dans le réglage `voice_catalog` (JSON `[{id, name}]`, 100 voix au plus).
  - *Musique* : bibliothèque (`/music`) avec lecteur, choix unique (dont « Sans musique ») → `PATCH params.track_id`,
    « Confirmer le choix » lance l'étape.
  - *Montage* : « Lancer le montage », durée du rendu (le rendu se lit dans l'aperçu).
  - *Final* (outil Export) : titre/description/hashtags éditables (`PATCH` `result`, recopié dans `metadata_json` par
    l'API), « Valider le projet » ; le téléchargement passe par « Exporter » dans l'en-tête (fichier
    `vivi-{id}.mp4`).

### Actions de la scène sélectionnée (sous l'aperçu)
Quelle que soit l'étape ouverte (y compris « Export » d'une vidéo terminée), la scène choisie dans la liste, la timeline ou
avec les flèches propose deux boutons sous l'aperçu : « Régénérer le clip de la scène N » (ouvre l'étape Clips sur cette
scène, volet du prompt déjà ouvert et amené sous les yeux : `PanelProps.promptOpen`, le panneau est remonté via sa `key`)
et « Régénérer la voix » (ouvre l'étape Voix). Après une modification, le montage devient périmé : l'aperçu montre alors le
clip de la scène au lieu de l'ancien rendu (`renderIsCurrent`, `studio.ts` : le rendu ne sert d'aperçu que si l'étape
montage est validée ou à valider) ; il faut valider les clips puis relancer le montage pour obtenir un nouveau rendu.

### Reprise, scènes manquantes et prompt d'une scène (panneaux Clips et Voix)
- Étape en échec après la régénération d'**une** scène : « La régénération de la scène N a échoué » avec « Relancer la
  scène N » (ne refait que celle-là, provider et modèle choisis) et « Tout régénérer ».
- Étape en cours : le bandeau dit ce qui est généré (« Régénération de la scène N en cours : cette scène seulement » ou
  « Génération de toutes les scènes en cours : k sur M déjà prêtes », avec la marche à suivre pour n'en refaire qu'une) et
  propose « Arrêter la génération » (`runningScope`, `steps.ts` ; `flow.cancel`). Arrêtée : « Génération arrêtée », puis
  « Reprendre (N restantes) » / « Tout régénérer ».
- « Régénérer tous les clips » et « Tout régénérer » demandent confirmation (nombre de scènes, profil, clips choisis
  remplacés) et renvoient vers « Régénérer le clip de la scène » pour n'en refaire qu'une.
- Étape en échec avec des scènes déjà produites : le bandeau d'échec affiche « 2 scènes sur 4 déjà générées » et deux
  boutons, « Reprendre (2 restantes) » (`run {resume: true}`) et « Tout régénérer » (comportement précédent, nouveaux
  appels payants). Sans scène produite : « Relancer » seul. `resumeInfo` (`steps.ts`) calcule le texte et le reste.
- Pied du panneau : « Générer les N clips (voix) manquant(e)s » (`run {only_missing: true}`) tant que des scènes n'ont
  aucun média et que l'étape n'est pas `pending` (`missingScenes`, `steps.ts`).
- Volet « Préciser le prompt de cette scène » (Clips) : l'assistant IA (`Générer`, `Reformuler`, `Consigne`, voir
  « Assistant IA ») travaille le prompt visuel de la scène sélectionnée ; « Valider et régénérer » (ou « Régénérer avec le
  même prompt » s'il n'a pas changé) lance `run {scene_id, visual_prompt}` : le prompt est enregistré sur la scène et seul
  son clip est régénéré (profil de la scène respecté). Le brouillon se vide après envoi ; changer de profil ne le perd pas.

### Bandeau d'activité
Au centre de l'en-tête, une pastille liste les générations en cours (« Clips : scène 2 », « Voix off : 3 scènes sur 8 »), où que l'on soit dans l'éditeur : « Voir » ouvre l'étape et sélectionne la scène visée, « Arrêter » interrompt la génération. Elle disparaît quand rien ne tourne. La scène visée par une régénération porte une pastille qui clignote dans le storyboard. `activities()` (`studio.ts`), `components/studio/ActivityBar.tsx`.

### État d'une génération en cours
Savoir ce qui se passe sans chercher : l'étape qui tourne montre un anneau qui tourne (frise des étapes, bandeau d'activité, carte du panneau). La carte du panneau (`.generation`) dit la portée (« Scène 13 », « 2 scènes sur 8 »), le temps écoulé et le temps restant (`GenerationTiming`), une barre d'avancement (déterminée par scène, sinon indéterminée) et « Arrêter ».
- Données : `running_since` (API, `GET /projects/{id}`, = `updated_at` de l'étape tant qu'elle est `running`, sinon `null`). Écoulé = maintenant − `running_since` (rafraîchi chaque seconde, `useNow`).
- Restant (`generationTiming`, `studio.ts`) : dès qu'une scène est prête, rythme mesuré (écoulé ÷ scènes faites × scènes restantes) ; avant, estimation du modèle choisi (`minutes_per_clip`, ComfyUI seulement : un modèle payant n'annonce pas de durée) ; sans l'un ni l'autre, seulement l'écoulé. À 0 : « plus long que prévu ». Arrondi à l'excès (5 s, 30 s au-delà de 5 min). L'estimation vient du contexte `UnitSecondsContext` fourni par `Studio.tsx` (carte du `provider/model` de l'étape Clips, sinon la carte recommandée).
- Boutons grisés : pendant une génération (`busyReason`), les boutons du panneau et des actions de scène gardent un anneau devant leur libellé et affichent au survol la raison (« En cours : Clips, scène 13 ») ; le texte est posé en variable CSS `--busy-reason` sur `.studio`, attribut `data-busy`.

## Colonnes latérales et saisie
- Éditeur, grand écran : la colonne des scènes (200 à 480 px) et le panneau de l'étape (320 à 720 px) se règlent en
  glissant leur bord (`PanelEdge`, ou flèches gauche/droite quand la poignée a le focus ; double clic : largeur par défaut)
  et se replient avec le bouton rond posé sur le bord ; rouvrir se fait du même bouton. Le panneau replié reste monté
  (les brouillons ne sont pas perdus). Disposition mémorisée dans le navigateur (`usePanelLayout`, clé `studio-layout`).
  Sous 900 px, poignées et boutons disparaissent (onglets).
- `TextArea` (`components/TextArea.tsx`) remplace tous les `<textarea>` : la zone grandit avec son contenu (jusqu'à 60 %
  de la hauteur de la fenêtre, puis défile) et suit les changements de largeur. Avec `maxLength`, un compteur
  « n / max » apparaît dessous et passe au rouge à la limite. Limites alignées sur l'API (`src/limits.ts` : thème 2000,
  prompt visuel 4000 ; consigne de l'assistant 300 ; message du chat de plan 2000) ; pas de compteur là où l'API n'impose rien.
- Pas de texte d'explication permanent dans l'éditeur : l'état se lit sur les pastilles et boutons, le détail passe en
  infobulle (étape périmée, « Relancer la scène », « Reprendre », « Tout régénérer »). Restent affichés : les erreurs et
  les blocages qui demandent une action (clé API manquante).

## Mobile et accessibilité
- Mesures (version de production, Lighthouse mobile, 2026-10-20) : accessibilité 100 sur l'éditeur (96 → 100 après
  correction), bonnes pratiques 100 ; trace avec processeur ralenti 4× et réseau « Fast 4G » : LCP 812 ms, CLS 0 ; bundle
  JS 335 ko (105 ko compressés), CSS 30 ko. SEO : `noindex` et `robots.txt` « Disallow: / » sont voulus (interface
  privée), donc le score SEO n'a pas de sens ici ; `llms.txt` non pertinent.
- Corrections de la passe : contraste du texte secondaire (`--muted` `#9aa3ab`), zone `main` dans l'éditeur (l'aperçu),
  nom accessible des blocs de voix de la timeline contenant leur texte visible, absence de clip / voix dite aux lecteurs
  d'écran dans la liste des scènes, méta-description.
- Navigation hors éditeur sous 720 px : barre d'onglets fixée en bas (zone du pouce) au lieu de la barre latérale.
- Mouvement réduit : transitions et animations d'interface rendues instantanées (`index.css`).
- Écran tactile (`pointer: coarse`) : boutons compacts et boutons de l'assistant à 32 px minimum, pastilles à 36 px ;
  bouton de suppression des cartes à 40 px. La frise des étapes (défilante sous 900 px) garde l'étape affichée visible.

## Musique (`/music`)
Code : `pages/Music.tsx`.
- Tableau : nom, tags (pastilles), durée `m:ss` (`clock`), lecteur `AudioPlayer` (URL présignée ; lecture, barre de progression, une seule piste à la fois), suppression par icône.
- « Importer une piste » : modale (fichier `audio/*`, nom proposé d'après le fichier tant qu'il n'a pas été saisi, tags
  séparés par des virgules, découpés par l'API) → `POST /api/music` en `multipart/form-data` (`api()` laisse le navigateur
  fixer le `Content-Type` quand le corps est un `FormData`). Erreurs de l'API affichées dans la modale (« Fichier vide »,
  « Le fichier doit être un fichier audio », « Fichier audio illisible », 413 « Fichier trop volumineux (maximum 50 Mo) »).
- Import : `components/ImportTrack.tsx` (bouton + fenêtre fichier, nom, tags), partagé avec l'étape Musique de l'éditeur,
  où la piste importée est aussitôt choisie.
- Suppression : `ConfirmDialog` (« Supprimer la piste »), puis `DELETE /api/music/{id}` ; échec affiché sous l'en-tête.
- Bibliothèque vide : invitation à importer.

## Réglages (`/providers`, anciennement « Providers »)
Code : `pages/Providers.tsx`, logique pure `src/settings.ts`.
- Une carte par provider (Claude, Gemini, fal.ai, ComfyUI, ElevenLabs) : rôle, pastille de connexion issue de
  `GET /api/providers/health` (« Connecté » vert, « Non connecté » rouge, « Test… » gris : libellé + couleur), champs de réglages (saisie libre, ou liste pour `gemini_model`, alimentée par `llm.gemini` de
  `GET /api/providers/models`). Carte « Choix par défaut » : provider de rédaction `llm_provider` (Claude / Gemini :
  idées, scripts et métadonnées des prochaines étapes lancées), « Profil vidéo proposé à l'étape Clips » (les mêmes
  cartes `ModelCards`, sur plusieurs colonnes ; choisir une carte règle `default_video_provider` et
  `default_video_model` ; un réglage hérité ou indisponible, ex. `workflow`, s'affiche sur la carte que l'étape Clips
  proposera réellement) et
  `project_budget_usd` (« Budget maximum par vidéo ($) », défaut 10, 0 = sans limite : voir `docs/costs.md`).
- Toutes les listes de choix passent par un même rendu (`select`) ; `withCurrent` (`src/settings.ts`) garde proposable
  une valeur enregistrée absente de la liste.
- Secrets (`anthropic_api_key`, `gemini_api_key`, `fal_key`, `elevenlabs_api_key`) : champ mot de passe vide, la valeur masquée
  (`••••abcd`) en indication ; vide = clé conservée (une clé ne peut pas être effacée depuis l'admin).
- « Enregistrer » (actif seulement s'il y a des modifications) → `PUT /api/settings` avec **les seuls champs modifiés**
  (`settingsBody(saved, draft)` : non-secrets différents de la valeur enregistrée, secrets saisis non vides ; une valeur
  masquée n'est jamais renvoyée). La réponse (masquée) devient la référence, puis les connexions sont retestées.
- « Retester » relance `GET /api/providers/health` (bouton « Test en cours… » pendant l'appel). Seule la réponse au
  dernier test est retenue : un test plus ancien qui répond en retard (ex. lancé avant l'enregistrement de nouvelles
  clés) n'écrase pas le résultat.
- Si `GET /api/providers/models` échoue : message « Liste des modèles indisponible » + raison et « Réessayer ».

## Coûts (`/costs`)
Code : `pages/Costs.tsx`, logique pure `src/costs.ts`.
- Filtres projet et provider dans l'URL (`?project_id=&provider=`, transmis tels quels à `GET /api/costs`) ; « Effacer
  les filtres ». La liste des providers cumule ceux rencontrés depuis l'ouverture de la page (elle ne rétrécit pas
  quand un filtre est appliqué).
- Pagination : 50 appels, puis « Afficher plus (N restants) » (`limit` augmenté de 50). La liste des projets du filtre
  charge les 100 premiers par titre (au-delà, les projets plus anciens s'affichent « Projet n° N »).
- Synthèse : total dépensé, nombre d'appels affichés (« 50 derniers appels affichés sur 58 ») et
  d'échecs ; répartitions par provider et par projet en barres horizontales d'une seule teinte, montant et part du
  total écrits à côté de chaque barre (`breakdown` trie et calcule la part et la longueur relative ; `formatShare`
  affiche « < 1 % » pour un poste non nul). Cliquer une barre applique (ou retire) le filtre correspondant.
- Tableau des appels : date, projet (lien vers l'éditeur), étape (les appels de l'assistant IA s'affichent « Assistant
  IA (champ) »), provider et modèle, durée, coût, statut (« Réussi » /
  « Échec », badge texte + couleur) et message d'erreur. Rafraîchi à chaque événement SSE.

## Assistant IA (`components/AssistField.tsx`, `src/assist.ts`)
- `AssistField({label, kind, value, onChange, context, locked, children})` remplace `Field` pour un champ texte : libellé
  (relié au contrôle par `useId`, passé à `children(id)`), sur la **même ligne** que l'action de l'IA : un seul bouton, « Générer »
  quand le champ est vide, « Améliorer » sinon (nom accessible « … avec l'IA : <champ> »), et un bouton à curseurs qui
  déplie une consigne facultative (300 caractères au plus, prop `instructionPlaceholder` ; Ctrl ou Cmd + Entrée la lance aussi ; Entrée va à la ligne). Le champ vient ensuite. Même motif
  partout (accueil, script, fiche visuelle, prompts de scène et de référence : `PromptEditor` réutilise `AssistField`).
  Appel `POST /api/ai/assist` (voir `api.md`, `assistant-ia.md`).
- Le résultat **remplace le texte du brouillon** (`useDraft` via `onChange`) : rien n'est enregistré. Réponse tardive :
  les panneaux écrivent par mise à jour fonctionnelle (`useDraft().update(fn)`, à partir du brouillon le plus récent ;
  scènes visées par leur clé, `patchByKey`), donc les autres champs modifiés pendant l'attente sont conservés ; le champ
  concerné est en lecture seule pendant sa demande ; si sa valeur a changé malgré tout (annulation, rechargement), la
  réponse est ignorée (« Le champ a changé pendant la demande : proposition ignorée. », `replyIsStale`) ; le bouton
  d'enregistrement du formulaire apparaît comme pour une saisie, et quitter l'étape demande confirmation. Sous le champ,
  « Proposition de l'IA, pas encore enregistrée. » + « Annuler la proposition » rétablit le texte précédent (tant que
  le champ contient la proposition et que le brouillon n'est pas enregistré ni annulé, prop `unsaved` ; après
  plusieurs propositions de suite, le texte d'avant la première).
- Pendant l'appel : boutons inactifs, libellé « Génération… » / « Amélioration… », champ entouré en pointillé de la
  couleur d'accent, `aria-busy`. Erreur affichée sous le champ (`role="alert"`, `detail` de l'API, ex. `502` «
  Assistant IA indisponible : … »).
- Inactif si `locked` (action en cours, étape ou étape en aval `running`, comme les autres boutons du panneau) ;
  « Améliorer » n'existe que si le champ a du texte. Boutons en `aria-disabled` (restent focalisables, raison en infobulle) ; noms
  accessibles distincts par scène (prop `scope`, ex. « Générer avec l'IA : voix off, scène 2 ») ; Entrée dans la consigne
  ignorée pendant une composition IME. Contexte transmis : `projectId` (sauf création), `sceneId`
  (scène enregistrée) et `durationS` (durée du brouillon, budget de mots de la voix off).
- Logique pure (`assist.ts`, tests `assist.test.ts`) : `assistBody` (corps de requête, consigne nettoyée, champs vides
  omis), `assistBlocked` (raison d'inactivité), `canUndo`, `replyIsStale`, `patchByKey`, `ASSIST_LABELS` (noms accessibles des boutons, ex.
  « ✨ Générer : voix off ») et `assistStepLabel` (journal des coûts : `assist:voice_text` → « Assistant IA (voix off) »).
- `Modal` laisse le focus initial au premier élément focalisable (choix du navigateur).

## Socle partagé
- `src/api.ts` : `api<T>(path, init)` (préfixe `/api`, cookie, JSON, `ApiError(status, detail)`), types `Project`
  (dont `autopilot`, `current_status`), `ProjectCard` (élément de `GET /projects`, avec `thumbnail_url`), `ProjectDetail`, `Step`, `Scene`, `Asset`, `MusicTrack`, `ProviderModels`, `Estimate`, `StepPatch` et
  `latestAsset(assets, kind, sceneId?)`. Un corps `FormData` part sans `Content-Type` JSON (upload multipart). Les réponses sans corps (`202`, `204`) renvoient `undefined`. `useApi` ne retient
  que la réponse à la dernière requête (une réponse plus ancienne arrivée en retard est ignorée).
- `src/format.ts` : `usd` (montants en dollars, jusqu'au millième), `dateTime` (date et heure), `clock` (durée `m:ss`).
- `components/ProjectFields.tsx` : champs du brief (étape Idée) ; `ui.tsx` : `FormActions` (« Annuler » + envoi),
  `ConfirmDialog` (confirmation sur la modale native, pas `window.confirm`).
- `src/steps.ts` : `STEP_ORDER`, `STEP_LABELS`, `STATUS_LABELS` (noms alignés sur `backend/app/state.py`) et
  `currentStep(steps)` : première étape non validée, l'étape optionnelle `reference` en `pending` étant ignorée ;
  `final` si tout est validé.
- `useApi<T>(path)` (dans `api.ts`) : `{data, error, reload}` ; `path` null : aucun appel (ni donnée ni erreur) ; `errorMessage(err)` : `detail` de la réponse JSON de l'API (y compris en 5xx, ex. `503` « File d'attente
  indisponible ») ou « Serveur injoignable » (réseau, proxy sans backend, 5xx sans JSON).
- `src/events.ts` : `useEvents(onEvent)` sur `EventSource("/api/events")` ; charges utiles illisibles ignorées ;
  flux fermé par le serveur (ex. session expirée) → revérification de la session (redirection vers `/login` sur 401).
- `src/index.css` : jetons de la direction « graphite » (contrat complet : `docs/design-system.md`) et primitives
  (`.btn`, `.input`, `.field`, `.form`, `.modal`, `.table`, `.table-wrap`, `.page-head`, `.empty`, `.page-error`, `.sr-only`,
  couleurs de statut `.st-*` → `--st` et `.status-badge`) ; `src/components/ui.tsx` : `Field`, `Modal` (`<dialog>` natif, titre relié par `useId`), `ErrorState` (message + « Réessayer »).

## Génération longue
La barre de progression de l'étape en cours (scènes prêtes sur le total) et l'alerte de fin (titre d'onglet + notification, onglet masqué seulement) s'appuient sur le flux SSE et le rechargement toutes les 5 s (`useCompletionAlert`).

## Confirmations avant les actions sensibles
`hooks/useConfirm` : `const { confirm, dialog } = useConfirm()`, puis `confirm({ title, message, confirmLabel, onConfirm })` ;
`dialog` se rend dans le composant (modale native `ConfirmDialog`). Elle précède :
- toute régénération d'une étape qui a déjà un résultat (`StepPanel`) : le message ajoute « À refaire ensuite : … »
  (`affectedDownstream`, étapes en aval ayant un résultat) ;
- « Arrêter » (panneau d'étape, bandeau d'activité, écran du plan) ;
- « Générer les N clips / voix manquants », « Régénérer cette voix », régénération d'une image de référence existante ;
- « Valider le plan et générer » (lance la génération automatique, payante).
Les suppressions (projet, piste, variante) et la sortie avec modifications non enregistrées avaient déjà la leur.

Pendant une génération, les champs de prompt (scène, image de référence), l'assistant « Améliorer » et le choix du
générateur d'image restent libres : ce sont des brouillons locaux. Les boutons de génération passent en « Mettre en
file » ; seuls les actions que l'API refuse alors (import de clip, choix de variante, import d'image pendant l'étape reference) restent grisées.
