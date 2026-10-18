"""Execute shop background agent jobs — reports and digests (D3 B62)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.db.models.shop_agent_background_job import ShopAgentBackgroundJob
from app.repositories import shop_agent_background_job as job_repo
from app.services.shop_live_agent_analytics import ShopLiveAgentAnalyticsService
from app.services.shop_widget_quality import ShopWidgetQualityService

logger = logging.getLogger(__name__)


async def _gather_shop_digest_context(
    db: AsyncSession,
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
) -> dict[str, Any]:
    analytics = await ShopLiveAgentAnalyticsService(db).build_report(
        organization_id=organization_id,
        tenant_id=minerp_tenant_id,
        days=7,
    )
    quality = await ShopWidgetQualityService(db).build_report(
        organization_id=organization_id,
        minerp_tenant_id=minerp_tenant_id,
        days=7,
        weak_limit=5,
        faq_gap_limit=5,
    )
    return {
        "analytics": analytics.model_dump(mode="json"),
        "quality": {
            "widget_conversations": quality.widget_conversation_count,
            "weak_replies": [w.model_dump(mode="json") for w in quality.weak_replies[:5]],
            "faq_gaps": [g.model_dump(mode="json") for g in quality.faq_gaps[:5]],
        },
    }


async def _summarize_goal(*, goal: str, context: dict[str, Any]) -> str:
    """Produce a digest summary — JSON fallback when no LLM is configured."""
    return json.dumps({"goal": goal, "context": context}, ensure_ascii=False, indent=2)[:4000]


async def run_shop_background_job(db: AsyncSession, job_id: UUID) -> ShopAgentBackgroundJob:
    row = await job_repo.get_by_id(db, job_id)
    if row is None:
        raise BadRequestError(message="Background job not found", details={"job_id": str(job_id)})
    if row.status == "running":
        return row

    started = datetime.now(UTC)
    await job_repo.update_status(db, row, status="running", started_at=started)

    try:
        context: dict[str, Any] = {"job_type": row.job_type, "goal": row.goal}
        context["shop"] = await _gather_shop_digest_context(
            db,
            organization_id=row.organization_id,
            minerp_tenant_id=row.minerp_tenant_id,
        )

        summary = await _summarize_goal(goal=row.goal, context=context)
        finished = datetime.now(UTC)
        next_run: datetime | None = None
        final_status = "completed"
        if row.job_type == "digest" and row.digest_interval_hours:
            next_run = finished + timedelta(hours=row.digest_interval_hours)
            final_status = "pending"

        row = await job_repo.update_status(
            db,
            row,
            status=final_status,
            result_summary=summary,
            result_json=context,
            error_message=None,
            finished_at=finished,
            next_run_at=next_run if next_run else row.next_run_at,
        )
        return row
    except Exception as exc:
        logger.exception("Shop background job failed job=%s", job_id)
        finished = datetime.now(UTC)
        return await job_repo.update_status(
            db,
            row,
            status="failed",
            error_message=str(exc)[:2000],
            finished_at=finished,
        )
