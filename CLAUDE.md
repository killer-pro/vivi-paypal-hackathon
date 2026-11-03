# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Vivi (dépôt `video_virale`) : application de création de vidéos verticales 9:16 (idée → histoire → script → références → clips → voix → musique → montage FFmpeg → métadonnées). Backend FastAPI + worker Arq, admin React/Vite. Tout est en français (code, commentaires, docs, commits). Voir `README.md` et `docs/README.md` (index de la doc).

## Commandes (depuis la racine)
- `npm run setup` : `backend/.env`, venv Python 3.12+ (`backend/.venv`), dépendances backend et admin.
- `npm run dev` : Docker (Postgres/Redis/MinIO) + migrations + API :8000 + worker Arq + admin :5173 + ComfyUI :8188 (ignoré s'il tourne déjà). `api`, `worker`, `admin`, `comfy`, `infra`, `migrate` lancent un seul composant.
- `npm test` (pytest puis vitest) ; `npm run lint` (ruff, mypy, `tsc -b`, oxlint).
- Un seul test : `cd backend && .venv/bin/pytest tests/test_x.py::test_nom` ; côté admin : `cd admin && npx vitest run src/steps.test.ts`.
- Les tests backend exigent Postgres démarré et deux bases : `docker compose exec postgres createdb -U vv video_virale_test` et `... video_virale_mig`.
- `FAKE_PROVIDERS=true` dans `backend/.env` : tout le flow tourne avec des providers factices (aucune clé API).
- L'API et le worker lisent `.env` au démarrage : les redémarrer ensemble après modification. Les réglages saisis dans l'écran Réglages (table `settings`) sont relus à chaque job.

## Architecture
- **L'API ne fait jamais d'appel provider** : elle enfile `run_step_job` dans Redis (Arq) ; le worker exécute (`backend/app/worker.py`, `services/pipeline.py` : `run_step` et un exécuteur par étape) et publie des événements sur Redis pub/sub, relayés au navigateur par SSE (`/api/events`).
- `services/steps.py` (`launch_step`, autopilot) et `services/flow.py` (état des étapes, péremption `stale`, 409 si une étape tourne) sont partagés par l'API et le worker. `services/budget.py` applique le plafond de coût par projet.
- Providers (`backend/app/providers/`) : Claude, Gemini, fal.ai, ComfyUI local, ElevenLabs, fakes, choisis via `registry.py`. Tout appel passe par `tracked_call` (`services/costs.py` : journal `provider_calls`, retries, timeouts). `max_tries = 1` : un job interrompu n'est jamais rejoué (évite un double appel payant).
- ComfyUI : profils vidéo (`fast`, `balanced`, `precision`, `max`) dans `providers/profiles.py`, graphes JSON dans `backend/workflows/` paramétrés par `providers/workflows.py`. Avec une image de référence, le graphe est choisi selon l'entrée (Kontext puis Wan I2V). Sortie normalisée en 720×1248 à 16 fps dont dépend le montage.
- Fichiers dans MinIO (S3), lus par le navigateur via URLs présignées. Réglages : `AppSettings` (`app_settings.py`) superpose la table `settings` à l'environnement ; la base prime.
- Admin (`admin/src/`) : logique pure dans des modules `*.ts` testés par vitest (`steps.ts`, `studio.ts`, `plan.ts`…), composants dans `components/` et `pages/`. Thème graphite « Studio » (`docs/design-system.md`).

## Conventions du projet
- **Migrations Alembic** (`backend/migrations/versions/`, nommage `00NN_nom.py`) : ne jamais modifier une migration existante, en créer une nouvelle avec le numéro suivant (`ls ... | sort -V`).
- **Documentation** : une fonctionnalité = un fichier `docs/*.md` ; toute modification de logique met à jour le doc concerné et ajoute une ligne à `docs/changelog.md`.
- ruff : lignes de 120 max (E501 ignoré), règles `E,F,I,B,UP` ; mypy avec `check_untyped_defs`. La CI (`.github/workflows/ci.yml`) lance ruff, mypy, pytest, tsc, oxlint, vitest.
- Priorité produit : vidéos non linéaires (scènes indépendantes), voir `docs/story.md` et `docs/workflow-video.md`.
