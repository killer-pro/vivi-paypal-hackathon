# Voix importées

Une scène peut utiliser une voix enregistrée au lieu de la voix de synthèse ElevenLabs : langue que la synthèse ne parle
pas (wolof…), comédien réel, dialogue enregistré à part.

- Import : étape Voix de l'éditeur, scène sélectionnée, bouton « Importer une voix » (« Remplacer la voix importée » quand
  la voix actuelle en est une). API : `POST /projects/{id}/scenes/{scene_id}/upload-voice` (voir `api.md`).
- L'asset `voice` créé porte `meta.imported = true` et `meta.text` (texte de la scène au moment de l'import) ; coût nul.
  Le fichier doit être un audio lisible (ffprobe), formats de la bibliothèque musicale (`mp3`, `wav`, `m4a`, `aac`, `ogg`,
  `flac`), 50 Mo au plus.
- Le montage et le rendu final deviennent périmés. Les clips ne le deviennent pas : un clip lip-sync déjà produit garde la
  voix sur laquelle ses lèvres sont calées ; il faut régénérer le clip de la scène pour que l'avatar dise la voix importée.
- « Générer les voix » (toutes les scènes, ou seulement les manquantes) garde les voix importées et ne synthétise que les
  autres ; si toutes sont importées, l'étape se termine sans appel ni voix configurée. « Régénérer cette voix » sur une
  scène la resynthétise quand même (`_voice`, `services/pipeline.py`).
- Avatar parlant : la voix importée de la scène est celle que l'avatar prononce (`_imported_voices`, `talk_voice`), sans
  exiger de voix ElevenLabs pour le personnage.
- Le texte de voix de la scène reste celui des sous-titres : le garder identique à ce qui est dit dans l'enregistrement.

Limite : le prix affiché de « Générer les voix » compte toutes les scènes, voix importées comprises.
