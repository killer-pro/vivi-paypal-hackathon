# Profils de génération vidéo

Le modèle vidéo d'un lancement de l'étape Clips se choisit sur des **cartes** : profils ComfyUI locaux (notés) et
modèles cloud fal (facturés). Données : `GET /api/providers/models`, clé `video` (liste de cartes, voir
`docs/settings-providers.md`) ; refus au lancement d'un modèle inconnu (`400`) ou indisponible (`409`, raison affichée
dans le pied du panneau comme toute erreur d'API). Même contrôle pour l'autopilot (`launch_step`,
`services/video_models.py`) : il s'arrête avant les clips, l'étape en `failed` avec la raison.

## Catalogue (`backend/app/providers/profiles.py`)
Un profil = id (le `model` du provider `comfyui`), nom, description, notes vitesse et qualité (1 à 5, demi-étoiles),
durée indicative d'un clip de 3 s (M4 Max 36 Go, RAM libérée), résolution native, ESRGAN oui/non, image de départ
oui/non. Toutes les sorties finissent en `ImageScale` lanczos **720×1248** à 16 fps (49 images pour 3 s) : le montage en
dépend. Une seed aléatoire par prompt, un seul ComfyUI, clips générés l'un après l'autre.

| Id | Nom | Workflow | Vitesse | Qualité | Durée / clip de 3 s |
|---|---|---|---|---|---|
| `fast` | Rapide (recommandé, défaut) | Wan 2.2 14B T2V, 320×576 | 4 | 3,5 | ≈ 5 min |
| `balanced` | Équilibré | Wan 2.2 14B T2V, 384×672 | 3 | 4 | ≈ 7 min 30 s |
| `precision` | Précision | Flux dev (image 576×1008) puis Wan 2.2 14B I2V 384×672 | 2 | 5 | ≈ 11 min |
| `max` | Maximum | Wan 2.2 14B T2V, 480×832 + ESRGAN 4x-UltraSharp | 1 | 5 | ≈ 18 min |

- Défauts : `default_video_provider = comfyui`, `default_video_model = fast` (`DEFAULT_PROFILE`, `app_settings.py`) ;
  ce profil est le seul `recommended: true` de `GET /providers/models` (`services/video_models.py`).
- Ancien modèle `workflow` (projets et réglages d'avant les profils) : exécuté comme `max` (`LEGACY_NAMES`). Le réglage
  `default_video_model` est lu et écrit `max` par `AppSettings` (`RENAMED`) : `GET /api/settings`, les lancements et
  les Réglages de l'admin voient `max` ; la ligne en base est réécrite au prochain enregistrement de ce réglage.
- Workflows : un JSON par type de graphe dans `backend/workflows/` (T2V, I2V, Flux), paramétrés par
  `providers/workflows.py` ; détail des graphes et fichiers de modèles requis : `docs/providers.md`.
- Précision : l'image Flux est conservée comme asset `keyframe` (`meta.clip_asset_id` = id du clip, coût 0), visible en
  `poster` de la variante. Elle n'est pas validée avant l'animation (image puis vidéo dans le même job). Si l'animation
  échoue sur une erreur relançable (HTTP 5xx/429 de ComfyUI), la nouvelle tentative automatique (`tracked_call`) reprend
  l'image déjà produite au lieu de refaire Flux (≈ 2 min) ; cette image vit avec le provider (une instance par job,
  un clip ComfyUI à la fois) et est oubliée dès le clip réussi ; un « Relancer » manuel (nouveau job) refait l'image.
