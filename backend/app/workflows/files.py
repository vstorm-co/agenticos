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

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from app.db.models.workflow_file import WorkflowFile
from app.db.session import get_worker_db_context
from app.repositories import workflow_file as workflow_file_repo
from app.services.file_storage import (
    delete_files_best_effort,
    get_file_storage,
    sniff_container,
    sniff_image_header,
)
from app.services.workflow_execution import context
from app.workflows.contracts.io import FileRef
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

    The images, PDF and the ZIP-based office formats by signature; valid UTF-8
    as JSON when it parses as JSON, otherwise as plain text; anything else as
    `application/octet-stream`. Only the start is examined, so a large file
    costs a slice, and text is never mistaken for a binary it merely mentions.
    """
    head = data[:_SNIFF_BYTES]
    image = sniff_image_header(head)
    if image is not None:
        return image
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    container = sniff_container(head)
    if container == "zip":
        return DOCX if _is_docx(data) else "application/zip"
    if container is not None:
        return "application/octet-stream"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    try:
        json.loads(text)
    except ValueError:
        return "text/plain"
    return "application/json"


def _is_docx(data: bytes) -> bool:
    """Whether a ZIP holds a Word document - its central directory names one."""
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


async def save(data: bytes, *, content_type: str, filename: str | None) -> FileRef:
    """Store `data` as a new file of this run, made by this step, and name it.

    Every call mints a new file, so a step that saves is `at_least_once`: a retry
    after a lost answer stores a second copy rather than finding the first.
    """
    current = context.current()
    file_id = uuid4()
    storage_path = f"workflow-files/{current.organization_id}/{current.workflow_run_id}/{file_id}"
    await get_file_storage().save_at(storage_path, data)
    try:
        async with get_worker_db_context() as db:
            await workflow_file_repo.create(
                db,
                file_id=file_id,
                organization_id=current.organization_id,
                workflow_run_id=current.workflow_run_id,
                producing_node_run_id=current.node_run_id,
                storage_path=storage_path,
                content_type=content_type,
                byte_size=len(data),
                filename=filename,
            )
    except BaseException:
        await delete_files_best_effort([storage_path])
        raise
    return FileRef(file_id=file_id, content_type=content_type, byte_size=len(data))
