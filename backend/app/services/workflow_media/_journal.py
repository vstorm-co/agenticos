"""Short durable transactions around one paid effect; no authority is granted here."""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_media_operation import WorkflowMediaOperation
from app.db.session import get_worker_db_context
from app.repositories import workflow_media_operation as media_repo
from app.repositories import workflow_run as run_repo
from app.services.media_inspection import MediaInfo
from app.services.video_generation import VideoReceipt
from app.services.workflow_execution.context import DispatchContext
from app.services.workflow_media._authority import fence
from app.services.workflow_media._errors import MediaOperationError
from app.services.workflow_media._pricing import CostFact


class ImageReceipt(BaseModel):
    """The provider's own id for one image response, for billing reconciliation.

    An image response cannot be collected again, so this is evidence only: it
    names the charge a member looks up when resolving an unknown hold.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=64)
    api: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    kind: Literal["response"] = "response"
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")


class MediaJournal:
    """An immutable operation/effect identity, separate from its current collector.

    A receipt or fee remains a fact after lease loss, revocation or cancellation.
    These callbacks therefore lock only the journal, never the secret row held
    by the bounded provider call. Storing a workflow file has a separate current
    authority, attempt and claim check.
    """

    def __init__(self, operation: WorkflowMediaOperation) -> None:
        self.id = operation.id
        self.organization_id = operation.organization_id
        self.workflow_run_id = operation.workflow_run_id
        self.node_run_id = operation.node_run_id
        self.origin_attempt_id = operation.origin_attempt_id
        self.request_hash = operation.request_hash
        self._submission_token = operation.submission_token

    async def _load(
        self, db: AsyncSession, *, require_submitted: bool = True
    ) -> WorkflowMediaOperation:
        row = await media_repo.get(db, self.id, organization_id=self.organization_id, locked=True)
        if (
            row is None
            or row.workflow_run_id != self.workflow_run_id
            or row.node_run_id != self.node_run_id
            or row.origin_attempt_id != self.origin_attempt_id
            or row.request_hash != self.request_hash
            or (
                require_submitted
                and (
                    self._submission_token is None or row.submission_token != self._submission_token
                )
            )
        ):
            raise MediaOperationError(
                "MEDIA_JOURNAL_MISMATCH", "The media operation identity changed"
            )
        return row

    async def start(self, current: DispatchContext) -> WorkflowMediaOperation:
        """Commit the only prepared→submitting transition before the external effect."""
        async with get_worker_db_context() as db:
            token = await fence(db, current, locked=True)
            row = await self._load(db, require_submitted=False)
            latest = await run_repo.get_latest_attempt(db, node_run_id=row.node_run_id)
            if (
                row.phase != "prepared"
                or row.submission_token is not None
                or row.superseded_at is not None
                or row.collector_token != current.claim_token
                or latest is None
                or latest.id != row.collector_attempt_id
                or latest.attempt_no != current.attempt_no
                or latest.status != "in_flight"
            ):
                raise MediaOperationError(
                    "MEDIA_ALREADY_SUBMITTED", "This operation cannot submit again"
                )
            row = await media_repo.change(
                db,
                row.id,
                organization_id=self.organization_id,
                values={
                    "phase": "submitting",
                    "submission_token": token,
                    "effect_started_at": datetime.now(UTC),
                },
            )
        self._submission_token = token
        return row

    async def receipt(self, receipt: VideoReceipt | ImageReceipt) -> None:
        """Acknowledge only a closed, correctly pinned provider receipt before polling
        for a video, or before an image response's output is validated."""
        async with get_worker_db_context() as db:
            row = await self._load(db)
            if (receipt.provider, receipt.api, receipt.model) != (
                row.provider,
                row.provider_api,
                row.model,
            ):
                raise MediaOperationError(
                    "MEDIA_RECEIPT_MISMATCH", "The provider receipt does not match this operation"
                )
            payload = receipt.model_dump(mode="json")
            if row.provider_receipt is not None and row.provider_receipt != payload:
                raise MediaOperationError(
                    "MEDIA_RECEIPT_MISMATCH", "A different receipt cannot replace this operation"
                )
            await media_repo.change(
                db,
                row.id,
                organization_id=self.organization_id,
                values={
                    "provider_receipt": payload,
                    "submitted_at": row.submitted_at or datetime.now(UTC),
                    "phase": row.phase
                    if row.phase in {"stored", "failed", "cancelled"}
                    else "submitted",
                },
            )

    async def cost(self, fact: CostFact) -> None:
        """Persist monotonic observed fees; canonical attempt settlement books them once."""
        async with get_worker_db_context() as db:
            row = await self._load(db)
            if fact.held_usd > row.reserved_usd or fact.evidence.kind != row.media_kind:
                raise MediaOperationError(
                    "MEDIA_PRICE_MISMATCH", "The cost evidence exceeds its admitted basis"
                )
            incurred = max(row.incurred_usd, fact.incurred_usd)
            # A delayed incomplete observation cannot undo a reconciled fee or
            # restore a hold already released by stronger evidence.
            complete = row.accounting_complete or fact.complete
            held = Decimal(0) if complete else min(row.held_usd, fact.held_usd)
            # The label must describe the retained amount. An older, smaller
            # reported fee cannot relabel a larger catalog estimate as exact.
            replace_evidence = fact.incurred_usd > row.incurred_usd or (
                fact.incurred_usd == row.incurred_usd
                and (not row.accounting_complete or fact.complete)
            )
            changes: media_repo.MediaChanges = {
                "incurred_usd": incurred,
                "held_usd": held,
                "accounting_complete": complete,
            }
            if replace_evidence:
                changes.update(
                    cost_source=fact.source, cost_evidence=fact.evidence.model_dump(mode="json")
                )
            await media_repo.change(
                db, row.id, organization_id=self.organization_id, values=changes
            )

    async def output(self, data: bytes, metadata: MediaInfo) -> WorkflowMediaOperation:
        """Journal exact inspected bytes before any deterministic blob write."""
        digest = hashlib.sha256(data).hexdigest()
        async with get_worker_db_context() as db:
            row = await self._load(db)
            if (
                metadata.kind != row.media_kind
                or metadata.byte_size != len(data)
                or len(data) > row.reserved_bytes
            ):
                raise MediaOperationError(
                    "MEDIA_OUTPUT_MISMATCH", "The inspected output does not match this operation"
                )
            payload = metadata.model_dump(mode="json")
            if row.output_sha256 is not None and (
                row.output_sha256 != digest or row.output_metadata != payload
            ):
                raise MediaOperationError(
                    "MEDIA_OUTPUT_MISMATCH", "Different output bytes cannot replace this operation"
                )
            return await media_repo.change(
                db,
                row.id,
                organization_id=self.organization_id,
                values={
                    "output_sha256": digest,
                    "output_metadata": payload,
                    "submitted_at": row.submitted_at or datetime.now(UTC),
                    "phase": row.phase
                    if row.phase in {"stored", "failed", "cancelled"}
                    else "collecting",
                },
            )

    async def interrupted(self, *, reason: str) -> None:
        """Release only proven unsubmitted work; every uncertain paid effect keeps its hold."""
        async with get_worker_db_context() as db:
            row = await self._load(db, require_submitted=False)
            if row.phase == "stored":
                return
            changes: media_repo.MediaChanges = {"reason_code": reason}
            if row.phase == "prepared" and row.submission_token is None:
                changes.update(
                    phase="failed", held_usd=Decimal(0), held_bytes=0, accounting_complete=True
                )
            elif row.phase not in {"failed", "cancelled"}:
                changes["phase"] = (
                    "collecting"
                    if row.output_sha256 is not None
                    else "submitted"
                    if row.provider_receipt is not None
                    else "unknown"
                )
            await media_repo.change(
                db, row.id, organization_id=self.organization_id, values=changes
            )

    async def reject_output(self, *, reason: str) -> None:
        """Known unusable bytes are not published; their incurred fees still survive."""
        async with get_worker_db_context() as db:
            row = await self._load(db)
            if row.phase != "stored":
                await media_repo.change(
                    db,
                    row.id,
                    organization_id=self.organization_id,
                    values={"phase": "failed", "held_bytes": 0, "reason_code": reason},
                )

    async def read(self) -> WorkflowMediaOperation:
        async with get_worker_db_context() as db:
            return await self._load(db, require_submitted=False)


def collectable(row: WorkflowMediaOperation) -> bool:
    """Proof that recovery can avoid a new provider submission.

    Only a video receipt names a job that can be collected again; an image
    receipt is billing evidence for reconciliation, not collection proof.
    """
    return row.phase not in {"failed", "cancelled", "prepared"} and (
        row.output_sha256 is not None
        or (row.media_kind == "video" and row.provider_receipt is not None)
    )
