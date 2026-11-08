# Déploiement sur un serveur

Fichiers : `deploy/docker-compose.yml`, `deploy/Caddyfile`, `admin/Dockerfile`, `backend/Dockerfile`.

## Architecture
- **Caddy** (seul service qui publie des ports, 80 et 443) : HTTPS automatique (Let's Encrypt), sert l'admin compilé (image
  construite par `admin/Dockerfile`), relaie `/api/*` vers l'API (sans tampon, pour le flux SSE `/api/events`) et
  `s3.<domaine>` vers MinIO.
- **MinIO derrière `s3.<domaine>`** : les URLs présignées signent l'hôte, donc le code et le navigateur doivent utiliser la
  même adresse. `MINIO_ENDPOINT=https://s3.<domaine>` ; dans le réseau Docker, ce nom est un alias de Caddy.
- **API, worker, migrations** : même image `vivi-backend`. `migrate` (`alembic upgrade head`) s'exécute avant l'API et le
  worker à chaque `up`.
- Postgres, Redis, MinIO : sans port publié (Docker contourne ufw pour les ports publiés). MinIO vient de l'image
  Chainguard (`minio/minio` n'est plus publiée sur Docker Hub).

## Configuration
- `deploy/.env` (modèle `deploy/.env.example`) : `DOMAIN`, `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`. Sans nom de domaine,
  `sslip.io` en fournit un à partir de l'IP (`45-13-235-135.sslip.io`).
- `backend/.env` : clés des services, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `SECRET_KEY` (secrets non par défaut : l'API refuse
  de démarrer en prod sinon). Le compose impose `APP_ENV=prod`, `PUBLIC_URL` et les adresses internes (base, Redis,
  MinIO), qui priment sur `backend/.env`.

## Serveur de démo (VPS Contabo)
- Code dans `/root/vivi`, dépôt git qui accepte le push direct (`receive.denyCurrentBranch updateInstead`). Depuis le
  poste : remote `vivi` (`vivi:/root/vivi`).
- Mise à jour : `git push vivi main`, puis `ssh vivi 'cd /root/vivi/deploy && docker compose up -d --build'`.
- Journaux : `ssh vivi 'cd /root/vivi/deploy && docker compose logs -f api worker'`.
- Scripts de `backend/scripts/` dans le conteneur : `docker compose exec -T -e PYTHONPATH=. api python scripts/<script>.py …`
  (sans `PYTHONPATH=.`, le module `app` est introuvable).
- Forfaits : PayPal en **sandbox** (identifiants dans les Réglages du serveur). Un plan PayPal par forfait, créé le
  2026-11-08 avec `paypal_create_plan.py --tier starter|creator|pro` (Starter `P-9K826277PP850050YNLX53CA`, Créateur
  `P-7JW2861824309351BNLX53EA`, Pro `P-8J88911395757691CNLX53GY`) et inscrit dans `billing_config`. Aucun réglage
  `credits_*` en base : les défauts du code s'appliquent (200 crédits d'inscription, crédit à 0,01 $, marge ×3).
  Le compte démo (`demo@example.com`, abonnement sandbox de l'ancien plan unique) a les avantages du Starter.
- Pas de ComfyUI sur le serveur (pas de GPU) : clips, image de départ et images de référence passent par Comfy Cloud
  (`default_video_provider=comfycloud`, `image_provider=comfycloud`), le texte par Groq.
- E-mails : `BREVO_API_KEY` et `BREVO_SENDER` dans `backend/.env` (API Brevo), `SMTP_*` (SMTP Brevo) en secours ;
  envoi vérifié depuis le conteneur de l'API le 2026-11-08.
- DNS : un des résolveurs de Contabo ne répond pas (3 s perdues par requête, appels aux providers en échec au hasard).
  Docker utilise 1.1.1.1 et 8.8.8.8 (`/etc/docker/daemon.json`), le système aussi
  (`/etc/systemd/resolved.conf.d/dns.conf`).
- Données : copie de la base et des fichiers du poste local le 2026-11-07 (`pg_dump` puis `pg_restore`, objets MinIO
  réimportés). Après restauration, les clés API chiffrées en base sont rechiffrées avec la `SECRET_KEY` du serveur et le
  mot de passe de l'admin reprend `ADMIN_PASSWORD`. Le compte `demo@example.com` (compte du jury) a sa propre copie des
  projets vedettes et un mot de passe propre au serveur.
