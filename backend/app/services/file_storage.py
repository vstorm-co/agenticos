"""File storage service for chat file uploads.

Supports local filesystem storage.
Files are organized per-user: {storage_root}/{user_id}/{uuid}_{filename}
"""

import logging
import os
import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.blocking import delete_cancel_safe, run_blocking, write_bytes_cancel_safe
from app.core.config import settings

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
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return None


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

    def get_full_path(self, storage_path: str) -> Path | None:
        """Return absolute filesystem path if available (local storage only)."""
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

    def get_full_path(self, storage_path: str) -> Path | None:
        """Return absolute filesystem path for local files."""
        try:
            file_path = self._resolve_safe_path(storage_path)
        except ValueError:
            return None
        return file_path if file_path.exists() else None


def get_file_storage() -> BaseFileStorage:
    """Factory: create file storage backend based on settings."""
    media_dir = getattr(settings, "MEDIA_DIR", "media")
    return LocalFileStorage(base_dir=media_dir)
