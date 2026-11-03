# Sécurité

Application multi-comptes (e-mail + mot de passe, rôles `user` et `admin`) destinée à tourner derrière HTTPS en production.
Code : `backend/app/api/auth.py`, `backend/app/config.py`, `backend/app/main.py`.

## Environnements : `APP_ENV`
| Valeur | Effet |
|---|---|
| `dev` (défaut, poste local) | Avertissement au démarrage si `ADMIN_PASSWORD` / `SECRET_KEY` ont une valeur par défaut ; cookie sans `Secure` ; `/docs`, `/redoc`, `/openapi.json` ouverts. |
| toute autre valeur (`prod`, `staging`…) | **Refus de démarrer** avec `ADMIN_PASSWORD` ∈ {`change-me`} ou `SECRET_KEY` ∈ {`dev-secret`, `change-me-too`} ; cookie de session `Secure` (HTTPS requis) ; `/docs`, `/redoc`, `/openapi.json` répondent `404`. |

## Authentification
- Comptes e-mail + mot de passe (`users`) : mots de passe hachés par scrypt (`app/security.py`), longueur 8–128 validée
  avant tout hachage ; connexion `POST /api/auth/login {email, password}` avec le même message et un hachage factice
  vérifié quand l'adresse est inconnue (pas d'énumération, durée comparable).
- Jetons e-mail (vérification 48 h, réinitialisation 1 h) : aléatoires, seule leur empreinte SHA-256 est stockée, usage
  unique (consommés par une seule requête `UPDATE … RETURNING`).
- Cookie `session` signé (itsdangerous, `SECRET_KEY`) contenant `{uid, epoch}` ; l'époque est **par utilisateur**
  (`users.session_epoch`), incrémentée par la déconnexion, la vérification d'adresse et la réinitialisation du mot de
  passe. `HttpOnly`,
  `SameSite=Lax`, `Secure` hors `dev`, valable 30 jours. Les cookies de l'ancien format (`{user, epoch}`) sont refusés.
- **Prise de compte avant inscription** : un tiers qui inscrit l'adresse d'autrui avec son mot de passe ne garde pas le
  compte. Une nouvelle inscription sur un compte non vérifié envoie un lien de réinitialisation (et non de
  vérification) ; la réinitialisation marque l'adresse vérifiée et révoque les sessions, la vérification aussi.
- Inscription, renvoi du lien et mot de passe oublié : réponse identique quel que soit l'état du compte, 5 demandes par
  heure et par adresse cliente (`signup_throttle`), e-mail envoyé après la réponse (un échec SMTP est journalisé sans le
  lien).
- Envoi SMTP (`app/mailer.py`) : certificat et nom d'hôte vérifiés (`ssl.create_default_context()`). Port 465 : TLS dès
  la connexion (`SMTP_SSL`) ; autres ports : `STARTTLS` obligatoire avant tout login, port 25 compris dès qu'un
  utilisateur SMTP est renseigné ; seul le port 25 sans identifiants (relais local) reste en clair.
