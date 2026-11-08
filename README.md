# Vivi

> **PayPal AI Hackathon submission.** Vivi is an AI tool that turns an idea into a finished vertical video
> (script, clips, voice, music, edit). For this hackathon we added **PayPal payments** so users pay for each AI
> generation with credits: one-off **credit packs** (Orders v2: create, capture, verified webhook) and three monthly
> **plans** (Starter, Créateur, Pro) billed with **PayPal Subscriptions**, each with its own credits and limits (queue,
> references, video length, generation profiles). Everything runs locally with fake AI providers and the
> **PayPal sandbox**, no paid API key needed. The interface switches between French and English.
>
> ### Try it in 5 minutes
> 1. `npm install && npm run setup` then set `FAKE_PROVIDERS=true` in `backend/.env`.
> 2. `npm run dev`, open http://localhost:5173, create an account (the verification link is printed in the API log).
> 3. In **Settings**, enter your PayPal sandbox `Client ID` and `Secret` (https://developer.paypal.com, Apps & Credentials, Sandbox).
> 4. Open **Plans**, click **Pay with PayPal** on a credit pack and pay with a sandbox personal account: credits are added once.
> 5. For subscriptions, create the sandbox plan of each tier once:
>    `cd backend && uv run python scripts/paypal_create_plan.py --tier starter` (then `creator`, `pro`),
>    and click **Subscribe with PayPal** on a plan.
>
> PayPal code: `backend/app/services/paypal_client.py`, `services/payments.py`, `services/billing.py`,
> `services/access.py`, `api/billing_api.py`, `api/paypal_webhook.py`, `admin/src/components/BillingOffers.tsx`.
> Details: `docs/paiement.md`, `docs/abonnement.md`.
>
> License: [MIT](LICENSE).

Workflow guidé de création de vidéos verticales (9:16) pour TikTok / Reels / Shorts : idée, script, image de référence
(optionnelle), clips, voix off, musique, montage FFmpeg, titre / description / hashtags. Chaque étape se valide
(ou se régénère) depuis une interface d'administration de type éditeur vidéo (frise des étapes, storyboard des scènes,
aperçu 9:16, timeline). Un mode automatique enchaîne toutes les étapes. Documentation : `docs/README.md`.

| Pièce | Technologie |
|---|---|
| API | FastAPI, SQLAlchemy (asyncio), Alembic, Postgres 16 |
| Worker | Arq (Redis 7), FFmpeg |
| Fichiers | MinIO (S3) |
| Providers | Claude, Gemini, fal.ai, ComfyUI (local), ElevenLabs |
| Admin | React, Vite, TypeScript |

