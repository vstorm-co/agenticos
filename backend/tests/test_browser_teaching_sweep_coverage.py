"""Without Redis the sweep cannot read a hold, so it judges a recording on authority alone."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.browser_teaching import TeachingReason, TeachingRefused
from app.services.browser_teaching import _sweep

pytestmark = pytest.mark.anyio


def _row() -> SimpleNamespace:
    return SimpleNamespace(
        organization_id=uuid4(),
        owner_user_id=uuid4(),
        run_id=uuid4(),
        call_id="call",
        hold_id=uuid4(),
        capture_ends_at=datetime.now(UTC) + timedelta(minutes=5),
    )


@pytest.mark.parametrize("refusal", [None, TeachingReason.OWNERSHIP_LOST])
async def test_a_recording_is_judged_on_authority_when_no_hold_can_be_read(
    monkeypatch, refusal
) -> None:
    monkeypatch.setattr(_sweep._access, "deployment_enabled", lambda organization_id: True)
    monkeypatch.setattr(_sweep.live_browse, "client", lambda: None)
    hold = AsyncMock()
    monkeypatch.setattr(_sweep._hold, "current", hold)
    authority = AsyncMock(side_effect=None if refusal is None else TeachingRefused(refusal))
    monkeypatch.setattr(_sweep._access, "authority", authority)
    assert await _sweep._recording_refusal(AsyncMock(), _row(), datetime.now(UTC)) == refusal
    hold.assert_not_awaited()
    authority.assert_awaited_once()