- Toutes les routes `/api/*` exigent le cookie (flux SSE `/api/events` compris), sauf `/api/health` et `/api/auth/*`.
- **Limitation des tentatives** (`LoginThrottle`) : 5 échecs en 5 minutes pour une même adresse cliente → `429` avec
  `Retry-After`, y compris avec le bon mot de passe pendant le blocage. Un succès remet le compteur à zéro. L'état est en
  mémoire du processus (un redémarrage de l'API le vide). Derrière un reverse proxy, lancer uvicorn avec
  `--proxy-headers` (et `--forwarded-allow-ips` adapté) pour que l'adresse cliente soit celle de l'utilisateur et non
  celle du proxy ; sinon tous les clients partagent le même compteur.

## Isolation des comptes
- Un projet appartient à un compte (`projects.user_id`). Toute route `{project_id}` passe par `require_project_access`
  (`app/api/projects.py`, dépendance des routeurs `projects`, `steps`, `plan`) : projet absent ou d'un autre compte →
  le même `404 "Projet introuvable"`. L'admin accède à tous les projets, mais sa liste ne contient que les siens.
- Les ids secondaires du chemin (asset, scène, file d'attente, message du plan) sont cherchés dans le projet de l'URL :
  un asset d'un autre projet placé dans l'URL de son propre projet donne `404`.
- `POST /api/ai/assist` (`project_id` du corps) et `GET /api/costs` appliquent la même règle ; les appels sans projet
  ne sont visibles que de l'admin.
- Flux SSE `/api/events` : un utilisateur ne reçoit que les événements de ses projets (ni ceux des autres, ni ceux sans
  projet) ; l'admin reçoit tout.
- Réservé à l'admin (`require_admin`, `403`) : `GET`/`PUT /api/settings` (clés API globales), `GET /api/providers/voices`,
  `POST`/`DELETE /api/music`. Ouvert à tout compte connecté : santé des providers, cartes de modèles, styles,
  `GET /api/music`, `GET /api/settings/editor` (choix par défaut, sans secret).
- `tests/test_isolation.py` parcourt toutes les routes `{project_id}` de l'app (contrôlées contre le schéma OpenAPI) et
  exige un `404` pour un autre compte : une nouvelle route non protégée fait échouer la CI.

## Données et entrées
- Clés API des providers : **chiffrées au repos** (Fernet, clé dérivée de `SECRET_KEY`, préfixe `enc:v1:`, `app/crypto.py` ; migration `0011` pour les clés déjà saisies) ; masquées à la lecture (`••••` + 4 derniers caractères), jamais renvoyées en clair ;
  une valeur masquée renvoyée telle quelle est ignorée à l'écriture.
- `voice_id` (réglage `default_voice_id` ou paramètre d'étape) : `[A-Za-z0-9_-]{1,64}`, car il est inséré dans l'URL
  d'ElevenLabs ; refusé avant tout appel payant. `gemini_model` : `[A-Za-z0-9._-]+`.
- Fichiers importés (clips, musiques) : clé de stockage générée par le serveur (nom aléatoire, extension et type MIME
  d'une liste fermée), nom d'origine nettoyé et gardé à part comme simple donnée (`docs/imports-fichiers.md`).
- Plafonds : durée cible ≤ 180 s, thème ≤ 2000 caractères, titre ≤ 200, nom de piste ≤ 200, fichier audio ≤ 50 Mo.
- Test de connexion des providers (`GET /api/providers/health`) : appels gratuits, 10 s maximum, la clé reste dans les
  en-têtes (jamais dans l'URL).

## Dépenses
Budget par projet et suppression sûre : `docs/costs.md`. Un job n'est jamais rejoué automatiquement (`max_tries = 1`).

## Limites connues (non traitées)
- Changer `SECRET_KEY` rend les clés API enregistrées illisibles (traitées comme absentes) : les ressaisir dans Réglages. Les sauvegardes de la base ne contiennent plus de clé en clair, mais restent à protéger avec `SECRET_KEY`.
- « Sortir » incrémente l'époque **du compte** : toutes ses sessions ouvertes (cookie copié compris) sont révoquées d'un coup, pas celles des autres comptes. Une déconnexion sans session valide ne révoque rien. Les cookies de l'ancien format (sans `uid`) sont refusés : une reconnexion est nécessaire après la mise à jour (migration `0015`).
- Pas de jeton CSRF : la protection repose sur `SameSite=Lax` (pas de cookie sur une requête POST/PUT/DELETE
  intersites).
- fal.ai : le test de connexion ne vérifie que la présence de la clé (pas de point d'entrée gratuit).
- Postgres, Redis et MinIO du `docker-compose.yml` utilisent des identifiants de développement et n'écoutent que sur
  `127.0.0.1` : à remplacer pour tout déploiement.

Limites du lot 1 (comptes, détail dans `docs/comptes.md`) :
- Pré-détournement résiduel : si un attaquant inscrit l'adresse d'un tiers puis que ce tiers clique le lien de
  vérification d'origine (au lieu de se réinscrire ou d'utiliser « mot de passe oublié »), le compte est vérifié avec le
  mot de passe de l'attaquant (compte vide, aucune donnée de la victime).
- Léger écart de temps de réponse (quelques ms) entre inscription ou oubli pour un compte existant et inexistant.
- L'adresse du destinataire figure dans le journal en cas d'échec d'envoi.
- `GET /api/providers/health` est accessible à tout compte connecté (sondes sortantes avec les clés globales).
- Le jeton de vérification ou de réinitialisation reste dans l'URL du navigateur après usage (usage unique).
- Les pages `/music` et `/providers` ne sont filtrées que dans la navigation ; l'API renvoie `403` aux non-admins.
- Les 100 crédits d'inscription sont accordés à la vérification de l'adresse (`docs/credits.md`) ; un attaquant peut les obtenir pour une adresse qu'il ne possède pas en faisant vérifier le compte qu'il a créé.

## Paiement
- Le webhook Stripe est le seul point d'accès ouvert qui crédite : signature HMAC vérifiée (tolérance 5 min, temps constant), secret vide = tout refusé, événements dédupliqués en base, effets et marquage dans une même transaction. Voir `docs/paiement.md`.
- Le portail et le paiement ne s'ouvrent que pour le client Stripe du compte connecté ; la clé secrète et le secret de webhook sont chiffrés en base et masqués dans Réglages.

## Admin SaaS
- Les routes `/api/admin/*` passent toutes par `require_admin` (`403` sinon) : liste des comptes, ajustement de crédits (motif obligatoire, tracé dans le registre append-only) et marges. Voir `docs/admin-saas.md`.

## Liste de contrôle avant une mise en production
1. Seuls les crédits bornent la dépense d'un client (`docs/credits.md` : réservation avant chaque génération, assistant IA compris) ; l'abonnement et le paiement sont en place (`docs/abonnement.md`, `docs/paiement.md`) : configurer `stripe_webhook_secret` avant d'ouvrir les achats.
2. `APP_ENV=prod`, `ADMIN_EMAIL` et `ADMIN_PASSWORD` forts avant la première migration, `PUBLIC_URL` en HTTPS, SMTP configuré, `SECRET_KEY` aléatoire (`openssl rand -hex 32`) dans `backend/.env`.
3. HTTPS devant l'API et l'admin (le cookie `Secure` n'est pas envoyé en HTTP) ; `--proxy-headers` si proxy (sinon tout le site partage une seule IP pour les limitations de débit : inscription, renvoi, oubli, connexion).
4. Identifiants Postgres / Redis / MinIO propres, non exposés publiquement ; sauvegardes de la base.
5. Budget par projet adapté (Réglages), clés API à droits limités chez les providers.
6. Exécuter `npm test` et `npm run lint`.
