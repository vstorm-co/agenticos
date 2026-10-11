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
from app.core.exceptions import AuthenticationError
from app.core.security import verify_token
from app.services.session import SessionService, hash_token, successor_refresh_token

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

    async def test_a_rotation_stamped_in_the_future_is_outside_the_window(self) -> None:
        """A clock set back after the rotation would keep the spent token inside
        the window for as long as the clock stays behind."""
        row = _row(rotated_ago=-timedelta(minutes=10))
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


class TestTheSuccessorToken:
    """Every request in a grace burst must be answered with the one token the row
    holds, so the successor has to be rebuildable from what the row stores."""

    def test_the_same_spent_token_mints_the_same_successor(self) -> None:
        expires_at = datetime.now(UTC) + timedelta(days=7)
        first = successor_refresh_token(
            "spent", subject="u-1", credential_version=0, expires_at=expires_at
        )
        again = successor_refresh_token(
            "spent", subject="u-1", credential_version=0, expires_at=expires_at
        )
        assert first == again

    def test_different_spent_tokens_mint_different_successors(self) -> None:
        expires_at = datetime.now(UTC) + timedelta(days=7)
        first = successor_refresh_token(
            "a", subject="u-1", credential_version=0, expires_at=expires_at
        )
        second = successor_refresh_token(
            "b", subject="u-1", credential_version=0, expires_at=expires_at
        )
        assert first != second

    def test_the_successor_carries_the_expiry_and_version_it_was_given(self) -> None:
        expires_at = datetime.now(UTC) + timedelta(days=7)
        token = successor_refresh_token(
            "s", subject="u-1", credential_version=3, expires_at=expires_at
        )
        payload = verify_token(token)
        assert payload is not None
        assert payload["cv"] == 3
        assert payload["exp"] == int(expires_at.timestamp())


class TestReissueWithinGrace:
    def _row(self, *, holds: str, expires_at: datetime) -> MagicMock:
        return MagicMock(user_id="u-1", expires_at=expires_at, refresh_token_hash=hash_token(holds))

    def test_answers_with_the_token_the_row_holds(self) -> None:
        expires_at = datetime.now(UTC) + timedelta(days=7)
        successor = successor_refresh_token(
            "spent", subject="u-1", credential_version=0, expires_at=expires_at
        )
        row = self._row(holds=successor, expires_at=expires_at)

        assert (
            SessionService(MagicMock()).reissue_within_grace(row, "spent", credential_version=0)
            == successor
        )

    def test_refuses_once_the_row_has_rotated_past_it(self) -> None:
        row = self._row(holds="a-later-token", expires_at=datetime.now(UTC) + timedelta(days=7))

        with pytest.raises(AuthenticationError):
            SessionService(MagicMock()).reissue_within_grace(row, "spent", credential_version=0)

    def test_refuses_after_the_credential_version_moved(self) -> None:
        expires_at = datetime.now(UTC) + timedelta(days=7)
        successor = successor_refresh_token(
            "spent", subject="u-1", credential_version=0, expires_at=expires_at
        )
        row = self._row(holds=successor, expires_at=expires_at)

        with pytest.raises(AuthenticationError):
            SessionService(MagicMock()).reissue_within_grace(row, "spent", credential_version=1)
