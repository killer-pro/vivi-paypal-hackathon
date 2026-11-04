# Réglages, providers et coûts (API)

Accès : `GET`/`PUT /api/settings` et `GET /api/providers/voices` (voix du compte du fournisseur) sont réservés à
l'administrateur (`ADMIN_ONLY`, `403 "Réservé à l'administrateur"` pour un autre compte). Santé, cartes de modèles et
`GET /api/settings/editor` restent ouverts à tout compte connecté : l'éditeur en a besoin.

- `GET /api/settings/editor` : choix par défaut affichés par l'éditeur (`EDITOR_KEYS` : `default_voice_id`,
  `voice_catalog`, `default_video_provider`, `default_video_model`, `image_provider`, `start_image_provider`), sans
  aucun secret.
- `GET /api/settings` : `AppSettings.all_masked()` (secrets affichés `••••` + 4 derniers caractères).
- `PUT /api/settings {clé: valeur}` : `400` si une clé n'est pas dans `EDITABLE_KEYS` ou si `llm_provider` n'est ni
  `claude` ni `gemini`, ou si `gemini_model` contient autre chose que des lettres, chiffres, `.`, `_`, `-`
  (rien n'est écrit).
  Une valeur commençant par `••••` (secret renvoyé tel quel) est ignorée : elle n'écrase pas le secret.
- `GET /api/providers/health` : `{claude, gemini, ollama, fal, comfyui, elevenlabs, langfuse}` (booléens ; Claude, Gemini et ElevenLabs = clé acceptée par le service, testée par un appel gratuit de 10 s max ; fal = clé renseignée, faute de point d'entrée gratuit ; ComfyUI = serveur joignable ; Langfuse = clés acceptées, voir `langfuse.md`). L'admin affiche « Non connecté » pour tout `false` (clé absente, refusée ou service injoignable).
- `GET /api/providers/models` : `{"video": [carte, ...], "image": [{provider, id, name, available, reason}], "llm": {"gemini": [...]}}`
  (`image` : modèles de l'image de référence de chaque provider, Gemini (`gemini_image_model` puis `IMAGE_PRICES`) puis
  fal (`flux`), grisés sans la clé du provider (« Clé API gemini manquante, à saisir dans Réglages → Gemini »), `services/video_models.py::image_cards`) ; carte =
  `{provider, id, name, description, speed, quality, minutes_per_clip, cost_usd_per_clip, available, reason, recommended}`
  (profils ComfyUI notés avec leur durée par clip, modèles fal avec leur coût par clip de 3 s ; indisponible =
  `available: false` et `reason` ; `recommended: true` pour le seul profil local par défaut, `DEFAULT_PROFILE`), dans l'ordre fal puis ComfyUI (Rapide, Équilibré, Précision, Maximum) ; `llm.gemini` = modèles Gemini
  connus (clés de `PRICES` dans `providers/gemini.py`). Jamais de `500` : ComfyUI éteint, muet (3 s pour tout l'appel), URL invalide ou
  réponse inattendue de `/object_info` → cartes locales grisées « ComfyUI injoignable » ou « Modèle manquant : <fichier> » ; délai dépassé : cartes disponibles avec la raison « ComfyUI ne répond pas (occupé ?) » (avertissement). Catalogue et
  affichage dans l'admin : `docs/profils-generation.md`. Plus de clé `comfyui_workflows` (réglage
  `comfyui_workflow_path` supprimé : `PUT /api/settings` le refuse en `400` comme toute clé inconnue).
- `default_video_model` : l'ancienne valeur `workflow` est lue et écrite `max` (`RENAMED` dans `app_settings.py`).
- `GET /api/costs?project_id=&provider=&since=&limit=&offset=` : `{total_usd, by_provider, by_project, calls, calls_total}`.
  L'admin voit tous les appels ; un utilisateur, ceux de ses projets seulement (les appels sans projet sont réservés à
  l'admin) ; un `project_id` absent ou d'un autre compte → `404 "Projet introuvable"`.
  Agrégats calculés en SQL (`group_by`) sur tous les appels qui correspondent ; `calls` = une page (`limit` 1–1000, défaut 200, à partir de `offset`), plus récents d'abord, et `calls_total` = nombre d'appels correspondants ; `since` est une date ISO.
- `project_budget_usd` (réglage éditable, défaut `10`, `0` = sans limite) : budget maximum par vidéo, voir `costs.md`.
  Refusé (`400`) si ce n'est pas un nombre positif ou nul. `default_voice_id` : lettres, chiffres, `_` et `-`, 64 max
  (l'identifiant finit dans l'URL d'ElevenLabs).
- Toutes ces routes exigent l'authentification (cookie de session).
