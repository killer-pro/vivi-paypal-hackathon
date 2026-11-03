"""Fichiers envoyés par le client (clips importés, musiques).

Règle : la clé de stockage est entièrement générée par le serveur (nom aléatoire + extension d'une liste fermée) et le
type MIME vient de cette même liste, jamais du client. Le nom d'origine n'est qu'une donnée affichée : nettoyé ici, il
n'entre dans aucune clé ni aucun chemin.
"""
import unicodedata
from dataclasses import dataclass
from uuid import uuid4

from fastapi import HTTPException, UploadFile

ORIGINAL_NAME_MAX_CHARS = 255  # colonne `asset_originals.original_name`


@dataclass(frozen=True)
class UploadKind:
    label: str  # dans « Extension {label} non supportée »
    types: dict[str, str]  # extension acceptée → type MIME enregistré


VIDEO = UploadKind("vidéo", {"mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
                             "mkv": "video/x-matroska", "m4v": "video/x-m4v"})
AUDIO = UploadKind("audio", {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4", "aac": "audio/aac",
                             "ogg": "audio/ogg", "flac": "audio/flac"})
# Extension d'un fichier téléchargé, par type MIME d'asset : imports (ci-dessus) et fichiers générés (PNG de référence ou
# d'image de départ, MP3 de voix, MP4 de clip et de rendu). Type inconnu (ancien import) : `bin`, jamais rien du client.
DOWNLOAD_EXTENSIONS = {mime: ext for kind in (VIDEO, AUDIO) for ext, mime in kind.types.items()} | {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


@dataclass(frozen=True)
class Upload:
    data: bytes
    ext: str  # de `UploadKind.types`
    content_type: str
    original_name: str | None  # nettoyé, tronqué ; None si le client n'a pas donné de nom exploitable

    def key(self, prefix: str) -> str:
        return f"{prefix}/{uuid4().hex}.{self.ext}"


def clean_name(filename: str | None) -> str:
    """Nom d'origine affichable : sans caractères de contrôle ni de format (catégories Unicode C*, dont l'inversion de
    sens U+202E), dernier segment après `/` ou `\\`, espaces de bord retirés. Vide s'il ne reste que des points."""
    name = "".join(c for c in filename or "" if not unicodedata.category(c).startswith("C"))
    name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name if name.strip(".") else ""


def upload_extension(name: str, kind: UploadKind) -> str:
    """Extension (minuscules) de `name` si elle est dans la liste de `kind` ; 400 sinon, sans extension compris."""
    _, dot, ext = name.rpartition(".")
    ext = ext.lower() if dot else ""
    if ext not in kind.types:
        raise HTTPException(400, f"Extension {kind.label} non supportée (acceptées : {', '.join(kind.types)})")
    return ext


def download_extension(content_type: str) -> str:
    return DOWNLOAD_EXTENSIONS.get(content_type, "bin")


async def read_upload(file: UploadFile, kind: UploadKind, max_bytes: int) -> Upload:
    """Fichier lu et contrôlé : extension acceptée (400), taille (413), non vide (400)."""
    name = clean_name(file.filename)
    ext = upload_extension(name, kind)
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"Fichier trop volumineux (maximum {max_bytes // 1024 // 1024} Mo)")
    if not data:
        raise HTTPException(400, "Fichier vide")
    return Upload(data, ext, kind.types[ext], name[:ORIGINAL_NAME_MAX_CHARS] or None)
