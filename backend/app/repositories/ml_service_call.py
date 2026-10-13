"""Reading and writing the ML service usage log."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.ml_service_call import MLServiceCall


async def record(
    db: AsyncSession,
    *,
    organization_id: UUID,
    requested_by_user_id: UUID | None,
    service: str,
    status: str,
    input_bytes: int,
    units: int,
    unit: str,
    duration_ms: int,
    failure_stage: str | None = None,
    failure_reason: str | None = None,
) -> MLServiceCall:
    """Write one call's record."""
    row = MLServiceCall(
        organization_id=organization_id,
        requested_by_user_id=requested_by_user_id,
        service=service,
        status=status,
        input_bytes=input_bytes,
        units=units,
        unit=unit,
        duration_ms=duration_ms,
        failure_stage=failure_stage,
        failure_reason=failure_reason,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get(db: AsyncSession, call_id: UUID, *, organization_id: UUID) -> MLServiceCall | None:
    """One call record, or None where it belongs to another tenant.

    The organization is part of the lookup rather than checked afterwards, so a
    row from a different tenant is indistinguishable from one that never existed.
    """
    result = await db.execute(
        select(MLServiceCall).where(
            MLServiceCall.id == call_id,
            MLServiceCall.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_for(
    db: AsyncSession,
    *,
    organization_id: UUID,
    service: str | None,
    skip: int,
    limit: int,
) -> list[MLServiceCall]:
    """A page of an organization's calls, newest first."""
    statement = select(MLServiceCall).where(MLServiceCall.organization_id == organization_id)
    if service is not None:
        statement = statement.where(MLServiceCall.service == service)
    statement = statement.order_by(MLServiceCall.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(statement)
    return list(result.scalars().all())


async def count_for(db: AsyncSession, *, organization_id: UUID, service: str | None) -> int:
    """How many calls the organization has made, for the page's total."""
    statement = (
        select(func.count())
        .select_from(MLServiceCall)
        .where(MLServiceCall.organization_id == organization_id)
    )
    if service is not None:
        statement = statement.where(MLServiceCall.service == service)
    result = await db.execute(statement)
    return int(result.scalar_one())
