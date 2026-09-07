"""The single credential check a chat socket runs - at the handshake and, since
#1437, on every inbound frame.

`authenticate_socket_token` is what stops an open socket outliving the
revocation of the session that opened it. These pin each refusal it makes, so a
socket is never more permissive than a fresh connection bearing the same token:
an expired token, an ended impersonation, and a suspended account each close the
door here, and the door is the same one the next frame knocks on.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AuthenticationError, NotFoundError
from app.services.ws_auth import authenticate_socket_token

pytestmark = pytest.mark.anyio


def _user(*, is_active: bool = True) -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user.is_active = is_active
    return user


def _payload(subject: str, *, token_type: str = "access") -> dict[str, str]:
    return {"sub": subject, "type": token_type}


class TestAuthenticateSocketToken:
    """Every path from a raw token to a user, or to a refusal."""

    async def test_a_live_token_resolves_to_its_user(self) -> None:
        user = _user()
        with (
            patch(
                "app.services.ws_auth.verify_token",
                return_value=_payload(str(user.id)),
            ),
            patch("app.services.ws_auth.ImpersonationService") as impersonation,
            patch("app.services.ws_auth.UserService") as user_service,
        ):
            impersonation.return_value.verify = AsyncMock(return_value=None)
            user_service.return_value.get_by_id = AsyncMock(return_value=user)
            resolved = await authenticate_socket_token(MagicMock(), "token")

        assert resolved is user

    async def test_impersonation_is_verified_before_the_subject_is_loaded(self) -> None:
        """The `act` check is what refuses an ended impersonation, so it has to
        run - and run against this token, on this session."""
        user = _user()
        db = MagicMock()
        payload = _payload(str(user.id))
        with (
            patch("app.services.ws_auth.verify_token", return_value=payload),
            patch("app.services.ws_auth.ImpersonationService") as impersonation,
            patch("app.services.ws_auth.UserService") as user_service,
        ):
            verify = AsyncMock(return_value=None)
            impersonation.return_value.verify = verify
            user_service.return_value.get_by_id = AsyncMock(return_value=user)
            await authenticate_socket_token(db, "the-token")

        impersonation.assert_called_once_with(db)
        verify.assert_awaited_once_with(payload=payload, token="the-token", subject=str(user.id))

    async def test_an_unverifiable_token_is_refused(self) -> None:
        with (
            patch("app.services.ws_auth.verify_token", return_value=None),
            pytest.raises(AuthenticationError, match="Invalid or expired token"),
        ):
            await authenticate_socket_token(MagicMock(), "token")

    async def test_a_non_access_token_is_refused(self) -> None:
        with (
            patch(
                "app.services.ws_auth.verify_token",
                return_value=_payload(str(uuid4()), token_type="refresh"),
            ),
            pytest.raises(AuthenticationError, match="Invalid token type"),
        ):
            await authenticate_socket_token(MagicMock(), "token")

    async def test_a_token_without_a_subject_is_refused(self) -> None:
        with (
            patch("app.services.ws_auth.verify_token", return_value={"type": "access"}),
            pytest.raises(AuthenticationError, match="Invalid token payload"),
        ):
            await authenticate_socket_token(MagicMock(), "token")

    async def test_an_ended_impersonation_is_refused(self) -> None:
        """`verify` raises for an impersonation whose row is gone; the refusal
        propagates unchanged, so the socket closes with the reason it minted."""
        with (
            patch(
                "app.services.ws_auth.verify_token",
                return_value=_payload(str(uuid4())),
            ),
            patch("app.services.ws_auth.ImpersonationService") as impersonation,
            pytest.raises(AuthenticationError, match="Impersonation has ended"),
        ):
            impersonation.return_value.verify = AsyncMock(
                side_effect=AuthenticationError(message="Impersonation has ended")
            )
            await authenticate_socket_token(MagicMock(), "token")

    async def test_an_unknown_subject_is_refused(self) -> None:
        with (
            patch(
                "app.services.ws_auth.verify_token",
                return_value=_payload(str(uuid4())),
            ),
            patch("app.services.ws_auth.ImpersonationService") as impersonation,
            patch("app.services.ws_auth.UserService") as user_service,
            pytest.raises(AuthenticationError, match="User not found"),
        ):
            impersonation.return_value.verify = AsyncMock(return_value=None)
            user_service.return_value.get_by_id = AsyncMock(
                side_effect=NotFoundError(message="User not found")
            )
            await authenticate_socket_token(MagicMock(), "token")

    async def test_a_suspended_account_is_refused(self) -> None:
        user = _user(is_active=False)
        with (
            patch(
                "app.services.ws_auth.verify_token",
                return_value=_payload(str(user.id)),
            ),
            patch("app.services.ws_auth.ImpersonationService") as impersonation,
            patch("app.services.ws_auth.UserService") as user_service,
            pytest.raises(AuthenticationError, match="User account is disabled"),
        ):
            impersonation.return_value.verify = AsyncMock(return_value=None)
            user_service.return_value.get_by_id = AsyncMock(return_value=user)
            await authenticate_socket_token(MagicMock(), "token")
