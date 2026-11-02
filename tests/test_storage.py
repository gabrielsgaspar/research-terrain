from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import PreconditionFailed

from terrain.storage import GCSStore, MemoryStore, ObjectExistsError


def test_memory_create_refuses_overwrite():
    s = MemoryStore()
    s.create("a/b", b"one")
    with pytest.raises(ObjectExistsError):
        s.create("a/b", b"two")
    assert s.read_bytes("a/b") == b"one"


def test_memory_roundtrip_list_and_download(tmp_path):
    s = MemoryStore()
    src = tmp_path / "src.txt"
    src.write_bytes(b"hello")
    s.create("p/x", src)
    s.create("p/a", b"z")
    s.create("q/y", b"w")
    assert s.exists("p/x") and not s.exists("p/nope")
    assert s.list("p/") == ["p/a", "p/x"]
    out = tmp_path / "out.txt"
    s.download("p/x", out)
    assert out.read_bytes() == b"hello"


def test_memory_read_missing_raises():
    with pytest.raises(FileNotFoundError):
        MemoryStore().read_bytes("nope")


def test_gcs_create_bytes_uses_generation_match_zero():
    client = MagicMock()
    blob = client.bucket.return_value.blob.return_value
    GCSStore("bkt", client=client).create("p/x", b"data")
    blob.upload_from_string.assert_called_once_with(b"data", if_generation_match=0)


def test_gcs_create_file_uses_generation_match_zero(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    client = MagicMock()
    blob = client.bucket.return_value.blob.return_value
    GCSStore("bkt", client=client).create("p/x", f)
    blob.upload_from_filename.assert_called_once_with(str(f), if_generation_match=0)


def test_gcs_create_maps_precondition_failure():
    client = MagicMock()
    blob = client.bucket.return_value.blob.return_value
    blob.upload_from_string.side_effect = PreconditionFailed("exists")
    with pytest.raises(ObjectExistsError):
        GCSStore("bkt", client=client).create("p/x", b"data")


def test_gcs_list_and_exists():
    client = MagicMock()
    b1, b2 = MagicMock(), MagicMock()
    b1.name, b2.name = "p/b", "p/a"
    client.list_blobs.return_value = [b1, b2]
    client.bucket.return_value.blob.return_value.exists.return_value = True
    s = GCSStore("bkt", client=client)
    assert s.list("p/") == ["p/a", "p/b"]
    assert s.exists("p/a") is True
