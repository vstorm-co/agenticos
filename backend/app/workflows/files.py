"""A run's files, as a node handler reads and writes them (#1791).

Every file node goes through here, so there is one answer to "may this step
read that file": the `FileRef` is looked up in the run's own organization, and
it must belong to this run or be one the run was started with
(`workflow_file_repo.get_for_run`). Anything else - another organization's
file, another run's, a deleted one - is the same `FILE_NOT_FOUND`, so an id
learned somewhere is no key and a probe learns nothing.

A file's type is what its bytes say it is (`sniff`), never what a sender
declared, and bytes are stored before the row that names them. A row whose
insert fails takes its stored object with it, so a failed write leaves
nothing behind.
"""

import codecs
import hashlib
import io
import json
import zipfile
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.locks import LockScope, hold_subject
from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import ResourceRefKind
from app.db.session import get_worker_db_context
from app.repositories import workflow_file as workflow_file_repo
from app.repositories import workflow_media_operation as media_repo
from app.repositories import workflow_run as workflow_run_repo
from app.services.file_storage import (
    delete_files_best_effort,
    get_file_storage,
    sniff_container,
    sniff_image_header,
)
from app.services.file_upload import zip_has_too_many_members
from app.services.media_inspection import MediaInfo
from app.services.media_types import sniff_av_header
from app.services.workflow_execution import context
from app.services.workflow_execution.exceptions import InvalidBindingError, WorkflowFileQuotaError
from app.workflows.contracts.io import FileRef, file_refs
from app.workflows.contracts.results import Failed, WorkflowError

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

FILE_NOT_FOUND = "FILE_NOT_FOUND"
FILE_TOO_LARGE = "FILE_TOO_LARGE"

# How many leading bytes `sniff` reads: enough for every signature it knows
# and a look at whether the start of a file is text.
_SNIFF_BYTES = 4096


@dataclass(frozen=True)
class StoredFile:
    """A file's bytes and what its row says about them."""

    data: bytes
    content_type: str
    filename: str | None


def failed(code: str, message: str, *, retryable: bool = False, **details: object) -> Failed:
    return Failed(
        error=WorkflowError(code=code, message=message, details=details, retryable=retryable)
    )


def not_found() -> Failed:
    return failed(FILE_NOT_FOUND, "This file does not exist, or this run may not read it")


def sniff(data: bytes) -> str:
    """The media type these bytes are, from their own first bytes.

    Images, PDF and office formats use their signatures. Small UTF-8 files are
    parsed as JSON; larger ones beginning with an object or array are provisionally
    JSON, validated by the step that reads them. Other UTF-8 prefixes are text.
    Classification decodes at most the prefix, including an incomplete UTF-8
    character at its boundary, and never parses a whole large download.
    """
    head = data[:_SNIFF_BYTES]
    image = sniff_image_header(head)
    if image is not None:
        return image
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    media = sniff_av_header(head)
    if media is not None:
        return media
    container = sniff_container(head)
    if container == "zip":
        return DOCX if _is_docx(data) else "application/zip"
    if container is not None:
        return "application/octet-stream"
    try:
        text = codecs.getincrementaldecoder("utf-8")().decode(head, final=len(data) <= _SNIFF_BYTES)
    except UnicodeDecodeError:
        return "application/octet-stream"
    if len(data) > _SNIFF_BYTES:
        return "application/json" if text.lstrip().startswith(("{", "[")) else "text/plain"
    try:
        json.loads(text)
    except ValueError:
        return "text/plain"
    return "application/json"


def _is_docx(data: bytes) -> bool:
    """Whether a ZIP holds a Word document - its central directory names one.

    A ZIP declaring more members than `CHAT_ARCHIVE_MAX_MEMBERS` is not opened:
    it is no Word document, and listing it would cost more than the answer is worth.
    """
    if zip_has_too_many_members(data):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


