"""Tenant-scoped media journals and reservations; these functions never commit."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_media_operation import WorkflowMediaOperation
from app.db.models.workflow_run import NodeAttempt, NodeAttemptStatus, WorkflowRun


@dataclass(frozen=True, slots=True)
class MediaAdmission:
    id: UUID
    organization_id: UUID
    workflow_run_id: UUID
    node_run_id: UUID
    attempt_id: UUID
    collector_token: UUID
    request_hash: str
    media_kind: str
    provider: str
    provider_api: str
    model: str
    pricing_snapshot: dict[str, object]
    secret_id: UUID
    secret_generation: UUID
    reserved_usd: Decimal
    reserved_bytes: int
    output_file_id: UUID
    output_filename: str


class MediaChanges(TypedDict, total=False):
    collector_attempt_id: UUID
    collector_token: UUID
    submission_token: UUID
    phase: str
    provider_receipt: dict[str, object]
    effect_started_at: datetime
    submitted_at: datetime
    superseded_at: datetime
    reason_code: str | None
    held_usd: Decimal
    incurred_usd: Decimal
    booked_usd: Decimal
    cost_source: str
    cost_evidence: dict[str, object]
    accounting_complete: bool
    held_bytes: int
    output_sha256: str
    output_metadata: dict[str, object]
    stored_file_id: UUID


async def create(db: AsyncSession, admission: MediaAdmission) -> WorkflowMediaOperation:
    row = WorkflowMediaOperation(
        id=admission.id,
        organization_id=admission.organization_id,
        workflow_run_id=admission.workflow_run_id,
        node_run_id=admission.node_run_id,
        origin_attempt_id=admission.attempt_id,
        collector_attempt_id=admission.attempt_id,
        collector_token=admission.collector_token,
        request_hash=admission.request_hash,
        media_kind=admission.media_kind,
        provider=admission.provider,
        provider_api=admission.provider_api,
        model=admission.model,
        pricing_snapshot=admission.pricing_snapshot,
        secret_id=admission.secret_id,
        secret_generation=admission.secret_generation,
        phase="prepared",
        reserved_usd=admission.reserved_usd,
        held_usd=admission.reserved_usd,
        incurred_usd=Decimal(0),
        booked_usd=Decimal(0),
        accounting_complete=False,
        reserved_bytes=admission.reserved_bytes,
        held_bytes=admission.reserved_bytes,
        output_file_id=admission.output_file_id,
        output_filename=admission.output_filename,
    )
    db.add(row)
    await db.flush()
    return row


async def get(
    db: AsyncSession,
    operation_id: UUID,
    *,
    organization_id: UUID,
    locked: bool = False,
) -> WorkflowMediaOperation | None:
    query = select(WorkflowMediaOperation).where(
        WorkflowMediaOperation.id == operation_id,
        WorkflowMediaOperation.organization_id == organization_id,
    )
    if locked:
        query = query.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(query)).scalar_one_or_none()


async def current_for_node(
    db: AsyncSession,
    *,
    organization_id: UUID,
    node_run_id: UUID,
    locked: bool = False,
) -> WorkflowMediaOperation | None:
    query = select(WorkflowMediaOperation).where(
        WorkflowMediaOperation.organization_id == organization_id,
        WorkflowMediaOperation.node_run_id == node_run_id,
        WorkflowMediaOperation.superseded_at.is_(None),
    )
    if locked:
        query = query.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(query)).scalar_one_or_none()


async def current_for_nodes(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_run_id: UUID,
    node_run_ids: list[UUID],
) -> dict[UUID, tuple[WorkflowMediaOperation, Decimal]]:
    """One bounded query for an already authorized page, including superseded holds."""
    if not node_run_ids:
        return {}
    operation = WorkflowMediaOperation
    totals = (
        select(
            operation.node_run_id,
            func.sum(operation.held_usd + operation.incurred_usd - operation.booked_usd).label(
                "unresolved_usd"
            ),
        )
        .where(
            operation.organization_id == organization_id,
            operation.workflow_run_id == workflow_run_id,
            operation.node_run_id.in_(node_run_ids),
        )
        .group_by(operation.node_run_id)
        .subquery()
    )
    query = (
        select(operation, totals.c.unresolved_usd)
        .join(totals, totals.c.node_run_id == operation.node_run_id)
        .where(
            operation.organization_id == organization_id,
            operation.workflow_run_id == workflow_run_id,
            operation.node_run_id.in_(node_run_ids),
            operation.superseded_at.is_(None),
        )
    )
    return {
        row.node_run_id: (row, Decimal(total)) for row, total in (await db.execute(query)).tuples()
    }


async def change(
    db: AsyncSession,
    operation_id: UUID,
    *,
    organization_id: UUID,
    values: MediaChanges,
) -> WorkflowMediaOperation:
    """Apply a reviewed transition while the caller holds the operation lock."""
    query = (
        update(WorkflowMediaOperation)
        .where(
            WorkflowMediaOperation.id == operation_id,
            WorkflowMediaOperation.organization_id == organization_id,
        )
        .values(**values)
        .returning(WorkflowMediaOperation)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(query)).scalar_one()


async def unbooked_for_node(
    db: AsyncSession,
    *,
    organization_id: UUID,
    node_run_id: UUID,
) -> list[WorkflowMediaOperation]:
    """Costs awaiting canonical settlement, including superseded/late operations."""
    query = (
        select(WorkflowMediaOperation)
        .where(
            WorkflowMediaOperation.organization_id == organization_id,
            WorkflowMediaOperation.node_run_id == node_run_id,
            WorkflowMediaOperation.incurred_usd > WorkflowMediaOperation.booked_usd,
        )
        .order_by(WorkflowMediaOperation.created_at, WorkflowMediaOperation.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list((await db.execute(query)).scalars())


async def outstanding_usd(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_run_id: UUID | None = None,
    uncovered_only: bool = False,
) -> Decimal:
    """Reserve unknown spend and journaled fees the run ledger has not booked yet.

    A workflow already counts an in-flight collector's reservation. Subtract only
    that matching reservation, never another node's, and retain any uncovered part.
    Organization spending does not count in-flight attempts, so it uses the whole
    amount. A lease timestamp never releases a media hold.
    """
    operation = WorkflowMediaOperation
    amount = operation.held_usd + operation.incurred_usd - operation.booked_usd
    if uncovered_only:
        covered = case(
            (
                NodeAttempt.status == NodeAttemptStatus.IN_FLIGHT.value,
                func.coalesce(NodeAttempt.reserved_usd, 0),
            ),
            else_=0,
        )
        query = (
            select(func.coalesce(func.sum(func.greatest(amount - covered, 0)), 0))
            .select_from(operation)
            .outerjoin(
                NodeAttempt,
                (NodeAttempt.id == operation.collector_attempt_id)
                & (NodeAttempt.organization_id == operation.organization_id)
                & (NodeAttempt.node_run_id == operation.node_run_id),
            )
        )
    else:
        query = select(func.coalesce(func.sum(amount), 0))
    query = query.where(operation.organization_id == organization_id)
    if workflow_run_id is not None:
        query = query.where(operation.workflow_run_id == workflow_run_id)
    return Decimal((await db.execute(query)).scalar_one())


async def unbooked_nodes(db: AsyncSession, *, limit: int) -> list[tuple[UUID, UUID, UUID]]:
    """Bounded worker scan for facts left after a crash or a late collector."""
    operation = WorkflowMediaOperation
    query = (
        select(operation.organization_id, operation.workflow_run_id, operation.node_run_id)
        .where(operation.incurred_usd > operation.booked_usd)
        .group_by(operation.organization_id, operation.workflow_run_id, operation.node_run_id)
        .order_by(func.min(operation.created_at), operation.node_run_id)
        .limit(limit)
    )
    return list((await db.execute(query)).tuples())


async def held_bytes(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_run_id: UUID | None = None,
    exclude_operation_id: UUID | None = None,
) -> int:
    query = select(func.coalesce(func.sum(WorkflowMediaOperation.held_bytes), 0)).where(
        WorkflowMediaOperation.organization_id == organization_id,
    )
    if workflow_run_id is not None:
        query = query.where(WorkflowMediaOperation.workflow_run_id == workflow_run_id)
    if exclude_operation_id is not None:
        query = query.where(WorkflowMediaOperation.id != exclude_operation_id)
    return int((await db.execute(query)).scalar_one())


async def workflow_has_unresolved(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID,
) -> bool:
    operation = WorkflowMediaOperation
    query = (
        select(operation.id)
        .join(
            WorkflowRun,
            (WorkflowRun.id == operation.workflow_run_id)
            & (WorkflowRun.organization_id == operation.organization_id),
        )
        .where(
            operation.organization_id == organization_id,
            WorkflowRun.workflow_id == workflow_id,
            or_(
                operation.held_usd > 0,
                operation.held_bytes > 0,
                operation.incurred_usd > operation.booked_usd,
            ),
        )
        .limit(1)
    )
    return (await db.execute(query)).first() is not None
