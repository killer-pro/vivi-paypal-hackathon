# API HTTP (projets, étapes, événements)

Code : `backend/app/api/` (`auth.py`, `projects.py`, `steps.py` — étapes et choix du clip —, `events.py`, `assist.py` — assistant IA —), routeurs montés dans `backend/app/main.py`.
File de jobs : `backend/app/queue.py` (Arq + Redis), worker : `backend/app/worker.py`.
Tous les chemins sont préfixés par `/api`.

## Authentification
Code : `backend/app/api/auth.py`. Corps JSON ; e-mail normalisé (`normalize_email` : sans espaces, minuscules, ≤ 254
caractères), mot de passe de 8 à 128 caractères (validé avant tout hachage → `422`).
- `POST /auth/register {email, password}` → `202 {"ok": true}`, que l'adresse soit libre ou déjà prise. Crée le compte
  (rôle `user`) et envoie `{PUBLIC_URL}/verify?token=…` (48 h) ; compte existant non vérifié : lien de
  réinitialisation `{PUBLIC_URL}/reset?token=…` (1 h), mot de passe inchangé (le titulaire de la boîte reprend la main
  sur un compte qu'un tiers aurait inscrit à son adresse) ; compte vérifié : aucun e-mail.
- `POST /auth/verify {token}` → `200 {"ok": true}` ; marque l'adresse vérifiée et révoque les sessions ouvertes avant
  (reconnexion nécessaire) ; `400 "Lien invalide ou expiré"` (falsifié, expiré, déjà utilisé ou d'un autre type).
- `POST /auth/resend` (connecté) → `202` ; renvoie le lien si l'adresse n'est pas vérifiée.
- `POST /auth/login {email, password}` → `200 {id, email, role, email_verified}` et cookie `session` signé
  (`{uid, epoch}`, `SECRET_KEY`), `HttpOnly`, `SameSite=Lax` (+ `Secure` si `APP_ENV` n'est pas `dev`), 30 jours.
  Échec → `401 "Email ou mot de passe incorrect"` (même message, même hachage vérifié, que le compte existe ou non).
  Limitation : 5 échecs en 5 minutes par adresse cliente → `429 {"detail": "Trop de tentatives : réessayez dans N s"}`
  avec l'en-tête `Retry-After`, même avec le bon mot de passe pendant le blocage ; un succès remet le compteur à zéro
  (état en mémoire du processus ; derrière un proxy, lancer uvicorn avec `--proxy-headers`).
- `POST /auth/logout` : incrémente l'époque de session de l'appelant (toutes **ses** sessions sont révoquées, pas celles
  des autres comptes) et supprime le cookie. `GET /auth/me` → `{id, email, role, email_verified}` ou `401`.
- `POST /auth/forgot {email}` → `202` toujours ; envoie `{PUBLIC_URL}/reset?token=…` (1 h) si le compte existe.
- `POST /auth/reset {token, password}` → `200` ; change le mot de passe, révoque les sessions du compte et marque
  l'adresse vérifiée si elle ne l'était pas (le lien prouve la possession de la boîte) ; `400` sinon.
- Inscription, renvoi et mot de passe oublié : 5 demandes par heure et par adresse cliente (`signup_throttle`) → `429`.
  Un échec d'envoi d'e-mail est journalisé (sans le lien) et ne change pas la réponse.
- Toutes les routes sont protégées par `current_user` (cookie absent, invalide, expiré, d'un ancien format, compte
  supprimé ou session révoquée → `401`), sauf `/api/health` et `/api/auth/*` (hors `resend` et `me`). Hors
  `APP_ENV=dev`, `/docs`, `/redoc` et `/openapi.json` sont fermés (404).
- **Isolation par propriétaire** : chaque route `/projects/{id}/…` (routeurs `projects`, `steps`, `plan`) passe par la
  dépendance `require_project_access` → `404 "Projet introuvable"` si le projet n'existe pas **ou** n'est pas à
  l'appelant (même réponse : pas d'énumération) ; l'admin ouvre tous les projets. `GET /projects` ne liste que les
  projets de l'appelant, admin compris. Les autres ids du chemin (asset, scène, file, message) sont cherchés dans le
  projet de l'URL (`404` sinon). `POST /ai/assist` vérifie de même le `project_id` du corps, `GET /costs` filtre par
  propriétaire (voir `settings-providers.md`).

## Projets
| Méthode | Chemin | Effet |
|---|---|---|
| `GET` | `/projects` | Page `{items, total}` ; chaque élément `{id, title, status, autopilot, created_at, current_step, current_status, cost_usd, thumbnail_url, render_asset_id}` . Paramètres : `q` (cherche dans le titre et le thème, sans casse, `%` et `_` littéraux, 100 caractères max), `status` (`draft` = en cours, `done` = terminés), `sort` (`recent` défaut, `oldest`, `title` A→Z, `cost` plus coûteux d'abord), `limit` (1–100, défaut 24), `offset` (≥ 0). `total` = tous les projets qui correspondent, pas seulement la page. Ordre total (id en dernier) : pas de doublon ni d'oubli d'une page à l'autre. `422` sur paramètre invalide. `status` : `draft` à la création, `done` dès que l'étape `final` est validée, de nouveau `draft` si `final` est périmée ou relancée (`sync_status`, appelé par `approve`, `run`, `PATCH` étape/projet et `select-clip` ; migration `0002` pour les projets existants). `current_step` = première étape non approuvée, l'étape optionnelle `reference` encore en `pending` étant ignorée (`null` si tout est approuvé) et `current_status` son statut ; `cost_usd` = somme du journal des coûts (le détail `GET /projects/{id}` ajoute `cost_by_step` : dépenses par étape, appels de l'assistant IA regroupés sous `assist`, étapes à 0 $ omises ; et `budget_usd` : plafond par vidéo, 0 = sans limite) ; `thumbnail_url` = URL présignée du dernier rendu, sinon du clip choisi de la première scène qui en a un (`null` sinon), vignette des cartes de l'accueil ; `render_asset_id` = id du dernier rendu (`null` sans rendu), pour le bouton « Exporter » (`GET /projects/{id}/assets/{asset_id}/download`, redirection vers MinIO). |
| `POST` | `/projects {title, theme, platform, target_duration_s}` | `201` : crée le projet et ses 9 étapes en `pending`. `422` si `title` > 200 caractères, `theme` > 2000, `platform` > 30 ou `target_duration_s` hors de 1–180 s. |
| `GET` | `/projects/{id}` | Projet (dont `autopilot: bool`, voir `autopilot.md`) + `steps` (ordre du flow ; chaque étape porte `target_scene` (id de la scène si le dernier lancement, en cours ou en échec, ne visait qu'elle : « Relancer » ne refait que celle-là), `progress: {done, total} | null` (étape par scène en cours pour toutes les scènes) et `resume: {done, total} | null`, non nul pour une étape clips ou voix en échec qui a déjà produit des scènes : de quoi la reprendre) + `scenes` (par position) + `assets` (avec `url` présignée MinIO, 1 h, et `original_name` : nom nettoyé du fichier importé, `null` pour un asset généré). `404` si absent. |
| `PATCH` | `/projects/{id} {title?, theme?, platform?, target_duration_s?}` | Modifie le brief (mêmes contraintes qu'à la création, `422` sinon). Étapes produites (approuvées ou à valider) passées en `stale` : toutes si thème, plateforme ou durée changent, seulement `final` si seul le titre change ; rien si aucune valeur ne change. |
| `GET` | `/projects/{id}/assets/{asset_id}/download` | `307` vers une URL présignée avec `Content-Disposition: attachment; filename="vivi-{id}.{ext}"` (téléchargement du rendu), `{ext}` tiré du type MIME de l'asset (liste fermée, `bin` sinon), jamais de sa clé. `404` si l'asset n'appartient pas au projet. |
| `DELETE` | `/projects/{id}` | `204` ; étapes, scènes et assets supprimés en cascade, puis les fichiers MinIO du projet (assets et préfixe `projects/{id}/`, segments de montage compris) (échec de stockage : journalisé, la suppression reste valide). `409` si une étape tourne (son job continuerait d'appeler des providers payants). |
| `GET` | `/projects/{id}/estimate?provider=&model=` | Coût estimé des clips : Σ `estimate_cost(model, durée)` sur les scènes (`services/budget.py`, partagé avec le contrôle de budget au lancement). Défauts : réglages `default_video_provider` / `default_video_model`. Provider ou modèle inconnu → `400`. |
| `POST` | `/projects/{id}/scenes/{scene_id}/upload-clip` (multipart `file`) | `201` : vidéo locale ajoutée comme variante suivante de la scène (choisie d'office si la scène n'avait pas de clip). Clé `projects/{id}/clip/<32 hex>.<ext>` générée par le serveur, extension et type MIME d'une liste fermée (`mp4`, `mov`, `webm`, `mkv`, `m4v`), nom d'origine nettoyé dans `asset_originals` (`docs/imports-fichiers.md`). `400` extension absente ou non supportée, ou fichier vide, `413` au-delà de 100 Mo, `404` scène hors projet, `409` si `clips` ou `montage` tourne. |
| `DELETE` | `/projects/{id}/assets/{asset_id}` | `204` : supprime l'asset (son nom d'origine suit en cascade) et ses fichiers ; une variante choisie est remplacée par la plus récente des autres (`montage` et `final` en `stale`), son image de départ est supprimée avec elle. `404` si l'asset n'est pas au projet, `409` si `clips` ou `montage` tourne. |
| `POST` | `/projects/{id}/scenes/{scene_id}/select-clip {asset_id}` | Choisit le clip de la scène pour le montage. `404` si la scène n'est pas au projet ou si l'asset n'est pas un clip de cette scène. `montage` et `final` déjà produits passent en `stale` (voix et musique ne sont pas touchées). |

## Étapes
| Méthode | Chemin | Effet |
|---|---|---|
| `PATCH` | `/projects/{id}/steps/{name} {params?, result?, scenes?}` | Édite les paramètres / le résultat. `scenes` (étape `script` uniquement, sinon `422` ; `voice_text` et `visual_prompt` non vides après suppression des espaces, sinon `422`) : mise à jour par `id` (le clip sélectionné est conservé), création des scènes sans `id`, suppression des absentes. Sur l'étape `final`, un `result` fourni est aussi recopié dans `Project.metadata_json` (une seule source pour les métadonnées publiées ; le drapeau `autopilot` est conservé). Les étapes aval approuvées ou à valider passent en `stale` (sauf l'étape optionnelle ignorée, validée sans résultat, qui reste validée) ; les assets sont conservés. |
| `POST` | `/projects/{id}/steps/{name}/run {scene_id?, provider?, model?, start_image?, resume?, only_missing?, visual_prompt?}` | `202` : passe l'étape en `running`, passe l'aval produit en `stale` et enfile le job Arq `run_step_job`. `start_image` (`comfyui` | `gemini`, étape `clips` uniquement, sinon `422`) : générateur de l'image de départ pour ce lancement (voir `profils-generation.md`). `provider`/`model` (étape `clips` uniquement, sinon `422`) valent pour ce lancement seulement : ils priment sur `params` sans les modifier (ex. une variante d'une scène avec un autre profil). Pour `reference`, le provider et le modèle d'image (`params.provider`/`params.model`, sinon réglage `image_provider`, défaut Gemini) sont vérifiés de même : inconnus → `400` (« Provider d'image inconnu : x », « Modèle d'image inconnu pour gemini : x »), indisponibles → `409` (« Clé API gemini manquante, à saisir dans Réglages → Gemini »), rien n'est réclamé ni enfilé. Pour `clips`, le modèle effectif (choix ponctuel, sinon `params`, sinon réglages) est vérifié avant tout job : provider ou modèle inconnu → `400` (« Modèle vidéo inconnu pour comfyui : x ») ; carte indisponible → `409` avec la raison de la carte (« Clé API fal manquante, à saisir dans Réglages → fal.ai », « ComfyUI injoignable », « Modèle manquant : <fichier> »), sauf un ComfyUI qui ne répond pas dans le délai (« ComfyUI ne répond pas (occupé ?) ») : lancement accepté, le job attend son tour ; l'ancien modèle `workflow` vaut le profil `max` (`docs/profils-generation.md`). Même vérification (`launch_step`, `services/video_models.py`) pour les lancements de l'autopilot : il s'arrête avant d'enfiler les clips, l'étape passe en `failed` avec cette raison. `resume` (clips, voix ; toutes les scènes ; étape `failed`) : ne génère que les scènes que le dernier lancement complet n'avait pas produites (`409` s'il n'y en a aucune). `only_missing` (clips, voix ; toutes les scènes ; n'importe quel état) : ne génère que les scènes sans aucun clip / aucune voix (`409` « Aucune scène manquante » s'il n'en manque aucune) ; incompatible avec `resume` (`422`). `visual_prompt` (clips + `scene_id`, 1–4000 caractères, non vide) : nouveau prompt visuel de la scène, enregistré sur la scène au lancement (pas enregistré si le lancement est refusé) puis clip régénéré ; `422` hors clips ou sans scène, `404` si la scène n'est pas au projet. Les `422` de validation passent avant les `409` d'état. `202 {"queued": true}` si l'étape ou une étape qui en dépend tourne : la demande est mise en file (`docs/file-attente.md`) ; `409` si l'étape précédente n'est pas validée, si l'étape entière est déjà en cours, si la file est pleine, ou si le budget du projet serait dépassé (`docs/costs.md`). |
| `POST` | `/projects/{id}/autopilot` | `202` : mode automatique, lance `idea` puis le worker enchaîne et valide les étapes (voir `autopilot.md`). `409` si une étape tourne, `503` si Redis est indisponible. |
| `DELETE` | `/projects/{id}/autopilot` | `204` : arrête l'enchaînement (l'étape en cours finit, la suite n'est pas lancée). |
| `POST` | `/projects/{id}/steps/{name}/cancel` | `202` : arrête une étape en cours (`failed`, « Arrêtée par l'utilisateur », autopilot coupé, produit conservé) ; le worker interrompt l'appel en cours. `409` si elle ne tourne pas, `404` si l'étape est inconnue. |
| `POST` | `/projects/{id}/steps/{name}/approve` | `awaiting_validation → approved` (ou `stale → approved`). Une étape optionnelle (`reference`) en `pending` peut être approuvée directement : c'est « ignorer l'étape ». |

| `POST` | `/projects/{id}/steps/{name}/price {mêmes champs que run}` | `200 {credits, balance, sufficient, unlimited}` : prix en crédits du lancement `run` de mêmes options, sans rien lancer ni réserver ; `balance` est celui du propriétaire du projet (`null` et `unlimited: true` pour un compte admin). Mêmes refus que `run` (état, modèle, reprise). |
| `GET` | `/billing` | Offre (abonnement et recharges, `purchasable`), état d'abonnement, `manageable` (portail disponible). |
| `POST` | `/billing/checkout {kind, pack_id?}` | `{url}` de la page de paiement Stripe (`403` adresse non vérifiée, `404` recharge inconnue, `409` offre sans prix ou déjà abonné, `502` refus de Stripe). |
| `POST` | `/billing/portal` | `{url}` du portail client Stripe du compte (`409` sans achat). |
| `POST` | `/stripe/webhook` | Ouvert, protégé par `Stripe-Signature` (`400` sinon) ; crédite recharges et abonnements, idempotent (`docs/paiement.md`). |
| `GET` | `/admin/customers?q=&limit=&offset=` | Admin : comptes avec offre, solde, crédits consommés (`docs/admin-saas.md`). |
| `GET` | `/admin/customers/{id}` | Admin : un compte et son registre de crédits paginé (`404` inconnu). |
| `POST` | `/admin/customers/{id}/credits {amount, bucket, reason}` | Admin : ajustement manuel (`409` sous zéro ou compte admin, `422` motif vide / montant nul). |
| `GET` | `/admin/margins?since=` | Admin : coût de revient, crédits facturés et marge observée par action. |
| `GET` | `/access` | Fonctions réservées à l'abonnement encore verrouillées pour le compte et leur motif (`docs/abonnement.md`). Les refus sont des `403 « Réservé à l'abonnement : … »` (lancement clips avec un profil réservé, étape reference, import d'image de référence, style). |
| `GET` | `/credits?limit=50&before_id=` | Solde `{unlimited, balance: {subscription, topup, total}}` et registre du compte connecté (`entries`, id décroissant, `next_before_id`). |

Étape inconnue ou projet absent → `404`. `409` de crédits sur `run`, `/ai/assist` et le chat du plan : « Crédits insuffisants : il vous faut N crédits, il vous en reste M (…) » ; clips : « Une génération de clips est déjà en cours sur un autre de vos projets » (`docs/credits.md`).

### Règles 409 (conflit)
- `DELETE /projects/{id}/queue/{queued_id}` : `204`, retire une génération de la file (`404` si elle est déjà partie) ; `queue: [{id, step, scene_id}]` dans `GET /projects/{id}`.
- `run` alors qu'une étape précédente obligatoire n'est pas `approved` → `409 « Étape précédente non validée »`.
- `run` alors que l'étape est déjà `running` → `409 « Étape déjà en cours »`. Le passage à `running` est atomique
  (`UPDATE … WHERE status != 'running'`) : sur un double clic ou des requêtes concurrentes, une seule obtient la ligne
  et un seul job est enfilé.
- `approve` depuis un statut autre que `awaiting_validation`/`stale` (hors étape optionnelle en `pending`) → `409`.
- `PATCH` d'une étape `running` → `409`.
- `PATCH` ou `run` d'une étape alors qu'une étape **en aval** (`downstream(name)`) est `running` → `409 « Génération en
  cours (…) »` (`ensure_not_running`) : le job en cours lit les données qu'on modifierait ou invaliderait. Rien n'est
  modifié ni enfilé.
- `PATCH /projects/{id}` alors qu'une étape dépendante tourne (toutes si thème/plateforme/durée changent, `final` si
  seul le titre change) → `409`, le projet n'est pas modifié.
- `select-clip` pendant que `clips` ou `montage` est `running` → `409`.

Si Redis est indisponible au moment d'enfiler, l'étape passe en `failed` (« File d'attente indisponible … ») et l'API
répond `503` : l'étape reste relançable (et l'autopilot du projet s'arrête).

Le lancement (`run`, `POST /autopilot`, chaînage du worker) passe par une seule fonction, `launch_step`
(`services/steps.py`) : verrou du projet, `can_start`, `ensure_not_running`, claim atomique, aval `stale`, enqueue.

## Assistant IA (rédaction d'un champ)
`POST /ai/assist {field_kind, mode, text, instruction?, project_id?, scene_id?, duration_s?}` → `200 {"text"}`.
Code : `api/assist.py` (validation), `services/assist.py` (prompt, appel, nettoyage). Détails : `assistant-ia.md`.

- `field_kind` : `project_title`, `theme`, `hint`, `angle`, `voice_text`, `visual_prompt`, `reference_prompt`, `title`,
  `description`, `hashtags`. `mode` : `generate` (nouvelle proposition, le texte actuel peut inspirer) ou `rewrite`
  (reformuler `text`, en appliquant `instruction`, ex. « plus court », « plus punchy »).
- Contexte lu en base : brief du projet (`project_id`), angle validé, script actuel (champs de scène, image de référence
  et métadonnées), métadonnées actuelles (`title`/`description`/`hashtags`), scène (`scene_id`). Pour `voice_text`, la
  durée (`duration_s` du brouillon, sinon celle de la scène) fixe un budget d'environ 2,5 mots par seconde.
- **Rien n'est enregistré** : l'admin place le texte dans le brouillon du champ. Pas de verrou `409` côté API (aucune
  écriture) ; l'admin désactive l'assistant quand l'étape est verrouillée.
- LLM actif (`llm_provider` : Claude, Gemini ; fake si `FAKE_PROVIDERS=true`) via `tracked_call` : une ligne
  `provider_calls` par tentative, `step = "assist:<field_kind>"`, `project_id` si fourni → comptée dans `/costs` et le coût
  du projet. 2 tentatives (erreurs relançables), timeout 90 s, `max_tokens` 2000.
- Réponse nettoyée de façon conservatrice : bloc ```` ``` ```` englobant, première ligne « Voici… : » / « Here is… : »
  seule, libellé en tête seulement s'il nomme le champ demandé (« Titre : » pour un titre, pas pour un angle),
  guillemets seulement s'ils englobent tout le texte sans réapparaître à l'intérieur (« A » … « B » est gardé), gras
  seulement si toute la réponse est en gras ;
  champs d'une ligne (`project_title`, `title`, `hashtags`) ramenés sur une ligne ; hashtags normalisés (`#` devant,
  sans doublon, séparés par des espaces).
- Erreurs : `422` (message français) si `field_kind`/`mode` inconnu, `rewrite` avec texte vide, `text` > 6000
  caractères, `instruction` > 300, `scene_id` sans `project_id`, `duration_s` hors ]0, 600] ; `404` projet ou scène
  introuvable (ou scène d'un autre projet) ; `502 « Assistant IA indisponible : … »` sur `ProviderError` (clé, quota,
  réseau, réponse vide une fois nettoyée). Une réponse facturée mais vide une fois nettoyée reste au journal avec son
  coût réel (contrôle fait après `tracked_call`).

## Worker
`arq app.worker.WorkerSettings` : fonction `run_step_job(ctx, project_id, step, scene_id, overrides=None, timeout=None)`
(`overrides` → `PipelineContext.overrides`), 2 jobs en parallèle, `max_tries = 1` : un job n'est jamais rejoué automatiquement (pas de double appel provider payant).
Chaque job ouvre une session DB et un `ProviderRegistry` (client HTTP fermé en fin de job),
appelle `run_step` (voir `workflow-video.md`), puis publie l'événement de fin. En mode automatique, il valide ensuite
l'étape et lance la suivante (`advance`, voir `autopilot.md`) ; un job interrompu ou une étape orpheline au redémarrage
coupe l'autopilot du projet.
- **Timeout par job** : l'API le calcule au lancement avec `job_timeout(step, nb_scènes, provider_vidéo)` (`services/pipeline.py`) ;
  pour `clips`, le provider est celui du lancement (`provider` du corps, sinon `params`, sinon `default_video_provider`,
  via `clip_provider_name`) et ComfyUI (local) compte 5700 s par appel au lieu de 900 s :
  pour `clips` et `voice` (un appel par scène ; majorant du pire cas en séquence, la génération réelle en parallèle
  est plus courte), nb d'appels × (timeout de l'étape × 3 tentatives + backoff),
  + 120 s de marge ; deux appels pour `script` (réponse + relance ciblée, `LLM_CALLS`) ; un seul pour les autres étapes ; une seule scène si `scene_id` est fourni ; plafond
  `MAX_JOB_TIMEOUT` = 24 h. Arq 0.28 n'ayant pas de timeout par job, la valeur est passée en argument et appliquée par
  `run_step_job` (`asyncio.timeout`) ; le `job_timeout` Arq global vaut `MAX_JOB_TIMEOUT + 60` (filet de sécurité).
  Un job enfilé sans timeout (ancienne version) est limité à 1200 s.
- Job expiré (timeout ci-dessus) : l'étape passe en `failed` (« job interrompu ou expiré ») et un événement est publié.
  Job annulé (arrêt du worker) : idem, puis l'annulation est propagée.
- Job dont l'étape n'est plus `running` au démarrage (ex. réinitialisée en `failed` par un redémarrage du worker alors
  que le job attendait en file) : ignoré silencieusement, aucun appel provider.
- Au démarrage du worker, toute étape restée `running` passe en `failed` (« job interrompu (worker redémarré) ») :
  avec un worker unique, aucun job ne peut légitimement tourner à ce moment-là.

## Événements temps réel
`GET /events` (`text/event-stream`) relaie le canal Redis `vv:events` : chaque événement
`{project_id, step, status, error}` est envoyé en `data: {json}`. Sans événement pendant 15 s, un commentaire
`: ping` est envoyé (un premier `: ping` part aussi dès l'abonnement).
Filtré par compte (`visible_events`, `owner_filter`) : un utilisateur ne reçoit que les événements de ses projets
(propriétaire cherché une fois par projet et par connexion, dans une session courte), jamais ceux sans `project_id` ;
l'admin reçoit tout. Le `: ping` part aussi quand seuls des événements filtrés arrivent pendant 15 s.

## Réordonner les scènes
`POST /api/projects/{id}/scenes/reorder` avec `{"scene_ids": [3, 1, 2]}` : renumérote les scènes de 1 à n dans cet ordre et renvoie les scènes. La liste doit contenir chaque scène du projet une fois (`422`) ; `409` si `clips`, `voice` ou `montage` sont en cours. `montage` et `final` passent en `stale` (clips, voix et musique restent validés).

## Plan : génération et chat
- `GET /api/styles` : styles visuels proposés (`[{id, label}]` : `realistic`, `anime`, `illustration`). Un projet porte un `style` (vide = aucun), changé via `POST /projects` ou `PATCH /projects/{id}` (`422` « Style inconnu »).
- `POST /api/projects/{id}/plan/generate` (`202`) : lance `idea` avec un autopilot borné, qui enchaîne sur `story` puis s'arrête (l'histoire reste `awaiting_validation` ; un projet existant dont la story est validée et vide va jusqu'à `script`). `409` si une étape tourne.
- `GET /api/projects/{id}/plan/messages` : historique du chat `[{id, role, content, can_undo, created_at}]` ; `can_undo` vaut vrai pour le seul dernier message de l'IA qui a modifié le plan.
- `POST /api/projects/{id}/plan/chat` avec `{"message": "…"}` (1 à 2000 caractères) : l'IA répond et, si besoin, renvoie le plan complet modifié (titre, fiche visuelle, 1 à 30 scènes), appliqué par le serveur ; réponse `{messages: [user, assistant], plan_changed}`. `409` si une étape tourne ou si le budget est atteint, `502` si l'IA échoue ou renvoie un plan invalide (plan et historique inchangés). Étapes aval produites : `stale`.
- `POST /api/projects/{id}/plan/messages/{mid}/undo` (`204`) : rétablit le plan d'avant ce message ; `409` si ce n'est pas le dernier changement ou si une étape tourne.