async def _row_for(ref: FileRef) -> WorkflowFile | None:
    current = context.current()
    async with get_worker_db_context() as db:
        return await workflow_file_repo.get_for_run(
            db,
            ref.file_id,
            organization_id=current.organization_id,
            workflow_run_id=current.workflow_run_id,
        )


async def load(ref: FileRef, *, max_bytes: int) -> StoredFile | Failed:
    """The bytes `ref` names, if this run may read them and they fit in `max_bytes`.

    The size is checked on the row before anything is read, so a step bounded
    at ten megabytes never pulls a two-hundred-megabyte download into memory.
    """
    row = await _row_for(ref)
    if row is None:
        return not_found()
    if row.byte_size > max_bytes:
        return failed(
            FILE_TOO_LARGE,
            f"This file is {row.byte_size} bytes, over this step's limit of {max_bytes}",
            byte_size=row.byte_size,
            max_bytes=max_bytes,
        )
    try:
        data = await get_file_storage().load(row.storage_path)
    except FileNotFoundError:
        return not_found()
    return StoredFile(data=data, content_type=row.content_type, filename=row.filename)


async def open_stream(ref: FileRef) -> tuple[StoredFile, AsyncIterator[bytes]] | Failed:
    """The file's bytes in chunks, for a step that must never hold it whole.

    The `StoredFile` carries no data - only what the row says - and the stream is
    opened before it is returned, so a missing object fails here rather than
    part-way through a transfer.
    """
    row = await _row_for(ref)
    if row is None:
        return not_found()
    try:
        chunks = await get_file_storage().open_stream(row.storage_path)
    except FileNotFoundError:
        return not_found()
    return StoredFile(data=b"", content_type=row.content_type, filename=row.filename), chunks


async def load_verified(ref: FileRef, *, max_bytes: int) -> StoredFile | Failed:
    """Read one scoped file, verifying its reference and the actual streamed size.

    Media consumers need metadata as well as authority. The row is still the
    authority; a caller cannot relabel it or bypass the byte ceiling by forging a
    FileRef. The stream is bounded independently of that row and always closed.
    """
    row = await _row_for(ref)
    if row is None:
        return not_found()
    if row.byte_size != ref.byte_size or row.content_type != ref.content_type:
        return failed(
            "FILE_METADATA_MISMATCH", "The file reference does not match its stored metadata"
        )
    if row.byte_size > max_bytes:
        return failed(FILE_TOO_LARGE, "The file exceeds this step's byte limit")
    try:
        chunks = await get_file_storage().open_stream(row.storage_path)
    except FileNotFoundError:
        return not_found()
    data = bytearray()
    try:
        async for chunk in chunks:
            if len(data) + len(chunk) > max_bytes:
                return failed(FILE_TOO_LARGE, "The stored bytes exceed this step's byte limit")
            data.extend(chunk)
    except FileNotFoundError:
        return not_found()
    finally:
        close = getattr(chunks, "aclose", None)
        if close is not None:
            await close()
    if len(data) != row.byte_size:
        return failed("FILE_METADATA_MISMATCH", "The stored file size could not be verified")
    return StoredFile(data=bytes(data), content_type=row.content_type, filename=row.filename)


def normalized_filename(filename: str | None) -> str | None:
    """Keep a JSONB-safe basename and its extension inside the database's 255 characters."""
    if filename is None:
        return None
    name = filename.replace("\x00", "").encode("utf-8", errors="replace").decode()
    name = name.replace("\\", "/").rsplit("/", 1)[-1] or "file"
    stem, dot, suffix = name.rpartition(".")
    if dot and stem and len(suffix) < 32:
        return stem[: 254 - len(suffix)] + dot + suffix
    return name[:255]


