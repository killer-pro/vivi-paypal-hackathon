# Architecture

## Composants
| Composant | Rôle | Code |
|---|---|---|
| API FastAPI | Auth par cookie, projets, étapes, musique, réglages, coûts, SSE | `backend/app/main.py`, `backend/app/api/` |
| Worker Arq | Exécute `run_step_job` (appels providers, FFmpeg) ; `queue.py` : un client Redis par boucle d'événements | `backend/app/worker.py`, `backend/app/queue.py` |
| Pipeline | `run_step` et les 8 exécuteurs | `backend/app/services/pipeline.py` (+ `prompts.py`, `script_parsing.py`, `timeouts.py`, `choices.py`) |
| Lancement / autopilot | `launch_step` (API et worker), mode automatique | `backend/app/services/steps.py` |
| État du flow | Lecture des étapes, péremption (`stale`), statut du projet, 409 si une étape tourne | `backend/app/services/flow.py` |
| Budget | Plafond de dépense par projet, coût estimé des clips | `backend/app/services/budget.py` |
| Providers | Claude, fal.ai, ComfyUI, ElevenLabs, fakes, registre | `backend/app/providers/` |
| Coûts | `tracked_call` (journal, retries, timeouts), `WriteGate` (écritures concurrentes) | `backend/app/services/costs.py` |
| Montage | Rendu FFmpeg 9:16 | `backend/app/services/montage.py` |
| Admin | React / Vite / TypeScript, thème graphite (éditeur « Studio », `docs/design-system.md`) | `admin/` |
| Qualité | `ruff`, `pytest`, `vitest`, `tsc`, `oxlint` ; CI GitHub Actions | `.github/workflows/ci.yml`, `npm run lint`, `npm test` |
| Infra | Postgres 16, Redis 7, MinIO (`docker-compose.yml`) | |

## Flux
```
Admin (navigateur :5173)
  | /api (proxy Vite -> :8000), cookie session
  v
API FastAPI --- SQL --------> Postgres (projets, étapes, scènes, assets, coûts, réglages)
  |  \-- enfile run_step_job --> Redis (file Arq)  --> Worker Arq --> providers / FFmpeg
  |                                                        |  \-- fichiers --> MinIO (S3)
  |<-- événements {project_id, step, status, error} -- Redis pub/sub (vv:events) <--+
  \-- SSE /api/events --> Admin (rafraîchit liste et éditeur)
```
Le navigateur lit les fichiers par URL présignée MinIO (1 h). L'API ne fait jamais d'appel provider : tout passe par le worker.

## Modèle de données (`backend/app/models.py`, migrations `0001` à `0004`)
- `projects` : titre, thème, plateforme, durée cible, statut, `metadata_json` (titre / description / hashtags publiés).
- `steps` : (projet, nom) unique, `status`, `params`, `result`, `error`, `run_id` (dernier lancement complet des étapes par scène, pour la reprise : `docs/workflow-video.md`).
- `scenes` : position, texte de voix, prompt visuel, durée, `selected_clip_asset_id`.
- `assets` : type (`reference`, `clip`, `voice`, `render`), clé MinIO, `variant`, `meta`; scène optionnelle (`SET NULL` si la scène disparaît).
- `asset_originals` : nom de fichier d'origine d'un asset importé (clé primaire et FK `assets.id` en `CASCADE`),
  donnée affichée seulement, jamais dans une clé (migration `0005`, `docs/imports-fichiers.md`).
- `music_library` : nom, tags, durée, clé MinIO.
- `provider_calls` : un appel provider (étape, provider, modèle, coût USD, durée, `ok`/`error`, erreur) ; `project_id` en `SET NULL`.
- `settings` : réglages modifiables depuis l'admin (clé / valeur ; clés API en clair, voir `docs/securite.md`).
- Index (migration `0003`) : `assets (project_id, kind, scene_id)`, `scenes (project_id, position)`,
  `provider_calls (project_id)` et `(created_at)`. Les modèles déclarent les mêmes index (testé).

## Configuration
`backend/app/config.py` (pydantic-settings, `.env` lu depuis le dossier de lancement, soit `backend/`) ; `AppSettings` superpose la table `settings` à l'environnement. `APP_ENV` (`dev` par défaut) distingue le poste local de la production
(`docs/securite.md`). Toutes les variables : `docs/exploitation.md`.

## Garde-fous
- Sécurité : connexion limitée en tentatives, cookie `Secure` et API non documentée hors `dev`, refus de démarrer avec les
  secrets par défaut hors `dev` (`docs/securite.md`).
- Coûts : budget par projet, plafond de durée, suppression refusée pendant une génération (`docs/costs.md`).
- Concurrence : clips et voix en parallèle avec écritures en base sérialisées (`docs/workflow-video.md`).

## Limites connues
- L'API et le worker lisent l'environnement (`backend/.env`) au démarrage : les redémarrer ensemble après l'avoir
  modifié. Les clés et réglages saisis dans l'admin (table `settings`) sont relus à chaque job, sans redémarrage.
- Au démarrage, l'API crée le bucket MinIO s'il manque (comme le worker ; une erreur est loguée sans bloquer). Si
  `ADMIN_PASSWORD` / `SECRET_KEY` gardent une valeur par défaut connue : avertissement en `APP_ENV=dev`, refus de
  démarrer sinon.
- `max_tries = 1` : un job interrompu n'est jamais rejoué (évite un double appel payant) ; l'étape passe en `failed` et se relance à la main.
- Un seul worker est supposé (reset des étapes `running` au démarrage).
- Aucun cron, aucune publication vers les plateformes en V1.
