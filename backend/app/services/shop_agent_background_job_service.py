"""Shop background agent job scheduling (D3 B62)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.db.models.shop_agent_background_job import ShopAgentBackgroundJob
from app.repositories import shop_agent_background_job as job_repo
from app.schemas.shop_agent_background_job import (
    ShopAgentBackgroundJobCreate,
    ShopAgentBackgroundJobList,
    ShopAgentBackgroundJobRead,
)

logger = logging.getLogger(__name__)


def _normalize_channels(channels: list[str]) -> list[str]:
    allowed = {"in_app", "email", "zalo", "telegram"}
    out = [c for c in channels if c in allowed]
    return out or ["in_app"]


def _to_read(row: ShopAgentBackgroundJob) -> ShopAgentBackgroundJobRead:
    return ShopAgentBackgroundJobRead(
        id=row.id,
        tenant_id=row.minerp_tenant_id,
        organization_id=row.organization_id,
        conversation_id=row.conversation_id,
        job_type=row.job_type,
        goal=row.goal,
        status=row.status,
        notify_channels=row.notify_channels,
        result_summary=row.result_summary,
        error_message=row.error_message,
        digest_interval_hours=row.digest_interval_hours,
        next_run_at=row.next_run_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ShopAgentBackgroundJobService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def schedule(
        self,
        data: ShopAgentBackgroundJobCreate,
        *,
        minerp_tenant_id: UUID,
        organization_id: UUID,
    ) -> ShopAgentBackgroundJobRead:
        if not settings.SHOP_AGENT_BACKGROUND_JOB_ENABLED:
            raise BadRequestError(message="Background agent jobs are disabled")

        digest_hours = data.digest_interval_hours
        if data.job_type == "digest" and digest_hours is None:
            digest_hours = 24

        next_run = datetime.now(UTC) if data.job_type == "digest" else None

        row = await job_repo.create(
            self.db,
            minerp_tenant_id=minerp_tenant_id,
            organization_id=organization_id,
            conversation_id=data.conversation_id,
            job_type=data.job_type,
            goal=data.goal.strip(),
            notify_channels=_normalize_channels(list(data.notify_channels)),
            digest_interval_hours=digest_hours if data.job_type == "digest" else None,
            next_run_at=next_run,
        )

        if data.job_type == "report":
            _enqueue_report_after_commit(self.db, row.id)

        return _to_read(row)

    async def list_for_tenant(
        self,
        minerp_tenant_id: UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> ShopAgentBackgroundJobList:
        limit = min(max(limit, 1), 100)
        items = await job_repo.list_for_tenant(
            self.db, minerp_tenant_id, skip=skip, limit=limit
        )
        total = await job_repo.count_for_tenant(self.db, minerp_tenant_id)
        return ShopAgentBackgroundJobList(
            items=[_to_read(i) for i in items],
            total=total,
        )

    async def get_for_tenant(self, minerp_tenant_id: UUID, job_id: UUID) -> ShopAgentBackgroundJob:
        row = await job_repo.get_by_id(self.db, job_id)
        if row is None or row.minerp_tenant_id != minerp_tenant_id:
            raise BadRequestError(
                message="Background job not found",
                details={"job_id": str(job_id)},
            )
        return row

    async def get_read_for_tenant(
        self, minerp_tenant_id: UUID, job_id: UUID
    ) -> ShopAgentBackgroundJobRead:
        return _to_read(await self.get_for_tenant(minerp_tenant_id, job_id))


def _enqueue_report_after_commit(session: AsyncSession, job_id: UUID) -> None:
    try:
        from app.core.background import spawn_after_commit
        from app.worker.tasks.shop_agent_background_job import run_shop_background_job_task

        spawn_after_commit(
            session,
            run_shop_background_job_task(job_id=job_id),
            name=f"shop_background_job:{job_id}",
        )
    except Exception:
        logger.warning("Could not enqueue shop background job %s", job_id, exc_info=True)