async def save(data: bytes, *, content_type: str, filename: str | None) -> FileRef:
    """Store `data` as a new file of this run, made by this step, and name it.

    Every call mints a new file, so a step that saves is `at_least_once`: a retry
    after a lost answer stores a second copy rather than finding the first.

    Raises:
        WorkflowFileQuotaError: The run, or its organization, would hold more
            stored bytes than `WORKFLOW_RUN_MAX_FILE_BYTES` /
            `WORKFLOW_ORG_MAX_FILE_BYTES`. The stored object is removed first.
    """
    current = context.current()
    file_id = uuid4()
    storage_path = f"workflow-files/{current.organization_id}/{current.workflow_run_id}/{file_id}"
    await get_file_storage().save_at(storage_path, data)
    try:
        async with get_worker_db_context() as db:
            await _enforce_quota(db, len(data))
            await workflow_file_repo.create(
                db,
                file_id=file_id,
                organization_id=current.organization_id,
                workflow_run_id=current.workflow_run_id,
                producing_node_run_id=current.node_run_id,
                storage_path=storage_path,
                content_type=content_type,
                byte_size=len(data),
                filename=normalized_filename(filename),
            )
    except BaseException:
        await delete_files_best_effort([storage_path])
        raise
    return FileRef(file_id=file_id, content_type=content_type, byte_size=len(data))


class ReservedFileError(ValueError):
    """The journal cannot authorize these exact bytes at this output identity."""


async def reserve_capacity(db: AsyncSession, *, size: int) -> None:
    """Check capacity under the file quota lock before journaling a new byte hold."""
    await _enforce_quota(db, size)


async def persist_reserved(db: AsyncSession, *, operation_id: UUID, data: bytes) -> FileRef:
    """Store one journaled media output in the caller's still-open transaction.

    The caller holds current run/node/credential authority and marks this same
    journal stored before committing. Identity, digest and metadata must already
    be durable before this call. A failed or cancelled transaction deliberately
    leaves its deterministic blob for reconciliation; it never removes a target
    another collector may have committed. Ordinary `save` retains its existing
    new-file and compensation behavior.
    """
    current = context.current()
    await hold_subject(db, LockScope.WORKFLOW_FILE_BYTES, current.organization_id)
    operation = await media_repo.get(
        db, operation_id, organization_id=current.organization_id, locked=True
    )
    if (
        operation is None
        or operation.workflow_run_id != current.workflow_run_id
        or operation.node_run_id != current.node_run_id
        or operation.superseded_at is not None
        or operation.phase not in {"collecting", "stored"}
        or current.claim.lost
        or current.claim_token is None
        or operation.collector_token != current.claim_token
    ):
        raise ReservedFileError("This dispatch may not persist the reserved media output")
    attempt = await workflow_run_repo.get_attempt(db, operation.collector_attempt_id)
    if attempt is None or attempt.attempt_no != current.attempt_no:
        raise ReservedFileError("This collector no longer owns the reserved media output")
    metadata = MediaInfo.model_validate(operation.output_metadata)
    if (
        metadata.kind != operation.media_kind
        or metadata.byte_size != len(data)
        or len(data) > operation.reserved_bytes
        or hashlib.sha256(data).hexdigest() != operation.output_sha256
    ):
        raise ReservedFileError("The output does not match the media journal's verified bytes")
    file_id = operation.output_file_id
    storage_path = f"workflow-files/{current.organization_id}/{current.workflow_run_id}/{file_id}"
    existing = await workflow_file_repo.get(db, file_id, organization_id=current.organization_id)
    if existing is not None:
        if (
            existing.workflow_run_id != current.workflow_run_id
            or existing.producing_node_run_id != current.node_run_id
            or existing.storage_path != storage_path
            or existing.content_type != metadata.media_type
            or existing.byte_size != len(data)
            or existing.filename != operation.output_filename
        ):
            raise ReservedFileError(
                "The reserved output identity belongs to different stored bytes"
            )
    else:
        await _enforce_quota(db, len(data), exclude_operation_id=operation.id)
        await get_file_storage().save_at(storage_path, data)
        await workflow_file_repo.create(
            db,
            file_id=file_id,
            organization_id=current.organization_id,
            workflow_run_id=current.workflow_run_id,
            producing_node_run_id=current.node_run_id,
            storage_path=storage_path,
            content_type=metadata.media_type,
            byte_size=len(data),
            filename=operation.output_filename,
        )
    return FileRef(file_id=file_id, content_type=metadata.media_type, byte_size=len(data))


