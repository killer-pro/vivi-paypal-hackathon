# Providers

> Les écrans de l'admin disent « Réglages » (`/providers`) ; « Non connecté » = clé absente, refusée ou service coupé
> (`GET /api/providers/health` ne renvoie que des booléens).

- **Contrat LLM** (`LLMProvider.complete(system, prompt, *, max_tokens=4000, json_schema=None)`) : `json_schema`
  (facultatif, schéma OpenAPI au format Gemini, types en majuscules) signale une réponse JSON attendue. Gemini l'impose
  (sortie structurée), Claude et le fake l'ignorent (le prompt demande déjà du JSON et l'appelant valide la réponse).
  Utilisé par les étapes `script` (`SCENES_SCHEMA`) et `final` (`FINAL_SCHEMA`) ; jamais pour l'assistant de rédaction.
- `ClaudeLLM` : texte via l'API Anthropic ; coût = tokens x `PRICE_IN_PER_M` / `PRICE_OUT_PER_M`. Client SDK créé avec
  `max_retries=0` : les retries sont faits (et journalisés) par `tracked_call`, pas en double par le SDK.
- `ComfyUIImage` (`providers/comfyui.py`) : image de référence générée par Flux dev sur votre ComfyUI (même graphe `flux-keyframe` que l'image de départ du profil Précision, 576×1008), `image_provider=comfyui`, modèle `flux-dev`. Gratuit ; ≈ 3 min par image mesuré sur un M4 Max. Disponible si les fichiers de `flux_files()` (`profiles.py`) sont installés. Ne replace pas d'images d'entrée (`references` ignoré).
- `OllamaLLM` (`providers/ollama.py`) : texte généré sur votre machine par Ollama (`POST /api/chat`), sans clé ni coût (`cost_usd` = 0). Réglages `llm_provider=ollama`, `ollama_url` (défaut `http://127.0.0.1:11434`) et `ollama_model` (défaut `gemma4`, meilleur compromis mesuré le 2026-11-04 : 9 s par script, 6,6 Go, JSON toujours valide ; `qwen3:14b` un peu plus rapide mais plus plat, `qwen3:32b` trop lent et trop lourd pour cohabiter avec ComfyUI, à télécharger avec `ollama pull`). Le schéma de sortie structurée est converti du format Gemini (types en majuscules, `nullable`, `propertyOrdering`) en JSON Schema par `standard_schema` (`providers/base.py`, partagé avec Groq) ; `keep_alive: 0` décharge le modèle après chaque réponse pour rendre la RAM à ComfyUI ; `think: false` évite que la réflexion mange les tokens. Santé : le modèle choisi est téléchargé. Pour les images de référence, Ollama ne sert à rien : elles restent à Gemini ou fal.ai, ou à ComfyUI (Flux Kontext) pour l'image de départ des scènes.
- `GroqLLM` (`providers/groq.py`) : texte via GroqCloud (API compatible OpenAI, `POST https://api.groq.com/openai/v1/chat/completions`, clé en en-tête `Authorization: Bearer`). Réglages `llm_provider=groq`, `groq_api_key` (env `GROQ_API_KEY`) et `groq_model` (défaut `openai/gpt-oss-120b`, seul modèle du compte qui a passé le test du 2026-11-07 : les six schémas du pipeline en JSON valide, ~1 s par appel ; `qwen/qwen3.8-27b` échoue au JSON imposé). Sortie structurée par `response_format: json_schema` en mode non strict (nos schémas n'exigent pas toutes leurs propriétés), schéma traduit par `standard_schema` ; une réponse refusée par Groq comme non conforme (`json_validate_failed`) est relançable. `reasoning_effort: low`. Prix (`PRICES`, USD par million de tokens, relevés le 2026-11-07) : gpt-oss-120b 0,15 / 0,60, gpt-oss-20b 0,075 / 0,30 ; un script complet coûte moins de 0,005 $. Santé : la liste des modèles répond avec la clé. Hébergé, il remplace Ollama sur un serveur sans GPU.
- `GeminiLLM` (`providers/gemini.py`) : texte via l'API REST Gemini (`POST
  https://generativelanguage.googleapis.com/v1beta/models/{modèle}:generateContent`, client `httpx` partagé du
  registre, aucune dépendance ajoutée). Le prompt système passe par `systemInstruction`, le prompt par `contents`,
  `max_tokens` par `generationConfig.maxOutputTokens` ; avec `json_schema`, `generationConfig.responseMimeType =
  "application/json"` et `responseSchema` (vérifié sur l'API réelle le 2026-10-18 : JSON brut, sans bloc ```` ``` ````). Le modèle est encodé dans l'URL (`quote`) et validé à
  l'enregistrement (lettres, chiffres, `.`, `_`, `-`). **La clé n'est envoyée que dans l'en-tête `x-goog-api-key`,
  jamais dans l'URL ni dans le corps.** Les messages d'erreur ne contiennent pas la clé de notre fait, mais un 4xx
  reprend jusqu'à 200 caractères de la réponse du provider (`raise_for_provider`). Pas de retry interne
  (`tracked_call` s'en charge).
  - **Réflexion** : `maxOutputTokens` est partagé entre la réflexion et le texte. Les étapes ne demandent que de
    l'écriture : on envoie `generationConfig.thinkingConfig.thinkingLevel` au niveau le plus bas documenté pour le modèle
    (`THINKING_LEVELS` : `minimal` pour 3.5-flash-lite et 3.6-flash, `low` pour 3.8-flash et 4-argon, minimum
    documenté). Pour un modèle absent de la table (3.1-flash-lite, dont seule la variante image est documentée, ou un
    modèle saisi hors liste), le champ n'est pas envoyé, pour éviter un 400. `thinkingBudget` n'est jamais envoyé
    (l'API refuse les deux en même temps).
  - **Erreurs** : réseau, 5xx et 429 relançables ; autres 4xx non. `finishReason = MAX_TOKENS` donne une erreur non
    relançable « réponse tronquée » : un texte tronqué n'est jamais renvoyé comme un succès. Toute autre raison que
    `STOP` (`SAFETY`, `RECITATION`…) donne « réponse interrompue (raison) », même si du texte partiel est présent.
    Une réponse vide ou une requête bloquée (`promptFeedback.blockReason`) donne « réponse vide ». Les parties
    `thought` sont ignorées.
  - **Coût** : `promptTokenCount` x prix d'entrée + (`candidatesTokenCount` + `thoughtsTokenCount`) x prix de sortie
    (réflexion facturée comme de la sortie). Sans `candidatesTokenCount`, sortie = `totalTokenCount` -
    `promptTokenCount`. Un compteur absent ou `null` compte 0. Après `PRICES_VALID_UNTIL` (2026-11-30, veille du
    premier changement de prix annoncé), un `logger.warning` signale une fois par processus que la table est
    périmée.
  - Santé = clé acceptée par le service : `GET /v1beta/models?pageSize=1` (liste gratuite, 10 s max, `key_is_valid` dans `providers/base.py`).
- `FalProvider` : images (`flux`) et vidéos (`kling`, `wan`, `ltx`) via la file fal.ai (polling jusqu'à `COMPLETED`). L'image de référence (`image`) est acceptée mais ignorée en V1 (modèles texte-vers-vidéo).
  - **Soumission jamais rejouée après acceptation** : seule la requête `POST` de soumission (pas encore facturée) peut
    échouer en erreur `retryable` et être relancée par `tracked_call`. Après soumission, le polling (`status_url`), la
    lecture du résultat (`response_url`) et le téléchargement réessaient sur place les erreurs réseau/5xx/429
    (`TRANSIENT_RETRIES = 5` par requête, même URL) ; au-delà, ou sur une erreur définitive, l'erreur est **non
    relançable** (le job payé n'est pas resoumis).
  - **Durée des clips** (`clip_duration`) : Kling v2 n'accepte que `duration` = `"5"` ou `"10"` ; la scène est arrondie à
    la plus petite valeur qui la couvre (3 s → 5 s, 6 s → 10 s, au-delà de 10 s → 10 s). Wan et LTX n'ont pas de paramètre
    de durée (clip fixe d'environ 5 s ; `aspect_ratio` non envoyé à LTX). La même durée arrondie sert à
    `estimate_cost` et au coût journalisé. Le montage coupe chaque clip à la durée de sa voix, ou tient sa dernière image s'il est plus court (jamais de boucle).
- `ComfyUIProvider` : un modèle par profil de génération (`models` = ids de `profiles.PROFILES` : `fast`, `balanced`,
  `precision`, `max` ; ancien nom `workflow` = `max`), catalogue et benchmark dans `docs/profils-generation.md`. Le
  profil choisit le workflow JSON livré (format API, placeholders, voir « ComfyUI en local » ci-dessous), sa résolution
  et l'upscale ESRGAN ; `precision` enchaîne deux prompts (image Flux, envoyée dans `input/` de ComfyUI par
  `POST /upload/image` sous le nom fixe `vv_keyframe.png`, réécrit à chaque run et verrouillé jusqu'à la fin de
  l'animation, puis Wan I2V) et renvoie l'image avec le clip (`GenerationResult.keyframe`). Coût 0 ; timeout
  d'un clip 5700 s (`CLIP_TIMEOUT_S`, polling toutes les 2 s dimensionné en conséquence) au lieu de 900 s pour les
  providers cloud. `availability()` : profil disponible si `GET /system_stats` répond et que chacun de ses fichiers
  (`required_files`) figure dans la liste du nœud chargeur (`GET /object_info/<nœud>`, formats ancien et `COMBO`) ;
  sinon « ComfyUI injoignable » ou « Modèle manquant : <fichier> ». Disponibilité : 3 s pour tout l'appel (`AVAILABILITY_TIMEOUT_S`,
  nœuds chargeurs interrogés ensemble, au lieu des 120 s du client) ; santé : même délai ; délai dépassé = « ComfyUI ne répond pas (occupé ?) »
  (carte `available: true` avec cette raison : lançable,
  le job attend son tour) ; connexion refusée ou URL invalide (`httpx.InvalidURL`, aussi en
  génération) = « ComfyUI injoignable » ; jamais de `500`. Réponse de `/upload/image` sans `name` → « comfyui: envoi
  de l'image de départ sans nom de fichier en retour ». Toutes les erreurs de génération sont non
  relançables (sauf 5xx/429 HTTP) :
  - serveur injoignable → « ComfyUI injoignable » ; profil inconnu → « comfyui: profil inconnu : x » ;
  - prompt terminé en erreur (`status.status_str == "error"` dans `/history`) → « échec du workflow (node : message
    ComfyUI) », par exemple `KSampler : MPS backend out of memory` ; interrompu → « génération interrompue » ;
  - prompt absent de `/history` **et** de `/queue` (en cours + en attente) pendant `MISSING_POLLS = 3` polls
    consécutifs (ComfyUI redémarré) → « prompt introuvable… », au lieu d'attendre la fin du timeout ;
  - appel abandonné (timeout de `tracked_call`, annulation du job, erreur de polling) : le prompt est retiré de ComfyUI
    avant de relancer l'exception, en best-effort (10 s max, protégé de l'annulation) : `POST /queue {"delete": [id]}`
    s'il est en attente, `POST /interrupt {"prompt_id": id}` s'il tourne. Le prompt d'un autre utilisateur n'est jamais
    touché. Vérifié sur le vrai ComfyUI : timeout à 45 s, prompt interrompu et file vide 2 s après.
- `ComfyCloudProvider` (`providers/comfycloud.py`, nom `comfycloud`) : mêmes profils (`fast`…`max`) et mêmes graphes
  que `ComfyUIProvider` (classe parente), exécutés sur les GPU de Comfy Cloud (`https://cloud.comfy.org/api`, en-tête
  `X-API-Key`, réglage `comfy_cloud_api_key`, env `COMFY_CLOUD_API_KEY`). `cloud_workflow` (`providers/workflows.py`)
  remplace les chargeurs `UnetLoaderGGUF` (absents du cloud) par `UNETLoader` et les modèles fp8 du cloud (`CLOUD_UNETS`).
  Suivi par `GET /api/job/{id}/status`, résultat par `/api/history_v2/{id}`, fichier par `/api/view`, qui redirige vers
  une URL signée lue sans la clé. Coût = durée d'exécution facturée (`GET /api/jobs/{id}`) x `USD_PER_GPU_S` (736 crédits
  par heure de GPU, 211 crédits par dollar) ; estimation avant lancement par `GPU_S_PER_CLIP`. Mesuré le 2026-11-07 :
  clip Rapide de 3 s en 36 s, 0,02 $. **Exige un abonnement payant** (Standard ou plus) : un compte gratuit, même avec
  des crédits achetés, reçoit 403 `FREE_TIER_NOT_ALLOWED` ou 402 `FREE_TIER_EXHAUSTED`, traduits en erreur non
  relançable `NO_PLAN`. Disponible dès qu'une clé est saisie (pas de requête par carte). 2 clips en parallèle
  (`CLIP_CONCURRENCY`) ; image de départ par Flux Kontext sur le cloud, comme en local (`COMFY_PROVIDERS` de
  `registry.py`). `ComfyCloudImage` : image de référence Flux dev sur le cloud (`image_provider=comfycloud`).
  `talk` : avatar parlant (lip-sync) à partir d'une image et d'une voix, modèle du réglage `lipsync_model` (`s2v`,
  `infinitetalk`, `ltx`), coût `cloud_talk_usd` ; `ProviderRegistry.talker()` le fournit (`FakeVideo.talk` en mode factice).
  Voir `avatar-parlant.md`.
- `ElevenLabsVoice` : synthèse vocale ; coût = nb de caractères x `PRICE_PER_CHAR`. Modèle `eleven_multilingual_v2`, ou `eleven_v3` dès que le texte contient une balise d'émotion entre crochets (`[excited]`, `[laughs]`, `[whispers]`…) : v3 la joue au lieu de la lire. `spoken()` retire ces balises des sous-titres, du compte de mots du script et du texte envoyé au LLM des métadonnées. Les prompts du script et de l'histoire autorisent une ou deux balises par scène.
- Erreurs HTTP : 5xx et 429 retryables, autres 4xx non (`raise_for_provider`).
- `AppSettings` : lit la table `settings` puis l'environnement ; seules les clés de `EDITABLE_KEYS` sont modifiables ; les secrets sont masqués (`••••` + 4 derniers caractères).
- `ProviderRegistry` : construit les providers à la demande ; `FAKE_PROVIDERS=true` renvoie les fakes (quel que soit
  `llm_provider`). `llm()` choisit le provider de texte selon le réglage `llm_provider` (`claude` par défaut,
  `gemini`, `groq` ou `ollama`) ; une autre valeur lève une `ProviderError` explicite (« llm_provider inconnu… »), l'API refusant déjà
  de l'enregistrer. Le rapport de santé teste tous les providers de texte, quel que soit le choix.
  `FakeLLM` répond un JSON de 2 scènes pour le script, des métadonnées (`title`, `description`, `hashtags`) pour l'étape
  final et « ok » sinon : le flow complet peut être parcouru sans clé API.

## Configuration
| Provider | Clé / réglage | Notes |
|---|---|---|
| Claude (LLM) | `ANTHROPIC_API_KEY` | Santé : liste des modèles (gratuite, 10 s max). Prix : `PRICE_IN_PER_M` / `PRICE_OUT_PER_M` dans `providers/claude.py`. |
| Groq (LLM, alternative hébergée) | `GROQ_API_KEY`, `groq_model`, `llm_provider=groq` | Clé GroqCloud (`gsk_…`). Modèle par défaut `openai/gpt-oss-120b`, prix dans `PRICES` de `providers/groq.py`. |
| Gemini (LLM, alternative) | `GEMINI_API_KEY`, `gemini_model`, `llm_provider=gemini` | Clé Google AI Studio. Modèle par défaut `gemini-3.5-flash-lite` (rapide, peu cher). Prix USD par million de tokens (entrée / sortie, réflexion comprise) dans `PRICES` de `providers/gemini.py`, relevés le 2026-10-17 : 3.5-flash-lite 0,30 / 2,50 ; 3.1-flash-lite 0,25 / 1,50 ; 3.6-flash et 3.8-flash 0,75 / 3,75 (doublent le 2027-01-01 selon Google) ; 4-argon (modèle phare, cher) 2,00 / 10,00 (double le 2026-12-01). Mettre à jour la table et `PRICES_VALID_UNTIL` à ces dates. Modèle absent de la table : prix le plus élevé de la table (estimation prudente). |
| fal.ai (image, vidéo) | `FAL_KEY` | Santé : clé renseignée seulement (fal n'a pas de point d'entrée gratuit pour la tester). Jusqu'à 3 clips en parallèle (`CLIP_CONCURRENCY`). Modèles vidéo `kling`, `wan`, `ltx`, image `flux`. Prix estimés (USD/s) modifiables dans `providers/fal.py` (`VIDEO_MODELS[...].price_per_second` : kling 0.28, wan 0.10, ltx 0.04 ; `IMAGE_PRICE = 0.025`), appliqués à la durée réellement générée (`clip_duration`). Ils servent à l'estimation avant lancement et au journal. Seul fournisseur de l'image de référence (`registry.image()`). Sans clé : aucune requête, `ProviderError` non relançable « Clé API fal manquante, à saisir dans Réglages → fal.ai » (image comme vidéo), cartes vidéo et image grisées avec cette raison, lancement de `reference` refusé (`409`). |
| ComfyUI (vidéo locale) | `COMFYUI_URL`, `default_video_model` (profil) | Profils `fast` (défaut), `balanced`, `precision`, `max` ; workflows livrés dans `backend/workflows/` (format API). Coût 0. Serveur injoignable = erreur non retryable, isolée aux étapes qui l'utilisent. |
| Comfy Cloud (vidéo, image) | `COMFY_CLOUD_API_KEY`, `default_video_provider=comfycloud` | Abonnement payant requis (Standard ou plus). Profils de ComfyUI, facturés au temps de GPU. Clé testée par `GET /api/user`. |
| ElevenLabs (voix) | `ELEVENLABS_API_KEY`, `default_voice_id` | Santé : `GET /v1/user` (gratuit). `voice_id` limité à `[A-Za-z0-9_-]{1,64}` (il finit dans l'URL). Prix : `PRICE_PER_CHAR` dans `providers/elevenlabs.py`. `GET /providers/voices` liste les voix du compte (`GET /v1/voices`) pour remplir le catalogue. **`default_voice_id` est obligatoire** pour l'étape voix (identifiant d'une voix ElevenLabs ; en mode fake, n'importe quelle valeur, ex. `fake-voice`). |

Clé API absente (fal, ElevenLabs, Gemini, Claude) : l'appel lève avant toute requête une `ProviderError` non relançable
« Clé API <provider> manquante, à saisir dans Réglages → <carte> » (`base.require_key`), au lieu d'un en-tête invalide refusé par
httpx (« Illegal header value b'Key ' » pour fal, réessayé comme une erreur réseau), d'un `401` du service ou d'un
`TypeError` du SDK Anthropic ; la santé reste `false` sans requête. Les clés sont relues sans espaces de bord
(`AppSettings.get`) : une clé collée avec un retour à la ligne ne casse plus l'en-tête, une clé faite d'espaces vaut
absente.

Image de référence (`registry.image(provider)`, provider choisi sur l'étape, sinon réglage `image_provider`) :
- **Gemini** (défaut, même clé `gemini_api_key` que la rédaction) : `GeminiImage` (`providers/gemini.py`),
  `generateContent` avec `responseModalities: ["IMAGE"]` et `imageConfig.aspectRatio = "9:16"`, image en base64 dans
  `inlineData` (PNG, JPEG ou WebP). Modèle `gemini_image_model` (défaut `gemini-3.1-flash-image`, « Nano Banana 2 »,
  vérifié le 2026-10-22 : JPEG 768×1376), puis les autres modèles de `IMAGE_PRICES`. Coût par tokens
  (`tokens_cost`, prix relevés le 2026-10-22 : 0,50 $ / 60 $ par million, ≈ 0,07–0,09 $ l'image) journalisé dans
  `provider_calls`. Réponse sans image (refus de sécurité `IMAGE_SAFETY`, `blockReason`) : erreur non relançable
  « gemini: aucune image dans la réponse (…) ». `generate(…, references=[octets])` joint des images d'entrée (`inlineData`, avant le
  texte) : utilisé pour l'image de départ des scènes (option `start_image_provider`, voir `profils-generation.md`).
- **fal** : `flux` (clé `fal_key`). Un ancien paramètre d'étape `model: flux` sans provider vaut fal.

Réglages modifiables dans l'admin (`EDITABLE_KEYS`) : clés API (dont `gemini_api_key` et `groq_api_key`, secrets masqués), `llm_provider`
(`claude` | `gemini` | `groq` | `ollama`, défaut `claude`), `gemini_model` (défaut `gemini-3.5-flash-lite`), `groq_model` (défaut `openai/gpt-oss-120b`, un `/` permis), `comfyui_url`, `default_voice_id`, `voice_catalog` (JSON `[{"id", "name"}]`, identifiants au format `voice_id`, uniques, 100 au plus ; liste proposée à l'étape Voix), `default_video_provider` (défaut `comfyui`), `default_video_model` (défaut `fast`, profil Rapide), `image_provider` (`gemini` | `fal`, défaut `gemini`), `gemini_image_model` (défaut `gemini-3.1-flash-image`). `comfyui_workflow_path` n'existe plus (refusé en écriture). La base prime sur l'environnement.

Limites : l'image de référence n'est pas transmise aux modèles texte-vers-vidéo de fal.ai en V1 ; un secret ne peut pas être effacé depuis l'admin (valeur vide = retour à l'environnement). Les clés et réglages enregistrés depuis l'admin sont relus à chaque job (le worker crée un `ProviderRegistry` par job) : pas de redémarrage. Les variables d'environnement (`backend/.env`, dont `FAKE_PROVIDERS`) sont lues au démarrage : redémarrer API et worker après les avoir modifiées.

## ComfyUI en local (clips gratuits)

### Prérequis
- ComfyUI installé localement (ici `~/Documents/projet/stabledifusion/ComfyUI`, venv `venv/`), avec les custom nodes
  **ComfyUI-VideoHelperSuite** (node `VHS_VideoCombine`, sortie mp4) et, pour le 14B, **ComfyUI-GGUF**
  (`UnetLoaderGGUF`).
- Modèles communs : `models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors`.
- Rapide, Équilibré, Maximum (Wan 2.2 14B T2V) : `models/diffusion_models/Wan2.2-T2V-A14B-HighNoise-Q4_K_M.gguf` et
  `Wan2.2-T2V-A14B-LowNoise-Q4_K_M.gguf`, `models/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors` et
  `..._low_noise.safetensors`, `models/vae/wan_2.1_vae.safetensors` (le 14B utilise le VAE Wan 2.1) ; Maximum ajoute
  `models/upscale_models/ESRGAN/4x-UltraSharp.pth` (nodes natifs `UpscaleModelLoader`/`ImageUpscaleWithModel`).
- Précision : Wan 2.2 14B I2V (`Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf`, `...-LowNoise-...`, LoRA
  `wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors` / `..._low_noise...`, mêmes umt5 et VAE Wan 2.1) et
  Flux dev (`flux1-dev-Q4_K_S.gguf`, `text_encoders/clip_l.safetensors` et `t5xxl_fp8_e4m3fn.safetensors`,
  `vae/ae.safetensors`).
- Liste exacte par profil : `required_files` (`backend/app/providers/profiles.py`) ; un fichier absent grise la carte du
  profil (« Modèle manquant : <fichier> »).
- Lancement sur Mac (MPS) : `./run_mac.sh --port 8188` dans le dossier ComfyUI (active le venv,
  `PYTORCH_ENABLE_MPS_FALLBACK=1`, `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0`, `--force-fp16`). La carte ComfyUI de l'écran
  Providers passe à « Connecté » quand `GET /system_stats` répond.

### Choisir le profil
Le workflow n'est plus un réglage : on choisit un **profil de génération** (cartes de l'étape Clips et des Réglages,
`default_video_model`), qui fixe workflow, résolution et upscale. Catalogue, notes, benchmark du 2026-10-21 et ajout
d'un profil : `docs/profils-generation.md`. Le Wan 2.2 5B (`wan22-5b-t2v`) est retiré (benchmark : 30 min 30 s en 704x1280 natif, image
sombre et déformée).

### Comparaison historique (même prompt, 3 s, 480x832, M4 Max 36 Go, 2026-10-17 ; 5B retiré depuis)
Prompt : « a cinematic vertical shot of a red fox running through a snowy pine forest, golden hour sunlight, drifting
snow ». Clips de démonstration dans `~/Documents/projet/video_virale_demos/` (`clip-5b-480p.mp4`, `clip-14b-480p.mp4`,
`clip-14b-576p.mp4`, `clip-14b-480p-5s.mp4`).
- **5B** : couleurs très saturées (vert et bleu criards), arbres en texture « peinte », renard flou et déformé dès qu'il
  bouge, mouvement de caméra peu cohérent.
- **14B** : lumière de fin de journée réaliste (contre-jour, rayons, ombres longues bleutées), troncs et neige nets,
  traces de pas, renard anatomiquement cohérent avec une vraie démarche, poil détaillé. Défauts restants : pattes un peu
  floues dans le mouvement, caméra presque fixe, 16 fps (moins fluide que 24 fps, le montage passe en 30 fps par
  duplication d'images).
- **14B en 576x1024** : un peu plus de détail (troncs, poil), mais pas de différence nette une fois mis à l'échelle en
  1080x1920, pour 2,3 fois plus de temps : non retenu.
- Ces défauts sont traités depuis la Tâche 20A (voir « Réglages optimisés ») : prompt long avec mouvement de caméra
  explicite, upscale ESRGAN et interpolation 30 fps au montage.

### Workflow 14B T2V : `backend/workflows/comfyui-wan22-14b-t2v.json` (Rapide, Équilibré, Maximum)
Converti par script depuis le workflow « 12_WAN22-14B_t2v-qualite » de l'utilisateur (format UI → format API) :
- deux experts : `UnetLoaderGGUF` haut bruit et bas bruit (Q4_K_M), chacun suivi de `LoraLoaderModelOnly` (LoRA
  lightx2v 4 étapes, force 1) puis `ModelSamplingSD3` (shift 5) ;
- `CLIPLoader` (umt5, type `wan`) → prompt positif `{{PROMPT}}` et négatif du workflow d'origine ;
- `EmptyHunyuanLatentVideo` `{{WIDTH}}`x`{{HEIGHT}}` (9:16, résolution du profil : 320x576, 384x672 ou 480x832),
  `length` = `{{FRAMES}}` ;
- `KSamplerAdvanced` haut bruit : étapes 0 à 2 sur 4, cfg 1, `euler`/`simple`, seed `{{SEED}}`, bruit restant transmis ;
  `KSamplerAdvanced` bas bruit : étapes 2 à 4, sans ajout de bruit ;
- `VAEDecode` (VAE **Wan 2.1**) → `ImageScale` (nœud `17`, **lanczos, 720x1248**) → `VHS_VideoCombine` (**16 fps**,
  cadence native du 14B, `video/h264-mp4`, `yuv420p`, crf 19, préfixe `video_virale/wan22_14b_t2v`). Profil Maximum :
  le code (`workflows._with_esrgan`) insère `UpscaleModelLoader` + `ImageUpscaleWithModel` (**ESRGAN 4x-UltraSharp**)
  entre le décodage et `ImageScale`, puis mêle (`ImageBlend`, 50 %, `workflows.PLAIN_SHARE`) cette version à la simple
  mise à l'échelle lanczos du décodage : ESRGAN seul durcissait les contours et lissait la peau comme une peinture. Le passage à 30 fps se fait au montage (interpolation, voir `montage.md`).

### Workflow 14B I2V : `backend/workflows/comfyui-wan22-14b-i2v.json` (Précision)
Même graphe que le T2V avec les experts et LoRA I2V ; `LoadImage` (`{{IMAGE}}`, nom renvoyé par `/upload/image`) →
`WanImageToVideo` (`{{WIDTH}}`x`{{HEIGHT}}` = 384x672, `{{FRAMES}}`, `start_image`) qui fournit le latent et le
conditionnement des deux `KSamplerAdvanced` ; sortie identique (720x1248, 16 fps, préfixe `video_virale/wan22_14b_i2v`).

### Workflow Flux : `backend/workflows/comfyui-flux-keyframe.json` (image de départ de Précision)
`UnetLoaderGGUF` (`flux1-dev-Q4_K_S.gguf`), `DualCLIPLoader` (clip_l + t5xxl fp8, type `flux`), `FluxGuidance` 3,5,
`EmptySD3LatentImage` **576x1008**, `KSampler` 20 étapes, cfg 1, `euler`/`simple`, seed `{{SEED}}`, `SaveImage`
(préfixe `video_virale/keyframe`). Le même `visual_prompt` sert à l'image et à l'animation ; chaque prompt a sa
propre seed aléatoire.

### Placeholders (remplacés dans le texte du fichier avant parsing)
| Placeholder | Valeur | Notes |
|---|---|---|
| `{{PROMPT}}` | `visual_prompt` de la scène | Échappé pour une chaîne JSON (guillemets, retours à la ligne) ; inséré en dernier, donc un `{{SEED}}` écrit dans le prompt reste du texte. |
| `{{WIDTH}}`, `{{HEIGHT}}` | résolution native du profil (`Profile.width/height`) | Wan T2V et I2V seulement ; Flux est fixe (576x1008). |
| `{{FRAMES}}` | `frames_for(durée)` = `round(durée x 16) // 4 x 4 + 1`, plafonné à 81 | Nombre d'images 4n+1 attendu par Wan 2.2 14B à 16 fps : 3 s → 49, 5 s → 81 (max). |
| `{{SEED}}` | entier aléatoire dans [0, 2^32) | Nouveau à chaque prompt : deux variantes d'une scène diffèrent. |
| `{{IMAGE}}` | nom de l'image de départ dans `input/` | I2V seulement (Précision). |

Les marqueurs numériques sont écrits entre guillemets dans les fichiers (JSON valide) et deviennent des nombres JSON
(`workflows._load`). Un clip plus court que la voix est bouclé par le montage, un clip plus long est coupé.

### Temps et mémoire mesurés (M4 Max, 36 Go, ComfyUI seul, 2026-10-17)
Temps total d'un prompt (chargement des modèles compris) ; mémoire = colonne MEM de `top` pour le process ComfyUI, et
mémoire libre minimale du système (`memory_pressure`).

| Workflow | Clip | Images | Temps total | Échantillonnage | Mémoire (pic) | Libre (min) |
|---|---|---|---|---|---|---|
| 5B, 12 étapes | 3 s, 480x832 | 73 (24 fps) | ~665 s (11 min) | ~32 s/étape | ~26 Go | 26 % |
| 5B, 12 étapes | 3 s via l'application | 73 | 649 s | — | — | — |
| **14B, 4 étapes** | **3 s, 480x832** | **49 (16 fps)** | **947 s (15,8 min)** | ~214 s/étape | ~26 Go | 20 % |
| 14B, 4 étapes | 5 s, 480x832 | 81 | 2510 s (41,8 min) | ~550-600 s/étape | ~27 Go | 18 % |
| 14B, 4 étapes | 3 s, 576x1024 | 49 | 2163 s (36 min) | ~454-507 s/étape | ~24-26 Go | 20 % |

Le temps croît plus vite que le nombre de pixels ou d'images (attention) : x1,5 pixels → x2,3 temps ; 5 s au lieu de
3 s → x2,7. La mémoire du process reste sous 28 Go (échantillonnée toutes les 5 s) ; fermer les applications gourmandes
pendant la génération.

**Budget** : `CLIP_TIMEOUT_S = 5700` s par clip (environ x2 le pire cas du workflow par défaut : 5 s estimé à ~2760 s,
soit 2510 s mesurées sans upscale + ~250 s d'upscale pour 81 images). Les clips d'un projet sont générés l'un après
l'autre et le job `clips` reste plafonné à 24 h (`MAX_JOB_TIMEOUT`) : environ 78 clips de 3 s (18,4 min chacun) ou 28 de
5 s en 14B (profil Maximum). Pour un projet plus long ou plus rapide, choisir un profil plus rapide (Rapide ≈ 5 min
par clip de 3 s : environ 280 clips de 3 s en 24 h).

Montage vérifié : un clip 480x832 ou 720x1248 (16 ou 24 fps) est mis à l'échelle en 1080x1920 (recadrage d'environ
2,5 % de la largeur, ratio 0,577 contre 0,5625), passé en 30 fps (interpolé si la source est sous 24 fps) et
coupé/bouclé à la durée de la voix (test `test_render_accepts_16fps_portrait_clip`).

### Réglages optimisés (Tâche 20A, 2026-10-18)
Objectif : la meilleure image possible pour une vidéo de 30 s (10 clips de 3 s, rendu 1080x1920) avec au plus ~20 min
par clip de 3 s. Essais comparables (même prompt, même graine 123456, clips de 2 s / 33 images pour les A/B, puis
confirmation en 3 s via `ComfyUIProvider`), M4 Max 36 Go, ComfyUI 0.21.1 seul. Temps = soumission → fin, rechargement
des deux experts compris (ComfyUI les recharge à chaque prompt) ; mémoire = MEM de `top` (process ComfyUI) et mémoire
libre minimale du système. Clips et planches dans `~/Documents/projet/video_virale_demos/tuning/`.

| Essai | Réglage (le reste = workflow Tâche 18) | Clip | Temps | Mémoire (pic) | Libre (min) | Verdict |
|---|---|---|---|---|---|---|
| A1 | prompt court (19 mots, Tâche 18) | 2 s | 515 s | 21 Go | 21 % | renard minuscule, caméra fixe |
| **A2** | **prompt style Wan (101 mots, sujet + action puis caméra)** | 2 s | 539 s | 20 Go | 23 % | **renard en grand plan, travelling arrière (troncs qui défilent), anatomie nette** |
| A3 | prompt style Wan, caméra en tête (80 mots) | 2 s | 560 s | 24 Go | 19 % | proche de A2, caméra moins mobile, reflets verts parasites |
| U1 | A2 + ESRGAN 4x-UltraSharp → 720x1248 (passe séparée) | 2 s | +96 s | 11 Go | 72 % | **poil, yeux, oreilles nettement plus nets en 1080x1920, pas de scintillement** |
| B1 | A2 en 6 étapes (3+3) | 2 s | 771 s (+43 %) | 23 Go | 23 % | quasi identique à A2 : non retenu |
| B2 | A2 avec shift 8 (au lieu de 5) | 2 s | 545 s | 21 Go | 27 % | quasi identique (un peu moins de flocons) : non retenu |
| B3 | A2 en 544x960 | 2 s | 825 s (+53 %) | 24 Go | 19 % | autre cadrage, pas plus net que 480 + ESRGAN : non retenu |
| **C1** | **workflow retenu (prompt A2, graine aléatoire) via `ComfyUIProvider`** | **3 s** | **1106 s (18,4 min)** | **26 Go** | **20 %** | **net (poil, pattes, traces), travelling, 720x1248 16 fps, 49 images** |
| Tâche 18 | référence : prompt court, sans upscale | 3 s | 947 s | 26 Go | 20 % | pattes floues, caméra quasi fixe |

Montage (FFmpeg, même machine) : passage 16 → 30 fps par `minterpolate` (compensation de mouvement) ≈ 8 s pour un
clip de 3 s en 720x1248 (6,5 s pour 2 s ; 16 s pour 2 s si la source était en 1080x1872, d'où la sortie ComfyUI en
720x1248) ; aucun fantôme visible sur les pattes. La simple duplication d'images (avant) prend ~0,5 s mais saccade.

**Réglages retenus** : 14B Q4_K_M + LoRA lightx2v (force 1), 4 étapes (2 haut bruit + 2 bas bruit), cfg 1,
`euler`/`simple`, shift 5, 480x832, 49 images à 16 fps pour 3 s, négatif officiel Wan (chinois), puis ESRGAN
4x-UltraSharp ramené en 720x1248, et interpolation 30 fps au montage. **Temps attendu : ~18,5 min par clip de 3 s,
~3 h 05 pour 10 clips** (+ ~1,5 min de montage).

Non retenus / non testés :
- plus d'étapes, autre shift, résolution plus haute : gain invisible pour +43 à +53 % de temps ;
- cfg > 1 : avec la LoRA lightx2v (distillée pour cfg 1), cfg > 1 double le coût de chaque étape (passe négative)
  et sort du budget ; non testé faute de temps ;
- interpolation dans ComfyUI : le node natif `FrameInterpolate` existe mais `models/frame_interpolation/` est vide
  (RIFE/FILM à télécharger) ; `latent_upscale_models/` est vide aussi ;
- 4 s (65 images) : non mesuré ; d'après les mesures 3 s → 947 s et 5 s → 2510 s (attention quadratique), 4 s
  coûterait ~1600-1700 s + upscale, soit ~30 min : 8 clips de 3,75 s (~4 h) coûtent plus que 10 clips de 3 s (~3 h).
  Pour 30 s, préférer 10 scènes de 3 s.

### Style de prompt (Wan 2.2)
Le LLM écrit `visual_prompt` selon `VISUAL_PROMPT_GUIDE` (`services/prompts.py`, partagé par l'étape script, le chat du
plan et l'assistant IA) en **deux paragraphes**, car trois modèles le lisent (`providers.base.split_prompt`) :
1. l'image de départ, en anglais, 80 à 130 mots : sujet dans sa pose de départ, décor, lumière, style d'image **de la
   fiche visuelle** (le guide n'impose plus « photorealistic, cinematic » : le style vient du projet, `services/styles.py`,
   injecté aussi dans l'assistant IA et les images de référence) ; autonome, personnages et marques redécrits mot pour mot ;
2. `Motion: …`, 30 à 60 mots : le sujet en quelques mots, son action en 2 ou 3 gestes enchaînés décrits par ce qu'on voit,
   puis une **phrase de caméra explicite** (« low-angle tracking shot, the camera smoothly dollies backward following the
   subject », « slow dolly in », « slow pan left »).

Qui lit quoi : Flux et Kontext (image fixe) lisent le paragraphe 1 seul, la caméra leur est inutile ; Wan I2V (animation
d'une image fournie) lit `Motion:` seul, redécrire l'image concurrence l'image ; Wan T2V et fal lisent les deux, sans
l'étiquette (`plain_prompt`). Un prompt sans `Motion:` (anciens projets, saisie manuelle) sert partout tel quel, comme
avant. Logos décrits par forme/couleur/emplacement, jamais par leurs lettres (Wan ne sait pas écrire) ; aucune négation
dans le prompt anglais (le négatif est mort à cfg 1) ; règles de composition du benchmark des profils (sujet de taille
modérée avec de la marge, action décrite par ce qu'on voit, intérieur/extérieur séparés : `docs/assistant-ia.md`).
**À valider en A/B** (`backend/scripts/bench_comfy.py`) : la découpe I2V « Motion seul » n'est pas encore mesurée sur cette
machine. Exemple mesuré (A2/C1, avant les règles de composition) :

> A red fox runs through a snowy pine forest toward the camera, its paws kicking up bursts of powdery snow, thick orange
> fur ruffled by the cold wind. Low-angle tracking shot: the camera smoothly dollies backward at ground level, keeping
> the fox centered as the pine trunks slide past on both sides. Golden hour sunlight streams between the trees, warm rim
> light on the fur, long blue shadows across the snow, sparkling snowflakes drifting in the air. Shallow depth of field,
> sharp focus on the fox's face and legs, natural colors, realistic wildlife documentary, cinematic 35mm film look,
> vertical 9:16 composition.

Le négatif reste celui recommandé par Wan (en chinois, dans le workflow) : couleurs criardes, surexposition, image
statique, flou, sous-titres, mains/visages déformés, membres en trop, arrière-plan encombré, marche à reculons, etc.

### Utiliser ComfyUI dans l'application
Écran Réglages : carte ComfyUI (URL), puis « Profil vidéo proposé à l'étape Clips » (cartes : Rapide par défaut). À
chaque lancement de l'étape Clips, le profil se choisit sur les mêmes cartes, pour toutes les scènes ou une seule
(`docs/profils-generation.md`).
