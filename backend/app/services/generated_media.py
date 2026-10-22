"""Where media an agent generated is kept, how it is read back, and how long it stays.

Images, speech and video (#2259, #2260) use the same store. The kind of file is
carried by its extension and nothing else - the serving route types it from the
suffix, through the same allowlist the workspace routes use.

Agent-generated media is **organization-scoped**, and that is the whole of its
tenancy: the bytes live under a per-organization directory in the same file
store chat uploads and RAG documents use, and a file is addressed by the caller's
own organization plus the file's leaf name. A caller therefore reaches only its
own organization's files - the directory a request reads is built from the
caller's `organization_id`, never from anything the client sends - so a leaked or
guessed leaf name from another tenant resolves to a path this organization does
not own and is a 404.

That is a wider scope than a chat upload, which is owned by one user
(`file_upload.py`). It is deliberate and it is the trade the prefix design makes:
the boundary that can be enforced on every read without a lookup is the tenant.

**What is kept, and for how long** (#2310). Each file an agent stores is recorded
in `generated_media` - its organization, the conversation it was made in where
the run had one, and its size. That record is what bounds it:

- a per-organization byte quota (`GENERATED_MEDIA_QUOTA_MB`), checked before each
  paid generation call, so a tenant past it is told so before anything is spent.
  An admitted call holds its estimated size (`generated_media_reservations`)
  until its file is recorded, under a per-organization lock, so calls in flight
  at once are measured against each other. Every file counts, including one from
  a run with no conversation - a preview, a test run, a channel `/btw` aside, an
  API run that named no thread;
- deletion with the conversation it was generated in, and with the account
  whose conversations they were;
- deletion after `GENERATED_MEDIA_RETENTION_DAYS`, by the daily
  `sweep-generated-media` job, whether or not the conversation is still there;
- deletion after `UNLINKED_MEDIA_LIFETIME` by the same job, for a file with no
  conversation, even with retention off: no member can delete anything to free
  it, so this is what bounds how long it holds the quota;
- deletion with the organization, by prefix.

Deletion with a conversation, an account or an organization removes the rows in
its own transaction and hands the bytes to a job queued in that same transaction
(`queue_external_state_cleanup`): the bytes go only if the rows do, and a process
that dies after the commit does not take the unlink with it. The sweep deletes
the bytes first and a row only once its bytes are gone.

The record is bookkeeping, not the read path. A file written before the table
existed has no row: it is still served, is not counted, and goes with its
organization.
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.db.locks import LockScope, hold_subject
from app.db.session import get_db_context, get_worker_db_context
from app.repositories import generated_media_repo
from app.services.file_storage import get_file_storage

logger = logging.getLogger(__name__)

OWNER_PREFIX = "generated"
"""First path segment of every generated file, per organization.

`generated_<organization_id>` rather than `generated/<organization_id>` because
`LocalFileStorage.save` sanitises its owner argument into a single path component
- a slash would be collapsed to an underscore anyway, so the flat form is what is
actually written and is what the reader must reconstruct. It shares the store's
root with the per-user chat directories (`<user_id>/`), which cannot collide: a
user id is a bare UUID and this is always prefixed.
"""

SWEEP_BATCH = 500
"""Rows the retention sweep reads at a time."""

SWEEP_MAX_BATCHES = 40
"""Batches per sweep. A backlog - a deployment turning retention on over a year
of clips - is worked off over several daily runs rather than in one long one."""

SWEEP_TIME_BUDGET = timedelta(minutes=10)
"""How long one sweep starts new batches for, below the job's 15-minute timeout,
so a slow store ends a run between batches rather than cancelling one."""

UNLINKED_MEDIA_LIFETIME = timedelta(days=7)
"""How long a file with no conversation is kept, whatever the retention setting.

It counts against the quota, and no member can free it by deleting a thread, so
this is what keeps a burst of previews, `/btw` asides or API runs from refusing
the organization for longer than a week - and from being kept for good with
retention off."""


RESERVATION_LIFETIME = timedelta(hours=1)
"""How long a call's claim on the quota counts before its file is recorded.

Past the longest a generation call can take - a clip's time limit is at most 30
minutes, and its download follows - so a claim this old belongs to a call whose
process died before it could settle it. It stops counting then, and the sweep
removes it."""


def organization_directory(organization_id: UUID) -> str:
    """The storage prefix holding one organization's generated media."""
    return f"{OWNER_PREFIX}_{organization_id}"


