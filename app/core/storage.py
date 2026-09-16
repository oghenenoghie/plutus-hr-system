"""Object storage for uploaded bytes this app now hosts itself (employee
photos to start with) — see python-engineering.md's "Employee photos"
section for the contract: private bucket, signed URLs only, never a
public bucket or a raw stored URL.

Two implementations behind one interface:

- S3ObjectStorage: any S3-compatible provider (Cloudflare R2, AWS S3,
  Supabase Storage's S3 endpoint) — selected when all four
  object_storage_* credentials are set.
- LocalObjectStorage: local disk, signed with an HMAC token this process
  verifies itself via GET /storage/local/{key} — the same "unset in
  dev/test -> fall back to something that works without real
  credentials" shape as resend_api_key, so uploads work in local dev and
  CI without a real bucket.

Callers never construct either class directly — get_object_storage()
picks the right one from settings.
"""

import base64
import hashlib
import hmac
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import boto3
from botocore.client import Config as BotoConfig

from app.core.config import Settings, get_settings


class ObjectStorage(Protocol):
    def put_object(self, key: str, data: bytes, *, content_type: str) -> None: ...

    def delete_object(self, key: str) -> None: ...

    def presigned_url(self, key: str, *, ttl_seconds: int, base_url: str = "") -> str: ...


class S3ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        assert settings.object_storage_bucket
        self._bucket = settings.object_storage_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint_url,
            aws_access_key_id=settings.object_storage_access_key_id,
            aws_secret_access_key=settings.object_storage_secret_access_key,
            region_name=settings.object_storage_region,
            config=BotoConfig(signature_version="s3v4"),
        )

    def put_object(self, key: str, data: bytes, *, content_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def delete_object(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def presigned_url(self, key: str, *, ttl_seconds: int, base_url: str = "") -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=ttl_seconds,
        )


class LocalObjectStorage:
    """Disk-backed stand-in with the same signed-URL contract, for local
    dev and CI where no real bucket is configured. Never used when
    object_storage_bucket (and its S3 siblings) are set."""

    def __init__(self, settings: Settings) -> None:
        self._root = Path(settings.object_storage_local_dir)
        self._root.mkdir(parents=True, exist_ok=True)
        self._signing_secret = settings.object_storage_signing_secret.encode()

    def _path_for(self, key: str) -> Path:
        # Reject any key that could escape the storage root (e.g. "..").
        path = (self._root / key).resolve()
        if self._root.resolve() not in path.parents and path != self._root.resolve():
            raise ValueError("invalid object key")
        return path

    def put_object(self, key: str, data: bytes, *, content_type: str) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def delete_object(self, key: str) -> None:
        path = self._path_for(key)
        path.unlink(missing_ok=True)

    def _sign(self, key: str, expires_at: int) -> str:
        message = f"{key}:{expires_at}".encode()
        digest = hmac.new(self._signing_secret, message, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def verify(self, key: str, expires_at: int, signature: str) -> bool:
        if time.time() > expires_at:
            return False
        expected = self._sign(key, expires_at)
        return hmac.compare_digest(expected, signature)

    def presigned_url(self, key: str, *, ttl_seconds: int, base_url: str = "") -> str:
        expires_at = int(time.time()) + ttl_seconds
        signature = self._sign(key, expires_at)
        return f"{base_url}/api/v1/storage/local/{key}?exp={expires_at}&sig={signature}"

    def read(self, key: str) -> bytes:
        return self._path_for(key).read_bytes()


@lru_cache
def get_object_storage() -> ObjectStorage:
    settings = get_settings()
    if (
        settings.object_storage_bucket
        and settings.object_storage_access_key_id
        and settings.object_storage_secret_access_key
    ):
        return S3ObjectStorage(settings)
    return LocalObjectStorage(settings)


def photo_object_key(org_id: uuid.UUID, employee_id: uuid.UUID, version: int) -> str:
    return f"employee-photos/{org_id}/{employee_id}/{version}.webp"


def photo_thumbnail_key(org_id: uuid.UUID, employee_id: uuid.UUID, version: int) -> str:
    return f"employee-photos/{org_id}/{employee_id}/{version}-thumb.webp"
