"""B54 — widget idle auto-release."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.shop_live_agent_inbox import release_idle_human_sessions

pytestmark = pytest.mark.anyio


async def test_release_idle_skipped_when_disabled() -> None:
    db = AsyncMock()
    org_id = uuid4()
    tenant_id = uuid4()
    with (
        patch(
            "app.services.shop_live_agent_inbox.resolve_idle_release_minutes",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.services.shop_live_agent_inbox.release_idle_widget_sessions_for_organization",
            new=AsyncMock(),
        ) as release,
    ):
        await release_idle_human_sessions(db, organization_id=org_id, tenant_id=tenant_id)
    release.assert_not_awaited()


async def test_release_idle_runs_when_configured() -> None:
    db = AsyncMock()
    org_id = uuid4()
    tenant_id = uuid4()
    with (
        patch(
            "app.services.shop_live_agent_inbox.resolve_idle_release_minutes",
            new=AsyncMock(return_value=10),
        ),
        patch(
            "app.services.shop_live_agent_inbox.release_idle_widget_sessions_for_organization",
            new=AsyncMock(return_value=1),
        ) as release,
    ):
        await release_idle_human_sessions(db, organization_id=org_id, tenant_id=tenant_id)
    release.assert_awaited_once()
    idle_before = release.await_args.kwargs["idle_before"]
    assert idle_before < datetime.now(UTC)
