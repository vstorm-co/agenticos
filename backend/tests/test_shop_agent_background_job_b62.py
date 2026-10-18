"""B62 — shop background agent jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.schemas.shop_agent_background_job import ShopAgentBackgroundJobCreate
from app.services.shop_agent_background_job_service import ShopAgentBackgroundJobService

pytestmark = pytest.mark.anyio


async def test_schedule_report_spawns_after_commit() -> None:
    db = MagicMock()
    tenant_id = uuid4()
    org_id = uuid4()
    created_id = uuid4()
    now = datetime.now(UTC)

    async def fake_create(*_args, **kwargs):
        row = MagicMock()
        row.id = created_id
        row.minerp_tenant_id = kwargs["minerp_tenant_id"]
        row.organization_id = kwargs["organization_id"]
        row.conversation_id = kwargs["conversation_id"]
        row.job_type = kwargs["job_type"]
        row.goal = kwargs["goal"]
        row.status = "pending"
        row.notify_channels = kwargs["notify_channels"]
        row.result_summary = None
        row.error_message = None
        row.digest_interval_hours = kwargs["digest_interval_hours"]
        row.next_run_at = kwargs["next_run_at"]
        row.started_at = None
        row.finished_at = None
        row.created_at = now
        row.updated_at = now
        return row

    with (
        patch(
            "app.services.shop_agent_background_job_service.job_repo.create",
            fake_create,
        ),
        patch("app.core.background.spawn_after_commit") as spawn,
    ):
        out = await ShopAgentBackgroundJobService(db).schedule(
            ShopAgentBackgroundJobCreate(goal="FAQ gap 7 ngày", job_type="report"),
            minerp_tenant_id=tenant_id,
            organization_id=org_id,
        )

    assert out.id == created_id
    assert out.tenant_id == tenant_id
    spawn.assert_called_once()


async def test_schedule_digest_sets_interval() -> None:
    db = MagicMock()
    tenant_id = uuid4()
    org_id = uuid4()
    now = datetime.now(UTC)

    async def fake_create(*_args, **kwargs):
        row = MagicMock()
        row.id = uuid4()
        row.minerp_tenant_id = tenant_id
        row.organization_id = org_id
        row.conversation_id = None
        row.job_type = kwargs["job_type"]
        row.goal = kwargs["goal"]
        row.status = "pending"
        row.notify_channels = kwargs["notify_channels"]
        row.result_summary = None
        row.error_message = None
        row.digest_interval_hours = kwargs["digest_interval_hours"]
        row.next_run_at = kwargs["next_run_at"]
        row.started_at = None
        row.finished_at = None
        row.created_at = now
        row.updated_at = now
        return row

    with patch(
        "app.services.shop_agent_background_job_service.job_repo.create",
        fake_create,
    ):
        out = await ShopAgentBackgroundJobService(db).schedule(
            ShopAgentBackgroundJobCreate(
                goal="Daily digest",
                job_type="digest",
                digest_interval_hours=24,
            ),
            minerp_tenant_id=tenant_id,
            organization_id=org_id,
        )

    assert out.job_type == "digest"
    assert out.digest_interval_hours == 24
    assert out.next_run_at is not None
