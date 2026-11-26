"""The platform's state document remains PostgreSQL JSONB-safe for binary files."""

import base64
import errno
import json

import pytest

from app.agents.capabilities.sandbox._capped import CappedStateBackend, document_size


@pytest.mark.parametrize("payload", [b"binary\x00bytes", b"\x00", b"line\n\x00\n", b"\xff\x00"])
def test_nul_bytes_use_base64_and_roundtrip_with_metadata(payload):
    backend = CappedStateBackend(max_bytes=4096)
    backend.write_bytes("folder/../binary", b"before")
    original = dict(backend.files["/binary"])
    backend.write_bytes("./binary", payload)
    stored = backend.files["/binary"]
    assert stored["encoding"] == "base64"
    assert stored["content"] == [base64.b64encode(payload).decode("ascii")]
    assert stored["created_at"] == original["created_at"]
    assert stored["modified_at"] >= original["modified_at"]
    assert "\\u0000" not in json.dumps(backend.files)
    restored = CappedStateBackend(json.loads(json.dumps(backend.files)), max_bytes=4096)
    assert restored.read_bytes("binary") == payload
    assert backend.stored_size() == document_size(backend.files, backend.directories)


def test_binary_expansion_counts_against_quota_without_partial_write():
    backend = CappedStateBackend(max_bytes=300)
    backend.write_bytes("kept", b"old")
    files, directories = dict(backend.files), set(backend.directories)
    for path in ("new/child/file", "kept"):
        with pytest.raises(OSError) as result:
            backend.write_bytes(path, b"\x00" * 300)
        assert result.value.errno == errno.ENOSPC
        assert backend.files == files
        assert backend.directories == directories
        assert backend.read_bytes("kept") == b"old"
        assert backend.stored_size() == document_size(files, directories)


def test_plain_utf8_stays_text_and_later_text_overwrite_removes_binary_encoding():
    backend = CappedStateBackend(max_bytes=4096)
    backend.write_bytes("binary", b"\x00")
    backend.write_bytes("binary", "zażółć\n".encode())
    assert "encoding" not in backend.files["/binary"]
    assert backend.read_bytes("binary") == "zażółć\n".encode()
