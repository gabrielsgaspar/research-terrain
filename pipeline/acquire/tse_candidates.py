"""Acquire the TSE candidate files. Contract: pipeline/README.md. Logic: terrain.sources.tse."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from terrain.catalog import dataset
from terrain.manifest import write_manifest
from terrain.sources.tse import AcquireError, Headers, acquire
from terrain.storage import GCSStore

TIMEOUT = 120


def _headers(resp: urllib.response.addinfourl) -> Headers:
    length = resp.headers.get("Content-Length")
    return Headers(
        last_modified=resp.headers.get("Last-Modified", ""),
        etag=resp.headers.get("ETag", ""),
        content_length=int(length) if length is not None else None,
    )


def _request(url: str, method: str) -> urllib.request.Request:
    # identity: a compressed body would make Content-Length meaningless
    return urllib.request.Request(url, method=method, headers={"Accept-Encoding": "identity"})


class UrllibFetcher:
    def head(self, url: str) -> Headers:
        with urllib.request.urlopen(_request(url, "HEAD"), timeout=TIMEOUT) as resp:
            return _headers(resp)

    @contextmanager
    def get(self, url: str) -> Iterator[tuple[Headers, BinaryIO]]:
        with urllib.request.urlopen(_request(url, "GET"), timeout=TIMEOUT) as resp:
            yield _headers(resp), resp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-out", required=True, type=Path)
    args = parser.parse_args()

    store = GCSStore(os.environ["TERRAIN_BUCKET"])
    with tempfile.TemporaryDirectory() as tmp:
        manifest = acquire(
            store,
            UrllibFetcher(),
            candidates=dataset("tse_candidates"),
            complementar=dataset("tse_candidates_complementar"),
            today=datetime.now(UTC).date(),
            tmp_dir=Path(tmp),
            code_commit=os.environ.get("CODE_COMMIT", ""),
        )
        if manifest["status"] == "created":
            write_manifest(manifest, store, args.manifest_out)
        else:
            args.manifest_out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "gcs_prefix": manifest["gcs_prefix"]}))


if __name__ == "__main__":
    try:
        main()
    except AcquireError as err:
        raise SystemExit(f"acquire failed: {err}") from err