def _storage_path(organization_id: UUID, filename: str) -> str:
    """The storage path of one leaf name, inside the caller's own directory.

    Raises:
        NotFoundError: For anything but a single leaf name. The serving route's
            path parameter already cannot carry a separator, but a caller
            reaching this directly must not be able to climb into another
            organization's directory with `../`, which resolves inside the shared
            storage root rather than escaping it.
    """
    if "/" in filename or "\\" in filename or filename in {"", ".", ".."}:
        raise NotFoundError(message="Generated file not found", details={"filename": filename})
    return f"{organization_directory(organization_id)}/{filename}"


@dataclass(frozen=True)
class StoredGeneratedMedia:
    """One generated file found in the caller's organization, not yet read."""

    storage_path: str
    size: int


async def save_generated_media(organization_id: UUID, data: bytes, *, filename: str) -> str:
    """Store one generated file's bytes and return the leaf name it is served under.

    Only the bytes: :func:`keep_generated_media` is what an agent's tools call,
    and it also records the file so it is counted and expires.

    The leaf is unique (the store stamps a UUID prefix), so it is all a caller
    needs to read the file back: :func:`load_generated_media` rebuilds the
    organization directory from the *reader's* own id, which is what keeps one
    tenant's leaf name meaningless to another.

    Args:
        organization_id: The organization the file belongs to.
        data: The file's bytes.
        filename: A name such as `image.png` or `speech.mp3`. Its extension is
            what the serving route types the file by, so it must be the real
            format of `data`.
    """
    storage = get_file_storage()
    storage_path = await storage.save(organization_directory(organization_id), filename, data)
    return PurePosixPath(storage_path).name


async def keep_generated_media(
    organization_id: UUID,
    data: bytes,
    *,
    filename: str,
    conversation_id: UUID | None,
    reservation_id: UUID | None = None,
) -> str:
    """Store one generated file and record it; returns the leaf it is served under.

    Recorded in a session of its own: this runs inside a tool call, which holds
    none. The record replaces the call's reservation in the same transaction, so
    the quota counts the file at its real size from the moment it stops counting
    the estimate. A record that cannot be written removes the bytes again before
    the error goes on - a file with no row is counted by nothing and swept by
    nothing, which is the state #2310 exists to end - and leaves the reservation
    for the caller to release.

    Args:
        organization_id: The organization the file belongs to.
        data: The file's bytes.
        filename: A name such as `image.png`; its extension types the file.
        conversation_id: The thread the run answers in, when it has one. The file
            is deleted with that thread.
        reservation_id: The claim :func:`admit_generated_media` made for this
            call, where it made one.
    """
    leaf = await save_generated_media(organization_id, data, filename=filename)
    storage_path = _storage_path(organization_id, leaf)
    try:
        async with get_db_context() as db:
            await generated_media_repo.create(
                db,
                organization_id=organization_id,
                conversation_id=conversation_id,
                filename=leaf,
                storage_path=storage_path,
                size_bytes=len(data),
            )
            if reservation_id is not None:
                await generated_media_repo.release(
                    db, organization_id=organization_id, reservation_id=reservation_id
                )
    except BaseException:
        # `BaseException`, because a person pressing Stop or a run timing out
        # cancels the call here, and that leaves the same unrecorded file. The
        # unlink is shielded so the cancellation cannot interrupt it in turn -
        # though not a second native `task.cancel()`, which a shield does not
        # hold against; that file is left behind, unrecorded. A failed unlink
        # is logged so the error that got here, a cancellation above all, is
        # the one that goes on.
        with anyio.CancelScope(shield=True):
            try:
                await get_file_storage().delete(storage_path)
            except Exception:
                logger.exception(
                    "generated_media_not_unlinked",
                    extra={"organization_id": str(organization_id), "storage_path": storage_path},
                )
        raise
    return leaf


@dataclass(frozen=True)
class Admission:
    """Whether one generation call may go ahead, and the quota it holds if so."""

    admitted: bool
    reservation_id: UUID | None = None
    """The claim :func:`keep_generated_media` replaces and
    :func:`release_generated_media` drops - `None` where nothing was held: a
    refusal, or a deployment with no quota."""


