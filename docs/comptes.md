# Comptes, vérification d'e-mail et isolation

Lot 1 de la logique SaaS : chaque personne a son compte et ne voit que ses projets. Conception complète (crédits,
abonnement, recharges : lots suivants) : [`docs/superpowers/specs/2026-11-01-saas-design.md`](superpowers/specs/2026-11-01-saas-design.md).
Routes : `docs/api.md` ; règles de sécurité : `docs/securite.md`. Code : `backend/app/api/auth.py`, `security.py`,
`mailer.py`, `api/projects.py`, `api/events.py`.

## Abonnement
L'état d'abonnement d'un compte (`subscription_ends_at`) et les fonctions qu'il débloque sont décrits dans `docs/abonnement.md`.

## Modèle
- `users` : `email` (unique, normalisé : sans espaces, minuscules), `password_hash` (scrypt), `role` (`user` ou `admin`),
  `email_verified_at` (nul tant que l'adresse n'est pas confirmée), `session_epoch` (révocation des sessions du compte).
- `email_tokens` : jetons à usage unique (`kind` = `verify` ou `reset`), seule l'empreinte SHA-256 est stockée, `expires_at`
  (vérification 48 h, réinitialisation 1 h), `used_at`.
- `projects.user_id` : propriétaire du projet (obligatoire, indexé).
- Rôles : `user` (éditeur) et `admin` (en plus : Réglages, clés API globales, import de musique, vue sur tous les projets
  par URL).

## Parcours
1. **Inscription** (`/register`) : crée le compte (rôle `user`, non vérifié) et envoie un lien de vérification. Réponse
   identique que l'adresse soit libre ou déjà prise (pas d'énumération).
2. **Vérification** (`/verify?token=`) : marque l'adresse vérifiée, **révoque les sessions ouvertes** et connecte le
   titulaire du lien, qui arrive directement dans l'app.
