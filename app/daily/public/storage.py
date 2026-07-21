"""Media storage adapters (local + S3-compatible interface)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class StoredMedia:
    key: str
    public_url: str
    bytes_written: int


class MediaStorage(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> StoredMedia: ...

    def exists(self, key: str) -> bool: ...

    def remove(self, key: str) -> None: ...

    def get_public_url(self, key: str) -> str: ...


class LocalMediaStorage:
    """Dev/default: files under data/public_media, served via /media/..."""

    def __init__(self, root: Path, *, public_base_url: str = "/media") -> None:
        self.root = root
        self.public_base_url = public_base_url.rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> StoredMedia:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredMedia(key=key, public_url=self.get_public_url(key), bytes_written=len(data))

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def remove(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def get_public_url(self, key: str) -> str:
        return f"{self.public_base_url}/{key.lstrip('/')}"

    def _path(self, key: str) -> Path:
        # Prevent path traversal outside root.
        resolved = (self.root / key.lstrip("/")).resolve()
        root = self.root.resolve()
        try:
            if not resolved.is_relative_to(root):
                raise ValueError("invalid storage key")
        except AttributeError:  # pragma: no cover
            if not str(resolved).startswith(str(root)):
                raise ValueError("invalid storage key")
        return resolved


class S3MediaStorage:
    """S3 / R2 compatible adapter (optional dependency: boto3)."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        public_base_url: str,
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> None:
        try:
            import boto3  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("boto3 is required for S3MediaStorage") from exc

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.public_base_url = public_base_url.rstrip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region or None,
        )

    def _full_key(self, key: str) -> str:
        key = key.lstrip("/")
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> StoredMedia:
        full = self._full_key(key)
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self.bucket, Key=full, Body=data, **extra)
        return StoredMedia(key=key, public_url=self.get_public_url(key), bytes_written=len(data))

    def exists(self, key: str) -> bool:
        full = self._full_key(key)
        try:
            self._client.head_object(Bucket=self.bucket, Key=full)
            return True
        except Exception:  # noqa: BLE001
            return False

    def remove(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=self._full_key(key))

    def get_public_url(self, key: str) -> str:
        return f"{self.public_base_url}/{key.lstrip('/')}"


def default_media_storage(project_root: Path | None = None) -> MediaStorage:
    root = project_root or Path(__file__).resolve().parents[3]
    backend = os.environ.get("CONNOR_MEDIA_STORAGE", "local").strip().lower()
    # Prefer same-origin relative /media so Next rewrites work in production.
    # Absolute http://127.0.0.1… breaks visitor browsers — do not default to it.
    public_base = os.environ.get("CONNOR_MEDIA_PUBLIC_BASE_URL", "/media").strip() or "/media"
    if backend in {"s3", "r2"}:
        bucket = os.environ.get("CONNOR_MEDIA_S3_BUCKET", "")
        if not bucket:
            raise RuntimeError("CONNOR_MEDIA_S3_BUCKET is required for S3 storage")
        if public_base.startswith("/"):
            raise RuntimeError(
                "CONNOR_MEDIA_PUBLIC_BASE_URL must be an absolute HTTPS URL for S3/R2"
            )
        return S3MediaStorage(
            bucket=bucket,
            prefix=os.environ.get("CONNOR_MEDIA_S3_PREFIX", "posts"),
            public_base_url=public_base,
            endpoint_url=os.environ.get("CONNOR_MEDIA_S3_ENDPOINT"),
            region=os.environ.get("CONNOR_MEDIA_S3_REGION"),
        )
    local_root = Path(
        os.environ.get("CONNOR_MEDIA_LOCAL_ROOT", str(root / "data" / "public_media"))
    )
    return LocalMediaStorage(local_root, public_base_url=public_base)
