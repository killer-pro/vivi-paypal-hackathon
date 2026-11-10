# Avatar parlant (lip-sync)

Un personnage s'adresse au spectateur face caméra, et sa bouche suit sa voix ElevenLabs. Le mode se choisit par projet
(`Project.lipsync`, migration `0021`). Le modèle est un réglage global (`lipsync_model`). La génération passe toujours
par Comfy Cloud, car ces modèles n'existent pas dans notre ComfyUI local.

## Quelles scènes parlent
`services/lipsync.py`, `talks(project, scene)` : une scène parle quand le mode est actif, qu'un personnage dit sa voix
off (`Scene.speaker`, voir `story.md`) et qu'il est visible dans la scène (sujet principal `reference` ou élément de
`elements`). Une scène peut en sortir avec la case « Parle face caméra » (`Scene.lipsync`, migration `0022`,
`PUT /projects/{id}/scenes/{scene_id}/lipsync` `{"lipsync": false}`). Elle devient alors un clip animé ordinaire, avec
la voix du personnage hors champ : utile pour un effet ou un mouvement que le lip-sync ne sait pas rendre, car il n'anime
que le visage (exemple : un personnage qui se forme à partir de particules de lumière). Les autres scènes (narrateur,
personnage hors champ, scène sortie) restent des clips ordinaires, générés avec le profil choisi. `GET /projects/{id}`
donne pour chaque scène `on_screen` (personnage qui parle visible) et `lipsync`.

En mode avatar parlant, le script prépare ces scènes (`prompts.py`) :
- l'inventaire (`LIPSYNC_INVENTORY`) demande que le personnage qui parle soit visible dans chacun de ses beats ;
- le prompt de scène (`LIPSYNC_SCENE`) le cadre en plan taille, mains et décor visibles, visage de face, bouche
  visible, regard caméra, avec une émotion nette, des gestes de mains amples et une caméra lente. Un plan rapproché
  poitrine et caméra fixe donnaient un avatar statique, sans gestes (retour de la promo Vivi).

Les balises d'émotion ElevenLabs (`[excited]`, `[laughs]`…, voir `providers.md`) rendent la voix plus vivante, et le
lip-sync suit le rire ou le chuchotement joué.

Changer le mode rend périmées les étapes clips, montage et final, mais pas l'histoire. Pour des prompts cadrés face
caméra, il faut réécrire le plan.

## Génération (étape clips)
Pour une scène qui parle, l'étape clips :
1. prend la **voix** de la scène, c'est-à-dire la dernière si elle dit le même texte avec la même voix
   (`voice_matches` lit `meta.text` et `meta.voice_id`, désormais enregistrés sur chaque voix). Sinon, elle en
   synthétise une nouvelle, facturée sous l'étape clips et rangée parmi les voix de la scène ;
2. compose l'**image de départ** comme pour un clip : Gemini si c'est le générateur choisi, sinon Flux Kontext avec la
   référence du personnage, sinon Flux dev depuis le prompt ;
3. appelle `ComfyCloudProvider.talk` avec le graphe `backend/workflows/comfyui-talk-<modèle>.json`, l'image et la voix
   envoyées sous des noms uniques. Durée de la vidéo = durée de la voix + `PAD_S` ;
4. stocke le clip avec `meta.voice_asset_id` (la voix utilisée) et `meta.lipsync` (le modèle). L'admin affiche
   « (lip-sync) » sur la variante.

Une seule passe couvre la voix : un test de 8 s n'a montré aucune dérive du visage (S2V et InfiniteTalk, 2026-11-09).

## Modèles (`TALK_MODELS`, `providers/profiles.py`)
| id | Modèle | Sortie | GPU par seconde de voix | Constat du test |
|---|---|---|---|---|
| `s2v` (défaut) | Wan 2.2 S2V 14B fp8 | 480×832, 16 i/s | ≈ 6,5 s | le plus rapide et le moins cher, bouche bien articulée |
| `infinitetalk` | InfiniteTalk (Wan 2.1 I2V 480p) | 480×832, 25 i/s | ≈ 13,5 s | expressions les plus vivantes |
| `ltx` | LTX-2.3 22B, image + audio | 704×1280, 24 i/s | ≈ 9 s | image la plus nette, bouche moins marquée |

Coût de revient : `cloud_talk_usd` (image de départ ≈ 20 s de GPU, plus la voix × le taux du modèle), auquel s'ajoute
la voix (`TALK_VOICE_USD`) dans le devis de l'étape (`clip_scene_costs_usd`). Exemple : une voix de 4 s en S2V coûte
≈ 0,025 $.

Les graphes viennent des modèles officiels de ComfyUI (`video_wan2_2_14B_s2v`, `video_wan2_1_infinitetalk`,
`video_ltx2_3_ia2v`), convertis au format API et réduits à un seul locuteur et une seule passe. Marqueurs : `{{IMAGE}}`,
`{{AUDIO}}`, `{{PROMPT}}`, `{{SEED}}`, `{{WIDTH}}`, `{{HEIGHT}}`, `{{FRAMES}}` (4n + 1 images à la cadence du modèle,
`talk_frames`), `{{DURATION}}` (LTX).

Voix enregistrée (wolof, comédien) : importée dans l'étape Voix, c'est elle que l'avatar prononce (`voix-importees.md`).

Changer de modèle lip-sync en gardant les images validées : lancer les clips avec `reuse_start_image` (API) ; chaque scène repart de l'image de départ de son clip choisi, sans repayer Kontext (environ 20 s de GPU par clip), et la nouvelle variante garde cette même image.

## Montage
Un clip qui porte `meta.voice_asset_id` est monté avec **cette** voix, même si une autre a été générée depuis.
Le segment est `synced` : ni la voix ni le clip ne changent de vitesse (pas de `converge`), et la scène dure le temps de
la voix plus la marge.

## Retouche d'un clip lip-sync
Un clip lip-sync peut être retouché hors de l'app à la même durée : écran d'application incrusté, plan de coupe,
coupes franches entre plusieurs plans lip-sync (ex. compter sur ses doigts, que le modèle ne sait pas caler sur un mot).
L'import avec `retouches` (`upload-clip`, case « Importer comme retouche du clip lip-sync choisi » sous « Importer une
vidéo » quand le clip choisi est lip-sync) garde la voix du clip d'origine : le montage la cale sans changer de vitesse.
Sans cette case, la variante importée est montée comme un clip ordinaire (`converge` change la vitesse de la voix et
décale les lèvres).

## Interface
- **Nouvelle vidéo** : choix « Format » entre Voix off et Avatar parlant.
- **Étape Clips** : case « Avatar parlant » (`PATCH /projects/{id}` `{"lipsync": …}`). Dans le détail d'une scène où le
  personnage qui parle est visible, case « Parle face caméra ».
- **Réglages**, Choix par défaut : liste « Avatar parlant (lip-sync, Comfy Cloud) ».

## Limites
- Il faut une clé Comfy Cloud avec un abonnement payant. Sans elle, l'étape clips échoue sur la scène qui parle, avec
  le message de clé manquante.
- Les encodeurs audio sont entraînés en anglais (S2V) ou en chinois (InfiniteTalk) ; le français est passé au test.
- Un personnage par scène ; le mode « deux locuteurs » d'InfiniteTalk n'est pas branché.
