import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import ADMIN_ONLY
from app.db import get_session
from app.models import MusicTrack
from app.services.montage import probe_duration
from app.storage import Storage, get_storage
from app.uploads import AUDIO, read_upload

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

router = APIRouter(prefix="/music", tags=["music"])  # bibliothèque commune : lecture pour tous, écriture admin


def track_out(track: MusicTrack, storage: Storage) -> dict:
    return {"id": track.id, "name": track.name, "tags": track.tags, "duration_s": track.duration_s,
            "url": storage.presign(track.key)}


async def measure_duration(data: bytes) -> float:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "upload"
        path.write_bytes(data)
        try:
            return await probe_duration(path)
        except Exception:
            raise HTTPException(400, "Fichier audio illisible") from None


@router.get("")
async def list_music(session: AsyncSession = Depends(get_session), storage: Storage = Depends(get_storage)) -> list[dict]:
    tracks = (await session.scalars(select(MusicTrack).order_by(MusicTrack.id))).all()
    return [track_out(t, storage) for t in tracks]


@router.post("", status_code=201, dependencies=ADMIN_ONLY)
async def upload_music(file: UploadFile = File(...), name: str = Form(..., min_length=1, max_length=200),
                       tags: str = Form(""),
                       session: AsyncSession = Depends(get_session), storage: Storage = Depends(get_storage)) -> dict:
    """Piste importée : clé et type MIME tirés de l'extension (liste fermée `AUDIO`), affichée sous `name`."""
    upload = await read_upload(file, AUDIO, MAX_UPLOAD_BYTES)
    duration = await measure_duration(upload.data)
    key = upload.key("music")
    await storage.put(key, upload.data, upload.content_type)
    track = MusicTrack(name=name, tags=[t.strip() for t in tags.split(",") if t.strip()], duration_s=duration, key=key)
    session.add(track)
    await session.commit()
    return track_out(track, storage)


@router.delete("/{track_id}", status_code=204, dependencies=ADMIN_ONLY)
async def delete_music(track_id: int, session: AsyncSession = Depends(get_session),
                       storage: Storage = Depends(get_storage)) -> Response:
    track = await session.get(MusicTrack, track_id)
    if track is None:
        raise HTTPException(404, "Musique introuvable")
    await session.delete(track)
    await session.commit()
    await storage.delete_many([track.key])
    return Response(status_code=204)