- Image de départ envoyée à ComfyUI sous un nom fixe, `vv_keyframe.png` (`overwrite`), réécrite à chaque run : un seul
  fichier dans `input/`. `LoadImage` hache le fichier (`IS_CHANGED`, sha256) : pas d'image périmée servie depuis le
  cache. Un verrou (`_keyframe_slot()`, `comfyui.py`, un par boucle d'événements) garde l'envoi et l'animation ensemble : deux jobs Précision
  simultanés (worker `max_jobs = 2`) ne s'écrasent pas l'image (suppose un seul worker par ComfyUI).
- Anciens fichiers `vv_keyframe_<uuid>.png` laissés par les runs d'avant ce nom fixe : à supprimer une fois,
  `find <dossier ComfyUI>/input -name 'vv_keyframe_*.png' -delete` (ne touche pas `vv_keyframe.png`).
- Disponibilité : carte grisée (`available: false`, `409` au lancement) si ComfyUI refuse la connexion ou si son URL
  est invalide (« ComfyUI injoignable ») ou si un fichier de `required_files` manque (« Modèle manquant : <fichier> ») ;
  modèles fal grisés « Clé API fal manquante, à saisir dans Réglages → fal.ai » sans clé.
- ComfyUI qui ne répond pas en 3 s, tout l'appel compris (ex. longue génération avec swap saturé) : **occupé, pas en
  panne**. La carte reste `available: true` avec la raison « ComfyUI ne répond pas (occupé ?) » ; le lancement (API,
  autopilot, admin) est accepté et le job attend son tour. Une seule source (`Availability`) pour la carte et le
  contrôle au lancement : ils ne peuvent pas diverger.

## Image de référence (tous les profils)
Une image par élément récurrent du script, choisie par scène : `docs/references.md`.

Si le projet a une image de référence (étape facultative), **chaque scène part d'elle**, quel que soit le profil : Flux
Kontext la replace dans la scène (mêmes personnages, mêmes marques), puis Wan 2.2 I2V l'anime à la résolution du profil
(ESRGAN compris pour Maximum). Sans référence, rien ne change : texte seul (Rapide, Équilibré, Maximum) ou image Flux dev
inventée par scène (Précision). C'est l'app qui choisit le graphe selon l'entrée (`ComfyUIProvider.generate`), l'utilisateur
ne choisit que le profil. Coût en temps : + l'image Kontext (≈ 5 min par scène : 293 s mesurées le 2026-10-22, M4 Max, canette rouge replacée dans une rue de nuit, même objet conservé) sur les durées ci-dessus.
Lancement refusé (`409`) si un fichier manque pour ce mode (`reference_availability` : Wan I2V, Kontext). Point

### Image de départ composée par Gemini (option avancée)
Au lieu de Kontext, **Gemini** peut composer l'image de départ des scènes qui ont des images de référence : les images
d'entrée (la principale d'abord, puis les autres éléments de la scène, 2 au plus comme pour Kontext) partent avec le
même prompt d'édition (`KONTEXT_PREFIX` + paragraphe image, sans « Motion: ») à `GeminiImage.generate(references=…)`
(modèle `gemini_image_model`, 9:16). Wan I2V anime ensuite cette image telle quelle (`ComfyUIProvider.generate(start_image=…)`
saute Kontext) ; elle est conservée comme `keyframe` du clip.
- **Préférence** : réglage `start_image_provider` (`comfyui` = Kontext, par défaut ; `gemini`), écran Providers.
  **Choix par lancement** : Avancé du panneau Clips (`params.start_image` de l'étape, ou `start_image` d'un lancement de scène) ;
  vide = la préférence. Sans effet hors ComfyUI (fal anime sa propre image) et pour une scène sans image de référence.
- Coût : un appel Gemini par scène (≈ 0,08 $ estimé : `estimate_image_cost`, 1290 jetons de sortie au prix du modèle),
  ajouté à l'estimation du lancement (budget) et journalisé (`provider_calls`, étape `clips`, provider `gemini`).
  Lancement refusé (`409`) sans clé Gemini. Un refus de Gemini (sécurité) fait échouer la scène avec son message ; la reprise
  (`resume`) refait les scènes manquantes, sans repli automatique sur Kontext.
- Pas de Kontext : plus de temps GPU par image, mais l'image arrive en ~768×1376 et Wan I2V la met à l'échelle de son profil
  (graphe `ImageScale`). Qualité comparée à Kontext : à juger sur un projet réel (non mesurée).
d'accroche d'une offre payante : `VideoProvider.reference_availability` / le choix `image is not None` dans `generate`.

## Benchmark du 2026-10-21 (source des notes)
Clip de 3 s (49 images à 16 fps), sortie 720×1248, M4 Max 36 Go, RAM libérée, même prompt (poulpe dans un bocal),
même seed ; script `backend/scripts/bench_comfy.py` (variantes B, C, H, I, D, F, G).

