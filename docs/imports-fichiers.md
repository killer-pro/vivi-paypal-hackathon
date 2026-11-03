# Imports de fichiers (clips, musiques)

Fichiers envoyés depuis l'admin : variante de clip importée (`POST /api/projects/{id}/scenes/{scene_id}/upload-clip`)
et piste de musique (`POST /api/music`). Code commun : `backend/app/uploads.py`.

## Règle : rien du client dans la clé de stockage
- **Clé générée par le serveur** : `projects/{id}/clip/<32 hex>.<ext>` (clip) ou `music/<32 hex>.<ext>` (musique),
  nom aléatoire `uuid4().hex`. Le nom de fichier du client n'entre jamais dans une clé, un chemin ni un en-tête
  (le téléchargement `…/assets/{id}/download` nomme le fichier `vivi-{id}.<ext>`, `<ext>` tiré du type MIME de
  l'asset par `DOWNLOAD_EXTENSIONS`, `bin` pour un type inconnu : jamais la clé, qu'un ancien import tenait du client).
- **Extension d'une liste fermée** (`UploadKind`), en minuscules, qui donne aussi le type MIME enregistré ; le
  `Content-Type` annoncé par le client est ignoré.

| Import | Extensions acceptées → type MIME |
|---|---|
| Clip (`VIDEO`) | `mp4` → `video/mp4`, `mov` → `video/quicktime`, `webm` → `video/webm`, `mkv` → `video/x-matroska`, `m4v` → `video/x-m4v` |
| Musique (`AUDIO`) | `mp3` → `audio/mpeg`, `wav` → `audio/wav`, `m4a` → `audio/mp4`, `aac` → `audio/aac`, `ogg` → `audio/ogg`, `flac` → `audio/flac` |

  Toute autre extension, ou pas d'extension du tout → `400` « Extension vidéo non supportée (acceptées : …) » (ou « Extension audio … »), avant
  toute lecture du fichier et sans rien stocker. Ensuite : `413` au-delà de la taille maximale (clip 100 Mo, musique
  50 Mo), `400` « Fichier vide ».
- L'extension est lue sur le nom **nettoyé** (voir plus bas) : `x.mp4/../../evil` → nom `evil`, sans extension →
  `400` ; `x.mp4\0.exe` → `x.mp4.exe` → `400`.

## Nom d'origine (table `asset_originals`)
- Une ligne par asset importé : `asset_id` (clé primaire, FK `assets.id` `ON DELETE CASCADE`), `original_name`
  (≤ 255 caractères), `created_at`. Migration `0005_asset_originals`. Supprimer l'asset (variante, projet) supprime la
  ligne.
- Nettoyage (`clean_name`) : caractères de contrôle et de format Unicode retirés (dont `\0`, `ESC`, inversion de sens
  U+202E), dernier segment après `/` ou `\`, espaces de bord retirés, tronqué à 255 caractères. Un nom vide ou fait
  seulement de points (`..`) n'est pas enregistré.
- **Donnée affichée seulement** : renvoyée dans `original_name` des assets (`GET /api/projects/{id}`, réponse de
  l'upload ; `null` pour un asset généré ou un import sans nom). L'admin l'affiche en infobulle sur « (importée) » d'une
  variante (`importedTitle`, `admin/src/studio.ts`).
- Musique : pas de ligne `asset_originals` ; le nom affiché est le champ `name` saisi à l'import (colonne
  `music_library.name`).

## Clip importé
Variante suivante de la scène (`meta = {model: "upload", cost_usd: 0}`), choisie d'office si la scène n'avait pas de
clip (montage et final passent alors en `stale`). `409` si `clips` ou `montage` tourne, `404` si la scène n'est pas au
projet.
