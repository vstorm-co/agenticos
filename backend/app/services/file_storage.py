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
import shutil
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.blocking import (
    create_cancel_safe,
    delete_cancel_safe,
    run_blocking,
    write_bytes_cancel_safe,
)
from app.core.config import settings

if TYPE_CHECKING:
    from botocore.client import BaseClient

logger = logging.getLogger(__name__)

# What S3 says when the object is not there. Anything else a request comes back
# with - a refused policy, a throttle, an outage - is a fact about the store
# rather than about the object, and is never reported as "missing".
_MISSING_OBJECT_CODES = frozenset({"NoSuchKey", "NoSuchBucket", "404"})

# How much of an object is in this process at once while it is being served.
# Small enough that a burst of concurrent downloads is bounded by the number of
# requests rather than by the size of what they asked for; large enough that a
# 50 MB document is not fifty thousand round trips.
STREAM_CHUNK_BYTES = 256 * 1024


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


async def delete_prefix_best_effort(prefix: str) -> None:
    """Remove everything under one prefix, logging - not raising on - a failure.

    Handed to `spawn_after_commit` by the teardown paths, for
    `delete_files_best_effort`'s reason: a removal before the commit is undone by
    a rollback as files already gone, leaving restored rows pointing at nothing
    (#1293).

    A failure is logged rather than swallowed: the rows that referenced these
    bytes are gone by now, so nothing else will ever name this prefix and the
    warning is its only remaining trace.
    """
    try:
        removed = await get_file_storage().delete_prefix(prefix)
    except Exception as exc:
        logger.warning("Failed to remove stored prefix %s: %s", prefix, exc)
        return
    if removed:
        logger.info("storage_prefix_removed", extra={"prefix": prefix, "files": removed})


# The canonical MIME strings for the office/legacy/email formats FA-013 adds, so
# the tables below and the allowlist name one string rather than repeating it.
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_XLSM_MIME = "application/vnd.ms-excel.sheet.macroEnabled.12"
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_DOC_MIME = "application/msword"
_XLS_MIME = "application/vnd.ms-excel"
_MSG_MIME = "application/vnd.ms-outlook"
_ODT_MIME = "application/vnd.oasis.opendocument.text"
_ODS_MIME = "application/vnd.oasis.opendocument.spreadsheet"
_ODP_MIME = "application/vnd.oasis.opendocument.presentation"
_TIFF_MIME = "image/tiff"

ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    _TIFF_MIME,
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "text/css",
    "text/xml",
    "application/xml",
    "text/x-python",
    "text/javascript",
    "text/x-yaml",
    "application/json",
    "application/pdf",
    _DOCX_MIME,
    _DOC_MIME,
    _ODT_MIME,
    # Spreadsheets: the two OOXML ones, legacy `.xls` (xlrd) and OpenDocument
    # `.ods` (odfpy). Each has a reader; a type accepted here that nothing can
    # parse would reach an agent without a workspace as nothing at all.
    _XLSX_MIME,
    _XLSM_MIME,
    _XLS_MIME,
    _ODS_MIME,
    _PPTX_MIME,
    _ODP_MIME,
    _MSG_MIME,
    "application/x-yaml",
}

IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# TIFF is accepted but is *not* web-safe: a browser cannot draw it inline, so it is
# kept out of `RENDER_SAFE_MIME_TYPES` and converted to PNG only at the point it is
# shown to the model (`attachments.py`).
#
# Types safe to render inline on a browser tab from this deployment's own origin.
# Anything a chat attachment may hold that is not here - `text/html`, an SVG, a
# spreadsheet, a TIFF - is served as a download rather than displayed, so it
# cannot run as a script on the origin the app itself is served from (#702).
RENDER_SAFE_MIME_TYPES = IMAGE_MIME_TYPES | {"application/pdf"}

