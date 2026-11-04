"""The single credential check a chat socket runs - at the handshake and, since
#1437, on every inbound frame.

`authenticate_socket_token` is what stops an open socket outliving the
revocation of the session that opened it. These pin each refusal it makes, so a
socket is never more permissive than a fresh connection bearing the same token:
an expired token, an ended impersonation, and a suspended account each close the
door here, and the door is the same one the next frame knocks on.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, WebSocket
from starlette.types import Message, Scope

from app.api import deps
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.security import create_access_token
from app.services.ws_auth import authenticate_socket_token

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _user(*, is_active: bool = True) -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user.is_active = is_active
    return user


def _payload(subject: str, *, token_type: str = "access") -> dict[str, str]:
    return {"sub": subject, "type": token_type}


async def _handshake(headers: dict[str, str]) -> list[Message]:
    """Exercise FastAPI's cookie binding without a server or application lifespan."""
    app = FastAPI()

    @app.websocket("/ws")
    async def socket(websocket: WebSocket, user: deps.CurrentUserWS) -> None:
        await websocket.accept(subprotocol=websocket.state.accept_subprotocol)
        await websocket.send_text(str(user.id))
        await websocket.close()

    scope: Scope = {
        "type": "websocket",
        "path": "/ws",
        "query_string": b"",
        "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
        "scheme": "ws",
        "server": ("localhost", 8000),
        "client": ("127.0.0.1", 12345),
        "subprotocols": [],
    }
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, AsyncMock(return_value={"type": "websocket.connect"}), send)
    return sent


class TestSocketCookieIsolation:
    @pytest.fixture
    def socket_auth(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        @asynccontextmanager
        async def db_context() -> AsyncIterator[MagicMock]:
            yield MagicMock(refresh=AsyncMock())

        authenticate = AsyncMock(return_value=_user())
        monkeypatch.setattr(deps, "get_db_context", db_context)
        monkeypatch.setattr(deps, "authenticate_socket_key", AsyncMock(return_value=None))
        monkeypatch.setattr(deps, "authenticate_socket_token", authenticate)
        return authenticate

    async def test_the_handshake_uses_only_the_agenticos_cookie(
        self, socket_auth: AsyncMock
    ) -> None:
        sent = await _handshake(
            {"cookie": "access_token=other-app; agenticos_access_token=our-access"}
        )

        assert sent[0]["type"] == "websocket.accept"
        assert sent[1] == {"type": "websocket.send", "text": str(socket_auth.return_value.id)}
        assert socket_auth.await_args.args[1] == "our-access"

    async def test_another_apps_cookie_does_not_authenticate_a_socket(
        self, socket_auth: AsyncMock
    ) -> None:
        sent = await _handshake({"cookie": "access_token=other-app"})

        assert sent == [
            {"type": "websocket.close", "code": 4001, "reason": "Missing authentication token"}
        ]
        socket_auth.assert_not_awaited()

    async def test_the_existing_token_subprotocol_still_wins_over_cookies(
        self, socket_auth: AsyncMock
    ) -> None:
        sent = await _handshake(
            {
                "cookie": "access_token=other-app; agenticos_access_token=our-access",
                "sec-websocket-protocol": "access_token.protocol-access, chat",
            }
        )

        assert sent[0] == {"type": "websocket.accept", "subprotocol": "chat", "headers": []}
        assert sent[1] == {"type": "websocket.send", "text": str(socket_auth.return_value.id)}
        assert socket_auth.await_args.args[1] == "protocol-access"


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

    async def test_the_handshake_refuses_an_already_expired_token(self) -> None:
        """A socket cannot be *opened* with a dead credential: the default
        enforces the token's own `exp`."""
        token = create_access_token(str(uuid4()), expires_delta=timedelta(seconds=-1))

        with pytest.raises(AuthenticationError, match="Invalid or expired token"):
            await authenticate_socket_token(MagicMock(), token)

    async def test_the_per_frame_check_tolerates_an_expired_token(self) -> None:
        """The socket outlives its 30-minute token, so `allow_expired` keeps a
        still-signed-in person's live session from being torn down for routine
        token aging - only revocation (checked below) closes it (#1437)."""
        user = _user()
        token = create_access_token(str(user.id), expires_delta=timedelta(seconds=-1))
        with (
            patch("app.services.ws_auth.ImpersonationService") as impersonation,
            patch("app.services.ws_auth.UserService") as user_service,
        ):
            impersonation.return_value.verify = AsyncMock(return_value=None)
            user_service.return_value.get_by_id = AsyncMock(return_value=user)
            resolved = await authenticate_socket_token(MagicMock(), token, allow_expired=True)

        assert resolved is user

    async def test_an_expired_impersonation_is_still_refused_on_the_socket(self) -> None:
        """`allow_expired` relaxes the token's `exp` only - an impersonation's own
        window is its row's `expires_at`, which `verify` enforces regardless, so
        an hour-old impersonation still closes even though token expiry is not
        checked."""
        token = create_access_token(
            str(uuid4()), act=str(uuid4()), expires_delta=timedelta(seconds=-1)
        )
        with (
            patch("app.services.ws_auth.ImpersonationService") as impersonation,
            pytest.raises(AuthenticationError, match="Impersonation has ended"),
        ):
            impersonation.return_value.verify = AsyncMock(
                side_effect=AuthenticationError(message="Impersonation has ended")
            )
            await authenticate_socket_token(MagicMock(), token, allow_expired=True)

    async def test_a_revoked_ordinary_session_closes_the_socket(self) -> None:
        """The #1501 door: an ordinary token whose `sid` names a deactivated row -
        signed out everywhere - is refused on the next frame, so the socket closes
        even though the account itself is untouched."""
        user = _user()
        row = MagicMock(
            user_id=user.id,
            is_active=False,
            impersonator_user_id=None,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        token = create_access_token(str(user.id), sid=str(uuid4()))
        with (
            patch("app.services.session.session_repo.get_by_id", AsyncMock(return_value=row)),
            pytest.raises(AuthenticationError, match="Session has ended"),
        ):
            await authenticate_socket_token(MagicMock(), token, allow_expired=True)

    async def test_a_live_ordinary_session_resolves_to_its_user(self) -> None:
        user = _user()
        row = MagicMock(
            user_id=user.id,
            is_active=True,
            impersonator_user_id=None,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        token = create_access_token(str(user.id), sid=str(uuid4()))
        with (
            patch("app.services.session.session_repo.get_by_id", AsyncMock(return_value=row)),
            patch("app.services.ws_auth.UserService") as user_service,
        ):
            user_service.return_value.get_by_id = AsyncMock(return_value=user)
            resolved = await authenticate_socket_token(MagicMock(), token, allow_expired=True)

        assert resolved is user
