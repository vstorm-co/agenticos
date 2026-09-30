"""`SessionService.claim_refresh_grace` - the window in which the refresh token a
rotation just spent may still refresh, instead of reading as a replay.

A browser whose refresh response was lost, or a second tab refreshing on the
same cookie a moment after the first, holds exactly that token. Before the
window, presenting it ended the session and signed the person out.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.core.config import settings
from app.services.session import SessionService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_REPO = "app.services.session.session_repo.get_by_previous_refresh_token_hash"


def _row(
    *,
    rotated_ago: timedelta | None = timedelta(seconds=5),
    impersonator_user_id: UUID | None = None,
    expires_at: datetime | None = None,
) -> MagicMock:
    now = datetime.now(UTC)
    return MagicMock(
        id=uuid4(),
        impersonator_user_id=impersonator_user_id,
        expires_at=expires_at or now + timedelta(days=1),
        rotated_at=None if rotated_ago is None else now - rotated_ago,
    )


class TestClaimRefreshGrace:
    async def test_a_token_spent_seconds_ago_refreshes(self) -> None:
        row = _row()
        with patch(_REPO, AsyncMock(return_value=row)) as lookup:
            assert await SessionService(MagicMock()).claim_refresh_grace("spent") is row
        # Locked, so two grace refreshes on one spent token serialize.
        assert lookup.await_args is not None
        assert lookup.await_args.kwargs == {"for_update": True}

    async def test_a_token_spent_past_the_window_is_left_to_reuse_detection(self) -> None:
        row = _row(rotated_ago=timedelta(seconds=settings.REFRESH_REUSE_GRACE_SECONDS + 1))
        with patch(_REPO, AsyncMock(return_value=row)):
            assert await SessionService(MagicMock()).claim_refresh_grace("spent") is None

    async def test_a_row_that_never_recorded_its_rotation_is_outside_the_window(self) -> None:
        """Rows rotated before `rotated_at` existed keep the old behaviour."""
        with patch(_REPO, AsyncMock(return_value=_row(rotated_ago=None))):
            assert await SessionService(MagicMock()).claim_refresh_grace("spent") is None

    async def test_an_unknown_token_is_no_grace(self) -> None:
        with patch(_REPO, AsyncMock(return_value=None)):
            assert await SessionService(MagicMock()).claim_refresh_grace("never") is None

    async def test_an_impersonation_is_never_refreshed(self) -> None:
        row = _row(impersonator_user_id=uuid4())
        with patch(_REPO, AsyncMock(return_value=row)):
            assert await SessionService(MagicMock()).claim_refresh_grace("spent") is None

    async def test_an_expired_session_is_not_extended(self) -> None:
        row = _row(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        with patch(_REPO, AsyncMock(return_value=row)):
            assert await SessionService(MagicMock()).claim_refresh_grace("spent") is None

    async def test_a_zero_window_turns_the_grace_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "REFRESH_REUSE_GRACE_SECONDS", 0)
        with patch(_REPO, AsyncMock(return_value=_row())) as lookup:
            assert await SessionService(MagicMock()).claim_refresh_grace("spent") is None
        lookup.assert_not_awaited()
