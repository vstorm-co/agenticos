"""`SessionService.verify_access_session` - the #1501 refusal that lets signing
out everywhere reach an ordinary access token."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import AuthenticationError
from app.services.session import SessionService

pytestmark = pytest.mark.anyio

_REPO = "app.services.session.session_repo.get_by_id"


def _row(
    *,
    user_id: UUID,
    is_active: bool = True,
    impersonator_user_id: UUID | None = None,
    expires_at: datetime | None = None,
) -> MagicMock:
    return MagicMock(
        user_id=user_id,
        is_active=is_active,
        impersonator_user_id=impersonator_user_id,
        expires_at=expires_at or datetime.now(UTC) + timedelta(days=1),
    )


class TestVerifyAccessSession:
    async def test_a_token_without_sid_is_left_alone(self) -> None:
        """A pre-#1501 token names no row, so it is not looked up and not refused -
        an existing sign-in is not logged out the moment this deploys."""
        with patch(_REPO, AsyncMock()) as get_by_id:
            await SessionService(MagicMock()).verify_access_session(
                payload={"sub": "u"}, subject="u"
            )
        get_by_id.assert_not_awaited()

    async def test_an_impersonation_token_is_verified_elsewhere_not_here(self) -> None:
        """A token with a valid `act` is an impersonation, bound to its row by
        ImpersonationService before this runs; looking that row up here would
        refuse it, so it returns early and never touches the repo."""
        with patch(_REPO, AsyncMock()) as get_by_id:
            await SessionService(MagicMock()).verify_access_session(
                payload={"act": str(uuid4()), "sid": str(uuid4())}, subject=str(uuid4())
            )
        get_by_id.assert_not_awaited()

    async def test_an_active_session_the_subject_owns_passes(self) -> None:
        user_id = uuid4()
        with patch(_REPO, AsyncMock(return_value=_row(user_id=user_id))):
            await SessionService(MagicMock()).verify_access_session(
                payload={"sid": str(uuid4())}, subject=str(user_id)
            )

    async def test_a_sid_naming_no_row_is_refused(self) -> None:
        with (
            patch(_REPO, AsyncMock(return_value=None)),
            pytest.raises(AuthenticationError, match="Session has ended"),
        ):
            await SessionService(MagicMock()).verify_access_session(
                payload={"sid": str(uuid4())}, subject=str(uuid4())
            )

    async def test_a_deactivated_session_is_refused(self) -> None:
        """Signing out everywhere flips `is_active`; the token is refused next use."""
        user_id = uuid4()
        with (
            patch(_REPO, AsyncMock(return_value=_row(user_id=user_id, is_active=False))),
            pytest.raises(AuthenticationError, match="Session has ended"),
        ):
            await SessionService(MagicMock()).verify_access_session(
                payload={"sid": str(uuid4())}, subject=str(user_id)
            )

    async def test_an_expired_session_is_refused(self) -> None:
        user_id = uuid4()
        expired = _row(user_id=user_id, expires_at=datetime.now(UTC) - timedelta(seconds=1))
        with (
            patch(_REPO, AsyncMock(return_value=expired)),
            pytest.raises(AuthenticationError, match="Session has ended"),
        ):
            await SessionService(MagicMock()).verify_access_session(
                payload={"sid": str(uuid4())}, subject=str(user_id)
            )

    async def test_an_impersonation_row_is_not_an_ordinary_session(self) -> None:
        """An ordinary token may not carry an impersonation `sid`: that row is
        verified by ImpersonationService for an `act` token, never here."""
        user_id = uuid4()
        row = _row(user_id=user_id, impersonator_user_id=uuid4())
        with (
            patch(_REPO, AsyncMock(return_value=row)),
            pytest.raises(AuthenticationError, match="Session has ended"),
        ):
            await SessionService(MagicMock()).verify_access_session(
                payload={"sid": str(uuid4())}, subject=str(user_id)
            )

    async def test_another_users_session_is_refused(self) -> None:
        """A `sid` replayed onto a token for a different subject is refused."""
        with (
            patch(_REPO, AsyncMock(return_value=_row(user_id=uuid4()))),
            pytest.raises(AuthenticationError, match="Session has ended"),
        ):
            await SessionService(MagicMock()).verify_access_session(
                payload={"sid": str(uuid4())}, subject=str(uuid4())
            )
