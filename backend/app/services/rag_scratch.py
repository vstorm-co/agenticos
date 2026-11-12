"""The parse scratch copies under `MEDIA_DIR/_rag_tmp` (#2681).

With local storage an upload, and each retry, writes bytes here for its
`ingest-document` job; the API and worker share this directory. Each dispatch
owns its copy. With S3 the worker downloads into an execution-private temporary
directory instead, so pods need no shared filesystem (see `parse_source`).

That job removes it once no attempt of it is coming, a document delete removes
its copies after the commit, and `sweep_stale` removes whatever a lost job or a
deployment from before #2681 left. Until then every copy stayed for good: the
content of a deleted document, base or account remained on the media volume.
"""

import logging
import tempfile
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.blocking import run_blocking
from app.core.config import settings
from app.repositories import rag_document_repo

logger = logging.getLogger(__name__)

SCRATCH_DIRECTORY = "_rag_tmp"

# A copy is written before the request that queues its job commits, so for a
# moment it names a document no other session can see - or, for a retry, one
# still reading `error`. An hour is far past any commit, and a copy a live job
# still needs is kept by its document being `processing`, not by its age.
_STALE_AFTER = timedelta(hours=1)

# Ids per lookup: one bind parameter each, under the driver's limit however
# much a deployment from before #2681 accumulated.
_LOOKUP_BATCH = 1000


@dataclass(frozen=True)
class ScratchSweep:
    removed: int
    kept: int


@asynccontextmanager
async def parse_source(filepath: Path, *, storage_path: str | None) -> AsyncGenerator[Path]:
    """Open a worker-local copy for S3, or retain the shared local-storage path.

    Each S3 execution owns its directory, including overlapping lease attempts.
    A retry downloads again; cancellation and parser failures remove its copy.
    Storage errors propagate to the job rather than parsing an absent API file.
    """
    if storage_path is None:
        yield filepath
        return

    from app.services.file_storage import get_file_storage

    data = await get_file_storage().load(storage_path)
    with tempfile.TemporaryDirectory(prefix="agenticos-ingest-") as directory:
        path = Path(directory) / f"document{filepath.suffix.lower()}"
        async with await anyio.open_file(path, "wb") as file:
            await file.write(data)
        yield path


def scratch_dir() -> Path:
    return Path(settings.MEDIA_DIR) / SCRATCH_DIRECTORY


def _suffix(filename: str) -> str:
    return Path(filename).suffix.lower()


def scratch_path(document_id: UUID, *, attempt: int, filename: str) -> Path:
    """Where one dispatch of a document puts its copy.

    One file per dispatch, not per document: a job's cleanup can run after the
    person already pressed Retry (its settler may run late), and with a shared
    name it would remove the copy the retry just wrote.
    """
    return scratch_dir() / f"{document_id}-{attempt}{_suffix(filename)}"


def discard(path: str | Path) -> bool:
    """Remove one copy; whether a file was removed.

    A filesystem failure is logged, not raised: this runs as an ingest job
    ends, and an unlink that failed must not replace the job's own outcome. A
    path outside the scratch directory comes off a job's payload and is refused
    rather than unlinked.
    """
    candidate = Path(path)
    try:
        # By the directory's name, not its resolved path: the worker may spell
        # `MEDIA_DIR` differently from the API that wrote the payload.
        if candidate.parent.name != SCRATCH_DIRECTORY:
            logger.warning("Refusing to remove %s: not a parse scratch copy", candidate)
            return False
        candidate.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("Failed to remove the parse scratch copy %s: %s", candidate, exc)
        return False
    return True


async def discard_document(document_id: UUID, *, filename: str, attempts: int) -> int:
    """Remove every copy a document's dispatches can have left; how many were there.

    The names are known - one per attempt, and the single name a deployment
    from before #2681 used - so nothing scans the directory. Off the event loop,
    like every other unlink in a request process (#1294).
    """
    suffix = _suffix(filename)
    names = [f"{document_id}{suffix}"]
    names += [f"{document_id}-{attempt}{suffix}" for attempt in range(1, attempts + 1)]
    paths = [scratch_dir() / name for name in names]
    return await run_blocking(_discard_all, paths)


def _discard_all(paths: list[Path]) -> int:
    return sum(discard(path) for path in paths)


def _document_of(name: str) -> UUID | None:
    try:
        return UUID(name[:36])
    except ValueError:
        return None


def _aged_copies(directory: Path, cutoff: float) -> dict[Path, UUID]:
    """Each copy written before `cutoff`, by the document its name says it is."""
    if not directory.is_dir():
        return {}
    candidates: dict[Path, UUID] = {}
    for path in directory.iterdir():
        document_id = _document_of(path.name)
        if document_id is None:
            continue
        try:
            if not path.is_file() or path.stat().st_mtime > cutoff:
                continue
        except FileNotFoundError:
            continue
        candidates[path] = document_id
    return candidates


async def sweep_stale(db: AsyncSession, *, now: datetime) -> ScratchSweep:
    """Remove the copies no job will parse again.

    One whose document is gone or no longer `processing`, and older than
    `_STALE_AFTER`. A copy of a `processing` document is kept: its job may be
    queued or retrying. A name that is not a document's is left alone.

    The directory is read and unlinked on the file pool, not the worker's loop:
    the first sweep after an upgrade walks every copy earlier releases left, and
    the loop it would block also renews every running job's lease.
    """
    candidates = await run_blocking(_aged_copies, scratch_dir(), (now - _STALE_AFTER).timestamp())
    ids = sorted(set(candidates.values()))
    processing: set[UUID] = set()
    for start in range(0, len(ids), _LOOKUP_BATCH):
        processing |= await rag_document_repo.processing_among(
            db, ids[start : start + _LOOKUP_BATCH]
        )
    stale = [path for path, document_id in candidates.items() if document_id not in processing]
    removed = await run_blocking(_discard_all, stale)
    return ScratchSweep(removed=removed, kept=len(candidates) - len(stale))
