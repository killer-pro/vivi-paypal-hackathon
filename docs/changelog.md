# Changelog

## 2026-11-03 (dépôt public)
- Webhook PayPal essayé de bout en bout par un tunnel Cloudflare (événement signé livré, crédit unique) ; procédure dans `paiement.md`.
- Dépôt public `vivi-paypal-hackathon` (sans docs de stratégie ni historique). Essai d'un clone neuf : vidéo complète en mode factice. Corrigés : identifiants PayPal saisis prioritaires sur le faux (faux partagé entre requêtes), voix par défaut en mode factice. Dépôt public seulement : RustFS remplace MinIO (retiré de Docker Hub), Redis ajouté à la CI.

## 2026-11-02 (docs et deck)
- PayPal : essai de bout en bout dans le bac à sable (commande, approbation, capture, crédit) ; correction d'un double appel de capture à l'écran et d'un identifiant de commande non validé. Docs : `paiement.md`, `soumission-paypal.md`.
- PayPal : recharges de crédits (commande, capture au retour, webhook de secours, faux client, bouton « Payer avec PayPal »). Tests : `test_paypal.py`, `billing.test.ts`. Docs : `paiement.md`, `soumission-paypal.md`.
- `soumission-paypal.md` : plan de soumission au PayPal AI Hackathon ; `financement.md` : Kiroween (non éligible) et Arbiter Hacks (à ignorer) lus.
- `financement.md` : relevé des hackathons ouverts (Devpost, DoraHacks), PayPal AI Hackathon en tête.
- `financement.md` : choix de la structure juridique pour un fondateur au Sénégal (Delaware via Stripe Atlas, Stripe indisponible au Sénégal, France et Label Startup comparés).
- Nouveaux `hebergement.md` (plan de mise en production, test de charge) et stratégie de financement dans `financement.md` ; diapositive « Ce que nous cherchons » concrétisée.
- README : connexion par e-mail et accès `/decouvrir`. Deck : diapositive « Modèle économique », images de remplacement (les anciennes n'existaient plus : le deck ne compilait plus), 11 diapositives. Nouveau `financement.md` (veille concours et programmes). Docs : `pitch.md`.

## 2026-11-02 (logo Gemini)
- Logo agrandi, avec « Vivi » placé sous le V dans la barre latérale et sur les écrans de compte.
- Logo : V néon (rose/violet/jaune) avec étincelle, généré avec Gemini et redessiné en SVG ; `.brand-mark` devient carré. Doc : `marque.md`.

## 2026-11-02 (logo)
- Nouveau logo : un V à branches inégales découpé dans le cadre 9:16, à la place du triangle pointe en bas. Doc : `marque.md`.

## 2026-11-02 (acquisition : page Découvrir)
- Un visiteur non connecté arrive sur `/decouvrir` (boutons Se connecter / S'inscrire) ; barre de recherche IA qui mémorise l'idée, mène à l'inscription puis à `/new` prérempli avec invitation à s'abonner.
- Connexion, inscription et autres écrans de compte sur le mur de clips (`ClipWall`, extrait de l'accroche). Doc : `landing.md`.

## 2026-11-02 (marque Vivi)
- L'app s'appelle Vivi : titre, barre latérale, connexion, landing, API, deck et fichiers téléchargés (`vivi-{id}.{ext}`).
- Nouveau logo (`admin/public/favicon.svg`), repris par `.brand-mark`. Docs : `marque.md` (nouveau), `design-system.md`, `api.md`, `admin.md`, `imports-fichiers.md`, `README.md`.

## 2026-11-02 (lot 5 SaaS : admin)
- API `/api/admin/*` (admin seulement) : liste des clients avec offre, solde et crédits consommés, détail avec registre, ajustement manuel de crédits avec motif (`credits.adjust`, jamais sous zéro), tableau coût de revient vs crédits facturés par action (`services/margins.py`).
- Admin : écrans Clients (liste, détail, ajustement) et Tarifs (valeur du crédit, marge, exceptions, coûts forfaitaires et locaux, marges observées).
- Docs : `admin-saas.md` (nouveau), `api.md`, `credits.md`, `securite.md`, `README.md`.

## 2026-11-02 (lot 4 SaaS : paiement Stripe)
- Stripe sans SDK (`stripe_client.py` : client REST réel, faux client, signature de webhook HMAC), offre dans le réglage `billing_config`, migration `0018` (`users.stripe_customer_id`, `stripe_events`). `POST /api/billing/checkout` et `/portal`, `GET /api/billing`, webhook signé et idempotent `POST /api/stripe/webhook` : recharges (`checkout.session.completed`), abonnement et renouvellement (`invoice.paid` : fin de période, lot d'abonnement remis au quota, reliquat expiré), fin d'abonnement (`customer.subscription.deleted`). Réservations ouvertes au renouvellement basculées sur le lot rechargé.
- Admin : section « Abonnement et recharges » sur la page Crédits (offres, retour de paiement, portail), nouveaux libellés du registre.
- Docs : `paiement.md` (nouveau), `abonnement.md`, `credits.md`, `securite.md`, `exploitation.md`, `api.md`, `README.md`.

## 2026-11-02 (lot 3 SaaS : accès par abonnement)
- Point d'accroche unique `services/access.py` : fonctions réservées à l'abonnement (profils Précision et Maximum, image de référence, styles) listées dans le réglage `subscription_locked`, état d'abonnement `users.subscription_ends_at` (migration `0017`, admin toujours abonné). Refus `403 « Réservé à l'abonnement : … »` au lancement (et au prix), à l'import d'image de référence et à la modification du style ; l'autopilot saute `reference` sans abonnement. `GET /api/access`, cartes de profil `locked`/`locked_reason`, `/auth/me` expose l'abonnement, script `set_subscription.py`.
- Admin : cartes de profil, styles et image de référence réservés restent visibles avec leur motif (au lieu d'être masqués).
- Docs : `abonnement.md` (nouveau), `api.md`, `comptes.md`, `exploitation.md`, `README.md`.

## 2026-11-02 (lot 2 SaaS : crédits)
- Crédits : solde à deux lots, registre append-only et réservations (migration `0016`), prix en crédits arrondi au supérieur (`services/pricing.py`, réglages `credits_*`), devis partagé par le lancement et `POST …/steps/{name}/price` (`preflight_launch`), réservation atomique au lancement (`409` si insuffisant, limite de clips simultanés), règlement par scène réussie, remboursement sur échec, annulation, timeout et redémarrage du worker, balayeur périodique des réservations orphelines. Assistant IA et chat du plan facturés (`credit_hold`). 100 crédits à la vérification de l'adresse (une fois par compte), `GET /api/credits`. Admin illimité ; budget en dollars réservé à l'admin.
- Admin : solde dans la barre latérale, page Crédits (registre paginé), prix et manque de crédits sur les boutons de lancement.
- Docs : `credits.md` (nouveau), `api.md`, `costs.md`, `comptes.md`, `securite.md`, `exploitation.md`, `README.md`.

## 2026-11-01 (lot 1 SaaS : comptes et isolation)
- Fin du mono-utilisateur : comptes e-mail + mot de passe (scrypt), vérification d'adresse, mot de passe oublié, sessions révoquées par compte (`app/api/auth.py`, `security.py`, `mailer.py`), migration `0015` (tables `users` et `email_tokens`, `projects.user_id`, admin créé depuis `ADMIN_EMAIL`/`ADMIN_PASSWORD`, projets existants rattachés à l'admin : reconnexion obligatoire). Règle anti-prise de compte (réinscription sur compte non vérifié = lien de réinitialisation, `/reset` vérifie l'adresse). SMTP avec certificat vérifié (465 TLS implicite, `STARTTLS` avec identifiants), faux mailer au journal en dev, `PUBLIC_URL`.
- Isolation : `require_project_access` sur les routes `{project_id}` (404 uniforme), liste de l'admin limitée à ses projets, SSE (`visible_events`) et coûts filtrés, Réglages / voix / import de musique réservés à l'admin, `GET /settings/editor` pour l'éditeur. Tests : `test_isolation.py`, `test_api_auth.py`.
- Admin : écrans de connexion, inscription, vérification, mot de passe oublié et réinitialisation, `auth.ts`, navigation filtrée par rôle, bandeau d'adresse non confirmée.
- Correctifs finaux : `scripts/seed_music.py` se connecte avec `--email` (défaut `ADMIN_EMAIL`) ; avertissement documenté : pas d'inscription publique avant le lot 2 (crédits).
- Docs : `comptes.md` (nouveau), `securite.md`, `api.md`, `exploitation.md`, `settings-providers.md`, `music.md`, `.env.example`.

## 2026-11-01 (suite)
- Landing : section « Pour TikTok, YouTube Shorts et Reels » (6 styles, 6 formats) et mur de 24 clips sans répétition. 16 nouvelles scènes (images Flux dev, clips Wan 2.2) générées en local par `backend/scripts/gen_landing_assets.py`, qui n'utilise plus Gemini.

## 2026-11-01 (landing : cas d'usage variés au lieu du renard)
- Accroche en mur de clips verticaux qui dérivent en colonnes, section « cas d'usage » (produit, immobilier, restauration, mode, voyage, application), lecteur de scènes sur une pub sneaker en trois plans, images du pipeline et de la conclusion refaites hors renard. Prompts de mouvement qui nomment chaque élément animé (corrige la lanterne figée). Doc : `landing.md`.

## 2026-10-31 (image de départ des scènes par Gemini, option avancée)
- Nouvelle préférence `start_image_provider` (`comfyui` = Flux Kontext par défaut, `gemini`) et choix par lancement (Avancé du panneau Clips, `start_image`) : Gemini compose l'image de départ des scènes qui ont des images de référence (`GeminiImage.generate(references=…)`), Wan I2V l'anime (`ComfyUIProvider.generate(start_image=…)` saute Kontext). Estimation du budget et refus sans clé Gemini avant le lancement. Qualité à comparer sur un projet réel. Docs : `profils-generation.md`, `providers.md`, `api.md`.

## 2026-10-31 (deck de présentation)
- Diaporama Beamer de 10 diapositives dans `pitch/deck.tex` (thème Studio, schémas TikZ du pipeline et de l'architecture, visuels de la landing). Doc : `pitch.md`.

## 2026-10-31 (page de présentation `/decouvrir`)
- Nouvelle page publique : accroche plein écran (fondu enchaîné, zoom lent et zoom au défilement), lecteur 9:16 interactif (trois scènes indépendantes réordonnables), carrousel du pipeline en huit étapes illustrées, points forts et conclusion plein cadre ; animations coupées avec `prefers-reduced-motion`. Images par Gemini (`GeminiImage.generate` accepte `aspect_ratio`) et clips par Wan I2V direct (ComfyUI, profil `fast`) via `backend/scripts/gen_landing_assets.py`, versionnés dans `admin/public/landing/`. Doc : `landing.md`.

## 2026-10-31 (journal IA : traces Langfuse selon les bonnes pratiques)
- Passage au SDK officiel `langfuse` (v5) : une trace par lancement d'étape (`run-<étape>`, session `projet-<id>`), une generation par tentative d'appel provider, noms stables verbe-d'abord, entrée en messages, tokens d'usage (`TextResult.input_tokens/output_tokens`, Claude et Gemini), coût, erreurs, environnement `APP_ENV`. Variable `LANGFUSE_BASE_URL` (nom standard) ; vidage à l'arrêt de l'API et du worker. Skill `langfuse` installé dans `~/.claude/skills`. Trace vérifiée sur le projet Langfuse via la CLI. Doc : `langfuse.md`.

## 2026-10-31 (journal IA : Langfuse Cloud)
- Chaque tentative d'appel provider est envoyée à Langfuse Cloud (trace par projet, generation avec prompt, réponse, coût, erreur) depuis `tracked_call`, en arrière-plan et sans jamais faire échouer une étape. Réglages `langfuse_public_key`, `langfuse_secret_key` (chiffrée), `langfuse_base_url` ; carte « Langfuse » dans Providers et clé `langfuse` dans `/api/providers/health`. Sans clés : désactivé. Doc : `langfuse.md`.

## 2026-10-31 (revue finale de la refonte du Plan)
- Validation du script (`approve`) : les images de référence qui n'existent pas encore (`pending`, `stale`) sont lancées à ce moment (`start_reference_after_script`, qui publie elle-même l'événement `running`) ; refus (budget…) silencieux, étape `failed` non relancée.
- Les clips lancés pendant la génération des images de référence attendent leur fin dans la file au lieu de partir sans elles.
- Worker : un échec inattendu du lancement des références ne fait plus échouer le job du script et la file du projet repart toujours (`try/finally`).
- Écran Plan : la confirmation « Valider le plan et générer » décrit ce qui se passe vraiment (images du casting manquantes lancées, clips/voix/musique/montage depuis la page projet). Docs : `references.md`, `admin.md`, `file-attente.md`.

## 2026-10-31 (refonte de l'écran Plan : synthèse)
- Refonte terminée : images de référence générées dès que le script est écrit, écran Plan en cartes (chat, casting, scènes avec pastilles et enchaînements, panneau Apparence), mêmes casting et enchaînements sur la page projet, présentation soignée de l'histoire et de la génération du plan (détail dans les entrées du jour ci-dessous). Vérifié de bout en bout en `FAKE_PROVIDERS=true` ; `compact_prompt` sans lambda (mypy), docstring de `PUT …/scenes/{id}/reference` alignée (`elements` = liste complète, principale comprise). Docs : `references.md`, `admin.md`.

## 2026-10-31 (écran Plan : histoire et génération du plan)
- Phase histoire en sections titrées avec compteur (Style, Éléments suivis par type, Beats et durée), pastille de type sur chaque élément, durée sur chaque beat, état vide en pointillés. « Écrire les scènes » et « Valider le plan et générer » partagent la barre d'action du bas (`PlanFoot`).
- Génération, échec et plan jamais généré : les étapes Idée, Histoire, Scènes avec leur état écrit, le temps écoulé et l'erreur de l'étape en échec (`PlanProgress`, `planProgress`). Docs : `story.md`, `admin.md`, `design-system.md`.

## 2026-10-31 (page projet : casting, enchaînements et accessoires)
- Onglets Script et Clips de la page projet : le casting (`CastStrip`, images toujours visibles) en tête de panneau ; cartes du Script avec vignette, pastilles et enchaînement comme à l'écran Plan. Liste des scènes : pastilles d'éléments et trait d'accent reliant les scènes enchaînées.
- « Image de référence » (Clips) ne garde que l'édition (prompt, import, régénération, ajout), sans son propre rendu d'image ; « Images envoyées avec le clip » affiche le nom des éléments et garde l'image principale dans les éléments de la scène (son état n'est plus perdu). `CastStrip` relance lui-même l'image d'un élément ; styles de carte avec casting partagés (`Cast.css`). Docs : `admin.md`, `references.md`.

## 2026-10-31 (écran Plan en cartes)
- Écran Plan en trois colonnes : chat, plan (casting avec images mises à jour en direct, scènes en cartes avec vignette de l'élément principal, pastilles d'éléments et leur état, enchaînement réglable depuis la carte), panneau Apparence (fiche visuelle, style, modèle d'image, dépense). « Générer » / « Réessayer » d'un élément du casting relancent sa seule image. Docs : `admin.md`, `design-system.md`.
- Écran Plan : les images de référence en cours ne verrouillent plus la relecture (`planLocks`) ; seuls l'enregistrement du plan (raison affichée) et le chat attendent leur fin. Enchaînement masqué tant que l'ordre du brouillon diffère de l'ordre enregistré ; cadre vide du casting nommé avec son état (lecteur d'écran, infobulle).
- Mode `FAKE_PROVIDERS` : le LLM factice répond aux passes histoire, inventaire et prompt visuel par scène (`fakes.py`), pour dérouler le flux histoire → scènes → casting sans clé API.

## 2026-10-31 (images de référence pendant la relecture du script)
- `reference` peut démarrer pendant la relecture du script (`can_start`) ; changer le texte du plan ne périme plus les images de référence, sauf si les éléments changent (`script_stale_names`).
- Lancement automatique : en fin de job `script`, le worker lance `reference` (`start_reference_after_script`) si le script liste des éléments, `reference` est `pending`/`stale` et l'autopilot est éteint ; un refus (budget, générateur) est silencieux et n'échoue pas le script. Docs : `references.md`, `story.md`.

## 2026-10-29 (enchaînement des scènes réglable)
- Clips : 2 images au plus par scène (`MAX_KONTEXT_IMAGES` et `MAX_SCENE_IMAGES` passent de 3 à 2 : essais Kontext, le troisième sujet disparaît toujours) et prompt allégé envoyé à Kontext (`compact_prompt` : le descripteur d'un élément envoyé en image est remplacé par son nom). Doc : `story.md`.
- Clips : le menu « Référence de la scène » disparaît ; une seule liste de cases avec miniatures (« Images envoyées avec le clip », 2 au plus, la plus ancienne est retirée). La première cochée est l'image principale. `toggled(ids, id)` simplifié.
- Case « Enchaîner » par scène dans Clips (`PUT …/scenes/{id}/continuity`, `continuity` exposé) ; une scène enchaînée ne se régénère pas seule tant que la précédente n'a pas de clip (409 et bouton grisé). Docs : `references.md`.

## 2026-10-29 (cohérence des scènes enchaînées)
- Scène « continue » dont le sujet entre dans l'image (absent de la scène précédente) : sa référence est envoyée avec la dernière image du clip précédent, sinon son identité n'était dans aucune entrée (projet 61, scène 3 : Gavrilo).

## 2026-10-29 (éléments de l'histoire en référence)
- Les éléments de l'histoire sans image (accessoires au-delà de 6, lieux) se promeuvent en référence depuis Clips (`story_id` sur `POST …/references`) ; plafond manuel de 12 (`MAX_REFERENCES_TOTAL`). Le choix des images d'une scène ne compte plus les éléments sans référence.

## 2026-10-29 (file d'attente des références, plusieurs images par scène)
- Mise en file des images de référence : les `params` partent avec `POST …/steps/reference/run` (le `PATCH` était refusé pendant l'étape, la demande n'arrivait jamais en file) et un élément seul se met en file pendant que l'étape tourne.
- Clips : « Autres images envoyées avec le clip » (cases à cocher, 3 images au plus avec la principale) ; `PUT …/reference` accepte `elements`. Docs : `references.md`, `file-attente.md`.

## 2026-10-29 (références visibles dans l'éditeur)
- Clips : la section « Image de référence » est dépliée dès que le script liste des éléments ; chaque carte indique les scènes qui l'utilisent et le menu « Référence de la scène » affiche la miniature choisie (`scenesUsing`). Doc : `references.md`.

## 2026-10-28 (durée totale de la story)
- Les durées des beats sont rééchelonnées quand leur somme s'écarte de plus de 10 % de la durée cible (`fit_durations`, entre 2 s et 5 s par beat) : la vidéo test de 30 s durait 25,5 s, celle de 60 s 54 s. Doc : `story.md`.

## 2026-10-28 (personnages sans sosie)
- La passe inventaire de la story demande des personnages humains ordinaires et originaux : jamais le visage, le nom ou le sosie d'une personnalité réelle (un patron de la vidéo test ressemblait à une figure politique).

## 2026-10-28 (type réel des images Gemini)
- Le type d'une image Gemini est déduit de ses octets (PNG, JPEG, WebP) et non du type annoncé : Gemini annonçait `image/png` pour des JPEG, d'où des références enregistrées en `.png` que ffmpeg refusait (`Invalid PNG signature`).

## 2026-10-28 (autopilot : images de référence)
- Le mode automatique génère l'étape `reference` quand le script liste des éléments récurrents (mascotte, produit, personnage), au lieu de toujours l'ignorer : le même sujet reste identique d'une scène à l'autre, et l'écran Plan affiche enfin les images. Sans élément récurrent, comportement inchangé. Doc : `autopilot.md`.

## 2026-10-28 (plafond de job pour les clips locaux)
- `MAX_JOB_TIMEOUT` passe de 6 h à 24 h : un projet de 17 scènes en clips ComfyUI séquentiels (un GPU, une scène à la fois) dépassait 6 h et le job expirait à 15/17. Docs : `api.md`, `providers.md`.

## 2026-10-26 (voix par personnage)
- Chaque beat de la story a un locuteur (personnage ou narrateur) et chaque personnage une voix du catalogue (attribuée automatiquement aux personnages qui parlent, modifiable dans l'écran Plan) ; `Scene.speaker` (migration `0014`) ; l'étape Voix synthétise chaque scène avec la voix de son locuteur, sinon celle du narrateur. Projets existants inchangés. Doc : `story.md`, `workflow-video.md`.

## 2026-10-26 (plusieurs images pour Kontext)
- Kontext reçoit jusqu'à 3 images par scène : l'image principale (dernière image du clip précédent ou référence de la scène) puis les références des autres éléments visibles, personnages d'abord (`extra_references`, `kontext_workflow` à `ReferenceLatent` enchaînés, `generate(..., references=)`).
- Coût indicatif : ≈ 10 min de Kontext pour 3 images contre ≈ 5 min pour une, mesuré sur une machine qui servait aussi à autre chose (à refaire à vide). Doc : `story.md`, `workflow-video.md`.

## 2026-10-26 (chaînage par dernière image)
- Chaque beat de la story porte `continuity` (`continue` : suite directe du précédent, `cut` : changement de lieu), copiée sur `Scene.continuity` (migration `0013`) et modifiable dans l'écran Plan.
- Clips : une scène `continue` part de la dernière image du clip précédent (`montage.last_frame`), envoyée à Kontext à la place de la seule image de référence ; génération séquentielle quand une scène est chaînée, repli sur la référence sans clip précédent. Les projets existants ne sont jamais chaînés.
- Doc : `story.md`, `workflow-video.md`.

## 2026-10-26 (scénario en passes : étape `story`)
- Nouvelle étape **`story`** entre `idea` et `script` : l'histoire en beats (résumé, voix off, durée) puis les éléments suivis (personnages, accessoires, lieux : descripteur figé, prompt de référence) et leur état dans chaque beat ; contrôles mécaniques (accessoire jamais repris, id inconnu, état qui revient en arrière), une relance ciblée par passe.
- `script` écrit un prompt visuel par beat avec les descripteurs et états des éléments présents (le serveur les ajoute s'ils manquent) ; `Scene.elements` ; `Scene.reference` peut être un accessoire. Projets existants : story validée et vide (migration `0012`), ancien chemin inchangé.
- Écran Plan : phase « histoire » modifiable (éléments, beats) avant « Écrire les scènes » ; la génération du plan s'arrête sur `story`. Panneau Histoire dans l'éditeur.
- Banc d'essai `eval_script.py --pipeline old|new|both` (thème du projet 52 ajouté). Correctif trouvé en réel : la lecture des réglages du LLM est sérialisée pendant les appels parallèles par beat. Docs : `story.md`, `workflow-video.md`, `autopilot.md`, `api.md`.

## 2026-10-25 (audit du prompt engineering)
- Guide de prompt visuel sans contradiction (une action en 2-3 gestes, logos sans lettres, aucune négation) et **sans style imposé** : le style du projet est injecté partout, y compris l'assistant IA et les images de référence.
- **Dernière scène = appel à l'engagement** (like, commente, partage) et première scène = accroche ; validation du script (`script_problems` : durée, voix off trop longue, engagement), une relance ciblée, repli garanti, défauts restants dans `result.warnings`.
- Prompt visuel en **deux paragraphes** (image fixe + `Motion:`) : Kontext/Flux lisent l'image, Wan I2V le mouvement, Wan T2V et fal les deux (`split_prompt`, `plain_prompt`). À valider en A/B sur la machine.
- Descripteur par élément récurrent ajouté en tête des prompts de scène par le serveur (`apply_descriptors`).
- Budget de tokens de sortie du script proportionnel au nombre de scènes (`script_max_tokens`, borné) : le défaut de 4000 tronquait les scripts de 30 s et plus.
- Banc d'essai `backend/scripts/eval_script.py`. Docs : `workflow-video.md`, `providers.md`, `references.md`, `assistant-ia.md`.

## 2026-10-25 (refonte design : prompt Lovable)
- `docs/lovable-prompt.md` : prompt pour générer la maquette de l'admin dans Lovable (tokens du design system, 8 écrans, états) et marche à suivre pour porter la maquette dans `admin/`.

## 2026-10-25 (audit : typage et Docker)
- `backend/Dockerfile` (+ `.dockerignore`) : image unique API/worker, Python 3.14, ffmpeg, utilisateur non root ; doc dans `docs/exploitation.md`.
- `mypy` ajouté (dépendance dev, config dans `pyproject.toml`, étape CI, `npm run lint`) ; 37 erreurs de typage corrigées (`rowcount` remplacé par `RETURNING`, `scalar_one()` pour les lignes obligatoires, `Storage` typé dans le contexte du pipeline, `TypeVar` des résultats de provider).

## 2026-10-25 (audit : clés API chiffrées)
- Clés API des réglages chiffrées au repos (`app/crypto.py`, Fernet dérivé de `SECRET_KEY`) ; migration `0011` chiffrant les clés existantes ; dépendance `cryptography`. Tests ajoutés. Doc : `docs/securite.md`.
- Session révocable : le cookie porte une « époque » stockée en base ; « Sortir » l'incrémente et invalide tous les cookies (dont un cookie copié). `require_auth` lit la base. Tests ajoutés.

## 2026-10-24 (voix : texte éditable et catalogue)
- Étape Voix : le texte prononcé de la scène se modifie directement (assistant IA compris) ; l'enregistrer périme la voix, le montage et l'export (`PUT /scenes/{id}/voice-text`).
- Réglages → ElevenLabs : catalogue de voix (nom + identifiant, ajout, retrait, import depuis le compte via `GET /providers/voices`) et voix par défaut choisie dans ce catalogue (réglage `voice_catalog`).
- Étape Voix : sélecteur de voix du catalogue à la place de l'identifiant ElevenLabs saisi à la main. Tests ajoutés.

## 2026-10-24 (référence de scène pendant les clips)
- Le choix de la « Référence de la scène » reste possible pendant la génération des clips (l'API ne le refuse plus) ; il vaut pour les scènes pas encore démarrées. Test ajouté.

## 2026-10-24 (ajout d'éléments de référence)
- Clips → Image de référence : bouton « Ajouter un élément » (nom + description) pour ajouter un personnage ou un objet que le script n'avait pas listé (`POST /projects/{id}/references`, 6 au plus). Identifiants d'éléments désormais sans accents (`ref_id`). Tests ajoutés.

## 2026-10-24 (import de référence pendant les clips)
- L'import d'une image de référence reste possible pendant la génération des clips (le job a déjà lu ses images, la nouvelle sert aux clips suivants) ; il n'est refusé (409) que pendant l'étape reference elle-même. Test ajouté.

## 2026-10-24 (plus de blocage pendant une génération)
- Prompt visuel des scènes et prompts des images de référence : champs et « Améliorer » (assistant IA) restent utilisables pendant une génération ; le prompt n'est envoyé qu'au lancement.
- Images de référence : choix du générateur et boutons de génération restent actifs (la demande part en file, libellé « Mettre en file ») ; seul l'import d'une image est grisé tant que l'étape ou les clips tournent, l'API le refusant.

## 2026-10-23 (confirmations avant les actions sensibles)
- Modale de confirmation (`useConfirm` + `ConfirmDialog`) avant : régénérer une étape qui a déjà un résultat (avec la liste des étapes aval à refaire), arrêter une génération (panneau, bandeau d'activité, écran du plan), générer en lot les clips ou voix manquants, régénérer une voix ou une image de référence existante, valider le plan et lancer la génération automatique.

## 2026-10-23 (arrêt sur image à l'export, aperçu calé sur le montage)
- Export : le clip est étiré jusqu'à la fin de la marge de 0,3 s de la scène (plus d'arrêt sur image d'environ 0,45 s à chaque fin de scène) ; les segments en cache sont ré-encodés.
- Aperçu sans rendu : chaque scène joue à la durée et aux vitesses du montage (voix accélérée ou ralentie, clip étiré) au lieu des 3 s du script ; la voix n'est plus coupée au changement de scène et la timeline affiche la durée réelle de chaque scène.

## 2026-10-23 (file d'attente, voix indépendante des clips)
- File d'attente par projet (5 demandes) : une génération demandée pendant qu'une autre bloque l'étape est mise en file puis lancée dans l'ordre ; bandeau d'activité avec flèche pour déplier et retirer les demandes en attente. Voir `docs/file-attente.md`.
- Voix et musique ne dépendent plus des clips : elles se lancent pendant leur génération et ne sont plus périmées par une régénération de clip ; seul le montage rassemble clips, voix et musique.

## 2026-10-23 (upscale moins brutal)
- Profil Maximum : l'agrandissement ESRGAN 4x-UltraSharp est mêlé à 50 % à un agrandissement lanczos simple (`ImageBlend`) avant le mp4, pour atténuer l'aspect peinture (peau lissée, contours durs). S'applique aux clips générés après ce changement ; les anciens clips ne sont pas modifiés. Réglage : `PLAIN_SHARE` dans `providers/workflows.py`.

## 2026-10-23 (état d'une génération en cours, coût au survol)
- Carte de génération compacte (anneau, scène, temps écoulé et restant, barre d'avancement, « Arrêter ») à la place de l'encart à bordure colorée et à longue phrase ; anneau sur l'étape en cours (frise, bandeau d'activité). Messages d'état sans bordure colorée.
- Temps : l'API expose `running_since` des étapes en cours ; estimation restante d'après la durée annoncée du profil ComfyUI, remplacée par le rythme mesuré dès qu'une scène est prête.
- Boutons grisés pendant une génération : anneau et raison au survol (« En cours : Clips, scène 13 »).
- Détail de dépense au survol ou au focus (plus de clic) ; postes « Chat du plan » nommés.
- Génération en cours : la pastille « Clips : scène 4 » (temps, Voir, Arrêter) passe au centre de l'en-tête au lieu d'une ligne sous celui-ci ; sur mobile elle occupe la ligne sous le titre, sans le temps. Bouton « Reprendre : <étape> » supprimé (la frise des étapes suffit).

## 2026-10-23 (éditeur : moins de texte, colonnes réglables, saisie extensible, musique dans l'aperçu)
- Textes d'aide permanents retirés de l'éditeur (étape périmée, étapes précédentes à valider, verrouillage, mode d'emploi du montage, flèches…) ; le détail passe en infobulle. Bandeau de coût réduit au détail par étape et au plafond.
- Colonnes des scènes et de l'étape : largeur réglable à la souris ou au clavier, repliables par un bouton, disposition mémorisée.
- `TextArea` auto-extensible avec compteur de caractères (rouge à la limite) sur tous les champs ; assistant IA sur la ligne du libellé, consigne repliée par défaut.
- Étape Idée validée : titre, plateforme et durée seuls en évidence ; thème, angle repliés, piste de départ et génération masqués.
- Correctif : la musique de fond jouait uniquement dans le rendu final. L'aperçu la lance maintenant avec la voix et le clip (niveau du montage, boucle, recalage sur la timeline).

## 2026-10-23 (refonte visuelle et responsive de l'admin)
- Fondations : police Geist (remplace IBM Plex), quatre niveaux de surface, rayons 6/10/14 px, transitions 120 ms, mouvement réduit respecté. Boutons, champs, listes déroulantes (flèche dessinée), contrôle segmenté, volets repliables et boutons radio redessinés.
- Icônes : jeu unique étendu (relancer, arrêter, importer, assistant, notes en étoiles SVG…), plus aucun `✓`, `★` ni emoji dans l'interface ; titres de projet nettoyés à l'affichage (`plainTitle`).
- Pages : Projets (recherche à loupe, squelettes de chargement, état vide), Nouvelle vidéo (largeur resserrée, hiérarchie), Réglages, Musique (lecteur audio maison, suppression par icône), Connexion.
- Éditeur : actions à icônes, aperçu surélevé, sous-titre proportionnel au cadre ; sur mobile, trois volets (Aperçu, Scènes, Étape) avec barre d'onglets en bas. Hors éditeur, navigation en barre d'onglets en bas sous 720 px.
- Docs : `docs/design-system.md` (surfaces, icônes, composants) et `docs/admin.md` (éditeur mobile) mis à jour.

## 2026-10-23 (montage : voix et clip convergent)
- Voix et clip de durées différentes : la scène dure à peu près la moyenne des deux. Voix plus longue : voix accélérée (×1,4 au plus), clip ralenti (×1,25 au plus) ; voix plus courte : voix ralentie (×0,85 au plus), clip accéléré. Fichiers d'origine inchangés. `voice_tempo` devient `converge`, nouveau `MAX_STRETCH`, segments en cache invalidés. Détail : `docs/montage.md`.

## 2026-10-23 (références par élément, pilotées par le script)
- Le script liste les éléments récurrents (personnages, produits) et attribue à chaque scène l'élément principal (`references`, `scenes.reference`, migration `0009`) ; l'étape reference génère une image par élément ; chaque clip part de l'image de sa scène. Admin : cartes d'éléments (prompt modifiable, import, régénération) et choix de la référence sous chaque scène. Détail : `docs/references.md`.

## 2026-10-23 (ComfyUI : modèles déchargés après chaque étape)
- `ComfyUIProvider._free()` appelle `POST /free` après chaque workflow (image Kontext/Flux, puis clip) : les modèles de l'étape finie ne restent plus en cache pendant que la suivante charge les siens (≈ 24 Go sur 36 Go de RAM). Mesure : scène avec image de référence, profil Rapide, 690 s contre 1517 s sans déchargement (prompts différents, une seule mesure chacune).

## 2026-10-23 (voix accélérée jusqu'à ×1,4)
- `MAX_TEMPO` passe de 1,25 à 1,4 : sur le projet McDonald's, 5 voix sur 20 dépassaient 1,25 (jusqu'à ×1,34 du clip) et laissaient une image figée. Tests de montage ajustés, `docs/montage.md` à jour.

## 2026-10-22 (parcours de création : idée → plan avec chat → éditeur)
- Nouvelle création en trois temps : écran `/new` (idée, style, durée, un seul bouton « Créer le plan »), écran `/projects/:id/plan` (chat avec l'IA à gauche, plan éditable à droite, scènes repliables, « Valider le plan et générer »), puis l'éditeur existant, qui renvoie vers l'écran Plan tant que l'idée ou le script n'est pas validé (anciens projets compris). L'ancienne création de l'accueil disparaît.
- Backend : `Project.style` (migration `0007`, `GET /styles`, directive injectée dans le prompt du script), autopilot borné à `script` (`POST …/plan/generate`), chat du plan (`plan_messages`, migration `0008`, `POST …/plan/chat`, historique, annulation du dernier changement ; refus si une étape tourne ou si le budget est atteint ; réponse invalide → 502 sans rien modifier).
- Admin : brouillon et carte de scène extraits de `ScriptPanel` (`usePlanDraft`, `SceneCard`), `Pills` et `TitleField` partagés.

## 2026-10-22 (assistant IA : un seul bouton)
- Les trois liens « Générer / Reformuler / Consigne » de chaque champ texte sont remplacés par une ligne unique : consigne facultative toujours visible + un seul bouton (« Générer avec l'IA » si vide, « Améliorer avec l'IA » sinon), comme l'éditeur de prompt des scènes. `PromptEditor` réutilise désormais `AssistField` (une seule logique d'assistant).

## 2026-10-22 (budgets cohérents et justifiés)
- Un seul format de montant (`usd`) et un seul mot (« Dépensé ») dans l'éditeur, l'accueil, l'étape Clips et la page Coûts ; l'ancien format `0,28 $` fabriqué à la main dans `models.ts` disparaît. Estimation des clips toujours préfixée « ≈ ».
- Éditeur : « Dépensé » discret avec détail par étape au clic (`cost_by_step`), ce qui est compté, le plafond par vidéo (`budget_usd`, enfin visible) ; le plafond ne s'affiche en clair qu'à partir de 80 %. Accueil : pas de « 0 $ » sur les vidéos locales.

## 2026-10-22 (bandeau d'activité)
- Éditeur : ligne fine sous l'en-tête qui dit quelle génération tourne (étape, scène ou avancement), avec « Voir » et « Arrêter », et pastille clignotante sur la scène visée dans le storyboard. Avant, il fallait ouvrir chaque scène pour savoir ce qui tournait.

## 2026-10-22 (image de référence pour tous les profils, voix accélérée)
- ComfyUI : dès que le projet a une image de référence, **tous les profils** l'utilisent. L'app choisit le graphe selon l'entrée : référence → Flux Kontext (`comfyui-flux-kontext.json`) → Wan I2V ; sans référence, comportement inchangé. Lancement refusé (`409`) si Kontext ou Wan I2V manquent. `VideoProvider.reference_availability` (point d'accroche d'une future offre payante). Modèle `flux1-kontext-dev-Q4_K_S.gguf` installé dans `ComfyUI/models/diffusion_models`.
- Montage : une voix plus longue que le clip est accélérée (×1,25 au plus) pour coller au clip ; sinon la dernière image est tenue, plus de clip bouclé. Clips demandés 0,3 s plus longs que la scène ; scènes limitées à 5 s dans le script.
- Nouveau `docs/comfyui-workflows.md` : installation, modèles, graphes et pièges, pour repartir de zéro.

## 2026-10-22 (plan du script : fiche visuelle, prompts autonomes, consigne)
- Script : le LLM écrit d'abord une fiche visuelle (`bible` : personnages, marques et logos décrits, décor, style), puis des `visual_prompt` autonomes de 120 à 180 mots qui la reprennent mot pour mot, avec mouvement dès la première seconde (plus de ralenti), cadrage différent d'une scène à l'autre et continuité de décor. Plus d'appel à l'action (like, commente, abonne-toi) en fin de vidéo.
- Éditeur : le panneau Script affiche la fiche visuelle (modifiable, reformulable avec une consigne) et un champ « Consigne pour régénérer le plan ». `POST …/steps/script/run` accepte `instruction`. L'image de référence part de la fiche par défaut.
- À savoir : ComfyUI en texte-vers-vidéo n'utilise pas l'image de référence ; la ressemblance vient du texte.

## 2026-10-22 (réordonner les scènes)
- API : `POST /api/projects/{id}/scenes/reorder` `{scene_ids}` : liste complète des scènes dans le nouvel ordre (`422` sinon, `409` si clips, voix ou montage tournent). Clips et voix suivent leur scène ; seuls le montage et le rendu final deviennent périmés.
- Éditeur : « Monter » / « Descendre » sous la scène sélectionnée du storyboard (`reorderedIds`, `SceneList`). Les durées de la timeline ne sont pas ajustables à la main : elles viennent de la voix.

## 2026-10-22 (coûts en NUMERIC)
- Migration `0006_cost_numeric` : `provider_calls.cost_usd` passe de `FLOAT` à `NUMERIC(12, 6)` (valeurs existantes arrondies à 6 décimales). Le modèle lit toujours des `float` (`asdecimal=False`) : seul le stockage devient exact. S'applique au prochain `npm run dev` / `npm run migrate`.

## 2026-10-22 (style des sous-titres, ErrorBoundary)
- Montage : choix du style des sous-titres (Contour, Boîte, Gros jaune) dans le panneau Montage, paramètre `subtitle_style` de l'étape (inconnu → Contour). `SUBTITLE_STYLES` / `ass_header` dans `services/montage.py`, tests ASS et rendu ffmpeg réel pour chaque style.
- Admin : `RouteErrorBoundary` autour des pages (une exception de rendu affiche un message et « Réessayer » au lieu d'un écran vide).

## 2026-10-22 (ClipsPanel découpé)
- `ClipsPanel` (520 → 264 lignes) : l'éditeur de prompt (dupliqué pour la scène et l'image de référence) devient `PromptEditor`, la section référence `ReferenceSection`. Comportement inchangé, sauf : consigne IA et historique d'amélioration ne sont plus gardés quand on change de scène (le brouillon du prompt, lui, l'est). Icône ✨ retirée des boutons IA.

## 2026-10-22 (génération longue : progression et notification)
- Étape en cours pour toutes les scènes : barre de progression (`<progress>`) sous la phrase d'état. À la fin d'une étape (à valider, terminée, échec, arrêtée) alors que l'onglet est masqué : titre d'onglet « Clips : à valider · … » et notification navigateur (autorisation demandée au premier lancement). `completionMessage` (`studio.ts`), `hooks/useCompletionAlert.ts`.

## 2026-10-22 (export d'un rendu périmé)
- Éditeur : « Exporter » n'est plus actif quand le montage est périmé, relancé ou en échec (il téléchargeait un ancien rendu) ; infobulle explicative et bouton « Reprendre : étape » (`exportBlockedReason`, testé).

## 2026-10-22 (imports sécurisés, image de référence)
- Imports de fichiers (clip importé, musique) : la clé de stockage ne reprend plus l'extension du nom envoyé par le
  client (injection de chemin/clé signalée par la revue de sécurité) : nom aléatoire + extension d'une liste fermée qui
  donne aussi le type MIME (`app/uploads.py`) ; extension inconnue → `400` « Extension vidéo non supportée ». Le nom
  d'origine, nettoyé (dernier segment, sans caractères de contrôle, 255 caractères), est gardé dans la nouvelle table
  `asset_originals` (migration `0005_asset_originals`, cascade à la suppression de l'asset), renvoyé en
  `original_name` et affiché en infobulle sur « (importée) ». Musique : `music/<32 hex>.<ext>` au lieu de toujours
  `.mp3`. Doc : `docs/imports-fichiers.md`.
- Image de référence : sans clé fal, la génération échouait tard dans le worker avec « fal: réseau (Illegal header
  value b'Key ') » (en-tête `Authorization: Key ` vide refusé par httpx, réessayé comme une panne réseau). Désormais :
  `ProviderError` non relançable « Clé API fal manquante, à saisir dans Réglages → fal.ai » avant toute requête (image, vidéo ;
  santé `false`), `POST …/steps/reference/run` refusé d'emblée (`409` avec cette raison, `400` modèle inconnu) par le
  même contrôle que les clips dans `launch_step` (`ModelRefused`, ex-`ClipModelRefused`), et `GET /providers/models`
  expose la disponibilité des modèles d'image (`image: [{provider, id, name, available, reason}]`). Admin : « Générer »
  désactivé avec la raison et un lien « Ouvrir les Réglages », modèle marqué « (indisponible) ».
- Revue des imports : un fichier sans extension est refusé comme une extension inconnue (`400`, plus de `mp4`/`mp3`
  par défaut) ; le nom du fichier téléchargé (`…/assets/{id}/download`) prend son extension du type MIME de l'asset
  (`DOWNLOAD_EXTENSIONS`, `bin` sinon) et non plus de la clé, qu'un ancien import tenait du client.
- Message de clé manquante reformulé « Clé API fal manquante, à saisir dans Réglages → fal.ai » (plus de
  « Génération impossible : fal : … » à deux préfixes) ; l'image de référence affiche la raison seule, la carte vidéo
  « kling indisponible (Clé API fal manquante, …) ».
- Image de référence par **Gemini** (défaut, même clé que la rédaction) : `GeminiImage` (`gemini-3.1-flash-image`,
  réglage `gemini_image_model`), fal reste disponible ; réglage `image_provider` (`gemini` | `fal`) ; cartes `image`
  par provider avec disponibilité ; contrôle au lancement par provider ; coût par tokens journalisé. Admin : choix du
  générateur (provider en clair) dans le volet Image de référence, Gemini par défaut quand il est disponible ;
  Réglages : modèle d'image Gemini et provider de l'image de référence. `ReferencePanel.tsx`, devenu inutilisé
  (référence dans `ClipsPanel`), supprimé.
- Étape en échec dont le relancement est bloqué (image de référence sans clé, modèle vidéo indisponible) : la raison
  s'affiche au-dessus de « Relancer » (avant : bouton grisé sans explication).
- Même contrôle pour ElevenLabs, Gemini et Claude sans clé (avant : `401` du service, ou `TypeError` du SDK Anthropic) ;
  clés relues sans espaces de bord.

## 2026-10-21 (profils de génération : suite de la revue)
- Autopilot : le contrôle du modèle vidéo (`400` inconnu, `409` indisponible avec la raison de la carte) est fait par
  `launch_step` (`services/video_models.py`, partagé avec `POST …/steps/clips/run`) : l'autopilot s'arrête avant
  d'enfiler les clips, l'étape passe en `failed` avec la raison. `video_cards` quitte `api/providers_api.py`.
- Carte vidéo : champ `recommended` (profil local par défaut, `DEFAULT_PROFILE`) ; l'admin le suit (pastille, groupe
  affiché en premier, repli de `pickable`) au lieu de `RECOMMENDED` codé en dur dans `models.ts`.
- Étape Clips : lancements désactivés tant que les modèles (et les réglages, sans choix enregistré) ne sont pas chargés
  ou sans carte disponible, raison affichée (`launchBlocked`) ; plus d'appel `/estimate` avec un modèle vide
  (`useApi` accepte un chemin `null`). Vérifié dans le navigateur (chargement en cours, ComfyUI injoignable).
- Réglages : un ancien `default_video_model = workflow` est lu et écrit `max` (`AppSettings`), la carte cochée et la
  valeur utilisée par les lancements coïncident.
- ComfyUI : image de départ de Précision envoyée sous un nom fixe `vv_keyframe.png` (réécrit, plus d'accumulation dans
  `input/`), envoi et animation gardés par un verrou (deux jobs simultanés ne s'écrasent pas l'image) ; `LoadImage`
  hache le fichier, pas de cache périmé. Anciens `vv_keyframe_*.png` : suppression unique documentée.
- ComfyUI : disponibilité et santé limitées à 3 s par requête (`GET /providers/models` et lancement des clips ne
  restent plus bloqués jusqu'à 120 s) ; URL invalide (`httpx.InvalidURL`) = « ComfyUI injoignable » au lieu d'un `500` ;
  réponse d'upload sans `name` = erreur claire. Vérifié sur une API jetable : serveur muet → 200 en 3,07 s, URL
  invalide → 200 en 8 ms, lancement des clips → 409 « ComfyUI injoignable ».
- Précision : après un échec relançable de l'animation, la nouvelle tentative automatique reprend l'image Flux déjà
  produite (gardée par le provider, par profil et prompt, jusqu'au clip réussi).
- ComfyUI : disponibilité bornée à 3 s pour tout l'appel (`asyncio.timeout`), nœuds chargeurs interrogés ensemble
  (`gather`) : le verrou du projet n'est plus tenu jusqu'à ≈ 21 s au lancement des clips.
- Image Flux gardée : oubli par `pop` (sans erreur si un autre appel au même prompt l'a déjà oubliée), durée de vie
  commentée ; verrou de l'image de départ créé par boucle d'événements (un `asyncio.Lock` global se liait à la
  première boucle et échouait dans une autre, constaté en test).
- ComfyUI occupé : un délai dépassé grise les cartes « ComfyUI ne répond pas (occupé ?) » (distinct de « ComfyUI
  injoignable ») mais ne bloque plus un lancement (API ou autopilot) : le job attend son tour, comme avant le contrôle.
  Connexion refusée, URL invalide, fichier ou clé manquants bloquent toujours (`409`).
- ComfyUI occupé, admin aligné : la carte reste `available: true` avec la raison « ComfyUI ne répond pas (occupé ?) »
  (champ `busy` retiré, une seule source pour la carte et le contrôle au lancement) ; l'admin la laisse choisir et
  lancer, avec un avertissement (`cardNotice`). Vérifié dans le navigateur (ComfyUI muet : cartes cochables,
  avertissement jaune, « Générer les clips » actif).
- `docs/autopilot.md` : « Limite connue » sur le contrôle du modèle (désormais fait aussi pour l'autopilot) retirée.

## 2026-10-21 (profils de génération : corrections de revue)
- Admin : `pickable` traduit l'ancien modèle `workflow` en `max` (Réglages : Maximum mis en évidence) et ne bascule plus
  jamais sur une carte payante (repli limité aux cartes gratuites) ; les Réglages affichent l'erreur de `/providers/models`.
- Libellés : Précision sans « validable » (pas de pause entre Flux et Wan), « (recommandé) » retiré de la description de Rapide.
- Docs : limite connue des `vv_keyframe_*.png` non supprimés dans `input/` de ComfyUI et nettoyage manuel.

## 2026-10-21 (profils de génération : documentation, nettoyage, vérification réelle)
- `docs/profils-generation.md` : catalogue des 4 profils, benchmark (une scène, une seed ; la RAM libre est le facteur
  n°1 : Maximum 45 min avec swap saturé contre 17 min 40 s RAM libérée), comment ajouter un profil, limites
  (profil recommandé dupliqué dans l'admin, contrôle `400`/`409` absent des lancements de l'autopilot).
- Docs mises à jour : `providers.md` (profils, workflows T2V/I2V/Flux, prérequis par profil, 5B retiré),
  `api.md`, `settings-providers.md`, `workflow-video.md` (asset `keyframe`), `assistant-ia.md` (règles de
  composition, aussi suivies par l'étape script), `autopilot.md`, `exploitation.md`, `README.md` (plus de
  `COMFYUI_WORKFLOW_PATH` / `comfyui_workflow_path`).
- Commentaire de `VISUAL_PROMPT_GUIDE` aligné sur les règles de composition ; `scripts/bench_comfy.py` passe `ruff`.
- Vérification réelle (API et worker de la branche sur une base, une file Redis et un bucket jetables ; ComfyUI
  `ram_free` 14,2 Go au lancement, 4,4 à 7 Go pendant, swap ≈ 17 Go) : Rapide 330,8 s (job 333 s), Précision
  140,4 s (Flux) + 535,5 s (I2V) = 675,9 s (job 679 s) ; clips 720×1248, 16 fps, 49 images (`ffprobe`) ; image
  `keyframe` 576×1008 en `poster` de la variante dans l'admin.

## 2026-10-21 (profils de génération : cartes dans l'admin)
- Étape Clips : choix du profil par cartes (`ModelCards`, groupe radio natif) : étoiles vitesse/qualité, durée (local)
  ou coût (cloud) par clip, « recommandé » sur Rapide, cartes indisponibles grisées avec leur raison ; le choix pour une
  seule scène reste dans « Avancé ». Estimation : durée totale pour un profil local. Bouton « Valider et régénérer »
  quand le prompt de la scène a changé ; image de départ (`keyframe`) en `poster` de la variante.
- Réglages : champ « Workflow » de ComfyUI retiré ; profil vidéo par défaut choisi sur les mêmes cartes.
- `src/models.ts` (`stars`, `clipCost`, `totalEstimate`, `pickable`) ; l'ancien `ModelPicker` est supprimé.

## 2026-10-21 (profils de génération : API des modèles et lancement)
- `GET /api/providers/models` : `video` devient une liste de cartes (`provider, id, name, description, speed, quality,
  minutes_per_clip, cost_usd_per_clip, available, reason`) : 4 profils ComfyUI, modèles fal grisés « Clé fal manquante »
  sans clé ; ComfyUI éteint ou réponse inattendue de `/object_info` : cartes locales grisées, jamais de 500.
- `POST …/steps/clips/run` : modèle inconnu du provider → `400`, carte indisponible → `409` avec la raison, avant tout
  job ; l'ancien modèle `workflow` vaut Maximum.
- Réglage `comfyui_workflow_path` supprimé (refusé à l'écriture) ; défauts `comfyui` / `fast`.
- Profil Précision : l'image de départ est conservée (`Asset` `keyframe`, `meta.clip_asset_id`).

## 2026-10-20 (démarrage)
- `npm run dev` lance tout l'essentiel : Docker, migrations, API, worker, admin et ComfyUI (ignoré s'il tourne déjà sur :8188 ;
  `dev:comfy` supprimé). `--kill-others-on-fail` : un composant qui se termine normalement n'arrête plus les autres.

## 2026-10-20 (incident ComfyUI : toute la vidéo régénérée au lieu d'une scène)
- Cause établie (file Arq, historique ComfyUI, base) : un job `clips` sans `scene_id` enfilé 51 s après l'échec d'une
  régénération de scène (« ComfyUI injoignable ») : le « Relancer » d'une étape en échec relançait toutes les scènes. Le
  workflow n'est pas en cause (un prompt, une sortie, `batch_size` 1 : une requête ComfyUI par scène).
- Arrêt d'une génération : `POST /projects/{id}/steps/{name}/cancel` et bouton « Arrêter la génération » ; le worker
  interrompt l'appel en cours (ComfyUI `/interrupt`) ; le produit est gardé et se reprend.
- L'interface dit ce qui est généré (une scène, ou toutes avec l'avancement k sur M) ; champ API `target_scene`
  (remplace `failed_scene`) et `progress`.
- `run_id` d'un lancement de scène : `scene:<id>:<aléa>`. À savoir : l'API et le worker de `npm run dev` ne se rechargent
  pas, à redémarrer après une mise à jour (`docs/exploitation.md`).

## 2026-10-20 (régénérer une scène sans refaire la vidéo)
- Vérifié et testé : régénérer une scène émet une seule requête au provider (un seul clip ComfyUI).
- Après l'échec de la régénération d'une scène, « Relancer » ne refait que cette scène (`run_id = "scene:<id>"`,
  champ `failed_scene`) ; avant, il relançait toute la vidéo.
- « Régénérer tous les clips » demande confirmation ; un nouveau prompt choisit d'office le nouveau clip pour la scène.
- Montage incrémental : segments par scène mis en cache dans le stockage (`montage.segment_key`) ; après une
  régénération, seule la scène modifiée est ré-encodée (`segments_rendered` / `segments_reused`) ; supprimés avec le
  projet (`Storage.delete_prefix`, `Storage.exists`).

## 2026-10-20 (retours d'usage : projet terminé, scène à refaire, musique)
- Éditeur : boutons « Régénérer le clip de la scène N » et « Régénérer la voix » sous l'aperçu, disponibles quelle que soit
  l'étape ouverte ; le premier ouvre l'étape Clips avec le volet du prompt de la scène déjà ouvert. Avant, sur une vidéo
  terminée (étape Export affichée), sélectionner une scène ne proposait aucune modification.
- Aperçu : l'ancien rendu n'est plus montré quand le montage est périmé (clip modifié) ; le clip de la scène le remplace.
- Musique : « Importer une piste » dans l'étape Musique de l'éditeur (composant partagé `ImportTrack`) ; la piste
  importée est aussitôt choisie.

## 2026-10-20 (évolutions demandées : reprise, régénération de scène, pagination, modèles, mobile)
- Reprise après un échec : `Step.run_id` (migration `0004`) identifie chaque lancement complet des clips et des voix ;
  `run {resume: true}` ne génère que les scènes restantes, `run {only_missing: true}` que celles sans média, quel que soit
  l'état de l'étape. `GET /projects/{id}` expose `resume: {done, total}` sur une étape en échec. Budget et timeout du job
  calculés sur les scènes à générer. Admin : « Reprendre (N restantes) » / « Tout régénérer », « Générer les N clips
  manquants ».
- Régénérer une scène avec plus de détails : `run {scene_id, visual_prompt}` enregistre le nouveau prompt sur la scène
  (refus de lancement : prompt inchangé) puis régénère son clip ; volet « Préciser le prompt de cette scène » avec
  l'assistant IA dans le panneau Clips.
- Pagination : `GET /projects` renvoie `{items, total}` (`q`, `status`, `sort`, `limit`, `offset`) ; `GET /costs` accepte
  `limit` et `offset` et renvoie `calls_total`. Accueil : recherche, filtre, tri, « Voir plus » ; Coûts : « Afficher plus ».
- Modèles de départ à l'accueil : six formats qui préremplissent sujet, durée et durée des scènes.
- Passe mobile et Lighthouse : accessibilité 100 sur l'éditeur en mobile, LCP 812 ms (processeur 4×, « Fast 4G »),
  correctifs (contraste, zone `main`, noms accessibles, cibles tactiles, modèles défilants, méta-description,
  `robots.txt`, `noindex`).
- Rupture d'API : le corps de `GET /projects` n'est plus une liste (voir ci-dessus) ; tests et admin mis à jour.

## 2026-10-20 (backend : lot 3, performance et dette ; documentation)
- Génération en parallèle : clips (3 à la fois avec fal.ai, 1 avec ComfyUI) et voix (2 à la fois) via `_per_scene` ;
  écritures en base sérialisées et protégées de l'annulation (`WriteGate` dans `services/costs.py`) ; à la première
  erreur, les scènes non lancées sont abandonnées et l'erreur d'origine est enregistrée sur l'étape.
- Migration `0003` : index sur `assets`, `scenes` et `provider_calls`.
- Redis : un client par boucle d'événements (enqueue et publication), fermé à l'arrêt de l'API et du worker.
- Refactor : helpers d'état du flow dans `services/flow.py` (la couche service ne dépend plus de `app.api`).
- Qualité : `ruff` (configuration, dépendance de dev, code conforme), CI GitHub Actions (backend + admin, non encore
  exécutée sur GitHub), `uv.lock` versionné.
- Documentation : nouveaux `docs/securite.md`, `docs/exploitation.md`, `docs/audit-v2.md`, `docs/README.md` (index) ;
  mise à jour de `README.md`, `architecture.md`, `workflow-video.md`, `api.md`, `providers.md`, `music.md`, `costs.md`,
  `admin.md`.

## 2026-10-20 (backend : lot 2, coûts)
- Budget par projet : réglage `project_budget_usd` (défaut 10 $, 0 = sans limite). Les lancements d'étapes payantes qui
  dépasseraient le budget (dépenses + coût estimé des clips) sont refusés en `409` ; en mode automatique, l'étape
  concernée passe en `failed` avec la raison et l'autopilot s'arrête. Champ « Budget maximum par vidéo » dans Réglages.
- Plafonds de saisie : `target_duration_s` ≤ 180 s, `theme` ≤ 2000 caractères, nom de piste ≤ 200 caractères (`422`
  au lieu d'un `500` en base pour ce dernier).
- Suppression : `DELETE /projects/{id}` refuse (`409`) pendant une génération et supprime les fichiers MinIO du
  projet ; `DELETE /music/{id}` supprime aussi le fichier (`Storage.delete_many`).
- Pas traité : reprise des clips déjà produits après un échec en cours de route (une relance régénère tout, sauf par
  scène via `scene_id`), `cost_usd` en `Float`.

## 2026-10-20 (backend : lot 1, sécurité)
- Audit du backend (277 tests verts avant) : constats et état de traitement dans `docs/audit-v2.md` ; lot 1 traité ici.
- Auth : limitation des tentatives de connexion (5 échecs / 5 min / client → `429` + `Retry-After`).
- Production : `APP_ENV` (`dev` par défaut) ; hors `dev`, refus de démarrer avec `ADMIN_PASSWORD` / `SECRET_KEY` par
  défaut, cookie de session `Secure`, `/docs`, `/redoc` et `/openapi.json` fermés.
- Providers : le test de connexion vérifie vraiment la clé de Claude, Gemini et ElevenLabs (appel gratuit, 10 s max) ;
  l'admin affiche « Non connecté » au lieu de « Injoignable » (clé absente, refusée ou service coupé).
- Voix : `voice_id` (réglage ou paramètre) limité à `[A-Za-z0-9_-]{1,64}` (il finit dans l'URL d'ElevenLabs) ; refus
  avant tout appel payant.

## 2026-10-20 (V2 : audit et refonte de l'éditeur)
- Audit de la V1 (rendu réel) : modèle mental « rail d'outils » inadapté à un pipeline, deux actions principales en
  concurrence, panneau étroit, largeurs de page différentes d'un écran à l'autre, cartes sans vignette, accent rose sur
  fond violet-noir (défaut du genre).
- Admin : nouvelle palette graphite neutre + accent bleu-vert (`docs/design-system.md`), pistes recolorées.
- Éditeur : frise horizontale des étapes (`Pipeline`, remplace `ToolRail`), colonne de scènes (`SceneList`), panneau de
  l'étape à droite, « Coût » libellé, une seule action principale (« Reprendre : <étape> » ou « Exporter »).
- Accueil, Réglages (ex-« Providers »), Coûts : une échelle de largeurs commune ; cartes sans clip : « Pas encore de
  clip » ; boutons de l'assistant IA discrets (seul « Générer » à l'accent, sans emoji).
- Correctif : la règle CSS `.st-pending` collée à un `@keyframes` (badge « à faire » mal stylé) est réparée.

## 2026-10-20 (points non couverts)
- Racine : `package.json` (`npm run dev` lance Docker, migrations, API, worker et admin ; `dev:comfy` ajoute ComfyUI ;
  `setup`, `test`, `lint`, `seed:music`…) en remplacement du `Makefile`. `docker-compose.yml` fige `name: video_virale-v1`
  pour garder les volumes Postgres/MinIO existants. README mis à jour.
- Accueil : bouton « Exporter » sur les cartes ayant un rendu (`GET /projects` expose `render_asset_id`). Les rendus sont déjà
  stockés dans MinIO. Nettoyage : worktree `video_virale-v1` et branches `feat/studio`, `feat/v1` supprimés.
- Musique : `backend/scripts/seed_music.py` ajoute 12 pistes libres de droits (Kevin MacLeod, CC0 / domaine public / CC BY 4.0)
  dans la bibliothèque MinIO ; pistes de test (Pulse 440, Ambiance calme) supprimées (`docs/music.md`).
- API : `GET /projects/{id}/estimate` renvoie `400` (au lieu de `500`) quand le modèle est inconnu du provider.
- Autopilot : une étape validée à la main juste avant le chaînage du worker ne bloque plus le mode automatique ;
  `advance` lance la suite si elle ne l'est pas déjà (`docs/autopilot.md`).

## 2026-10-18 (éditeur « Studio »)
- Admin : l'éditeur de flow (`ProjectFlow`, `StepBar`) est remplacé par un éditeur plein cadre type CapCut
  (`pages/Studio.tsx`) : en-tête (retour, titre éditable en place, état de l'autopilot avec « Arrêter », « Exporter »),
  rail d'outils à pastilles de statut (Idée, Script, Clips + image de référence, Voix, Musique, Montage, Export),
  panneau propriétés (panneaux existants, jargon technique replié dans « Avancé », pied d'actions collé en bas), aperçu
  9:16 (rendu final, sinon clip choisi + voix + sous-titre de la scène) et timeline à pistes colorées (clips avec
  vignettes, voix, musique ; blocs rayés en génération, « + » si vide ; tête de lecture). Raccourcis espace et ← →.
  Responsive sous 900 px. Barre latérale masquée dans l'éditeur.
- Panneaux Clips et Voix centrés sur la scène sélectionnée ; Script met en évidence la scène sélectionnée ; lecteurs de
  rendu retirés des panneaux Montage et Final (l'aperçu central les remplace, `RenderPreview` supprimé).
- Logique pure testée (`src/studio.ts`) : outils et pastilles, blocs de timeline, scène au temps t, graduations,
  libellé d'autopilot, raccourcis, URL présignées stables entre rechargements. `useProject` : `rename`,
  `stopAutopilot`. Doc : `docs/admin.md`.

## 2026-10-18 (accueil Studio : création en un geste)
- Admin : nouveaux jetons de couleur (fond `#15141b`, action principale rose `#ff3d81`, couleurs de piste clips / voix /
  musique / sous-titres) ; barre latérale fine de 72 px à icônes (Projets, Musique, Réglages, Coûts).
- Accueil : bloc « Nouvelle vidéo » (sujet avec assistant IA, durée 15/30/60 s, durée des scènes 3 s/5 s/Auto) ;
  « Créer la vidéo » crée le projet, écrit `scene_length_s` et lance l'autopilot ; « Pas à pas » crée sans autopilot.
  Le tableau des projets est remplacé par une grille de cartes 9:16 (vignette, avancement en 8 segments, état dont
  « En génération… », coût, suppression avec confirmation). Modale de création supprimée.
- API : `GET /projects` expose `autopilot`, `current_status` et `thumbnail_url` (dernier rendu, sinon clip choisi de la
  première scène).

## 2026-10-18 (mode automatique)
- `POST /projects/{id}/autopilot` lance `idea` et active le mode automatique ; `DELETE` l'arrête ; `GET /projects/{id}`
  expose `autopilot`. Drapeau dans `metadata_json` (pas de migration), conservé par l'étape `final`.
- Worker : en fin de job, l'étape est validée et la suivante lancée (`reference` ignorée, première piste de musique,
  `final` → projet `done`) ; échec, interruption ou redémarrage du worker coupent l'autopilot.
- `launch_step` (`services/steps.py`) partagé par l'API et le worker, sous verrou de la ligne projet : pas de double
  lancement, pas de relance après un arrêt. Doc : `autopilot.md`.

## 2026-10-18 (correctifs backend : loudness, sélection auto, durée de scène, prompt d'idée)
- Montage : son final normalisé par `loudnorm=I=-16:TP=-1.5:LRA=11` (avec ou sans musique).
- Clips : le clip généré pour une scène sans sélection est sélectionné d'office ; un choix existant n'est jamais écrasé.
- Script : `params.scene_length_s` (défaut `null` = libre) fixe la durée visée des scènes et donc leur nombre.
- Idée : prompt demandant un angle direct, une seule proposition, 2 à 4 phrases, sans introduction ni markdown.

## 2026-10-18 (clips ComfyUI : réglages optimisés Wan 2.2 14B)
- Workflow `wan22-14b-t2v` (défaut) : génération inchangée (480x832, 4 étapes lightx2v, shift 5, cfg 1), puis upscale
  ESRGAN `4x-UltraSharp` ramené en 720x1248 (lanczos) avant le mp4 16 fps : image nettement plus nette en 1080x1920.
  Mesuré : 1106 s (18,4 min) par clip de 3 s, pic ~26 Go ; ~3 h 05 pour 10 clips.
- Montage : les clips sous 24 fps sont interpolés en 30 fps par compensation de mouvement (`minterpolate`, ~8 s par
  clip de 3 s) au lieu de dupliquer des images ; mise à l'échelle lanczos.
- Script et assistant IA : `visual_prompt` guidé par `VISUAL_PROMPT_GUIDE` (80 à 120 mots, sujet + action d'abord,
  phrase de caméra explicite, lumière, style) : sujet en grand plan et vrai travelling au lieu d'un plan fixe.
- `CLIP_TIMEOUT_S` : 5400 → 5700 s (x2 le pire cas 5 s estimé avec l'upscale).
- Docs : tableau des essais (prompt, étapes, shift, résolution, upscale, interpolation) dans `providers.md`.

## 2026-10-18 (assistant IA : corrections de revue)
- Admin : une réponse tardive de l'assistant n'écrase plus les modifications faites pendant l'attente (mises à jour
  fonctionnelles `useDraft().update`, scène visée par sa clé, réponse ignorée si le champ a changé, champ en lecture
  seule pendant sa demande) ; « Annuler la proposition » disparaît après enregistrement ou annulation du brouillon ;
  noms accessibles distincts par scène, `aria-disabled`, Entrée ignorée pendant une composition IME.
- API : une réponse vide une fois nettoyée est journalisée à son coût réel (502 ensuite) ; nettoyage conservateur
  (guillemets seulement englobants, libellé du champ demandé seulement, gras seulement global, préambule « Voici… : »).
- Script : `json_schema` transmis au LLM seulement pour les étapes JSON ; timeout du job `script` couvrant la relance ;
  durées de scène absurdes (« 00:04 », millisecondes, plus de 60 s) traitées comme absentes, part répartie jamais sous 2 s.

## 2026-10-18 (assistant IA dans l'admin, étape script fiabilisée)
- **Assistant IA** : `POST /api/ai/assist` génère ou reformule le texte d'un champ (titre et thème du projet, piste,
  angle, voix off et prompt visuel des scènes, prompt de l'image de référence, titre/description/hashtags) avec le LLM
  actif, en tenant compte du projet (brief, angle, script, scène, budget de mots de la voix off). Coût tracé
  (`provider_calls.step = "assist:<champ>"`), erreurs `422`/`404`/`502` en français, réponses fake déterministes.
- Admin : composant `AssistField` (« ✨ Générer », « Reformuler », consigne facultative, « Annuler la proposition ») sur
  tous les champs texte, y compris la modale « Nouvelle vidéo » ; la proposition va dans le brouillon, jamais
  enregistrée d'office ; inactif quand l'étape est verrouillée. Écran Coûts : « Assistant IA (champ) ». Modales : focus
  initial via `data-autofocus`.
- **Bug « scène incomplète » (Gemini, angle markdown long)** : sortie structurée Gemini (`responseMimeType` +
  `responseSchema`) pour `script` et `final` via un paramètre facultatif `json_schema` du contrat LLM (ignoré par
  Claude) ; `parse_scenes` tolérant (noms de champs courants, champs en trop ignorés, durée « 4 s » convertie, durée
  absente répartie sur la cible) ; une relance automatique ciblée avec l'erreur de validation (tracée et facturée) ;
  erreur précise « scène N incomplète (champ vide) ». Prompt du script calé sur la durée cible : nombre de scènes,
  somme des durées, environ 2,5 mots par seconde de voix off.
- Docs : `assistant-ia.md` (nouveau), `api.md`, `admin.md`, `workflow-video.md`, `providers.md`, `costs.md`, README.

## 2026-10-17 (ComfyUI : workflow Wan 2.2 14B, qualité)
- Nouveau workflow livré `backend/workflows/comfyui-wan22-14b-t2v.json` (format API, converti depuis le workflow
  « 12_WAN22-14B_t2v-qualite » : deux experts GGUF Q4_K_M haut/bas bruit, LoRA lightx2v 4 étapes, VAE Wan 2.1,
  480x832 9:16, 16 fps). Il devient le **workflow par défaut** : 3 s en 15,8 min sur M4 Max (5B : 11 min), image
  nettement meilleure (lumière réaliste, détails nets, animal cohérent, couleurs naturelles). 576x1024 testé : 36 min
  pour 3 s, gain visuel faible, non retenu.
- `comfyui_workflow_path` accepte le nom d'un workflow livré (`wan22-14b-t2v`, `wan22-5b-t2v`) en plus d'un chemin ;
  défaut = `wan22-14b-t2v` (au lieu du chemin absolu du 5B). Un chemin déjà enregistré continue de fonctionner.
  `GET /api/providers/models` renvoie `comfyui_workflows` ; l'admin propose ces noms en suggestions avec une aide.
- `{{FRAMES}}` suit la cadence du workflow (`frame_rate` de `VHS_VideoCombine` ou `fps` de `CreateVideo`, 24 si
  absente) : 3 s → 49 images à 16 fps ; plafond 5 s (81 images à 16 fps, 121 à 24 fps).
- Timeout d'un clip ComfyUI : 5400 s (au lieu de 3600 s), car 5 s en 14B prennent 2510 s mesurées.
- Test du montage avec une source 16 fps 480x832 (rendu 1080x1920 à 30 fps).
- Docs : `providers.md` (comparaison 5B/14B, temps et mémoire mesurés, choix du workflow), `settings-providers.md`,
  `admin.md`, `api.md`, `workflow-video.md`, README.

## 2026-10-17 (ComfyUI : corrections de revue)
- `ComfyUIProvider` : un appel abandonné (timeout, annulation du job, erreur de polling) retire son prompt de ComfyUI
  (`POST /queue {"delete"}` s'il attend, `POST /interrupt {"prompt_id"}` s'il tourne ; best-effort, protégé de
  l'annulation), vérifié sur le vrai ComfyUI. Un prompt en erreur (`status_str == "error"`) donne une erreur non
  relançable avec le message ComfyUI (node et exception) ; un prompt absent de l'historique et de la file 3 polls de
  suite (ComfyUI redémarré) échoue tout de suite. Workflow lu en UTF-8 ; fichier absent → « workflow introuvable »
  (et non plus « ComfyUI injoignable »).
- Réglages : renvoyer le chemin du workflow livré (affiché par l'admin) l'enregistre vide, sans figer un chemin machine.
- Docs `providers.md` : conversion par script, recadrage d'environ 2,5 % assumé, prérequis limités au 5B, budget de
  3600 s expliqué.

## 2026-10-17 (clips gratuits avec ComfyUI local)
- Workflow livré `backend/workflows/comfyui-wan22-5b-t2v.json` (format API, Wan 2.2 5B texte → vidéo, 480x832 9:16,
  12 étapes, sortie mp4 `VHS_VideoCombine`), converti depuis le workflow « rapide » de l'utilisateur. Réglage
  `comfyui_workflow_path` vide (ou `COMFYUI_WORKFLOW_PATH=` vide) = ce workflow.
- `ComfyUIProvider` : placeholders `{{FRAMES}}` (`round(durée x 24) // 4 x 4 + 1`, max 121) et `{{SEED}}` (aléatoire
  par clip), remplacés par des nombres JSON ; `{{PROMPT}}`/`{{DURATION}}` inchangés.
- Timeouts : un clip ComfyUI dispose de 3600 s (900 s pour fal.ai), polling dimensionné en conséquence ; le timeout du
  job `clips` tient compte du provider du lancement (`step_timeout`, `clip_provider_name`).
- Docs : `providers.md` (section « ComfyUI en local », temps mesurés sur M4 Max), `api.md`, `workflow-video.md`, README.

## 2026-10-17 (Gemini : corrections de revue)
- `GeminiLLM` : réflexion réglée au plus bas documenté pour chaque modèle (`thinkingConfig.thinkingLevel`, table
  `THINKING_LEVELS`, champ omis si non documenté), car `maxOutputTokens` inclut la réflexion. `finishReason`
  `MAX_TOKENS` donne une erreur « réponse tronquée » non relançable, une autre raison que `STOP` donne « réponse
  interrompue » : jamais de texte tronqué en succès. Coût sans `candidatesTokenCount` = total - entrée, compteurs
  `null` comptés 0. Modèle encodé dans l'URL. `gemini-4-argon` ajouté (prix documenté). Avertissement dans les logs
  quand la table de prix dépasse `PRICES_VALID_UNTIL`.
- `PUT /settings` : `gemini_model` limité à lettres, chiffres, `.`, `_`, `-` (sinon `400`).
- Docs : `providers.md` (un 4xx peut reprendre jusqu'à 200 caractères de la réponse du provider ; la clé ne passe que
  par l'en-tête), `costs.md`, `settings-providers.md`.

## 2026-10-17 (Gemini, provider de texte alternatif)
- Backend : `GeminiLLM` (`providers/gemini.py`, API REST `generateContent` via `httpx`, clé dans l'en-tête
  `x-goog-api-key`, pas de retry interne, coût avec tokens de réflexion). Réglages `gemini_api_key` (secret, aussi
  `GEMINI_API_KEY`), `gemini_model` (défaut `gemini-3.5-flash-lite`) et `llm_provider` (`claude` | `gemini`, défaut
  `claude`, autre valeur refusée en `400`). `ProviderRegistry.llm()` choisit selon `llm_provider` ; `/providers/health`
  inclut `gemini`, `/providers/models` expose `llm.gemini`. Fakes inchangés sous `FAKE_PROVIDERS=true`.
- Admin : carte Gemini (clé masquée, modèle) et choix du provider de rédaction dans la carte « Choix par défaut » ;
  listes de choix factorisées (`select`, `withCurrent`).
- Docs : `providers.md`, `admin.md`, `costs.md`, `settings-providers.md`, README.

## 2026-10-17 (corrections de la revue finale)
- fal.ai : la soumission (`POST`, payante) n'est jamais rejouée ; seule elle peut être relancée par `tracked_call`.
  Polling, résultat et téléchargement réessaient sur place (5 fois par requête, même URL) puis échouent en erreur non
  relançable. Durée Kling arrondie à 5 ou 10 s (seules valeurs acceptées), Wan/LTX sans paramètre de durée (~5 s) ;
  estimation et coût journalisé sur la durée arrondie. Docs : `providers.md`.
- Worker : timeout de job calculé par l'API selon l'étape et le nombre de scènes (`job_timeout`, plafond 6 h), appliqué
  par `run_step_job` (Arq 0.28 n'a pas de timeout par job) ; un job dont l'étape n'est plus `running` (réinitialisée
  au redémarrage du worker) est ignoré sans appel provider. Docs : `api.md`.
- Montage : sous-titres en ASS 1080x1920 (pixels réels : 64 px, tiers inférieur) au lieu d'un SRT mis à l'échelle depuis
  384x288 ; `amix normalize=0` (la voix n'est plus baissée de 6 dB sous la musique) ; fichiers écrits en UTF-8.
  Docs : `montage.md`.
- API : `409` si une étape en aval tourne lors de l'édition ou du lancement d'une étape, ou si une étape dépendante tourne
  lors de l'édition du brief ; textes de scène vides refusés (`422`) ; `Project.status` passe à `done` quand le rendu
  final est validé (retour à `draft` s'il est invalidé, migration `0002`). Docs : `api.md`.
- Admin : étape verrouillée et bandeau explicatif quand une étape en aval tourne ; `detail` de l'API affiché même en
  5xx ; scène sans texte signalée avant l'envoi ; statut « Brouillon » / « Terminée » dans la liste ; Providers : test
  sans réponse obsolète, erreur de `/providers/models` affichée. Docs : `admin.md`.
- Exploitation : ports Docker liés à `127.0.0.1`, avertissement au démarrage de l'API si `ADMIN_PASSWORD`/`SECRET_KEY`
  sont des valeurs par défaut, bucket MinIO créé au démarrage de l'API, client Claude sans retries internes,
  suppression de `StepStatus` inutilisé. README : trois serveurs un par terminal, création des bases de test,
  rechargement des clés par job. Changelog trié du plus récent au plus ancien.

## 2026-10-17 (musique, providers, coûts)
- Admin : écrans Musique (tableau avec lecteur, import multipart, suppression confirmée), Providers (cartes avec pastille
  de connexion, réglages envoyés seulement s'ils sont modifiés, secrets jamais renvoyés masqués, « Retester ») et Coûts
  (total, répartitions en barres par provider et par projet, 200 derniers appels avec statut et erreur, filtres dans
  l'URL). Logique pure testée : `settingsBody`, `breakdown`, `formatShare`, `clock`. `api()` accepte un `FormData`.
  Styles partagés (`page-head`, `empty`, `table-wrap`, `status-badge`, `st-*`) déplacés dans `index.css`. Doc : `docs/admin.md`.

## 2026-10-17 (éditeur de flow, revue 1)
- API : l'édition du `result` de l'étape final met aussi à jour `Project.metadata_json` ; `POST …/steps/clips/run`
  accepte `provider`/`model` pour ce lancement seulement (transmis au job puis à `PipelineContext.overrides`).
- Admin : « Nouvelle variante » d'une scène n'écrase plus le choix global ; « Régénérer le script » demande confirmation
  et reste bloqué tant que des scènes modifiées ne sont pas enregistrées ; changer d'étape ou de page avec des
  modifications non enregistrées demande confirmation ; `useApi` ignore les réponses obsolètes ; éditeur remis à zéro
  au changement de projet ; une seule requête par double clic ; `locked` calculé une fois pour tous les panneaux.

## 2026-10-17 (éditeur de flow)
- Admin : éditeur de flow guidé `/projects/:id` (rail vertical des 8 étapes, panneau commun `StepPanel`, un panneau par
  étape : idée, script, référence, clips, voix, musique, montage, final), `useProject` (SSE + rafraîchissement de secours
  pendant une génération), logique pure `availableActions` / `previousApproved` / `hasResult` / `statusLabel` testée.
  Champs du brief (`ProjectFields`), `FormActions` et `usd` mutualisés avec la liste des projets. Doc : `docs/admin.md`.
- Admin : `api()` accepte les réponses sans corps (le `202` de `/run` était lu comme une erreur « Serveur injoignable »).
- API : `PATCH /projects/{id}` (édition du brief, aval périmé) et `GET /projects/{id}/assets/{asset_id}/download`
  (téléchargement du rendu) ; une étape `reference` ignorée ne passe plus en `stale`. Doc : `docs/api.md`.
- Fakes : `FakeLLM` produit des métadonnées pour l'étape final (flow complet parcourable en `FAKE_PROVIDERS=true`).

## 2026-10-17 (admin)
- Admin React (`admin/`, Vite + TypeScript) : socle (client `api`, étapes et libellés, hook SSE `useEvents`, jetons de design sombres), connexion, garde d'auth, navigation, liste des projets avec rail des étapes et modale « Nouvelle vidéo ». Doc : `docs/admin.md`.
- Admin : états d'erreur explicites (« Serveur injoignable » + « Réessayer ») pour la session et la liste, état de chargement, échec de déconnexion affiché, SSE robuste (JSON illisible ignoré, flux fermé → revérification de session), `useId` pour la modale. API : `current_step` ignore l'étape optionnelle `reference` en `pending`.

## 2026-10-17 (suite)
- API musique (`music.py`), réglages/providers (`providers_api.py`) et coûts (`costs_api.py`), protégées par `require_auth`. Docs : `docs/music.md`, `docs/settings-providers.md`.

## 2026-10-17
- Providers réels (Claude, fal.ai, ComfyUI, ElevenLabs), registre `ProviderRegistry` et `AppSettings` (réglages DB > env, secrets masqués).
- Journal des coûts, retries et timeouts : fonction `tracked_call` pour tracker les appels API avec retry automatique sur erreurs `retryable` et gestion des timeouts.
- Service de montage FFmpeg (`montage.py`) : clips 9:16 1080x1920 30 fps, boucle des clips courts, sous-titres SRT brûlés, musique optionnelle à 0,15. Doc : `docs/montage.md`.
- Exécuteurs d'étapes du pipeline (`pipeline.py`) : `run_step` et les 8 exécuteurs (idée, script, référence, clips, voix, musique, montage, final), parsing JSON tolérant, échecs lisibles et relançables. Doc : `docs/workflow-video.md`.
- API HTTP (`app/api/`) : authentification par cookie signé, projets (liste, création avec 8 étapes, détail avec URLs présignées, suppression, estimation du coût des clips, choix du clip), étapes (édition avec invalidation de l'aval, lancement atomique avec 409 au double clic, validation et saut de l'étape optionnelle), SSE `/api/events`. File Arq (`queue.py`) et worker (`worker.py`). Doc : `docs/api.md`.
- Correctifs API/worker : un job annulé ou expiré passe l'étape en `failed` (plus de `running` bloqué), pas de relance automatique des jobs (`max_tries = 1`), réinitialisation des étapes orphelines au démarrage du worker ; `select-clip` rend `montage`/`final` périmés et renvoie 409 pendant une génération de clips ou un montage. Suppression de `invalidate_downstream` (remplacée par `mark_stale` côté API).

## 2026-10-16
- V1 : workflow de création vidéo + admin. Backend (providers réels et factices, journal des coûts, montage FFmpeg 9:16, pipeline en 8 étapes, API, worker Arq, SSE) et admin React (projets, éditeur de flow, musique, providers, coûts).
- Documentation et lancement : `README.md`, `Makefile` (`up`, `migrate`, `api`, `worker`, `admin`, `test`), `docs/architecture.md`, mise à jour de `providers.md`, `workflow-video.md`, `montage.md`, `music.md`.

## 2026-11-03 (badge de crédits)
- Admin : la pastille de crédits de la barre latérale se recharge après une recharge (`notifyCreditsChanged` dans `hooks/useCredits.ts`), sans rafraîchir la page.

## 2026-11-04 (texte en local)
- Nouveau provider de texte `ollama` (`providers/ollama.py`) : idées, scripts et métadonnées générés par un modèle local, sans clé ni coût. Réglages `ollama_url` / `ollama_model`, carte dans Réglages → Providers, santé dans `/api/providers/health`. Pensé pour travailler sans carte bancaire.
- Ollama : `gemma4` par défaut (meilleur compromis mesuré sur 2 idées : 9 s, JSON valide, bon français) et `keep_alive: 0` (le modèle quitte la RAM après chaque réponse, au profit de ComfyUI).
- Image de référence locale : provider `comfyui` (`ComfyUIImage`, Flux dev, modèle `flux-dev`), choisissable dans Réglages → Image de référence ; aucune clé, aucun coût.