# A canonical format token, resolved from the declared MIME + extension + (byte
# phase) signature, drives parser dispatch and inline conversion - the declared
# MIME alone cannot, because browsers send `application/octet-stream` for `.msg`,
# `.odt`, `.xls` and often `.doc`/`.tiff` (#1591, §7 finding 1).
_MIME_TO_FORMAT = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
    _TIFF_MIME: "tiff",
    "application/pdf": "pdf",
    _DOCX_MIME: "docx",
    _DOC_MIME: "doc",
    _ODT_MIME: "odt",
    _XLSX_MIME: "xlsx",
    _XLSM_MIME: "xlsx",
    _XLS_MIME: "xls",
    _ODS_MIME: "ods",
    _PPTX_MIME: "pptx",
    _ODP_MIME: "odp",
    _MSG_MIME: "msg",
}

_EXTENSION_TO_FORMAT = {
    "png": "png",
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "gif": "gif",
    "webp": "webp",
    "tif": "tiff",
    "tiff": "tiff",
    "pdf": "pdf",
    "docx": "docx",
    "doc": "doc",
    "odt": "odt",
    "xlsx": "xlsx",
    "xlsm": "xlsx",
    "xls": "xls",
    "ods": "ods",
    "pptx": "pptx",
    "odp": "odp",
    "msg": "msg",
}

_FORMAT_TO_MIME = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "tiff": _TIFF_MIME,
    "pdf": "application/pdf",
    "docx": _DOCX_MIME,
    "doc": _DOC_MIME,
    "odt": _ODT_MIME,
    "xlsx": _XLSX_MIME,
    "xls": _XLS_MIME,
    "ods": _ODS_MIME,
    "pptx": _PPTX_MIME,
    "odp": _ODP_MIME,
    "msg": _MSG_MIME,
}

_FORMAT_TO_FILE_TYPE = {
    "png": "image",
    "jpeg": "image",
    "gif": "image",
    "webp": "image",
    "tiff": "image",
    "pdf": "pdf",
    "docx": "docx",
    "doc": "document",
    "odt": "document",
    "xlsx": "spreadsheet",
    "xls": "spreadsheet",
    "ods": "spreadsheet",
    "pptx": "presentation",
    "odp": "presentation",
    "msg": "email",
    "text": "text",
}

# A per-extension canonical MIME for the text family, so an octet-stream `.xml`
# or `.csv` is stored with a truthful type rather than the declared blob.
_EXTENSION_TO_TEXT_MIME = {
    "txt": "text/plain",
    "md": "text/markdown",
    "csv": "text/csv",
    "html": "text/html",
    "htm": "text/html",
    "css": "text/css",
    "xml": "application/xml",
    "json": "application/json",
    "py": "text/x-python",
    "js": "text/javascript",
    "yaml": "text/x-yaml",
    "yml": "text/x-yaml",
}

# Every extension the allowlist accepts, so a browser that sends
# `application/octet-stream` (or nothing) for a file it cannot type is validated
# on the extension instead (#1591, §2.3).
ALLOWED_EXTENSIONS = (
    set(_EXTENSION_TO_FORMAT)
    | set(_EXTENSION_TO_TEXT_MIME)
    | {"markdown", "ts", "tsx", "toml", "sql", "sh"}
)

_GENERIC_MIME_TYPES = {"", "application/octet-stream"}

# The accepted *specific* text MIME types: everything the allowlist accepts that is
# not one of the recognised binary/image formats. A declaration from this set on a
# binary extension (`text/plain` on `photo.png`) is a contradiction the byte phase
# cannot catch - images and PDF are not sniffed - so it is a conflict here (#1591).
_TEXT_MIME_TYPES = ALLOWED_MIME_TYPES - _MIME_TO_FORMAT.keys()


def normalize_media_type(content_type: str | None) -> str:
    """A media type lowercased and stripped of parameters (`; charset=utf-8`)."""
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def file_extension(filename: str) -> str:
    """The lowercase extension of a filename, or `""` when it has none."""
    return filename.lower().rsplit(".", 1)[-1] if "." in filename else ""


