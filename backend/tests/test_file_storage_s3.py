"""The S3 file-storage backend: what it asks the store for, and what it refuses.

`S3FileStorage` is the second `BaseFileStorage` (#1423). The local one keeps
files on the API container's disk, which is the honest answer for a single host
with an encrypted volume and stops being one at the second replica or the first
client who wants their own KMS key.

These are the parts a MinIO integration test cannot see, because MinIO answers
the same whether or not the request asked for encryption and answers nothing at
all to a key it rejects:

- **every write asks for server-side encryption**, which is the reason the
  backend exists;
- a key that climbs out of the configured prefix is refused rather than
  normalised;
- a missing object reaches a caller as `FileNotFoundError`, because every route
  that serves a stored file already answers 404 for one and would otherwise
  500 naming AWS.

`tests/integration/test_s3_file_storage.py` is the other half, against a real
store.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import settings
from app.services.file_storage import (
    LocalFileStorage,
    S3FileStorage,
    get_file_storage,
    reset_file_storage,
)

pytestmark = pytest.mark.anyio


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.closed = False

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        self.closed = True


class _Client:
    """Enough of a boto3 S3 client to record what the backend asked for."""

    def __init__(self, *, objects: dict[str, bytes] | None = None) -> None:
        self.objects = objects if objects is not None else {}
        self.puts: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.bodies: list[_Body] = []

    def put_object(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objects:
            raise _client_error("NoSuchKey")
        body = _Body(self.objects[Key])
        self.bodies.append(body)
        return {"Body": body}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.deleted.append(Key)
        self.objects.pop(Key, None)

    def head_object(self, *, Bucket: str, Key: str) -> None:
        if Key not in self.objects:
            raise _client_error("404")


def _client_error(code: str) -> Exception:
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code}}, "GetObject")


@pytest.fixture(autouse=True)
def _default_encryption(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FILE_STORAGE_S3_ENCRYPTION", "sse-s3")
    monkeypatch.setattr(settings, "FILE_STORAGE_S3_KMS_KEY_ID", None)


class TestEveryWriteAsksForEncryption:
    async def test_sse_s3_by_default(self) -> None:
        client = _Client()
        await S3FileStorage(client, "files").save("u/1", "a.png", b"bytes")

        assert client.puts[0]["ServerSideEncryption"] == "AES256"

    async def test_sse_kms_names_the_key_when_one_is_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "FILE_STORAGE_S3_ENCRYPTION", "sse-kms")
        monkeypatch.setattr(settings, "FILE_STORAGE_S3_KMS_KEY_ID", "arn:aws:kms:eu-west-1:1:key/k")
        client = _Client()

        await S3FileStorage(client, "files").save("u/1", "a.png", b"bytes")

        assert client.puts[0]["ServerSideEncryption"] == "aws:kms"
        assert client.puts[0]["SSEKMSKeyId"] == "arn:aws:kms:eu-west-1:1:key/k"

    async def test_sse_kms_without_a_key_id_lets_the_bucket_default_decide(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bucket can carry a default KMS key, and naming none is how a
        deployment asks for it rather than a second setting saying so."""
        monkeypatch.setattr(settings, "FILE_STORAGE_S3_ENCRYPTION", "sse-kms")
        client = _Client()

        await S3FileStorage(client, "files").save("u/1", "a.png", b"bytes")

        assert client.puts[0]["ServerSideEncryption"] == "aws:kms"
        assert "SSEKMSKeyId" not in client.puts[0]

    async def test_none_sends_no_encryption_header_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """For a compatible store with no KMS behind it - MinIO refuses SSE-S3
        without one. `doctor` reports it as unconfigured rather than healthy."""
        monkeypatch.setattr(settings, "FILE_STORAGE_S3_ENCRYPTION", "none")
        client = _Client()

        await S3FileStorage(client, "files").save("u/1", "a.png", b"bytes")

        assert "ServerSideEncryption" not in client.puts[0]


