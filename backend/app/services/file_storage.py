"""File storage service for chat file uploads.

Two backends, chosen by `FILE_STORAGE_BACKEND` at deployment time and never per
organization: the local filesystem, and any S3-compatible object store. Files
are organized per owner in both - `{owner}/{uuid}_{filename}` is the storage
path a row records, a directory under `MEDIA_DIR` in one and a key under an
optional prefix in the other.

Local is the default and stays the honest answer for a single host with an
encrypted volume. It stops being one the moment there are two API replicas
sharing no disk, or a client asks for object storage under their own KMS key,
which is what the S3 backend is for (#1423). Neither migrates what the other
holds; switching backend leaves the files already written where they were.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.blocking import delete_cancel_safe, run_blocking, write_bytes_cancel_safe
from app.core.config import settings

if TYPE_CHECKING:
    from botocore.client import BaseClient

logger = logging.getLogger(__name__)


async def delete_files_best_effort(storage_paths: list[str]) -> None:
    """Unlink stored uploads best-effort, logging - not raising on - a failure.

    Handed to `spawn_after_commit` by the teardown paths, so the unlinks run only
    once the transaction that removed the rows has committed: an unlink before the
    commit is undone by a rollback as a file already gone, leaving the restored row
    pointing at nothing (#1293). Takes ids, holds nothing of the request session,
    and resolves the storage backend when it runs.

    A failure is logged rather than swallowed: the row that named the file is gone
    by now, so a silent failure leaves an orphan nothing else can find - the warning
    is the only remaining trace of which path it was.
    """
    storage = get_file_storage()
    for storage_path in storage_paths:
        try:
            await storage.delete(storage_path)
        except Exception as exc:
            logger.warning("Failed to unlink stored file %s: %s", storage_path, exc)


ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "text/css",
    "text/xml",
    "text/x-python",
    "text/javascript",
    "text/x-yaml",
    "application/json",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    # Spreadsheets, and only the two OOXML ones. `.xls` is a different format
    # needing a different reader, and a type accepted here that nothing can parse
    # is worse than this refusal: an attachment with no text reaches an agent
    # without a workspace as nothing at all.
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
    "application/x-yaml",
}

SPREADSHEET_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
}

IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Types safe to render inline on a browser tab from this deployment's own origin.
# Anything a chat attachment may hold that is not here - `text/html`, an SVG, a
# spreadsheet - is served as a download rather than displayed, so it cannot run as
# a script on the origin the app itself is served from (#702).
RENDER_SAFE_MIME_TYPES = IMAGE_MIME_TYPES | {"application/pdf"}


def sniff_image_header(header: bytes) -> str | None:
    """The image media type a file's first bytes say it is, or `None`.

    The magic-number half of :func:`sniff_image_media_type`, split out because a
    stored file does not always have a path: an object store hands over bytes,
    and the same four types have to be recognised either way.
    """
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return None


def sniff_image_media_type(path: str) -> str | None:
    """The image media type a file's own bytes say it is, or `None` to refuse it.

    Read from the content, not the name on disk. An avatar is served from the
    app's own origin under a CSP that allows inline script, so a file whose bytes
    are HTML must never be served as anything a browser will run - and the stored
    name cannot be trusted to say what the bytes are: a `.png` uploaded with HTML
    inside it, or a valid image saved under a legacy extensionless name, both lie
    (#702). Matching the magic number answers for the bytes themselves, so the
    first is refused and the second still serves. Only the four image types this
    platform accepts are recognised; anything else - HTML, SVG, a PDF - is
    `None`.
    """
    try:
        with Path(path).open("rb") as handle:
            header = handle.read(16)
    except OSError:
        return None
    return sniff_image_header(header)


_AVATAR_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}


def avatar_filename(content_type: str) -> str:
    """The name to store an avatar under, its suffix taken from its type.

    The stored file is named for the content type the upload validated rather
    than for the caller's own filename, so what is on disk is self-describing
    whatever the client called it. Serving no longer depends on the name -
    `sniff_image_media_type` reads the bytes (#702) - so this is about a tidy,
    honest file on disk, not about correctness of the response.

    Raises:
        KeyError: If `content_type` is not one of the validated image types - the
            upload validates it first, so reaching this with anything else is a
            caller that skipped the check, and failing loudly is right.
    """
    return f"avatar.{_AVATAR_EXTENSIONS[content_type]}"


# Avatars are decoration rendered at 40px; the limit is what stops someone
# storing a 40MB photograph to be scaled down on every page load.
MAX_AVATAR_SIZE = 2 * 1024 * 1024


def classify_file(mime_type: str, filename: str) -> str:
    """Classify file type based on MIME type and extension."""
    if mime_type in IMAGE_MIME_TYPES:
        return "image"
    if mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
        return "pdf"
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "docx" or "wordprocessingml" in mime_type:
        return "docx"
    # Its own kind, not "text": the bytes are a zip of XML, so anything that
    # decodes them as UTF-8 gets mojibake, and the workspace needs to know to
    # write the extraction beside the original the way it does for a PDF.
    if ext in {"xlsx", "xlsm"} or mime_type in SPREADSHEET_MIME_TYPES:
        return "spreadsheet"
    return "text"


_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.\-]+")


def _sanitize_filename(filename: str) -> str:
    """Strip path separators, NULL bytes, and unsafe chars from a filename.

    The result is always a single path component with no traversal segments.
    Empty results fall back to `"file"` to preserve a non-empty name.
    """
    base = Path(filename).name.replace("\x00", "")
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", base).strip("._")
    return cleaned or "file"


def make_storage_filename(filename: str) -> str:
    """Create a unique storage filename to prevent collisions and path traversal."""
    safe = _sanitize_filename(filename)
    return f"{uuid.uuid4().hex[:12]}_{safe}"


class BaseFileStorage(ABC):
    """Abstract file storage backend."""

    @abstractmethod
    async def save(self, user_id: str, filename: str, data: bytes) -> str:
        """Save file and return storage path/key."""

    @abstractmethod
    async def load(self, storage_path: str) -> bytes:
        """Load file bytes by storage path."""

    @abstractmethod
    async def delete(self, storage_path: str) -> None:
        """Delete file by storage path."""

    @abstractmethod
    async def exists(self, storage_path: str) -> bool:
        """Whether this backend still holds the file that path names.

        Asked by the paths that decide whether to *advertise* a file - a hosted
        page's logo URL is only offered when the route behind it would answer
        something, because a browser cannot tell a 404 from a slow image.
        """

    def get_full_path(self, storage_path: str) -> Path | None:
        """The absolute filesystem path of a stored file, when there is one.

        `None` on any backend whose files are not on this host, which is what the
        serving routes read to decide between handing Starlette a path and
        loading the bytes themselves. Never a signal that the file is missing -
        :meth:`exists` answers that.
        """
        return None  # pragma: no cover


class LocalFileStorage(BaseFileStorage):
    """Store files on local filesystem."""

    def __init__(self, base_dir: str | Path = "media"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, storage_path: str) -> Path:
        """Resolve a storage path under base_dir, rejecting traversal attempts.

        The containment check is a `startswith` against the realpath of the root
        rather than a `Path.parents` membership test: both refuse the same paths,
        but only the first is a barrier static analysis recognises, so the second
        read as an unguarded path expression (CodeQL `py/path-injection`).

        It has to be the *whole* condition of its branch, which is why the root
        itself is answered before it rather than beside it. `py/path-injection`
        clears a normalised path where `startswith` alone decides the branch;
        written as `candidate != base and not candidate.startswith(prefix)`, the
        fall-through proves neither conjunct, so the guard stopped counting and
        both sinks in `load` stayed flagged (#903).
        """
        base = os.path.realpath(self.base_dir)
        candidate = os.path.realpath(Path(base) / storage_path)
        if candidate == base:
            return Path(base)
        # A filesystem root already ends in the separator, and `/` + `/` is a prefix
        # no descendant of it has.
        prefix = base if base.endswith(os.sep) else base + os.sep
        if not candidate.startswith(prefix):
            raise ValueError(f"Path escapes storage root: {storage_path}")
        return Path(candidate)

    async def save(self, user_id: str, filename: str, data: bytes) -> str:
        safe_user = _sanitize_filename(user_id)
        user_dir = self.base_dir / safe_user
        user_dir.mkdir(parents=True, exist_ok=True)
        storage_name = make_storage_filename(filename)
        file_path = user_dir / storage_name
        # Off the request loop (up to MAX_UPLOAD_SIZE bytes would otherwise stall
        # every other request on this worker), on the dedicated file pool, and
        # cancellation-safe: a cancelled upload must not leave a file whose path
        # the caller never received and so can neither record nor delete (#1108).
        await write_bytes_cancel_safe(file_path, data)
        return f"{safe_user}/{storage_name}"

    async def load(self, storage_path: str) -> bytes:
        file_path = self._resolve_safe_path(storage_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {storage_path}")
        return await run_blocking(file_path.read_bytes)

    async def delete(self, storage_path: str) -> None:
        await delete_cancel_safe(self._delete_blocking, storage_path)

    def _delete_blocking(self, storage_path: str) -> None:
        """The blocking half of :meth:`delete`, run on the file pool.

        `realpath` and `unlink` are blocking syscalls with no yield point, so a
        bulk teardown that unlinked a whole collection ran them all in one loop
        turn, stalling every other request on the worker (#1294). Off the loop,
        the per-file await also lets the teardown loops interleave.

        `missing_ok=True` rather than a check-then-unlink: two coroutines
        deleting one path now run on separate pool workers, so a guarded unlink
        would let both see the file, then one succeed and the other raise
        `FileNotFoundError`. The teardown loops call `delete` best-effort, so a
        path another path already removed must be a no-op.
        """
        self._resolve_safe_path(storage_path).unlink(missing_ok=True)

    async def exists(self, storage_path: str) -> bool:
        return self.get_full_path(storage_path) is not None

    def get_full_path(self, storage_path: str) -> Path | None:
        """Return absolute filesystem path for local files."""
        try:
            file_path = self._resolve_safe_path(storage_path)
        except ValueError:
            return None
        return file_path if file_path.exists() else None


class S3FileStorage(BaseFileStorage):
    """Store files in an S3-compatible object store, encrypted by the store.

    The same `{owner}/{uuid}_{filename}` storage path every row already records,
    used as an object key under `FILE_STORAGE_S3_PREFIX`. So a row written by one
    backend names a readable path under the other once the bytes are copied
    across, and nothing but this module knows which backend is running.

    **Encryption is asked for on every write** and is the reason this backend
    exists: `sse-s3` for the bucket's own key, `sse-kms` for a key the client
    brings. `none` is for a compatible store with no KMS behind it - MinIO
    refuses SSE-S3 without one - and `doctor` reports it as unconfigured.

    boto3 is synchronous, so every call runs on the same bounded file pool the
    local backend writes through: a 50 MB upload must not hold the event loop,
    and a cancelled request must not leave an object whose key the caller never
    received. There is no `get_full_path`: an object has no path on this host,
    which is what `BaseFileStorage`'s `None` default already says and what the
    serving routes read to decide between a file response and the bytes.
    """

    def __init__(self, client: BaseClient, bucket: str, *, prefix: str = "") -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _key(self, storage_path: str) -> str:
        """The object key one storage path names, refusing anything that climbs out.

        `..` in a key is not path traversal the way it is on a filesystem - S3
        treats it as a literal segment - but a deployment sharing one bucket
        between prefixes would still have its keys rewritten by a caller who
        could put one there, and the local backend refuses the same shape. So it
        is refused here rather than normalised, with the same `ValueError` the
        local backend raises, which the callers already handle.
        """
        cleaned = storage_path.strip("/")
        if not cleaned or any(part in {"..", "."} for part in cleaned.split("/")):
            raise ValueError(f"Path escapes storage root: {storage_path}")
        return f"{self.prefix}/{cleaned}" if self.prefix else cleaned

    def _encryption(self) -> dict[str, str]:
        """The server-side-encryption arguments every `put_object` carries."""
        mode = settings.FILE_STORAGE_S3_ENCRYPTION
        if mode == "sse-s3":
            return {"ServerSideEncryption": "AES256"}
        if mode == "sse-kms":
            args = {"ServerSideEncryption": "aws:kms"}
            if settings.FILE_STORAGE_S3_KMS_KEY_ID:
                args["SSEKMSKeyId"] = settings.FILE_STORAGE_S3_KMS_KEY_ID
            return args
        return {}

    async def save(self, user_id: str, filename: str, data: bytes) -> str:
        """The same storage path the local backend would have written.

        `_sanitize_filename` on the owner, which keeps only its last component -
        so `avatars/orgs/<id>` becomes `<id>`, exactly as on disk. Identical on
        both backends on purpose: a row written by one names a readable path
        under the other once the bytes are copied across.
        """
        safe_owner = _sanitize_filename(user_id)
        storage_name = make_storage_filename(filename)
        storage_path = f"{safe_owner}/{storage_name}"
        await run_blocking(self._put_blocking, self._key(storage_path), data)
        return storage_path

    def _put_blocking(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **self._encryption())

    async def load(self, storage_path: str) -> bytes:
        return await run_blocking(self._get_blocking, self._key(storage_path))

    def _get_blocking(self, key: str) -> bytes:
        """Read one object, translating "no such key" into the error callers expect.

        Every caller of `load` already handles `FileNotFoundError` - a row and its
        bytes can part company, and the routes answer 404 for it. botocore raises
        `ClientError` with a code instead, so a missing object would otherwise
        reach a route as a 500 naming AWS.
        """
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"NoSuchKey", "404", "NoSuchBucket"}:
                raise FileNotFoundError(f"File not found: {key}") from exc
            raise
        body: Any = response["Body"]
        try:
            read: bytes = body.read()
        finally:
            body.close()
        return read

    async def delete(self, storage_path: str) -> None:
        await delete_cancel_safe(self._delete_blocking, self._key(storage_path))

    def _delete_blocking(self, key: str) -> None:
        """`delete_object` is already idempotent: S3 answers 204 for a key that
        was never there, which is what the best-effort teardown loops need."""
        self.client.delete_object(Bucket=self.bucket, Key=key)

    async def exists(self, storage_path: str) -> bool:
        try:
            key = self._key(storage_path)
        except ValueError:
            return False
        return await run_blocking(self._head_blocking, key)

    def _head_blocking(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return False
        return True


def build_s3_client() -> BaseClient:
    """The boto3 client the S3 backend runs on, built from deployment settings.

    Deployment settings rather than an organization's vault secret, which is the
    opposite of the S3 *sync connector* beside it and deliberate: a sync source
    reads a bucket the tenant owns, under the tenant's own key, so the credential
    belongs to that tenant. This bucket belongs to the deployment and holds every
    tenant's files, so it is infrastructure - the same kind of setting as the
    database URL.

    With no key pair configured, boto3's own credential chain answers: an
    instance profile or an IRSA role, which is what a deployment on AWS should be
    using rather than a long-lived key in an environment file.
    """
    import boto3
    from botocore.config import Config

    client_kwargs: dict[str, Any] = {"region_name": settings.FILE_STORAGE_S3_REGION}
    if settings.FILE_STORAGE_S3_ACCESS_KEY and settings.FILE_STORAGE_S3_SECRET_KEY:
        client_kwargs["aws_access_key_id"] = settings.FILE_STORAGE_S3_ACCESS_KEY
        client_kwargs["aws_secret_access_key"] = settings.FILE_STORAGE_S3_SECRET_KEY
    if settings.FILE_STORAGE_S3_ENDPOINT:
        client_kwargs["endpoint_url"] = settings.FILE_STORAGE_S3_ENDPOINT
    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path" if settings.FILE_STORAGE_S3_PATH_STYLE else "auto"},
    )
    return boto3.client("s3", **client_kwargs, config=config)


_s3_storage: S3FileStorage | None = None


def get_file_storage() -> BaseFileStorage:
    """Factory: create file storage backend based on settings.

    The S3 backend is built once and reused. Its client opens a connection pool
    and reads the credential chain, and this is called per request - a fresh
    client per attachment would do both every time. The local backend stays
    per-call: it is a `Path` and an `mkdir`.
    """
    if settings.FILE_STORAGE_BACKEND == "s3":
        global _s3_storage
        if _s3_storage is None:
            if not settings.FILE_STORAGE_S3_BUCKET:
                raise RuntimeError(
                    "FILE_STORAGE_BACKEND=s3 needs FILE_STORAGE_S3_BUCKET set to the bucket to write to"
                )
            _s3_storage = S3FileStorage(
                build_s3_client(),
                settings.FILE_STORAGE_S3_BUCKET,
                prefix=settings.FILE_STORAGE_S3_PREFIX,
            )
        return _s3_storage
    media_dir = getattr(settings, "MEDIA_DIR", "media")
    return LocalFileStorage(base_dir=media_dir)


def reset_file_storage() -> None:
    """Forget the built S3 backend, so the next call reads the settings again.

    For tests, which move `FILE_STORAGE_*` between cases, and for nothing else:
    a running deployment reads its settings once at start.
    """
    global _s3_storage
    _s3_storage = None