| Config | Temps | Observation |
|---|---|---|
| 14B 480×832 + ESRGAN (Maximum) | 17 min 40 s | référence |
| 14B 480×832 sans ESRGAN | ≈ 15 min 30 s (déduit : −126 s) | même clip |
| 14B 384×672 (Équilibré) | 7 min 34 s | très proche de la référence |
| 14B 320×576 (Rapide) | 4 min 44 s | bonne |
| Flux (image, 2 min 42 s) puis Wan I2V 384×672 (8 min 30 s) (Précision) | 11 min 11 s | le plus net, cadrage visible sur l'image intermédiaire |
| 14B 480×832 avec NAG (prompt négatif actif) | 27 min | aucun gain visible |
| Wan 5B natif 704×1280 | 30 min 30 s | sombre, déformé : écarté |
| LTX-Video 2B distillé | 48 s | rendu « pâte à modeler » : écarté |
| Wan 1,3B | 21 min 40 s | inutilisable : écarté |

Limites : **une seule scène et une seule seed**, jugées sur des planches de 5 images ; les notes sont donc indicatives.
Le prompt négatif est sans effet à cfg 1 (LoRA 4 pas) ; NAG le rend actif mais double le temps : non retenu.

**Déchargement (2026-10-23)** : `ComfyUIProvider._free()` (`POST /free`, best-effort) est appelé après chaque workflow ; premier relevé : scène avec référence en 690 s contre 1517 s avant (prompts différents, une mesure chacune : à confirmer).

**La RAM libre est le facteur n°1 de la durée** : la même config Maximum a pris 45 min avec le swap saturé, contre
17 min 40 s RAM libérée. Fermer les applications gourmandes avant une génération locale ; `GET :8188/system_stats`
(`ram_free`) donne la mémoire libre vue par ComfyUI.

### Vérification dans l'application (2026-10-21, `POST …/steps/clips/run`)
Même machine, même scène (poulpe, prompt rédigé selon les règles de composition), ComfyUI 0.21.1, **RAM non libérée** :
`ram_free` de ComfyUI 14,2 Go au lancement (sur 38,7 Go), 4,4 à 7 Go pendant la génération, swap monté jusqu'à
≈ 17 Go (navigateur, Docker et autres applications ouverts). Temps ComfyUI (`execution_start` → `execution_success`)
et durée du job Arq :

| Profil | ComfyUI | Job | Sortie (`ffprobe`) |
|---|---|---|---|
| Rapide (`fast`) | 330,8 s (5 min 31 s) | 333 s | h264 720×1248, 16 fps, 49 images, 3,06 s |
| Précision (`precision`) | Flux 140,4 s + I2V 535,5 s = 675,9 s (11 min 16 s) | 679 s | h264 720×1248, 16 fps, 49 images, 3,06 s ; image `keyframe` PNG 576×1008 |

