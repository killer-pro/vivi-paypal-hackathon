# Montage vidéo (FFmpeg)

Service : `backend/app/services/montage.py`.

## Pipeline
1. Durée de chaque voix (`ffprobe`) + `PAD_S` (0,3 s) = durée de la scène.
2. Par scène : voix et clip **convergent** vers le milieu de leurs deux durées (`converge`, `montage.py`). Voix plus longue : voix accélérée (`atempo`, ×1,4 au plus = `MAX_TEMPO`), clip ralenti (`setpts`). Voix plus courte : voix ralentie (×0,85 au plus = `MIN_TEMPO`), clip accéléré. Clip jamais changé de plus de ×1,25 (`MAX_STRETCH`). Si les plafonds ne suffisent pas, la voix décide : clip coupé à la durée de la scène, ou dernière image tenue (`tpad`, `HOLD_LAST_FRAME`), jamais de reprise du début. La scène dure la durée convergée + 0,3 s : la voix est complétée par du silence (`apad`) et le clip est étiré pour remplir aussi cette marge (`converge` la compte), sans arrêt sur image à la fin de chaque scène (mesuré sur le projet 49 : 0,43 à 0,47 s figées par scène avant, quasi aucune après). **Les fichiers d'origine (clip, voix) restent intacts dans le stockage** : seul le segment monté est transformé (les clips ComfyUI sont demandés 0,3 s plus longs que la scène). Mesuré sur 20 scènes (voix 3,0 à 4,5 s, clip 3,31 s) : voix entre ×0,95 et ×1,15, clip entre ×0,85 et ×1,05 de vitesse, aucun plafond atteint.
3. Concaténation des vidéos et des voix, puis rendu final avec sous-titres, musique optionnelle et encodage H.264/AAC.

## Segments et cache
`render_segment(scène, dossier, nom)` encode une scène (étapes 1 et 2 ci-dessus) et renvoie un `Segment` (vidéo, voix, durée,
texte) ; `assemble(segments, musique, sortie, dossier)` fait l'étape 3 ; `render(...)` enchaîne les deux sans cache (tests,
usage direct). Le pipeline (`_montage`) met chaque segment en cache dans le stockage (`segment_key`) : seule une scène dont
le clip ou la voix a changé est ré-encodée (`docs/workflow-video.md`, « Montage incrémental »).

## Format 9:16
Sortie exactement 1080x1920 à 30 fps (`scale` lanczos + `crop` centré, `fps=30`, `setsar=1`), filtre construit par
`clip_filter(fps)` d'après la cadence du clip lue par `probe_fps` (`ffprobe`, `r_frame_rate`).

## Clips à cadence basse : interpolation
Un clip sous 24 fps (`MIN_SMOOTH_FPS`), comme la sortie Wan 2.2 14B à 16 fps, passe d'abord par `minterpolate`
(`fps=30`, `mi_mode=mci`, `mc_mode=aobmc`, `me_mode=bidir`, `vsbmc=1`) : les images intermédiaires sont calculées par
compensation de mouvement au lieu d'être dupliquées, ce qui supprime l'effet saccadé. Mesuré (M4 Max) : environ 8 s
pour un clip de 3 s en 720x1248, sans artefact visible sur un sujet en mouvement (pattes d'un renard qui court). Les
clips à 24 fps ou plus (providers cloud) gardent la simple conversion de cadence. Aucun modèle d'interpolation (RIFE,
FILM) n'est installé dans ComfyUI, d'où ce choix côté FFmpeg.

## Sous-titres
`build_ass` génère un fichier ASS (UTF-8) à partir de (texte, durée), brûlé via le filtre `subtitles` (libass).
- `PlayResX/PlayResY` = 1080x1920 : taille et marges sont en **pixels réels**. (Un SRT est mis à l'échelle par libass
  depuis une résolution de référence 384x288 : texte énorme et placé trop haut ; `original_size` ne change pas cette
  référence.)
- Style : Arial gras 64 px, blanc avec contour noir de 4 px, centré en bas (`Alignment=2`), `MarginV=420` px (tiers
  inférieur, au-dessus des boutons et légendes des plateformes), marges latérales 80 px ; retour à la ligne automatique.
- Texte : retours ligne et espaces multiples réduits à un espace ; `{`/`}` remplacés par des parenthèses et `\` par `/`
  (pas de balise ASS injectée par le texte de la voix off). Les tirets U+2010 et U+2011 (insécable, que les LLM
  écrivent dans « micro‑objectif ») deviennent `-` : la police ne les a pas et les affichait en carré vide (`FONT_SAFE`).

## Musique
Optionnelle, bouclée, mixée sous la voix (`amix`, durée = celle de la voix, `normalize=0` : la voix garde son niveau d'origine au lieu d'être divisée par le nombre d'entrées, soit -6 dB). Sans musique, seule la voix est conservée.

Volume réglable : paramètre `volume` de l'étape `music` (en %, 0 à 100 ; absent ou illisible : `MUSIC_VOLUME = 0.15`, soit 15 %), lu par `music_level` et passé à `assemble(..., music_volume=...)`. Il se règle avec le curseur « Volume sous la voix » du panneau Musique de l'éditeur (affiché quand une piste est choisie), enregistré au relâchement : comme tout changement de l'étape musique, le montage devient à refaire. L'aperçu sans rendu joue la musique à ce niveau (`musicVolume`, `admin/src/montage.ts`). Les segments en cache ne dépendent pas du volume : seul l'assemblage est refait.

## Loudness
En fin de chaîne audio (voix seule ou voix + musique), `LOUDNORM = loudnorm=I=-16:TP=-1.5:LRA=11` normalise le son final (-16 LUFS intégrés, crête -1,5 dB) pour un niveau homogène d'une vidéo à l'autre.

## Prérequis
FFmpeg et ffprobe doivent être dans le `PATH`, FFmpeg compilé avec libass (filtres `ass` / `subtitles`) : `ffmpeg -filters | grep -w subtitles`. Sur macOS, `brew install ffmpeg` fournit libass (vérifié avec FFmpeg 9.0.2) ; sinon utiliser le tap `homebrew-ffmpeg/ffmpeg/ffmpeg`.

Limite : une musique plus courte que la vidéo est bouclée ; le fichier musique n'est jamais supprimé de MinIO, même si la piste est retirée de la bibliothèque.

## Style des sous-titres
Paramètre `subtitle_style` de l'étape `montage` : `classic` (blanc, contour noir, 64 px, défaut), `box` (blanc sur boîte sombre semi-opaque) ou `bold` (jaune, 84 px, gros contour). `none` (« Sans ») : aucun sous-titre gravé (voix enregistrées dont le texte diffère du script, vidéo sous-titrée ailleurs) ; l'aperçu de l'éditeur n'affiche alors pas non plus le texte sur les clips. Une valeur inconnue retombe sur `classic`. Les segments en cache ne dépendent pas du style (seul l'assemblage final grave les sous-titres) : changer de style ne ré-encode aucune scène. Choix dans le panneau Montage de l'éditeur.