class TestTheKeyAPathNames:
    async def test_the_prefix_is_applied_to_every_key(self) -> None:
        """One bucket can hold more than one deployment without their keys meeting."""
        client = _Client()
        storage = S3FileStorage(client, "files", prefix="staging/")

        stored = await storage.save("u/1", "a.png", b"bytes")

        assert client.puts[0]["Key"] == f"staging/{stored}"
        assert not stored.startswith("staging/"), "the row records the path, not the prefix"

    async def test_the_stored_path_is_read_back_under_the_same_prefix(self) -> None:
        client = _Client()
        storage = S3FileStorage(client, "files", prefix="staging")

        stored = await storage.save("u/1", "a.png", b"bytes")

        assert await storage.load(stored) == b"bytes"

    @pytest.mark.security
    @pytest.mark.parametrize("path", ["../secrets/key", "a/../../b", "/", "", "."])
    async def test_a_path_that_climbs_out_of_the_prefix_is_refused(self, path: str) -> None:
        """S3 treats `..` as a literal segment rather than a parent, so this is
        not traversal the way it is on a filesystem - but a caller who could put
        one in a key could rewrite a neighbouring deployment's objects under a
        shared bucket, and the local backend refuses the same shape."""
        with pytest.raises(ValueError, match="escapes storage root"):
            await S3FileStorage(_Client(), "files", prefix="staging").load(path)

    async def test_an_owner_is_reduced_the_way_the_local_backend_reduces_it(self) -> None:
        """`_sanitize_filename` keeps the last component, so `avatars/orgs/<id>`
        is stored under `<id>` here exactly as it is on disk. Identical on both
        backends on purpose: a row written by one names a readable path under the
        other once the bytes are copied across."""
        client = _Client()

        stored = await S3FileStorage(client, "files").save("avatars/orgs/7", "a.png", b"x")

        assert stored.startswith("7/")


class TestWhatTheStoreSaysBackReachesTheCaller:
    async def test_a_missing_object_is_a_file_not_found(self) -> None:
        """Every route that serves a stored file answers 404 for this. A bare
        `ClientError` would reach one as a 500 naming AWS."""
        with pytest.raises(FileNotFoundError):
            await S3FileStorage(_Client(), "files").load("u/1/gone.png")

    async def test_any_other_client_error_is_not_disguised_as_a_missing_file(self) -> None:
        """Access denied is not "the file is not there", and a 404 for it is how a
        misconfigured bucket policy looks like an empty deployment."""
        client = _Client()

        def _refuse(**_kwargs: object) -> None:
            raise _client_error("AccessDenied")

        client.get_object = _refuse  # type: ignore[method-assign]

        from botocore.exceptions import ClientError

        with pytest.raises(ClientError):
            await S3FileStorage(client, "files").load("u/1/a.png")

    async def test_the_response_body_is_closed(self) -> None:
        """botocore's body holds the connection until it is closed, and a pool
        that runs out of them stalls every later read."""
        client = _Client(objects={"u/1/a.png": b"bytes"})

        await S3FileStorage(client, "files").load("u/1/a.png")

        assert client.bodies[0].closed

    async def test_deleting_a_key_that_was_never_there_is_a_no_op(self) -> None:
        """The teardown loops delete best-effort and may race each other."""
        client = _Client()

        await S3FileStorage(client, "files").delete("u/1/gone.png")

        assert client.deleted == ["u/1/gone.png"]

    async def test_exists_answers_for_a_key_that_is_there_and_one_that_is_not(self) -> None:
        client = _Client(objects={"u/1/a.png": b"bytes"})
        storage = S3FileStorage(client, "files")

        assert await storage.exists("u/1/a.png")
        assert not await storage.exists("u/1/b.png")

    async def test_exists_is_false_for_a_path_it_would_refuse(self) -> None:
        assert not await S3FileStorage(_Client(), "files").exists("../elsewhere")


class TestChoosingTheBackend:
    def test_local_is_the_default(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "FILE_STORAGE_BACKEND", "local")
        monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
        reset_file_storage()

        assert isinstance(get_file_storage(), LocalFileStorage)

    def test_s3_without_a_bucket_refuses_to_build(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Loudly at the first upload rather than quietly writing to a bucket
        called the empty string."""
        monkeypatch.setattr(settings, "FILE_STORAGE_BACKEND", "s3")
        monkeypatch.setattr(settings, "FILE_STORAGE_S3_BUCKET", "")
        reset_file_storage()

        with pytest.raises(RuntimeError, match="FILE_STORAGE_S3_BUCKET"):
            get_file_storage()

        reset_file_storage()

    def test_the_s3_backend_is_built_once_and_reused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Its client opens a connection pool and reads the credential chain, and
        this is called per request."""
        monkeypatch.setattr(settings, "FILE_STORAGE_BACKEND", "s3")
        monkeypatch.setattr(settings, "FILE_STORAGE_S3_BUCKET", "files")
        built = []
        monkeypatch.setattr(
            "app.services.file_storage.build_s3_client", lambda: built.append(1) or _Client()
        )
        reset_file_storage()

        first, second = get_file_storage(), get_file_storage()

        assert first is second
        assert built == [1]
        reset_file_storage()