class SavedFileBatch:
    """New files whose references are published only when the whole step succeeds."""

    def __init__(self) -> None:
        self._created: list[FileRef] = []

    async def save(self, data: bytes, *, content_type: str, filename: str | None) -> FileRef:
        ref = await save(data, content_type=content_type, filename=filename)
        self._created.append(ref)
        return ref

    async def discard(self) -> None:
        current = context.current()
        async with get_worker_db_context() as db:
            await hold_subject(db, LockScope.WORKFLOW_FILE_BYTES, current.organization_id)
            paths = await workflow_file_repo.delete_saved_batch(
                db,
                organization_id=current.organization_id,
                workflow_run_id=current.workflow_run_id,
                producing_node_run_id=current.node_run_id,
                file_ids=[ref.file_id for ref in self._created],
            )
        await delete_files_best_effort(paths)


@asynccontextmanager
async def saved_batch() -> AsyncGenerator[SavedFileBatch]:
    """Compensate earlier writes if a later file, render or collection fails."""
    batch = SavedFileBatch()
    try:
        yield batch
    except BaseException:
        await batch.discard()
        raise


async def _enforce_quota(
    db: AsyncSession, size: int, *, exclude_operation_id: UUID | None = None
) -> None:
    """Refuse a file that would pass the run's or the organization's stored-bytes ceiling.

    Sums under the organization's lock, held until the row is inserted, so two
    steps saving at once cannot both pass at the ceiling.
    """
    current = context.current()
    await hold_subject(db, LockScope.WORKFLOW_FILE_BYTES, current.organization_id)
    ceilings = (
        ("run", settings.WORKFLOW_RUN_MAX_FILE_BYTES, current.workflow_run_id),
        ("organization", settings.WORKFLOW_ORG_MAX_FILE_BYTES, None),
    )
    for scope, limit, run_id in ceilings:
        stored = await workflow_file_repo.sum_bytes(
            db, organization_id=current.organization_id, workflow_run_id=run_id
        )
        held = await media_repo.held_bytes(
            db,
            organization_id=current.organization_id,
            workflow_run_id=run_id,
            exclude_operation_id=exclude_operation_id,
        )
        if stored + held + size > limit:
            raise WorkflowFileQuotaError(
                scope=scope, limit=limit, stored=stored + held, requested=size
            )


async def import_output_files(
    db: AsyncSession,
    *,
    organization_id: UUID,
    source_run_id: UUID,
    target_run_id: UUID,
    output: object,
    node_instance_id: UUID,
) -> None:
    """Import nested output files only after the source run's access is checked.

    Verify ownership/imports at the source, rather than trusting a file id in
    JSON. References protect the producer from retention while consumers use it.
    """
    await hold_subject(db, LockScope.WORKFLOW_FILE_BYTES, organization_id)
    for ref in {ref.file_id: ref for ref in file_refs(output)}.values():
        source = await workflow_file_repo.get_for_run(
            db, ref.file_id, organization_id=organization_id, workflow_run_id=source_run_id
        )
        if source is None:
            raise InvalidBindingError(node_instance_id=node_instance_id, field="output_file")
        if (
            await workflow_file_repo.get_for_run(
                db, ref.file_id, organization_id=organization_id, workflow_run_id=target_run_id
            )
            is None
        ):
            await workflow_run_repo.create_resource_ref(
                db,
                organization_id=organization_id,
                workflow_run_id=target_run_id,
                kind=ResourceRefKind.FILE.value,
                ref=ref.model_dump(mode="json"),
            )
