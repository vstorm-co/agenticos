"""Large transfer files stay streamed and the caller retains its source handle."""

import asyncio
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from boto3.s3.transfer import TransferConfig

from app.core.config import settings
from app.services.file_storage import (
    STREAM_CHUNK_BYTES,
    LocalFileStorage,
    S3FileStorage,
    _BorrowedUploadStream,
)

pytestmark = pytest.mark.anyio


class _BoundedSource(BytesIO):
    def read(self, size: int | None = -1) -> bytes:
        assert size is not None and 0 < size <= STREAM_CHUNK_BYTES
        return super().read(size)


async def test_local_stream_round_trip_is_bounded_and_keeps_the_source_open(tmp_path: Path) -> None:
    data = b"document" * 100_000
    source = _BoundedSource(b"skip" + data)
    source.seek(4)
    storage = LocalFileStorage(str(tmp_path))
    path = await storage.save_stream("users/one", "resources.zip", source)
    assert await storage.load(path) == data
    assert not source.closed
    assert path.startswith("one/")


async def test_a_failed_stream_does_not_leave_an_unreachable_partial_file(tmp_path: Path) -> None:
    class FailingSource(BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            if self.tell():
                raise OSError("source failed")
            return super().read(4)

    storage = LocalFileStorage(str(tmp_path))
    with pytest.raises(OSError, match="source failed"):
        await storage.save_stream("one", "resources.zip", FailingSource(b"partial content"))
    assert not list(tmp_path.rglob("*.zip"))


async def test_an_existing_local_target_is_not_deleted_when_exclusive_creation_fails(
    tmp_path: Path,
) -> None:
    target = tmp_path / "existing.zip"
    target.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        LocalFileStorage._copy_stream_blocking(target, BytesIO(b"replacement"))
    assert target.read_bytes() == b"original"


async def test_local_cancellation_waits_for_cleanup(tmp_path: Path) -> None:
    storage = LocalFileStorage(str(tmp_path))
    source = BytesIO(b"content")
    task = asyncio.ensure_future(storage.save_stream("one", "resources.zip", source))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        result = await task
        pytest.fail(f"Cancelled save returned {result}")
    assert not list(tmp_path.rglob("*.zip"))
    assert not source.closed


async def test_s3_transfer_keeps_encryption_bounded_multipart_and_borrowed_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "FILE_STORAGE_S3_ENCRYPTION", "sse-s3")
    source = _BoundedSource(b"source content")
    client = MagicMock()
    received = bytearray()

    def upload(
        stream: _BorrowedUploadStream,
        bucket: str,
        key: str,
        *,
        ExtraArgs: dict[str, str],
        Config: TransferConfig,
    ) -> None:
        assert bucket == "files" and key.startswith("deployment/one/")
        assert ExtraArgs == {"ServerSideEncryption": "AES256"}
        assert Config.use_threads is False
        assert Config.multipart_chunksize == 8 * 1024 * 1024
        assert stream.seekable()
        assert stream.tell() == 0
        stream.seek(0)
        while chunk := stream.read(STREAM_CHUNK_BYTES):
            received.extend(chunk)
        stream.close()

    client.upload_fileobj.side_effect = upload
    path = await S3FileStorage(client, "files", prefix="deployment").save_stream(
        "users/one", "resources.zip", source
    )
    assert path.startswith("one/")
    assert received == b"source content"
    assert not source.closed


async def test_journaled_stream_paths_are_exact_and_contained(tmp_path: Path) -> None:
    storage = LocalFileStorage(str(tmp_path))
    source = _BoundedSource(b"bundle content")
    reserved = "portability/operation/staging/attempt/output.zip"
    await storage.save_stream_at(reserved, source)
    assert await storage.load(reserved) == b"bundle content"
    assert not source.closed
    with pytest.raises(ValueError, match="escapes"):
        await storage.save_stream_at("../outside.zip", BytesIO(b"no"))
    assert await storage.delete_prefix("portability/operation") == 1


async def test_s3_reserved_stream_path_is_not_replaced_with_a_random_key() -> None:
    client = MagicMock()
    storage = S3FileStorage(client, "files", prefix="deployment")
    source = BytesIO(b"bytes")
    await storage.save_stream_at("portability/operation/staging/result.zip", source)
    assert (
        client.upload_fileobj.call_args.args[2]
        == "deployment/portability/operation/staging/result.zip"
    )
    assert not source.closed
