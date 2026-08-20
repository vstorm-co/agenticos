"""File storage service for chat file uploads.

Supports local filesystem storage.
Files are organized per-user: {storage_root}/{user_id}/{uuid}_{filename}
"""

import logging
import mimetypes
import os
import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

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


def image_media_type_for(path: str) -> str | None:
    """The image media type this file may be served as, or `None` to refuse it.

    Guessed from the name on disk and checked against `IMAGE_MIME_TYPES`. An
    avatar is stored under whatever suffix the uploader's filename had, so a file
    saved as `x.html` guesses to `text/html` and is refused here rather than
    served as a script on the app's own origin (#702, and #634 for the logo).
    """
    media_type = mimetypes.guess_type(path)[0]
    return media_type if media_type in IMAGE_MIME_TYPES else None


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
        file_path.write_bytes(data)
        return f"{safe_user}/{storage_name}"

    async def load(self, storage_path: str) -> bytes:
        file_path = self._resolve_safe_path(storage_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {storage_path}")
        return file_path.read_bytes()

    async def delete(self, storage_path: str) -> None:
        file_path = self._resolve_safe_path(storage_path)
        if file_path.exists():
            file_path.unlink()

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
