"""Fichiers envoyés par le client : clé de stockage générée par le serveur (nom aléatoire, extension d'une liste fermée),
type MIME tiré de cette liste, nom d'origine nettoyé et gardé dans `asset_originals` (donnée affichée seulement)."""
import pathlib
import re
import subprocess
import tempfile

import pytest
from sqlalchemy import func, select

from app.models import Asset, AssetOriginal, Scene, Step
from app.uploads import VIDEO, clean_name, upload_extension
from tests.test_api_steps import set_status

MP4 = b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2mp41"


async def project_with_scene(api, session):
    r = await api.post("/api/projects", json={"title": "t", "theme": "chats", "platform": "tiktok", "target_duration_s": 30})
    pid = r.json()["id"]
    scene = Scene(project_id=pid, position=1, voice_text="a", visual_prompt="b", duration_s=3)
    session.add(scene)
    await session.commit()
    return pid, scene.id


async def upload_clip(api, pid, scene_id, filename, content_type="video/mp4"):
    return await api.post(f"/api/projects/{pid}/scenes/{scene_id}/upload-clip",
                          files={"file": (filename, MP4, content_type)})


@pytest.mark.parametrize(("filename", "expected"), [
    ("x.mp4/../../evil", "evil"),
    ("a/b\\c.mp4", "c.mp4"),
    ("..", ""),
    ("../", ""),
    ("  vidéo été 🎬.MOV  ", "vidéo été 🎬.MOV"),
    ("x.mp4\x00.exe", "x.mp4.exe"),
    ("nul\x00l\x1f\x7f‮4pm.exe", "null4pm.exe"),  # contrôles et inversion de sens (U+202E) retirés
    (None, ""),
])
def test_clean_name_keeps_a_displayable_basename(filename, expected):
    assert clean_name(filename) == expected


@pytest.mark.parametrize(("name", "ext"), [
    ("clip.MP4", "mp4"), ("a.b.webm", "webm"), ("x.mkv", "mkv"), ("x.m4v", "m4v"), ("x.mov", "mov"), (".mp4", "mp4"),
])
def test_upload_extension_comes_from_the_allowlist(name, ext):
    assert upload_extension(name, VIDEO) == ext


@pytest.mark.parametrize("name", ["x.exe", "x.mp4.exe", "x.MP4 ", "x.php", "x.svg", "evil", "", "x."])
def test_upload_extension_rejects_anything_else(name):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        upload_extension(name, VIDEO)
    assert e.value.status_code == 400 and e.value.detail.startswith("Extension vidéo non supportée")


HOSTILE = [
    ("a/b\\c.mp4", "mp4", "c.mp4"),
    ("../../../etc/passwd.webm", "webm", "passwd.webm"),
    ("clip été 🎬.MOV", "mov", "clip été 🎬.MOV"),
    ("x" * 1000 + ".mkv", "mkv", "x" * 255),
    ("rapport\x1b[31m.m4v", "m4v", "rapport[31m.m4v"),
]


@pytest.mark.parametrize(("filename", "ext", "original"), HOSTILE)
async def test_clip_upload_key_is_server_generated(api, session, filename, ext, original):
    pid, scene_id = await project_with_scene(api, session)
    r = await upload_clip(api, pid, scene_id, filename, content_type="text/html; charset=evil")
    assert r.status_code == 201, r.text
    asset = r.json()
    assert re.fullmatch(rf"projects/{pid}/clip/[0-9a-f]{{32}}\.{ext}", asset["key"])
    assert list(api.storage.files) == [asset["key"]]
    assert asset["content_type"] == api.storage.types[asset["key"]] == VIDEO.types[ext]  # jamais celui du client
    assert asset["original_name"] == original and "filename" not in asset["meta"]
    stored = await session.scalar(select(AssetOriginal.original_name).where(AssetOriginal.asset_id == asset["id"]))
    assert stored == original
    project = (await api.get(f"/api/projects/{pid}")).json()
    assert [a["original_name"] for a in project["assets"]] == [original]


