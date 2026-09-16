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

import asyncio
from typing import Any

import pytest

from app.core.config import settings
from app.services.file_storage import (
    LocalFileStorage,
    S3FileStorage,
    build_s3_client,
    get_file_storage,
    reset_file_storage,
)

pytestmark = pytest.mark.anyio


class _Body:
    """botocore's streaming body: `read()` for all of it, `read(n)` for a chunk."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0
        self.closed = False

    def read(self, size: int | None = None) -> bytes:
        if size is None:
            chunk, self._offset = self._data[self._offset :], len(self._data)
            return chunk
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

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

    def get_paginator(self, name: str) -> _Paginator:
        assert name == "list_objects_v2"
        return _Paginator(self.objects)

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any]) -> None:
        for entry in Delete["Objects"]:
            self.deleted.append(entry["Key"])
            self.objects.pop(entry["Key"], None)


class _Paginator:
    """One page of keys, which is all `delete_prefix` needs to be right about."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def paginate(self, *, Bucket: str, Prefix: str) -> list[dict[str, Any]]:
        matched = [{"Key": key} for key in self.objects if key.startswith(Prefix)]
        return [{"Contents": matched}] if matched else [{}]


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

    async def test_sse_kms_is_refused_without_a_key_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unnamed `aws:kms` is not the bucket's default key - S3 reads it as
        its own `aws/s3`. A deployment that asked for a client-held key and named
        none would have stored data under the wrong one, or had the write refused
        by a policy requiring theirs, and been told nothing either way."""
        monkeypatch.setattr(settings, "FILE_STORAGE_BACKEND", "s3")
        monkeypatch.setattr(settings, "FILE_STORAGE_S3_BUCKET", "files")
        monkeypatch.setattr(settings, "FILE_STORAGE_S3_ENCRYPTION", "sse-kms")
        monkeypatch.setattr(settings, "FILE_STORAGE_S3_KMS_KEY_ID", None)
        reset_file_storage()

        with pytest.raises(RuntimeError, match="FILE_STORAGE_S3_KMS_KEY_ID"):
            get_file_storage()

        reset_file_storage()

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

    async def test_a_head_that_is_refused_is_not_reported_as_a_missing_object(self) -> None:
        """`AccessDenied` is a fact about the bucket policy, not about the key. A
        blanket catch here reads as an agent with no avatar and a knowledge base
        whose documents have all been deleted, which is the wrong thing for
        anybody to act on."""
        client = _Client()

        def _refuse(**_kwargs: object) -> None:
            raise _client_error("AccessDenied")

        client.head_object = _refuse  # type: ignore[method-assign]

        from botocore.exceptions import ClientError

        with pytest.raises(ClientError):
            await S3FileStorage(client, "files").exists("u/1/a.png")

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


class TestSavingIsCancellationSafe:
    """An executor cannot interrupt a running `put_object`.

    So a cancelled request unwinds with the object written and its key never
    returned - bytes nothing points at, paid for every month until somebody goes
    looking. The local backend has had this since #1108; the bucket is the same
    failure with an invoice attached.
    """

    async def test_a_cancelled_upload_removes_the_object_it_wrote(self) -> None:
        client = _Client()
        storage = S3FileStorage(client, "files")

        saving = asyncio.ensure_future(storage.save("u/1", "a.png", b"bytes"))
        await asyncio.sleep(0)
        saving.cancel()
        with pytest.raises(asyncio.CancelledError):
            # Bound rather than left bare: `await saving` on its own is an
            # expression statement, which CodeQL reads as having no effect. The
            # await is the effect, and this says so.
            _cancelled = await saving

        assert client.objects == {}, "the object the cancelled put wrote is still there"
        assert client.deleted, "nothing was deleted, so nothing undid the put"

    async def test_a_content_addressed_write_lands_on_the_key_it_was_given(self) -> None:
        """`save_at` is the media store's, whose key is the digest of its bytes -
        and it does not undo itself on cancellation, because two callers writing
        one digest write identical bytes to one object (#55)."""
        client = _Client()

        await S3FileStorage(client, "files").save_at("media/org/conv/abc123", b"png")

        assert client.objects["media/org/conv/abc123"] == b"png"

    async def test_a_prefix_goes_with_everything_under_it(self) -> None:
        """Without this an S3 deployment would keep every picture any compacted
        history ever held: a digest records nothing about who references it."""
        client = _Client()
        storage = S3FileStorage(client, "files")
        await storage.save_at("media/org/conv/a", b"1")
        await storage.save_at("media/org/conv/b", b"2")
        await storage.save_at("media/org/other/c", b"3")

        removed = await storage.delete_prefix("media/org/conv")

        assert removed == 2
        assert list(client.objects) == ["media/org/other/c"]

    async def test_a_prefix_nothing_is_under_deletes_nothing(self) -> None:
        """A conversation that never offloaded a picture is the common case, and
        an empty page must not become an empty `delete_objects` call."""
        client = _Client()

        removed = await S3FileStorage(client, "files").delete_prefix("media/org/empty")

        assert (removed, client.deleted) == (0, [])

    async def test_an_uncancelled_upload_is_left_alone(self) -> None:
        client = _Client()

        stored = await S3FileStorage(client, "files").save("u/1", "a.png", b"bytes")

        assert client.deleted == []
        assert await S3FileStorage(client, "files").load(stored) == b"bytes"


class TestServingAnObjectDoesNotHoldItWhole:
    """A knowledge-base document can be 50 MB and its route is not rate-limited.

    Buffered, a handful of concurrent downloads is the API container's memory
    ceiling - a tenant taking the deployment down without reading anything they
    were not entitled to.
    """

    async def test_the_object_arrives_in_bounded_chunks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.file_storage.STREAM_CHUNK_BYTES", 4)
        client = _Client(objects={"u/1/a.bin": b"0123456789"})

        chunks = [c async for c in await S3FileStorage(client, "files").open_stream("u/1/a.bin")]

        assert chunks == [b"0123", b"4567", b"89"]
        assert client.bodies[0].closed

    async def test_a_missing_object_raises_before_the_first_chunk(self) -> None:
        """The route answers 404 for this, and it can only do that while nothing
        has gone out yet - a stream that dies mid-body is a truncated file."""
        with pytest.raises(FileNotFoundError):
            await S3FileStorage(_Client(), "files").open_stream("u/1/gone.bin")

    async def test_the_local_backend_hands_over_what_it_has(self, tmp_path: Any) -> None:
        """The default on the base class. Local files are served by
        `FileResponse` rather than through this, so one chunk is the honest
        answer and there is nothing to bound."""
        storage = LocalFileStorage(base_dir=tmp_path)
        stored = await storage.save("u", "a.bin", b"bytes")

        assert [c async for c in await storage.open_stream(stored)] == [b"bytes"]


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

    def test_half_a_key_pair_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Silently falling through to boto3's chain authenticates as a principal
        the operator did not name, on any host with an instance or task role -
        and everywhere else fails with "no credentials" about a key they did
        supply."""
        monkeypatch.setattr(settings, "FILE_STORAGE_S3_ACCESS_KEY", "AKIA")
        monkeypatch.setattr(settings, "FILE_STORAGE_S3_SECRET_KEY", "")

        with pytest.raises(RuntimeError, match="must both be set"):
            build_s3_client()

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