def resolve_format(mime_type: str | None, filename: str) -> str:
    """The canonical format token for a file.

    A specific, recognised declared MIME wins; the extension is the fallback for a
    missing or generic (`application/octet-stream`) type, and for a specific type
    this path does not recognise. Anything else is `"text"` - the historic default
    of `classify_file`. Validation, not this, rejects a MIME that *contradicts* the
    extension; here the declared MIME is simply believed when it is specific.
    """
    fmt = _MIME_TO_FORMAT.get(normalize_media_type(mime_type))
    if fmt is not None:
        return fmt
    return _EXTENSION_TO_FORMAT.get(file_extension(filename), "text")


def canonical_mime(mime_type: str | None, filename: str) -> str:
    """The MIME to persist on `ChatFile.mime_type`, resolved not just declared.

    For every recognised binary format this is the format's own canonical type, so
    an `application/octet-stream` `.tiff` is stored as `image/tiff` and the
    download route and the inline-conversion path read one trustworthy field. For
    the text family the declared type is kept when it is one we accept, else a
    per-extension guess, else `text/plain`.
    """
    fmt = resolve_format(mime_type, filename)
    known = _FORMAT_TO_MIME.get(fmt)
    if known is not None:
        # `.xlsm` shares the `xlsx` format token (one parser, one coarse file type),
        # but a macro-enabled workbook must not be persisted - and so served by the
        # download route - as an ordinary `.xlsx`. Its own accepted MIME is kept when
        # the extension or the declared type says macro-enabled (#1591).
        if fmt == "xlsx" and (
            normalize_media_type(mime_type) == _XLSM_MIME or file_extension(filename) == "xlsm"
        ):
            return _XLSM_MIME
        return known
    normalized = normalize_media_type(mime_type)
    if normalized in ALLOWED_MIME_TYPES:
        return normalized
    return _EXTENSION_TO_TEXT_MIME.get(file_extension(filename), "text/plain")


def sniff_container(data: bytes) -> str | None:
    """The container a file's own first bytes say it is: TIFF, OLE, ZIP, or `None`.

    Cheap and bounded - a handful of leading bytes - and enough to catch a forged
    signature that contradicts the resolved format before a parser is handed it.
    OLE (`D0 CF 11 E0`) backs legacy DOC/XLS/MSG; ZIP (`PK\\x03\\x04`) backs the
    OOXML and OpenDocument formats; TIFF is little- or big-endian.
    """
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "ole"
    if data[:4] == b"PK\x03\x04":
        return "zip"
    return None


# The container each recognised format must present in the byte phase. A format
# absent here (PDF, the images beyond TIFF, the text family) is not sniffed.
_FORMAT_TO_CONTAINER = {
    "tiff": "tiff",
    "doc": "ole",
    "xls": "ole",
    "msg": "ole",
    "docx": "zip",
    "xlsx": "zip",
    "pptx": "zip",
    "odt": "zip",
    "ods": "zip",
    "odp": "zip",
}


def has_format_conflict(mime_type: str | None, filename: str) -> bool:
    """Whether a *specific* declared MIME names a different format than the extension.

    `application/msword` on `photo.tiff`, or `image/png` on `payload.doc`: both a
    recognised, non-generic MIME and a recognised extension, disagreeing. An accepted
    *text* MIME on a binary extension (`text/plain` on `photo.png`) is a conflict too,
    since the byte phase does not sniff images or PDF and would otherwise route the
    bytes by extension. A generic MIME, an unrecognised one, or a text MIME on a text
    extension (which it refines rather than contradicts) is not a conflict.
    """
    normalized = normalize_media_type(mime_type)
    if normalized in _GENERIC_MIME_TYPES:
        return False
    ext_fmt = _EXTENSION_TO_FORMAT.get(file_extension(filename))
    if ext_fmt is None:
        return False
    mime_fmt = _MIME_TO_FORMAT.get(normalized)
    if mime_fmt is not None:
        return mime_fmt != ext_fmt
    # A specific text MIME (`text/plain`, `application/xml`, …) declared on a binary
    # extension (`photo.png`, `report.pdf`) is a contradiction that the byte phase
    # cannot catch, since images and PDF carry no sniffed container: refuse it here
    # rather than believe the extension and route arbitrary text bytes as an image
    # (#1591).
    return normalized in _TEXT_MIME_TYPES