@pytest.mark.parametrize("filename", ["x.exe", "x.mp4.exe", "x.mp4\x00.exe", "page.html", "x.mp4/../../evil", "..",
                                      "sans-extension"])
async def test_clip_upload_rejects_unsupported_extension(api, session, filename):
    pid, scene_id = await project_with_scene(api, session)
    r = await upload_clip(api, pid, scene_id, filename)
    assert r.status_code == 400 and r.json()["detail"].startswith("Extension vidéo non supportée")
    assert api.storage.files == {}
    assert await session.scalar(select(func.count()).select_from(Asset)) == 0


async def test_original_name_is_deleted_with_its_asset(api, session):
    pid, scene_id = await project_with_scene(api, session)
    first = (await upload_clip(api, pid, scene_id, "a.mp4")).json()
    await upload_clip(api, pid, scene_id, "b.mp4")
    assert (await api.delete(f"/api/projects/{pid}/assets/{first['id']}")).status_code == 204
    assert (await session.scalars(select(AssetOriginal.original_name))).all() == ["b.mp4"]
    assert (await api.delete(f"/api/projects/{pid}")).status_code == 204
    assert await session.scalar(select(func.count()).select_from(AssetOriginal)) == 0


async def test_music_upload_key_and_type_come_from_the_allowlist(api):  # pas du nom ni du type annoncés
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "a.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", str(p)], check=True)
        r = await api.post("/api/music", files={"file": ("../../x/piste.WAV", p.read_bytes(), "audio/evil")},
                           data={"name": "Piste", "tags": ""})
    assert r.status_code == 201, r.text
    [key] = api.storage.files
    assert re.fullmatch(r"music/[0-9a-f]{32}\.wav", key) and api.storage.types[key] == "audio/wav"


async def test_music_upload_rejects_unsupported_extension(api):
    for filename in ("a.exe", "piste"):
        r = await api.post("/api/music", files={"file": (filename, b"abc", "audio/mpeg")}, data={"name": "n", "tags": ""})
        assert r.status_code == 400 and r.json()["detail"].startswith("Extension audio non supportée")
    assert api.storage.files == {}


@pytest.mark.parametrize(("content_type", "ext"), [("video/mp4", "mp4"), ("video/quicktime", "mov"),
                                                   ("audio/mpeg", "mp3"), ("image/png", "png"),
                                                   ("text/html", "bin"), ('video/mp4"; x="', "bin")])
async def test_download_name_extension_comes_from_the_allowlist(api, session, content_type, ext):
    """Ancienne clé tirée du nom du client (avant 0005) : jamais recopiée dans `Content-Disposition`."""
    pid, scene_id = await project_with_scene(api, session)
    asset = Asset(project_id=pid, kind="render", key=f'projects/{pid}/clip/x.mp4"; evil=".sh', content_type=content_type)
    session.add(asset)
    await session.commit()
    r = await api.get(f"/api/projects/{pid}/assets/{asset.id}/download")
    assert r.status_code == 307
    assert r.headers["location"].endswith(f"?download=vivi-{pid}.{ext}")


async def test_uploaded_reference_targets_a_script_element_when_ref_is_given(api, session):
    pid, _ = await project_with_scene(api, session)
    url = f"/api/projects/{pid}/reference/upload"
    png = ("kroc.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")
    whole = await api.post(url, files={"file": png})
    element = await api.post(url, files={"file": png}, data={"ref": "kroc"})
    assert whole.status_code == element.status_code == 201
    assert "ref" not in whole.json()["meta"] and element.json()["meta"]["ref"] == "kroc"
    assert (await api.post(url, files={"file": png}, data={"ref": "Bad Id"})).status_code == 422


