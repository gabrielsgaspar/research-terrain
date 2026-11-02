"""Object storage behind one small interface.

`MemoryStore` is for tests. `GCSStore` talks to Google Cloud Storage. Neither
can overwrite an existing object: `create` raises `ObjectExistsError`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ObjectExistsError(FileExistsError):
    """Raised when `create` is called for a path that already exists."""


class Store(Protocol):
    def exists(self, path: str) -> bool: ...

    def list(self, prefix: str) -> list[str]: ...

    def read_bytes(self, path: str) -> bytes: ...

    def create(self, path: str, data: bytes | Path) -> None: ...

    def download(self, path: str, local_file: Path) -> None: ...


class MemoryStore:
    """A dict-backed store for tests."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def exists(self, path: str) -> bool:
        return path in self._objects

    def list(self, prefix: str) -> list[str]:
        return sorted(p for p in self._objects if p.startswith(prefix))

    def read_bytes(self, path: str) -> bytes:
        try:
            return self._objects[path]
        except KeyError:
            raise FileNotFoundError(path) from None

    def create(self, path: str, data: bytes | Path) -> None:
        if path in self._objects:
            raise ObjectExistsError(path)
        if isinstance(data, Path):
            data = data.read_bytes()
        self._objects[path] = bytes(data)

    def download(self, path: str, local_file: Path) -> None:
        local_file.write_bytes(self.read_bytes(path))


class GCSStore:
    """A store on a GCS bucket. Uploads use `if_generation_match=0`, so GCS
    itself refuses to overwrite an existing object."""

    def __init__(self, bucket_name: str, client: Any = None) -> None:
        if client is None:
            from google.cloud import storage

            client = storage.Client()
        self.bucket_name = bucket_name
        self._client = client
        self._bucket = client.bucket(bucket_name)

    def exists(self, path: str) -> bool:
        return bool(self._bucket.blob(path).exists())

    def list(self, prefix: str) -> list[str]:
        blobs = self._client.list_blobs(self._bucket, prefix=prefix)
        return sorted(b.name for b in blobs)

    def read_bytes(self, path: str) -> bytes:
        return self._bucket.blob(path).download_as_bytes()

    def create(self, path: str, data: bytes | Path) -> None:
        from google.api_core.exceptions import PreconditionFailed

        blob = self._bucket.blob(path)
        try:
            if isinstance(data, Path):
                blob.upload_from_filename(str(data), if_generation_match=0)
            else:
                blob.upload_from_string(data, if_generation_match=0)
        except PreconditionFailed as err:
            raise ObjectExistsError(path) from err

    def download(self, path: str, local_file: Path) -> None:
        self._bucket.blob(path).download_to_filename(str(local_file))