3. **Connexion** (`/login`) : réservée aux adresses confirmées. Mot de passe juste mais adresse non confirmée : `403` et
   bouton « Renvoyer le lien » (avec l'e-mail et le mot de passe saisis) ; les crédits d'inscription ne sont accordés
   qu'à la vérification (`docs/credits.md`).
4. **Mot de passe oublié** (`/forgot` puis `/reset?token=`) : change le mot de passe, **vérifie aussi l'adresse** (le
   lien prouve l'accès à la boîte) et révoque les sessions.

**Règle anti-prise de compte** : si quelqu'un inscrit l'adresse d'autrui, la vraie personne qui s'inscrit à son tour (compte
non vérifié existant) reçoit un lien de **réinitialisation** et non de vérification : elle choisit alors son mot de passe,
l'attaquant perd l'accès. Un compte déjà vérifié ne reçoit aucun e-mail à l'inscription.

## Isolation
- Dépendance `require_project_access` (`ensure_access`, `app/api/projects.py`) sur tous les routeurs `{project_id}`
  (`projects`, `steps`, `plan`) : projet absent ou d'un autre compte → le même `404 "Projet introuvable"`.
- Admin : `GET /projects` ne liste que **ses propres** projets, mais il peut ouvrir n'importe quel projet par son URL.
- Flux SSE `/api/events` filtré (`visible_events`) : un compte ne reçoit que les événements de ses projets ; les
  événements sans projet et ceux des autres comptes sont réservés à l'admin.
- Coûts (`GET /costs`) et assistant (`POST /ai/assist`) : même règle ; les appels sans projet ne sont visibles que de l'admin.
- Routes réservées à l'admin (`require_admin`, `403`) : `GET`/`PUT /settings`, `GET /providers/voices`, `POST`/`DELETE
  /music`. Routes de l'éditeur ouvertes à tout compte connecté : `GET /settings/editor` (voix, profil et fournisseurs par
  défaut, sans secret), `GET /music`, cartes de modèles, styles, `GET /providers/health`.
- `tests/test_isolation.py` exige un `404` pour un autre compte sur toutes les routes `{project_id}`.

## Configuration
| Variable | Défaut | Rôle |
|---|---|---|
| `ADMIN_EMAIL` | `admin@example.com` | adresse du compte admin créé par la migration `0015` ; normalisée en minuscules, sans espaces |
| `ADMIN_PASSWORD` | `change-me` | mot de passe initial de l'admin. **Sans `.env`, le défaut est `change-me` : à changer** (refus de démarrer hors `dev`) |
| `PUBLIC_URL` | `http://localhost:5173` | base des liens des e-mails (`{PUBLIC_URL}/verify?token=…`, `/reset?token=…`) |

Réglages SMTP (écran Réglages, admin ; table `settings`, ou à défaut `backend/.env` : `SMTP_HOST`, `SMTP_PORT`…) :
`smtp_host`, `smtp_port` (587 par défaut), `smtp_user`, `smtp_password` (chiffré au repos, masqué), `smtp_sender`
(défaut : `smtp_user`). Une clé Brevo (`brevo_api_key`) passe avant le SMTP ; sans l'une ni l'autre, aucun e-mail ne part.
Brevo en SMTP : `smtp-relay.brevo.com`, port 587, identifiant `…@smtp-brevo.com`, mot de passe = clé SMTP (`xsmtpsib-…`). Le certificat et le
nom d'hôte sont vérifiés ; port 465 : TLS implicite ; autres ports : `STARTTLS` obligatoire dès qu'un utilisateur est
renseigné (seul le port 25 sans identifiants reste en clair). Voir `docs/settings-providers.md`.

## Migration `0015`
Crée `users` et `email_tokens`, ajoute `projects.user_id`, **crée le compte admin** depuis `ADMIN_EMAIL` /
`ADMIN_PASSWORD` (adresse déjà vérifiée) et **rattache tous les projets existants** à cet admin. Le cookie change de
format (`{uid, epoch}`) : **reconnexion obligatoire après la mise à jour**, avec l'adresse e-mail de l'admin. Définir
`ADMIN_EMAIL` et `ADMIN_PASSWORD` avant de lancer la migration.

## En développement
Avec `FAKE_PROVIDERS=true`, aucun e-mail ne part : `FakeMailer` écrit chaque message (destinataire, sujet, corps avec le
lien) dans le journal du backend (sortie de l'API), au niveau avertissement : copier le lien de vérification depuis là.
Le vrai envoi SMTP ne journalise jamais le corps.

## Limites connues
1. Pré-détournement résiduel : si un attaquant inscrit l'adresse d'un tiers puis que ce tiers clique le lien de
   vérification d'origine (au lieu de se réinscrire ou d'utiliser « mot de passe oublié »), le compte est vérifié avec le
   mot de passe de l'attaquant (compte vide, aucune donnée de la victime).
2. Léger écart de temps de réponse (quelques ms) entre inscription ou oubli pour un compte existant et inexistant.
3. L'adresse du destinataire figure dans le journal en cas d'échec d'envoi.
4. `GET /api/providers/health` est accessible à tout compte connecté (sondes sortantes avec les clés globales).
5. Le jeton de vérification ou de réinitialisation reste dans l'URL du navigateur après usage (usage unique).
6. Les pages `/music` et `/providers` ne sont filtrées que dans la navigation ; l'API renvoie `403` aux non-admins.
7. Les 200 crédits d'inscription sont accordés à la vérification de l'adresse, une seule fois (`docs/credits.md`).
8. Seuls les crédits bornent la dépense d'un client ; l'abonnement et le paiement arrivent aux lots 3 et 4.

## Écrans de l'admin

Écrans hors session de l'admin (hors `Layout`), tous bâtis sur la carte commune `components/AuthCard.tsx` (`AuthCard`,
`AuthForm`, `AuthMessage`, `EmailField`, `PasswordField`, styles `pages/Login.css`). Logique pure dans `admin/src/auth.ts`
(tests `auth.test.ts`). Routes et règles côté API : `docs/api.md`, `docs/securite.md`.

| Route | Écran | Appel |
|---|---|---|
| `/login` | e-mail + mot de passe ; liens « Créer un compte », « Mot de passe oublié » ; « Renvoyer le lien » après un `403` | `POST /auth/login` puis `/` ; `POST /auth/resend` |
| `/register` | e-mail + mot de passe (8 à 128 caractères, `validPassword`) | `POST /auth/register` |
| `/verify?token=` | confirme l'adresse au montage (un seul appel, même en StrictMode), puis ouvre l'app (`/new` si une idée attend) | `POST /auth/verify` |
| `/forgot` | e-mail | `POST /auth/forgot` |
| `/reset?token=` | nouveau mot de passe | `POST /auth/reset` |

- Messages neutres : l'inscription affiche toujours « Si cette adresse est valide, un lien de confirmation vient d'être
  envoyé », le mot de passe oublié « Si un compte existe pour cette adresse, un lien de réinitialisation vient d'être
  envoyé » : la réponse ne révèle pas les comptes existants.
- `/reset` révoque les sessions ouvertes : après succès, l'écran propose « Se connecter ». `/verify` connecte et ouvre
  l'app. Jeton absent ou refusé : « Lien invalide ou expiré ».
- Un `401` ne renvoie vers `/login` que hors de ces écrans (`isPublicPath`, utilisé par `api`).

## Écrans connectés
- `Layout` lit `GET /auth/me` et fournit le compte par `MeContext` (`hooks/useMe.ts`).
- Navigation filtrée par rôle (`visibleNav`) : « Musique » et « Réglages » sont `adminOnly`. Dans l'éditeur, le bouton
  d'import de piste (panneau Musique) n'est montré qu'à l'administrateur (`POST /music` lui est réservé).
- Coûts : un filtre `project_id` d'un projet inconnu ou d'un autre compte (404) est retiré de l'URL.
