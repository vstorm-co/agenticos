"""Recover one deterministic blob and publish it with the operation in one transaction."""

import hashlib

from app.db.locks import LockScope, hold_subject
from app.db.models.workflow_media_operation import WorkflowMediaOperation
from app.db.session import get_worker_db_context
from app.repositories import workflow_media_operation as media_repo
from app.services.file_storage import get_file_storage
from app.services.media_inspection import MediaInfo
from app.services.organization_secret import OrganizationSecretService
from app.services.workflow_execution import context
from app.services.workflow_media import _authority
from app.services.workflow_media._admission import MediaConfig, recheck
from app.services.workflow_media._errors import MediaOperationError
from app.workflows import files
from app.workflows.nodes._media_config import (
    ImageGenerationOutput,
    MediaGenerationReceipt,
    VideoGenerationOutput,
)


async def recover_bytes(operation: WorkflowMediaOperation, config: MediaConfig) -> bytes | None:
    """Read only the admitted output identity, with a real bounded stream and digest."""
    await recheck(operation, config)
    path = f"workflow-files/{operation.organization_id}/{operation.workflow_run_id}/{operation.output_file_id}"
    try:
        chunks = await get_file_storage().open_stream(path)
    except FileNotFoundError:
        return None
    data = bytearray()
    try:
        async for chunk in chunks:
            if len(data) + len(chunk) > operation.reserved_bytes:
                raise MediaOperationError(
                    "MEDIA_OUTPUT_CORRUPT", "The retained output exceeds its admitted byte limit"
                )
            data.extend(chunk)
    except FileNotFoundError:
        return None
    finally:
        close = getattr(chunks, "aclose", None)
        if close is not None:
            await close()
    metadata = MediaInfo.model_validate(operation.output_metadata)
    if (
        len(data) != metadata.byte_size
        or hashlib.sha256(data).hexdigest() != operation.output_sha256
    ):
        raise MediaOperationError(
            "MEDIA_OUTPUT_CORRUPT", "The retained output does not match its journal"
        )
    return bytes(data)


async def persist(
    operation: WorkflowMediaOperation, config: MediaConfig, data: bytes
) -> ImageGenerationOutput | VideoGenerationOutput:
    current = context.current()
    async with get_worker_db_context() as db:
        await hold_subject(db, LockScope.WORKFLOW_FILE_BYTES, current.organization_id)
        run, _attempt = await _authority.dispatch_rows(db, current, locked=True)
        auth = await _authority.principal(db, current, run)
        secret = await OrganizationSecretService(db).workflow_media_secret(
            auth, operation.secret_id, provider=operation.provider, locked=True
        )
        if secret.authorization_generation != operation.secret_generation:
            raise MediaOperationError(
                "MEDIA_CREDENTIAL_CHANGED", "The original media credential has changed"
            )
        await _authority.fence(db, current, locked=True)
        ref = await files.persist_reserved(db, operation_id=operation.id, data=data)
        # A permission may be revoked while a slow blob write is in progress.
        # Use a fresh identity map before committing the file and success link.
        await recheck(operation, config)
        operation = await media_repo.change(
            db,
            operation.id,
            organization_id=current.organization_id,
            values={
                "phase": "stored",
                "stored_file_id": operation.output_file_id,
                "held_bytes": 0,
                "reason_code": None,
            },
        )
        metadata = MediaInfo.model_validate(operation.output_metadata)
        if operation.submitted_at is None:
            raise MediaOperationError(
                "MEDIA_JOURNAL_MISMATCH", "The media output has no durable submission fact"
            )
        receipt = MediaGenerationReceipt.model_validate(
            {
                "operation_id": operation.id,
                "provider": operation.provider,
                "model": operation.model,
                "submitted_at": operation.submitted_at,
                "cost_source": operation.cost_source or "catalog_estimate",
                "cost_usd": operation.incurred_usd,
                "held_usd": operation.held_usd,
            }
        )
        result = {**metadata.model_dump(), "file": ref, "receipt": receipt}
        if operation.media_kind == "image":
            return ImageGenerationOutput.model_validate(result)
        return VideoGenerationOutput.model_validate(result)
