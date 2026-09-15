"""The S3 file-storage backend against a real object store.

The unit tests next door assert what the backend *asks* for - the encryption
arguments, the prefix, the refusals - against a fake client. This asks a real
S3-compatible store whether the round trip works: what `save` writes, `load`
reads back, `exists` answers and `delete` removes (#1423).

MinIO is the store, behind the `objectstore` compose profile:

    make docker-minio

Skipped when nothing answers on `FILE_STORAGE_S3_ENDPOINT` (default
`http://localhost:9000`), the same bargain `tests/integration/conftest.py`
makes about Postgres - CI starts one, a laptop without Docker still runs
everything else.

`FILE_STORAGE_S3_ENCRYPTION` is `none` here and that is not an oversight: MinIO
refuses SSE-S3 without a KES server behind it, so asking for encryption would
test the absence of a KMS rather than the backend. What every write asks for is
held by `tests/test_file_storage_s3.py::TestEveryWriteAsksForEncryption`.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from app.core.config import settings
from app.services.file_storage import S3FileStorage

pytestmark = pytest.mark.anyio

ENDPOINT = os.environ.get("FILE_STORAGE_S3_ENDPOINT", "http://localhost:9000")
ACCESS_KEY = os.environ.get("FILE_STORAGE_S3_ACCESS_KEY", "minioadmin")
SECRET_KEY = os.environ.get("FILE_STORAGE_S3_SECRET_KEY", "minioadmin")


def _client() -> object:
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 1},
            connect_timeout=2,
            read_timeout=5,
        ),
    )


@pytest.fixture(scope="module")
def bucket() -> Iterator[str]:
    """A bucket of this run's own, emptied and removed afterwards."""
    from botocore.exceptions import BotoCoreError, ClientError

    client = _client()
    name = f"agenticos-test-{uuid.uuid4().hex[:12]}"
    try:
        client.create_bucket(Bucket=name)  # type: ignore[attr-defined]
    except (BotoCoreError, ClientError, OSError) as exc:
        pytest.skip(
            f"no S3-compatible store at {ENDPOINT} ({type(exc).__name__}) - make docker-minio"
        )
    try:
        yield name
    finally:
        listed = client.list_objects_v2(Bucket=name).get("Contents", [])  # type: ignore[attr-defined]
        for item in listed:
            client.delete_object(Bucket=name, Key=item["Key"])  # type: ignore[attr-defined]
        client.delete_bucket(Bucket=name)  # type: ignore[attr-defined]


@pytest.fixture
def storage(bucket: str, monkeypatch: pytest.MonkeyPatch) -> S3FileStorage:
    monkeypatch.setattr(settings, "FILE_STORAGE_S3_ENCRYPTION", "none")
    return S3FileStorage(_client(), bucket, prefix="deployment")


async def test_an_upload_is_readable_back_under_the_path_it_returned(
    storage: S3FileStorage,
) -> None:
    stored = await storage.save("users/abc", "report.pdf", b"%PDF-1.7 bytes")

    assert await storage.load(stored) == b"%PDF-1.7 bytes"


async def test_two_uploads_of_one_name_do_not_collide(storage: S3FileStorage) -> None:
    """The stored name carries a uuid for exactly this: two people attaching
    `invoice.pdf` must not overwrite each other."""
    first = await storage.save("users/abc", "invoice.pdf", b"one")
    second = await storage.save("users/abc", "invoice.pdf", b"two")

    assert first != second
    assert await storage.load(first) == b"one"
    assert await storage.load(second) == b"two"


async def test_exists_answers_before_and_after_a_delete(storage: S3FileStorage) -> None:
    stored = await storage.save("users/abc", "a.png", b"bytes")
    assert await storage.exists(stored)

    await storage.delete(stored)

    assert not await storage.exists(stored)


async def test_reading_a_deleted_object_is_a_file_not_found(storage: S3FileStorage) -> None:
    """What every route serving a stored file answers 404 for."""
    stored = await storage.save("users/abc", "a.png", b"bytes")
    await storage.delete(stored)

    with pytest.raises(FileNotFoundError):
        await storage.load(stored)


async def test_deleting_an_object_twice_is_a_no_op(storage: S3FileStorage) -> None:
    """The teardown loops delete best-effort and may race each other."""
    stored = await storage.save("users/abc", "a.png", b"bytes")

    await storage.delete(stored)
    await storage.delete(stored)


async def test_the_object_lands_under_the_configured_prefix(
    storage: S3FileStorage, bucket: str
) -> None:
    """One bucket, more than one deployment, no shared keys."""
    stored = await storage.save("users/abc", "a.png", b"bytes")

    keys = [
        item["Key"]
        for item in _client().list_objects_v2(Bucket=bucket).get("Contents", [])  # type: ignore[attr-defined]
    ]
    assert f"deployment/{stored}" in keys