async def test_reference_upload_is_allowed_while_clips_run_but_not_while_reference_runs(api, session):
    from app.models import Step
    pid, _ = await project_with_scene(api, session)
    url = f"/api/projects/{pid}/reference/upload"
    png = ("kroc.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")

    async def set_running(name):
        await session.execute(Step.__table__.update().where(Step.project_id == pid, Step.name == name).values(status="running"))
        await session.commit()

    await set_running("clips")
    assert (await api.post(url, files={"file": png}, data={"ref": "kroc"})).status_code == 201
    await set_running("reference")
    assert (await api.post(url, files={"file": png}, data={"ref": "kroc"})).status_code == 409


async def test_previous_reference_version_is_restored_as_the_latest(api, session):
    """Galerie des versions : une ancienne image redevient la dernière (celle des clips), copiée sous une nouvelle clé ;
    la version remplacée reste. Son téléchargement porte le nom de l'élément."""
    pid, _ = await project_with_scene(api, session)
    url = f"/api/projects/{pid}/reference/upload"
    first = (await api.post(url, files={"file": ("a.png", b"\x89PNG\r\n\x1a\nAAAA", "image/png")}, data={"ref": "kroc"})).json()
    await api.post(url, files={"file": ("b.png", b"\x89PNG\r\n\x1a\nBBBB", "image/png")}, data={"ref": "kroc"})
    r = await api.post(f"/api/projects/{pid}/reference/{first['id']}/restore")
    assert r.status_code == 201
    restored = await session.get(Asset, r.json()["id"])
    assert restored.meta["ref"] == "kroc" and restored.meta["restored_from"] == first["id"]
    assert await api.storage.get(restored.key) == b"\x89PNG\r\n\x1a\nAAAA"
    versions = (await session.scalars(select(Asset.id).where(Asset.project_id == pid, Asset.kind == "reference"))).all()
    assert len(versions) == 3 and max(versions) == restored.id
    download = await api.get(f"/api/projects/{pid}/assets/{restored.id}/download")
    assert download.headers["location"].endswith(f"?download=vivi-{pid}-kroc-{restored.id}.png")


async def test_only_a_reference_of_the_project_can_be_restored(api, session):
    pid, scene_id = await project_with_scene(api, session)
    clip = (await upload_clip(api, pid, scene_id, "c.mp4")).json()
    assert (await api.post(f"/api/projects/{pid}/reference/{clip['id']}/restore")).status_code == 404
    assert (await api.post(f"/api/projects/{pid}/reference/99999/restore")).status_code == 404


def wav(duration=1) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "a.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=duration={duration}", str(p)],
                       check=True)
        return p.read_bytes()


async def test_imported_voice_becomes_the_scene_voice_and_makes_the_montage_stale(api, session):
    pid, sid = await project_with_scene(api, session)
    await set_status(session, ["montage"], "approved")
    r = await api.post(f"/api/projects/{pid}/scenes/{sid}/upload-voice", files={"file": ("ibou 01.WAV", wav(), "x/y")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "voice" and body["scene_id"] == sid and body["original_name"] == "ibou 01.WAV"
    assert body["meta"]["imported"] is True and body["meta"]["text"] == "a"
    [key] = api.storage.files
    assert re.fullmatch(rf"projects/{pid}/voice/[0-9a-f]{{32}}\.wav", key)
    assert await session.scalar(select(Step.status).where(Step.project_id == pid, Step.name == "montage")) == "stale"


async def test_imported_voice_must_be_readable_audio_of_a_scene_of_the_project(api, session):
    pid, sid = await project_with_scene(api, session)
    url = f"/api/projects/{pid}/scenes/{sid}/upload-voice"
    assert (await api.post(url, files={"file": ("a.exe", b"abc", "audio/mpeg")})).status_code == 400
    assert (await api.post(url, files={"file": ("a.mp3", b"pas du son", "audio/mpeg")})).json()["detail"] == "Fichier audio illisible"
    other, _ = await project_with_scene(api, session)
    assert (await api.post(f"/api/projects/{other}/scenes/{sid}/upload-voice",
                           files={"file": ("a.wav", wav(), "audio/wav")})).status_code == 404
    assert api.storage.files == {}
