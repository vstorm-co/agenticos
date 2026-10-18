"""Shop agent background job repository (D3 B62)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.shop_agent_background_job import ShopAgentBackgroundJob


async def create(
    db: AsyncSession,
    *,
    minerp_tenant_id: uuid.UUID,
    organization_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    job_type: str,
    goal: str,
    notify_channels: list[str] | None,
    digest_interval_hours: int | None = None,
    next_run_at: datetime | None = None,
) -> ShopAgentBackgroundJob:
    row = ShopAgentBackgroundJob(
        minerp_tenant_id=minerp_tenant_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
        job_type=job_type,
        goal=goal,
        status="pending",
        notify_channels=notify_channels,
        digest_interval_hours=digest_interval_hours,
        next_run_at=next_run_at,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_by_id(db: AsyncSession, job_id: uuid.UUID) -> ShopAgentBackgroundJob | None:
    return await db.get(ShopAgentBackgroundJob, job_id)


async def list_for_tenant(
    db: AsyncSession,
    minerp_tenant_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 50,
) -> list[ShopAgentBackgroundJob]:
    q = (
        select(ShopAgentBackgroundJob)
        .where(ShopAgentBackgroundJob.minerp_tenant_id == minerp_tenant_id)
        .order_by(ShopAgentBackgroundJob.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(q)
    return list(result.scalars().all())


async def count_for_tenant(db: AsyncSession, minerp_tenant_id: uuid.UUID) -> int:
    q = select(func.count()).select_from(ShopAgentBackgroundJob).where(
        ShopAgentBackgroundJob.minerp_tenant_id == minerp_tenant_id
    )
    return int((await db.execute(q)).scalar_one())


async def list_due_digest_jobs(
    db: AsyncSession,
    *,
    limit: int = 20,
) -> list[ShopAgentBackgroundJob]:
    now = datetime.now(UTC)
    q = (
        select(ShopAgentBackgroundJob)
        .where(
            ShopAgentBackgroundJob.job_type == "digest",
            ShopAgentBackgroundJob.digest_interval_hours.isnot(None),
            ShopAgentBackgroundJob.status.in_(("pending", "completed")),
            ShopAgentBackgroundJob.next_run_at.isnot(None),
            ShopAgentBackgroundJob.next_run_at <= now,
        )
        .order_by(ShopAgentBackgroundJob.next_run_at.asc())
        .limit(limit)
    )
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_status(
    db: AsyncSession,
    row: ShopAgentBackgroundJob,
    *,
    status: str,
    result_summary: str | None = None,
    result_json: dict | None = None,
    error_message: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    next_run_at: datetime | None = None,
) -> ShopAgentBackgroundJob:
    row.status = status
    if result_summary is not None:
        row.result_summary = result_summary
    if result_json is not None:
        row.result_json = result_json
    if error_message is not None:
        row.error_message = error_message
    if started_at is not None:
        row.started_at = started_at
    if finished_at is not None:
        row.finished_at = finished_at
    if next_run_at is not None:
        row.next_run_at = next_run_at
    await db.flush()
    await db.refresh(row)
    return row
