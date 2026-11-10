# Bibliothèque musicale

- Import : depuis la page Musique ou directement dans l'étape Musique de l'éditeur (bouton « Importer une piste », la piste est alors choisie d'office).
- Bibliothèque commune à tous les comptes : `GET` pour tout compte connecté, `POST` et `DELETE` réservés à
  l'administrateur (`403` sinon).
- `GET /api/music` : liste `[{id, name, tags, duration_s, url}]` (`url` présignée MinIO).
- `POST /api/music` (multipart : `file`, `name`, `tags` séparés par des virgules) : `201` avec la piste créée.
  `400` si l'extension n'est pas dans la liste audio (`mp3`, `wav`, `m4a`, `aac`, `ogg`, `flac` ; un fichier
  sans extension est refusé), si le fichier est vide ou si ffprobe ne sait pas le lire ; `413` au-delà de 50 Mo ; `422` si `name` est vide ou dépasse 200 caractères.
  Les tags sont découpés sur les virgules, nettoyés, les vides sont ignorés.
- `DELETE /api/music/{id}` : `204`, `404` si inconnue. Supprime la ligne en base puis l'objet MinIO (`Storage.delete_many`,
  best-effort : un échec de stockage est journalisé, la suppression reste valide). Un projet dont l'étape `music`
  référence la piste échouera au montage (« piste introuvable »).
- La durée est mesurée avec `probe_duration` sur un fichier temporaire ; le fichier est stocké sous `music/<32 hex>.<ext>`,
  extension et type MIME tirés de la liste fermée (jamais du nom ni du `Content-Type` du client : `docs/imports-fichiers.md`).

## Pistes libres de droits (seed)
`backend/scripts/seed_music.py` (`npm run seed:music`, ou `uv run python scripts/seed_music.py [--api URL] [--email …] [--password …]`) se connecte en admin (`POST /api/music` est réservé à l'admin ; e-mail et mot de passe par défaut : `ADMIN_EMAIL` / `ADMIN_PASSWORD`), télécharge depuis Internet Archive 12 pistes de
Kevin MacLeod et les ajoute via `POST /api/music` (donc dans MinIO). Seules les licences compatibles avec un montage
(mixage, normalisation) sont retenues : CC0, domaine public, CC BY 4.0. Le script est idempotent (nom déjà présent →
ignorée). Le nom de chaque piste porte son crédit (`Titre — Kevin MacLeod (CC BY 4.0)`) : en CC BY 4.0, ce crédit doit
figurer dans la description de la vidéo publiée (« Music: <titre> by Kevin MacLeod, CC BY 4.0 »).
L'autopilot choisit la première piste de la bibliothèque (plus petit id).

Volume de la musique sous la voix : curseur du panneau Musique de l'éditeur, paramètre `volume` de l'étape (voir `montage.md`).