async def admit_generated_media(organization_id: UUID, *, estimate_bytes: int) -> Admission:
    """Admit one generation call against this organization's quota, holding its estimate.

    Asked before a paid generation call rather than at the save, so a tenant at
    its limit is refused before anything is spent - a clip refused after it was
    made would be money paid for nothing.

    The check and the claim are one step to every other admission: the
    organization's lock is taken before what is used is read, and an admitted
    call writes a reservation of `estimate_bytes` before the lock goes with the
    commit. What is used is every recorded file (`bytes_used`) plus every claim
    of a call still in flight, so concurrent runs and parallel calls in one
    response are measured against each other and cannot all pass on the same
    figure. A call is refused when its estimate would carry the organization
    past the quota. An estimate is a bound the tool sets from what it knows; a
    file larger than its estimate is recorded at its real size, so it is the
    file, not the admission, that may end over by the difference.

    A claim not settled within `RESERVATION_LIFETIME` - a call whose process
    died - stops counting and is removed by the sweep.

    Every file counts. A member frees one made in a conversation by deleting
    it; one made with none goes after `UNLINKED_MEDIA_LIFETIME`.

    Args:
        organization_id: The organization the file would belong to.
        estimate_bytes: The most this call is expected to store.
    """
    quota_mb = settings.GENERATED_MEDIA_QUOTA_MB
    if quota_mb == 0:
        return Admission(admitted=True)
    since = datetime.now(UTC) - RESERVATION_LIFETIME
    async with get_db_context() as db:
        await hold_subject(db, LockScope.GENERATED_MEDIA_PER_ORG, organization_id)
        used = await generated_media_repo.bytes_used(db, organization_id=organization_id)
        used += await generated_media_repo.bytes_reserved(
            db, organization_id=organization_id, since=since
        )
        if used + estimate_bytes > quota_mb * 1024 * 1024:
            return Admission(admitted=False)
        reservation_id = await generated_media_repo.reserve(
            db, organization_id=organization_id, size_bytes=estimate_bytes
        )
    return Admission(admitted=True, reservation_id=reservation_id)


async def release_generated_media(organization_id: UUID, reservation_id: UUID) -> None:
    """Give back the quota a call held, for a call that stored nothing.

    Shielded, because a call cancelled by Stop or a timeout releases here on its
    way out, and a cancellation that interrupted it would hold the quota until
    the claim expired. A release that fails is logged rather than raised, so the
    error that ended the call is the one that goes on; the claim stops counting
    after `RESERVATION_LIFETIME` either way.
    """
    with anyio.CancelScope(shield=True):
        try:
            async with get_db_context() as db:
                await generated_media_repo.release(
                    db, organization_id=organization_id, reservation_id=reservation_id
                )
        except Exception:
            logger.exception(
                "generated_media_reservation_not_released",
                extra={
                    "organization_id": str(organization_id),
                    "reservation_id": str(reservation_id),
                },
            )


async def load_generated_media(organization_id: UUID, filename: str) -> bytes:
    """Read one generated file back whole, scoped to the caller's organization.

    For a caller that needs the bytes in hand - an image handed to a video model
    as its first frame. A route serving a file to a browser uses
    :func:`open_generated_media` and streams it instead.

    Args:
        organization_id: The organization reading - the directory is built from
            this and never from the client, so a filename is only ever resolved
            within the caller's own tenant.
        filename: The leaf name returned by :func:`save_generated_media`.

    Raises:
        NotFoundError: If no such file exists for this organization.
    """
    storage_path = _storage_path(organization_id, filename)
    try:
        return await get_file_storage().load(storage_path)
    except (FileNotFoundError, ValueError) as exc:
        raise NotFoundError(
            message="Generated file not found",
            details={"filename": filename},
        ) from exc


async def open_generated_media(organization_id: UUID, filename: str) -> StoredGeneratedMedia:
    """Find one generated file in the caller's organization, without reading it.

    Its storage path and size, which is what a ranged answer is decided from:
    the bytes are then read a span at a time with `BaseFileStorage.open_range`,
    so serving a range of a large clip holds the range rather than the clip.

    Args:
        organization_id: The organization reading, as for :func:`load_generated_media`.
        filename: The leaf name returned by :func:`save_generated_media`.

    Raises:
        NotFoundError: If no such file exists for this organization.
    """
    storage_path = _storage_path(organization_id, filename)
    try:
        size = await get_file_storage().size(storage_path)
    except (FileNotFoundError, ValueError) as exc:
        raise NotFoundError(
            message="Generated file not found",
            details={"filename": filename},
        ) from exc
    return StoredGeneratedMedia(storage_path=storage_path, size=size)


def generated_media_url(filename: str) -> str:
    """The API path the interface fetches a stored generated file from."""
    return f"/api/v1/generated/{filename}"


@dataclass(frozen=True)
class SweptBatch:
    """What one batch of the retention sweep did."""

    removed: int
    after: tuple[datetime, UUID] | None
    """The `(created_at, id)` of the batch's last row, which the next batch reads
    past - `None` when the batch was not full, so there is nothing after it."""