def expected_container(mime_type: str | None, filename: str) -> str | None:
    """The container the resolved format must present, or `None` when unsniffed."""
    return _FORMAT_TO_CONTAINER.get(resolve_format(mime_type, filename))


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
    """Classify a file into the coarse `file_type` the router and DB row carry.

    Derived from the canonical format (`resolve_format`), so `document`,
    `presentation` and `email` join the historic `image | pdf | docx | spreadsheet
    | text`. The office/OpenDocument binaries are their own kinds rather than
    "text": their bytes are a zip or OLE container that a UTF-8 decode turns to
    mojibake, and the workspace needs to know to write the extraction beside the
    original the way it does for a PDF.
    """
    return _FORMAT_TO_FILE_TYPE[resolve_format(mime_type, filename)]


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

    async def save_at(self, storage_path: str, data: bytes) -> None:
        """Write `data` at exactly this path, rather than minting a name for it.

        The pair of :meth:`save`, for the one caller whose key is not this
        backend's to choose: content-addressed media, whose path *is* the digest
        of its bytes, so a second write of the same content has to land on the
        same object (#55). Everything a person uploads goes through `save`, which
        mints a unique name so two people attaching `invoice.pdf` do not collide.

        Overwrites. With a content address that is a write of identical bytes;
        with anything else it would be the caller's decision, and no caller in
        this codebase makes it.

        **It does not undo itself on cancellation**, which is the one way it
        differs from :meth:`save`. A cancelled upload leaves an orphan nobody can
        reach, so `save` removes what it wrote; a cancelled content-addressed
        write leaves a file *another writer may already be depending on*, because
        two callers writing the same digest write the same bytes to the same
        path. Removing it there would break the marker that names it, and the
        thing it would have saved is a file identical to one that belongs there.
        The bytes are bounded by the prefix they live under, which is deleted
        with the thing that references them.

        Not abstract, so a backend that cannot honour a caller-chosen key says so
        at the one call site rather than failing to import - and so adding a
        backend does not mean implementing a method it may have no use for.
        """
        raise NotImplementedError(
            f"{type(self).__name__} cannot write to a caller-chosen path"
        )  # pragma: no cover - every backend in this codebase implements it

    async def delete_prefix(self, prefix: str) -> int:
        """Remove everything stored under one path prefix; returns the count.

        What gives content-addressed media a lifetime. A digest records nothing
        about who still references it, so the objects are stored under the
        prefix of the thing that does - a conversation, and a tenant above it -
        and removed when *it* goes (#55).

        Not abstract, for `save_at`'s reason: a backend with no use for it says
        so at the call site rather than failing to import.
        """
        raise NotImplementedError(
            f"{type(self).__name__} cannot delete a prefix"
        )  # pragma: no cover - every backend in this codebase implements it

    async def open_stream(self, storage_path: str) -> AsyncIterator[bytes]:
        """The file's bytes in chunks, for a caller that must not hold it whole.

        The default reads it whole and yields one chunk, which is right for a
        backend whose files are already on this host - the serving routes hand
        those to `FileResponse`, which streams from disk and answers a range
        request. A backend whose objects arrive over the network overrides it.

        The object is *opened here*, not on the first chunk, so a missing file
        raises before a response has started going out and the route can still
        answer 404 (#1423).

        Raises:
            FileNotFoundError: the backend does not hold that path.
        """
        data = await self.load(storage_path)

        async def _one() -> AsyncIterator[bytes]:
            yield data

        return _one()

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

    async def save_at(self, storage_path: str, data: bytes) -> None:
        file_path = self._resolve_safe_path(storage_path)
        await run_blocking(self._write_at_blocking, file_path, data)

    @staticmethod
    def _write_at_blocking(file_path: Path, data: bytes) -> None:
        """Both syscalls on the pool. `mkdir` is one too, and on a network-backed
        volume it is the slow one."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(data)

    async def delete_prefix(self, prefix: str) -> int:
        """On the pool, and not cancellation-shielded.

        The teardown runs after the commit that removed what referenced these
        bytes, so a cancellation part-way leaves files nothing points at - which
        is what the *next* teardown of the same prefix removes, and what the
        prefix exists to bound. Shielding an `rmtree` of unknown size would hold
        a pool worker through a shutdown for no gain.
        """
        directory = self._resolve_safe_path(prefix)
        return await run_blocking(self._delete_prefix_blocking, directory)

    @staticmethod
    def _delete_prefix_blocking(directory: Path) -> int:
        """Remove a directory and everything in it; answer with the file count.

        Missing is not an error: a conversation that offloaded nothing has no
        directory, and the teardown must not care.
        """
        if not directory.is_dir():
            return 0
        count = sum(1 for path in directory.rglob("*") if path.is_file())
        shutil.rmtree(directory, ignore_errors=True)
        return count

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
        """The server-side-encryption arguments every `put_object` carries.

        `sse-kms` always names its key, and `get_file_storage` refuses to build a
        backend that does not have one. A `ServerSideEncryption: aws:kms` with no
        `SSEKMSKeyId` does **not** fall back to the bucket's default key, which
        is what this looked like it did: S3 encrypts under the AWS-managed
        `aws/s3` key instead. A deployment whose bucket default is a
        customer-managed key would have stored data under the wrong one, or had
        the write refused by a policy requiring theirs.
        """
        mode = settings.FILE_STORAGE_S3_ENCRYPTION
        if mode == "sse-s3":
            return {"ServerSideEncryption": "AES256"}
        if mode == "sse-kms":
            return {
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": settings.FILE_STORAGE_S3_KMS_KEY_ID or "",
            }
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
        key = self._key(storage_path)
        # Cancellation-safe for the reason the local backend's write is: an
        # executor cannot interrupt a running `put_object`, so a cancelled
        # request would unwind with the object written and its key never
        # returned - bytes nothing points at, paid for every month until
        # somebody goes looking (#1108's failure in a bucket).
        await create_cancel_safe(self._put_blocking, partial(self._delete_blocking, key), key, data)
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
            if exc.response.get("Error", {}).get("Code") in _MISSING_OBJECT_CODES:
                raise FileNotFoundError(f"File not found: {key}") from exc
            raise
        body: Any = response["Body"]
        try:
            read: bytes = body.read()
        finally:
            body.close()
        return read

    async def save_at(self, storage_path: str, data: bytes) -> None:
        """Write at exactly this key, for the content-addressed store (#55).

        Not cancellation-safe, and deliberately - the base class says why: two
        callers writing one digest write identical bytes to one key, so undoing
        a cancelled write would remove an object another writer is already
        depending on. The prefix it lives under is its lifetime.
        """
        await run_blocking(self._put_blocking, self._key(storage_path), data)

    async def delete(self, storage_path: str) -> None:
        await delete_cancel_safe(self._delete_blocking, self._key(storage_path))

    def _delete_blocking(self, key: str) -> None:
        """`delete_object` is already idempotent: S3 answers 204 for a key that
        was never there, which is what the best-effort teardown loops need."""
        self.client.delete_object(Bucket=self.bucket, Key=key)

    async def delete_prefix(self, prefix: str) -> int:
        """Remove every object under one key prefix; returns how many went.

        What gives offloaded media a lifetime on this backend too (#55): a
        digest records nothing about who references it, so the objects hang off
        the conversation's prefix and go when it does. Without this an S3
        deployment would keep every picture any compacted history ever held.

        Listed and deleted in pages, because a bucket is not a directory: there
        is nothing to remove but the keys themselves, and a thread holds only one
        page of them at a time.
        """
        return await run_blocking(self._delete_prefix_blocking, self._key(prefix))

    def _delete_prefix_blocking(self, key_prefix: str) -> int:
        removed = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=f"{key_prefix}/"):
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if not keys:
                continue
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})
            removed += len(keys)
        return removed

    async def exists(self, storage_path: str) -> bool:
        try:
            key = self._key(storage_path)
        except ValueError:
            return False
        return await run_blocking(self._head_blocking, key)

    async def open_stream(self, storage_path: str) -> AsyncIterator[bytes]:
        """One object, in bounded chunks, never held whole in this process.

        A knowledge-base document can be 50 MB, and the route serving it has no
        rate limit of its own - so a handful of concurrent downloads buffered in
        full is the API container's memory ceiling, which is a tenant taking the
        deployment down without reading anything they were not entitled to.

        `get_object` runs first and raises `FileNotFoundError` for a key that is
        not there, so the 404 is decided before the response starts.
        """
        body = await run_blocking(self._open_blocking, self._key(storage_path))
        return self._chunks(body)

    def _open_blocking(self, key: str) -> Any:
        """The open body of one object, translating a miss the way `load` does."""
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING_OBJECT_CODES:
                raise FileNotFoundError(f"File not found: {key}") from exc
            raise
        return response["Body"]

    async def _chunks(self, body: Any) -> AsyncIterator[bytes]:
        """Read the open body a chunk at a time, on the file pool.

        `body.read(n)` is a blocking socket read, so it belongs off the loop for
        the reason every other call here does. The body is closed however the
        iteration ends - botocore holds the connection until it is, and a pool
        that runs out of them stalls every later read.
        """
        try:
            while True:
                chunk: bytes = await run_blocking(body.read, STREAM_CHUNK_BYTES)
                if not chunk:
                    return
                yield chunk
        finally:
            await run_blocking(body.close)

    def _head_blocking(self, key: str) -> bool:
        """Whether the object is there, and only that.

        A blanket `except ClientError` would answer "not there" for an
        `AccessDenied`, a throttle or an outage - so a bad bucket policy would
        read as an agent with no avatar and a knowledge base whose documents
        have all been deleted, which is the wrong thing for anybody to act on.
        Only the codes that mean "no such object" answer `False`; everything
        else is the caller's to see.
        """
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING_OBJECT_CODES:
                return False
            raise
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

    key_id = settings.FILE_STORAGE_S3_ACCESS_KEY
    secret = settings.FILE_STORAGE_S3_SECRET_KEY
    if bool(key_id) != bool(secret):
        # Half a key pair silently falls through to boto3's own chain, which on a
        # host with an instance or task role authenticates as a principal the
        # operator did not name - and everywhere else fails with "no credentials"
        # about a key they did supply.
        raise RuntimeError(
            "FILE_STORAGE_S3_ACCESS_KEY and FILE_STORAGE_S3_SECRET_KEY must both be set "
            "or both be empty; empty means boto3's own credential chain answers"
        )
    client_kwargs: dict[str, Any] = {"region_name": settings.FILE_STORAGE_S3_REGION}
    if key_id and secret:
        client_kwargs["aws_access_key_id"] = key_id
        client_kwargs["aws_secret_access_key"] = secret
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
            if (
                settings.FILE_STORAGE_S3_ENCRYPTION == "sse-kms"
                and not settings.FILE_STORAGE_S3_KMS_KEY_ID
            ):
                # Not a default anybody can fall back to: S3 reads an unnamed
                # `aws:kms` as its own `aws/s3` key rather than as the bucket's
                # configured one, so a deployment that asked for a client-held
                # key and named none would get neither and be told nothing.
                raise RuntimeError(
                    "FILE_STORAGE_S3_ENCRYPTION=sse-kms needs FILE_STORAGE_S3_KMS_KEY_ID; "
                    "S3 reads an unnamed aws:kms as the AWS-managed aws/s3 key, not as the "
                    "bucket's default"
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
