import asyncio
import logging
from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger("app")


class Storage:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str):
        self.bucket = bucket
        self._s3 = boto3.client(
            "s3", endpoint_url=endpoint, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key, config=Config(signature_version="s3v4"), region_name="us-east-1",
        )

    async def ensure_bucket(self) -> None:
        def _ensure():
            try:
                self._s3.head_bucket(Bucket=self.bucket)
            except ClientError:
                self._s3.create_bucket(Bucket=self.bucket)
        await asyncio.to_thread(_ensure)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(self._s3.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    async def get(self, key: str) -> bytes:
        obj = await asyncio.to_thread(self._s3.get_object, Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    async def exists(self, key: str) -> bool:
        def _head() -> bool:
            try:
                self._s3.head_object(Bucket=self.bucket, Key=key)
                return True
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                    return False
                raise
        return await asyncio.to_thread(_head)

    async def delete_prefix(self, prefix: str) -> None:
        """Supprime tous les objets sous `prefix` (fichiers d'un projet, segments de montage compris). Même règle que
        `delete_many` : un échec est journalisé, jamais propagé."""
        def _keys() -> list[str]:
            pages = self._s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix)
            return [obj["Key"] for page in pages for obj in page.get("Contents", [])]
        try:
            keys = await asyncio.to_thread(_keys)
        except Exception:
            logger.exception("Liste des fichiers « %s » impossible (orphelins à nettoyer)", prefix)
            return
        await self.delete_many(keys)

    async def delete_many(self, keys: list[str]) -> None:
        """Supprime des objets (par lots de 1000, maximum de l'API S3). Échec : journalisé, jamais propagé : le stockage
        est nettoyé après la base, une panne ne doit pas défaire une suppression déjà validée."""
        def _delete():
            for start in range(0, len(keys), 1000):
                batch = [{"Key": key} for key in keys[start:start + 1000]]
                self._s3.delete_objects(Bucket=self.bucket, Delete={"Objects": batch, "Quiet": True})
        try:
            await asyncio.to_thread(_delete)
        except Exception:
            logger.exception("Suppression de %d fichier(s) du stockage impossible (orphelins à nettoyer)", len(keys))

    def presign(self, key: str, expires: int = 3600, download: str | None = None) -> str:
        """URL GET signée ; avec `download`, le navigateur enregistre le fichier sous ce nom."""
        params = {"Bucket": self.bucket, "Key": key}
        if download:
            params["ResponseContentDisposition"] = f'attachment; filename="{download}"'
        return self._s3.generate_presigned_url("get_object", Params=params, ExpiresIn=expires)


@lru_cache
def get_storage() -> Storage:
    return Storage(settings.minio_endpoint, settings.minio_access_key, settings.minio_secret_key, settings.minio_bucket)