Conformes aux durées annoncées (≈ 5 min, ≈ 11 min) malgré le swap (Maximum n'a pas été relancé ici). L'asset `keyframe` (`meta.clip_asset_id` = id du clip) est bien
servi en `poster` de la variante Précision dans l'étape Clips.

## Comment ajouter un profil
1. Ajouter un `Profile(...)` dans `PROFILES` (`backend/app/providers/profiles.py`), à sa place dans l'ordre d'affichage
   (l'API et les cartes suivent cet ordre) : id stable (il est enregistré dans `params` des étapes et dans
   `default_video_model`), notes et durée **mesurées** (script de benchmark, RAM libérée), résolution native 9:16
   (multiples de 16).
2. Réutiliser un workflow existant (`t2v`, `i2v` + `keyframe`) en jouant sur `width`, `height`, `esrgan`, `keyframe` ;
   un nouveau type de graphe = un nouveau `backend/workflows/comfyui-<nom>.json` (format API, marqueurs `{{PROMPT}}`,
   `{{SEED}}`, `{{FRAMES}}`, `{{WIDTH}}`, `{{HEIGHT}}`, sortie `ImageScale` 720×1248) et sa fonction dans
   `providers/workflows.py`, branchée dans `ComfyUIProvider.generate`.
3. Déclarer ses fichiers de modèles dans `required_files` (nœud chargeur, entrée, nom exact vu par ComfyUI) : c'est ce
   qui grise la carte si un fichier manque.
4. Tests : `tests/test_profiles.py`, `tests/test_workflows.py` (graphe produit), `tests/test_providers_http.py`.
5. Profil **recommandé** (pastille, repli de `pickable`, défaut des réglages) : changer `DEFAULT_PROFILE`
   (`profiles.py`) suffit, l'API le désigne par `recommended: true` sur sa carte et l'admin suit ce champ.

## Cartes (`admin/src/components/ModelCards.tsx`, styles `ModelCards.css`)
- Groupe radio accessible : `role="radiogroup"` libellé, une carte = `<label>` autour d'un `<input type="radio">` natif
  (flèches du clavier, focus visible sur toute la carte via `:has(input:focus-visible)`).
- Regroupées par provider (ComfyUI d'abord, groupe de la carte recommandée, puis fal.ai), dans l'ordre de l'API.
- Contenu : nom, pastille « recommandé » (carte `recommended` de l'API : Rapide), durée ou coût par clip, étoiles de
  vitesse et de qualité (lues « 3,5 sur 5 » par un lecteur d'écran, « non noté » pour un modèle cloud), description.
- Carte indisponible : radio `disabled`, nom et étoiles estompés, « Indisponible : <raison> » en clair (ex. « Clé fal
  manquante », « ComfyUI injoignable », fichier de modèle manquant).
- Carte disponible avec une raison (ComfyUI occupé) : choisissable et lançable, avertissement « Attention : <raison>.
  La génération attendra son tour. » en couleur d'attente (`cardNotice`, `models.ts`).
- Carte choisie : bordure accent et fond `--raised`. Cartes empilées (une colonne) dans le panneau, sur plusieurs
  colonnes dans Réglages (`.provider-defaults .model-group`), une colonne sous 300 px.

## Logique (`admin/src/models.ts`, testée par `models.test.ts`)
- `stars(note)` : « ★★★½☆ » (demi-étoile), `null` → « non noté ».
- `clipCost(carte)` : « ≈ 7 min 30 s par clip » (local) ou « ≈ 0,28 $ par clip » (cloud).
- `totalEstimate(carte, scènes)` : « ≈ 45 min pour 6 scènes » (ou le coût total pour le cloud).
- `pickable(cartes, choix)` : garde un choix disponible ; sinon (ancien modèle `workflow`, carte grisée, modèle inconnu)
  la carte recommandée si elle est disponible, sinon la première disponible ; sans carte disponible, le choix est inchangé.
- `cardNotice(carte)` : « Indisponible : <raison> » (carte grisée), « Attention : <raison>. La génération attendra son
  tour. » (carte disponible avec une raison), `null` sans raison.
- `launchBlocked(cartes, erreur, choix)` : raison d'empêcher un lancement (« Chargement des modèles vidéo… », « Chargement
  des réglages… », chargement en erreur, modèle inconnu, carte indisponible avec sa raison), `undefined` sinon.

## Étape Clips (`components/panels/ClipsPanel.tsx`)
- « Profil de génération, toutes les scènes » en tête du panneau ; « Avancé » : « Nouvelle variante, scène N » (choix
  propre à la scène, non enregistré). Les deux passent par `pickable`.
- Ligne d'estimation : « Durée estimée : ≈ 50 min pour 10 scènes » pour un profil local, coût `/estimate` pour le cloud.
- Pas de lancement avant le chargement de `/providers/models` (et de `/settings` si l'étape n'a pas de choix
  enregistré) ni sans carte disponible : « Générer les clips », « Générer les N clips manquants », « Relancer » /
  « Reprendre » / « Tout régénérer », « Nouvelle variante » et « Régénérer » de la scène sont désactivés, la raison
  (`launchBlocked`) affichée en clair sous les boutons ; `/estimate` n'est appelé qu'avec un choix lançable
  (`useApi(null)` : aucun appel).
- Le brouillon du prompt d'une scène est indépendant du profil : en changer ne le perd pas. Bouton « Valider et
  régénérer » si le brouillon diffère du prompt enregistré, « Régénérer avec le même prompt » sinon.
- Variante produite par un profil à image de départ (Précision) : l'asset `keyframe` dont `meta.clip_asset_id` vaut l'id
  du clip sert de `poster` à la vidéo.

## Réglages (`pages/Providers.tsx`)
« Profil vidéo proposé à l'étape Clips » : mêmes cartes ; choisir une carte règle `default_video_provider` et
`default_video_model`. Le champ « Workflow » de ComfyUI n'existe plus (réglage `comfyui_workflow_path` supprimé).