## Prérequis
- Docker (Postgres 16, Redis 7, MinIO) ;
- Python 3.12 ou plus (développé en 3.14) ; [uv](https://docs.astral.sh/uv/) (`npm run lint` utilise `uvx ruff` ; la CI installe les dépendances avec `uv sync --frozen`) ;
- Node.js (admin Vite / React) ;
- FFmpeg **avec libass** (filtre `subtitles`, nécessaire aux sous-titres brûlés). Vérification :
  `ffmpeg -filters | grep -w subtitles` doit afficher une ligne. Sur macOS, la formule `brew install ffmpeg`
  actuelle inclut libass (vérifié avec FFmpeg 9.0.2) ; si le filtre manque, utiliser le tap
  `brew install homebrew-ffmpeg/ffmpeg/ffmpeg`.

## Démarrage
Tout se pilote depuis la racine avec npm (`package.json`) :
```bash
npm install          # outil de lancement (concurrently)
npm run setup        # backend/.env (copié de .env.example), venv Python, dépendances backend et admin
npm run dev          # Postgres / Redis / MinIO (Docker), migrations, puis API :8000 + worker Arq + admin :5173 + ComfyUI :8188 (ignoré s'il tourne déjà)
```
Ouvrir http://localhost:5173 (compte admin : `ADMIN_EMAIL` / `ADMIN_PASSWORD`, voir `docs/comptes.md` ; un visiteur non connecté arrive sur la page `/decouvrir`). Ctrl+C arrête l'API, le worker, l'admin et le ComfyUI lancé par `dev` ; `npm run stop`
arrête les conteneurs.

| Commande | Rôle |
|---|---|
| `npm run infra` / `migrate` | conteneurs Docker seuls / migrations Alembic |
| `npm run api` / `worker` / `admin` / `comfy` | un seul composant (un terminal chacun) |
| `npm run seed:music` | ajoute des pistes libres de droits à la bibliothèque (voir `docs/music.md`) |
| `npm test` / `npm run lint` | pytest + vitest / ruff + tsc + oxlint |

Sans clé API, mettre `FAKE_PROVIDERS=true` dans `backend/.env` : tout le flow est parcourable avec des providers factices (renseigner tout de même `default_voice_id`, par exemple `fake-voice`, dans l'écran Réglages ; choisir un clip par scène avant le montage).

`npm test` lance `pytest` (backend) puis `vitest` (admin) ; `npm run lint` lance `ruff` (backend), `tsc` et `oxlint`
(admin). La CI (`.github/workflows/ci.yml`) exécute les deux. Les tests backend utilisent deux bases à créer une fois
(conteneur Postgres démarré) :
```bash
docker compose exec postgres createdb -U vv video_virale_test
docker compose exec postgres createdb -U vv video_virale_mig
```

## Configuration
Variables dans `backend/.env` (modèle : `.env.example`) : `DATABASE_URL`, `REDIS_URL`, `MINIO_*`, `ADMIN_PASSWORD`, `SECRET_KEY`,
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `FAL_KEY`, `ELEVENLABS_API_KEY`, `COMFYUI_URL`, `FAKE_PROVIDERS`, `APP_ENV` (`dev` par défaut ; toute autre valeur active le mode production, `docs/securite.md`). Toutes les variables : `docs/exploitation.md`.
Les clés et réglages peuvent aussi se saisir dans l'écran Réglages de l'admin (la base prime sur l'environnement), dont le **budget maximum par vidéo** (10 $ par défaut, 0 = sans limite : au-delà, les générations payantes sont refusées et le mode automatique s'arrête).
Rédaction (idées, scripts, métadonnées) : Claude par défaut ; pour utiliser Gemini, renseigner `GEMINI_API_KEY` (ou la
clé dans la carte Gemini) puis choisir « Gemini » dans « Choix par défaut » de l'écran Réglages (réglage
`llm_provider`, modèle `gemini_model`). Le même LLM alimente l'assistant IA de l'admin (« Générer » / « Reformuler »
à côté de chaque champ texte, `docs/assistant-ia.md`). Voix ElevenLabs : `default_voice_id` doit être renseigné.

## Parcours avec les providers réels (procédure)
Non automatisé (coûts réels). Pour un essai à coût maîtrisé :
1. Renseigner `ANTHROPIC_API_KEY`, `FAL_KEY` et `ELEVENLABS_API_KEY` (fichier `.env` ou écran Réglages), choisir une voix (`default_voice_id`), `FAKE_PROVIDERS=false` ; un changement de `.env` impose de redémarrer API **et** worker (les clés saisies dans l'écran Réglages, elles, sont prises en compte au job suivant).
2. Créer un projet de 5 à 10 s, modèle de clip `ltx` (le moins cher), idéalement 1 scène de 3 s ; contrôler l'estimation avant de lancer les clips.
3. Dérouler les 8 étapes, vérifier le rendu en 1080x1920 (`ffprobe`) et le total dans l'écran Coûts / `GET /api/costs`.
4. ComfyUI (optionnel, voir « Clips gratuits avec ComfyUI ») : choisir le provider `comfyui`.

## Clips gratuits avec ComfyUI (local)
Les clips peuvent être générés gratuitement par une instance ComfyUI locale au lieu de fal.ai (détails :
`docs/providers.md`, section « ComfyUI en local »).
1. Prérequis : ComfyUI avec les custom nodes ComfyUI-VideoHelperSuite et ComfyUI-GGUF, et les modèles Wan 2.2 14B
   T2V GGUF Q4_K_M (haut et bas bruit), les LoRA lightx2v 4 étapes t2v, `umt5_xxl_fp8_e4m3fn_scaled.safetensors` et
   `wan_2.1_vae.safetensors` ; pour le profil Précision, Wan 2.2 14B I2V et Flux dev (liste complète par profil dans
   `docs/providers.md`).
2. Lancer ComfyUI (Mac) : `cd ~/Documents/projet/stabledifusion/ComfyUI && ./run_mac.sh --port 8188`.
3. Écran Réglages : la carte ComfyUI doit être « Connecté » (URL par défaut `http://127.0.0.1:8188`). Le profil vidéo
   par défaut se choisit sur des cartes (ComfyUI « Rapide » par défaut) ; on peut en changer à chaque lancement de
   l'étape Clips, pour toutes les scènes ou une seule.
4. Profils (M4 Max 36 Go, RAM libérée, clip de 3 s) : Rapide ≈ 5 min, Équilibré ≈ 7 min 30 s, Précision ≈ 11 min,
   Maximum ≈ 18 min. La RAM libre compte autant que le profil (Maximum : 45 min avec le swap saturé). Les clips d'un
   projet sont générés un à la fois en local (avec fal.ai : jusqu'à 3 en parallèle). Catalogue et benchmark :
   `docs/profils-generation.md`.

## Licence
MIT, voir [`LICENSE`](LICENSE).
