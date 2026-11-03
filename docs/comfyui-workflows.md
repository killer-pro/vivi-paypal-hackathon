# Workflows ComfyUI (référence pour repartir de zéro)

Tout ce qu'il faut pour reconstruire la génération locale sur un Mac neuf : installation, modèles, les quatre graphes
livrés, et les pièges rencontrés. Les profils (ce que voit l'utilisateur) sont décrits dans `profils-generation.md`,
le branchement côté API dans `providers.md`.

## Installation
- ComfyUI : `/Users/mouhamadoudioufcisse/Documents/projet/stabledifusion/ComfyUI` (v0.21.1, `venv/` Python dédié),
  lancé par `npm run comfy` (`COMFYUI_DIR` pour un autre dossier) : `main.py --listen 127.0.0.1 --port 8188`. Intégré à
  `npm run dev`. L'URL se règle dans Réglages (`comfyui_url`).
- Nœuds personnalisés (`custom_nodes/`) : **ComfyUI-GGUF** (`UnetLoaderGGUF`, modèles quantifiés) et
  **ComfyUI-VideoHelperSuite** (`VHS_VideoCombine`, écriture du MP4). Rien d'autre.
- Nœuds natifs utilisés : `WanImageToVideo`, `EmptyHunyuanLatentVideo` (graphe T2V), `KSamplerAdvanced`,
  `ModelSamplingSD3`, `LoraLoaderModelOnly`, `FluxGuidance`, `ReferenceLatent`, `ConditioningZeroOut`,
  `EmptySD3LatentImage`, `LoadImage`, `ImageScale`, `UpscaleModelLoader`/`ImageUpscaleWithModel`.

## Fichiers de modèles (`ComfyUI/models/…`)
| Dossier | Fichier | Sert à |
|---|---|---|
| `diffusion_models` | `Wan2.2-T2V-A14B-{High,Low}Noise-Q4_K_M.gguf` | vidéo depuis le texte (Rapide, Équilibré, Maximum) |
| `diffusion_models` | `Wan2.2-I2V-A14B-{High,Low}Noise-Q4_K_M.gguf` | vidéo depuis une image (Précision, et tout profil avec une image de référence) |
| `diffusion_models` | `flux1-dev-Q4_K_S.gguf` | image de départ du profil Précision |
| `diffusion_models` | `flux1-kontext-dev-Q4_K_S.gguf` (6,8 Go) | image de départ quand une image de référence existe ; source : `huggingface.co/bullerwins/FLUX.1-Kontext-dev-GGUF` |
| `loras` | `wan2.2_{t2v_lightx2v_4steps_lora_v1.1,i2v_lightx2v_4steps_lora_v1}_{high,low}_noise.safetensors` | LoRA « lightx2v » : 4 étapes de diffusion au lieu de 20+ |
| `text_encoders` | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | texte → Wan |
| `text_encoders` | `clip_l.safetensors`, `t5xxl_fp8_e4m3fn.safetensors` | texte → Flux / Kontext |
| `vae` | `wan_2.1_vae.safetensors` (Wan), `ae.safetensors` (Flux) | décodage |
| `upscale_models/ESRGAN` | `4x-UltraSharp.pth` | agrandissement du profil Maximum |

Présents mais non utilisés : `wan2.2_ti2v_5B_fp16.safetensors` + `wan2.2_vae.safetensors` (Wan 5B, écarté au benchmark :
sombre et déformé), `flux1-dev-fp8.safetensors`. La liste exigée par profil est dans `providers/profiles.py`
(`required_files`) : une carte est grisée « Modèle manquant : … » si un fichier manque.

## Les graphes (`backend/workflows/*.json`, format API, marqueurs `{{…}}`)
Un JSON par type de graphe, jamais une copie par profil ; `providers/workflows.py` remplace `{{WIDTH}}`, `{{HEIGHT}}`,
`{{FRAMES}}`, `{{SEED}}`, `{{PROMPT}}`, `{{IMAGE}}` (et insère ESRGAN pour Maximum, mêlé à 50 % à un agrandissement lanczos simple pour garder des textures naturelles).

1. **`comfyui-wan22-14b-t2v.json`** — texte → vidéo. Deux modèles Wan (bruit fort puis faible) avec LoRA lightx2v,
   `ModelSamplingSD3` shift 5, `KSamplerAdvanced` en deux passes de 4 étapes (0→2 puis 2→fin), cfg 1, euler/simple.
   Sortie `ImageScale` lanczos 720×1248, `VHS_VideoCombine` 16 fps h264.
2. **`comfyui-wan22-14b-i2v.json`** — image → vidéo. Même squelette, modèles I2V, `WanImageToVideo` reçoit
   `start_image` (`LoadImage`, recadrée au centre à `WIDTH×HEIGHT`). Le prompt décrit le mouvement, l'image fixe le sujet.
3. **`comfyui-flux-keyframe.json`** — Flux dev, texte → image 576×1008 (20 étapes, `FluxGuidance` 3,5). Alimente le
   profil Précision : une image différente par scène, tirée du seul prompt.
4. **`comfyui-flux-kontext.json`** (dès qu'il y a une image de référence, tout profil) — **l'image de référence replacée dans la scène**. `LoadImage`
   (référence) → `ImageScale` 576×1008 (recadrage centré) → `VAEEncode` → `ReferenceLatent` sur le conditionnement du
   prompt → `FluxGuidance` 2,5 ; négatif = `ConditioningZeroOut` ; `KSampler` 20 étapes, cfg 1, depuis un
   `EmptySD3LatentImage` 576×1008. Le prompt est préfixé (`KONTEXT_PREFIX`) : « garde exactement le même personnage,
   tenue, produit et logo ; montre-les dans cette scène : … ». Sa sortie est l'image de départ du graphe 2.

## Chaînes par profil (choisies par l'app selon l'entrée)
| Profil | Sans image de référence | Avec image de référence |
|---|---|---|
| Rapide, Équilibré, Maximum | graphe 1 (texte → vidéo) | graphe 4 (référence → image de la scène) → graphe 2 |
| Précision | graphe 3 (Flux dev, image inventée) → graphe 2 | graphe 4 → graphe 2 |

Fichiers exigés en plus avec une référence : Wan I2V (+ LoRA I2V) et Kontext (`required_files(profile, reference=True)`).

## Pièges connus
- `LoadImage` hache le contenu du fichier : réécrire le même nom ne sert jamais une image périmée. Les deux fichiers
  d'entrée ont un nom fixe (`vv_keyframe.png`, `vv_reference.png`), écrasés à chaque run, sous un verrou commun
  (`_keyframe_slot`) pour que deux jobs ne se marchent pas dessus (un seul worker par ComfyUI).
- Wan veut `4n+1` images, 5 s au plus (81 images à 16 fps). Si la voix est plus longue que le clip, elle est **accélérée**
  (jusqu'à ×1,25, hauteur conservée) pour tenir dans le clip ; au-delà, la dernière image est tenue. Le montage ne boucle
  jamais un clip ; le script limite les scènes à 5 s.
- La mémoire : un seul clip à la fois (`CLIP_CONCURRENCY["comfyui"] = 1`), RAM libérée avant un lancement (36 Go).
- Temps indicatifs (M4 Max) : voir le benchmark de `profils-generation.md`. Avec référence : Kontext ≈ 5 min (293 s mesurées, image 576×1008) + I2V ≈ 8 min 30 s
  par clip de 3 s. Test Kontext validé le 2026-10-22 : la canette rouge de référence est reconnue et replacée dans une rue de nuit.
- Ajouter un workflow : déposer le JSON dans `backend/workflows/`, une fonction dans `providers/workflows.py`, un profil
  dans `providers/profiles.py` (+ `required_files`), puis mettre à jour ce fichier et `profils-generation.md`.