class GeneratedMediaService:
    """What happens to recorded generated media when its owner or its time goes."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def forget_conversations(
        self, organization_id: UUID, conversation_ids: Sequence[UUID]
    ) -> None:
        """Drop the records of what these threads generated, and queue their unlink.

        The unlink is a job queued in this transaction, not a task spawned after
        it: it runs only if the delete commits - an unlink before the commit is
        undone by a rollback as a file already gone (#1293) - and it survives
        the process, because the rows are the only record of the bytes and
        nothing could find them again once a lost unlink left them behind. For
        the same reason the paths go as `required_paths`: one the store refuses
        fails the job, so it is retried, rather than logged and left.
        """
        paths = await generated_media_repo.paths_in_conversations(
            self.db, organization_id=organization_id, conversation_ids=conversation_ids
        )
        await generated_media_repo.delete_in_conversations(
            self.db, organization_id=organization_id, conversation_ids=conversation_ids
        )
        await self._queue_unlink(paths, organization_id=organization_id)

    async def forget_user(self, user_id: UUID) -> None:
        """Drop what was generated in this person's own conversations, and queue its unlink.

        For account deletion: the person's conversations cascade with the
        account, which would leave their generated rows behind with no
        conversation and their bytes readable by the organization. Every
        organization at once - the paths are already scoped by the rows.
        """
        paths = await generated_media_repo.delete_in_conversations_of_user(self.db, user_id=user_id)
        await self._queue_unlink(paths, organization_id=None)

    async def _queue_unlink(self, paths: list[str], *, organization_id: UUID | None) -> None:
        if not paths:
            return
        from app.worker.tasks.teardown_tasks import queue_external_state_cleanup

        await queue_external_state_cleanup(
            self.db, [], [], required_paths=paths, organization_id=organization_id
        )

    async def sweep_batch(
        self,
        *,
        cutoff: datetime | None,
        unlinked_cutoff: datetime,
        after: tuple[datetime, UUID] | None,
    ) -> SweptBatch:
        """Delete one batch of expired files, read past `after`.

        Expired is older than `cutoff` (`None` with retention off) or, for a file
        with no conversation, older than `unlinked_cutoff`.

        The bytes before the row, and the row only once its bytes are gone: the
        other order leaves a file nothing can find. A file the store would not
        delete keeps its row and is logged; the next batch reads past it, so one
        stuck file cannot hold back every file behind it, and the next sweep
        tries it again.
        """
        storage = get_file_storage()
        batch = await generated_media_repo.expired(
            self.db, cutoff=cutoff, unlinked_cutoff=unlinked_cutoff, limit=SWEEP_BATCH, after=after
        )
        gone: list[UUID] = []
        for row in batch:
            try:
                await storage.delete(row.storage_path)
            except Exception:
                logger.exception(
                    "generated_media_not_unlinked",
                    extra={"organization_id": str(row.organization_id), "media_id": str(row.id)},
                )
                continue
            gone.append(row.id)
        removed = await generated_media_repo.delete_by_ids(self.db, ids=gone)
        last = batch[-1] if len(batch) == SWEEP_BATCH else None
        return SweptBatch(removed=removed, after=(last.created_at, last.id) if last else None)


async def sweep_expired_generated_media(*, now: datetime | None = None) -> int:
    """Delete every generated file past its lifetime; answer how many.

    Past the retention period, or - for a file with no conversation - past
    `UNLINKED_MEDIA_LIFETIME`, which applies with retention off too. Claims on
    the quota older than `RESERVATION_LIFETIME` go first: their calls died
    before they could settle them, and they already stopped counting.

    Each batch in a session of its own, committed before the next is read. One
    transaction for the whole run would be rolled back by the job's timeout,
    restoring rows whose bytes were already deleted, and a backlog that never
    finishes inside the timeout would then delete the same oldest files again
    every day and commit nothing. No new batch starts after `SWEEP_TIME_BUDGET`,
    so a slow store ends the run between batches; the next run goes on.

    Args:
        now: The moment the period is measured back from; a test freezes it.
    """
    now = now or datetime.now(UTC)
    days = settings.GENERATED_MEDIA_RETENTION_DAYS
    cutoff = now - timedelta(days=days) if days else None
    unlinked_cutoff = now - UNLINKED_MEDIA_LIFETIME
    stop_at = time.monotonic() + SWEEP_TIME_BUDGET.total_seconds()
    async with get_worker_db_context() as db:
        stale = await generated_media_repo.delete_stale_reservations(
            db, before=now - RESERVATION_LIFETIME
        )
    if stale:
        logger.warning("generated_media_reservations_expired", extra={"count": stale})
    removed = 0
    after: tuple[datetime, UUID] | None = None
    for _ in range(SWEEP_MAX_BATCHES):
        async with get_worker_db_context() as db:
            swept = await GeneratedMediaService(db).sweep_batch(
                cutoff=cutoff, unlinked_cutoff=unlinked_cutoff, after=after
            )
        removed += swept.removed
        if swept.after is None or time.monotonic() >= stop_at:
            break
        after = swept.after
    return removed
