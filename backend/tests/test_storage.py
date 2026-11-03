import uuid

import pytest
from botocore.exceptions import ClientError

from app.config import settings
from app.storage import Storage


async def test_put_get_presign_roundtrip():
    st = Storage(settings.minio_endpoint, settings.minio_access_key, settings.minio_secret_key, "vv-test")
    await st.ensure_bucket()
    key = f"t/{uuid.uuid4()}.bin"
    await st.put(key, b"hello", "application/octet-stream")
    assert await st.get(key) == b"hello"
    assert key in st.presign(key)


async def test_delete_many_removes_objects():
    st = Storage(settings.minio_endpoint, settings.minio_access_key, settings.minio_secret_key, "vv-test")
    await st.ensure_bucket()
    keys = [f"t/{uuid.uuid4()}.bin" for _ in range(2)]
    for key in keys:
        await st.put(key, b"x", "application/octet-stream")
    await st.delete_many(keys)
    for key in keys:
        with pytest.raises(ClientError):
            await st.get(key)
    await st.delete_many([])  # rien à supprimer : aucun appel


async def test_delete_many_batches_by_1000_and_never_raises(caplog):
    calls = []

    class FakeS3:
        def delete_objects(self, **kwargs):
            calls.append(len(kwargs["Delete"]["Objects"]))
            if len(calls) == 2:
                raise RuntimeError("MinIO coupé")

    st = Storage(settings.minio_endpoint, settings.minio_access_key, settings.minio_secret_key, "vv-test")
    st._s3 = FakeS3()
    await st.delete_many([f"k{i}" for i in range(2500)])  # le 2e lot échoue : journalisé, pas propagé
    assert calls == [1000, 1000] and "orphelins" in caplog.text


async def test_exists_and_delete_prefix():
    st = Storage(settings.minio_endpoint, settings.minio_access_key, settings.minio_secret_key, "vv-test")
    await st.ensure_bucket()
    root = f"t/{uuid.uuid4()}"
    keys = [f"{root}/a.bin", f"{root}/sub/b.bin"]
    for key in keys:
        await st.put(key, b"x", "application/octet-stream")
    other = f"t/{uuid.uuid4()}/c.bin"
    await st.put(other, b"x", "application/octet-stream")
    assert await st.exists(keys[0]) and not await st.exists(f"{root}/absent.bin")
    await st.delete_prefix(f"{root}/")
    assert not await st.exists(keys[0]) and not await st.exists(keys[1])
    assert await st.exists(other)  # un autre préfixe n'est pas touché
    await st.delete_many([other])
