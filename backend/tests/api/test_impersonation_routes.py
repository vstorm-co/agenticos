"""The three routes an impersonation passes through, and what each refuses.

`POST /admin/users/{id}/impersonate` opens one, `GET /auth/me` says whether the
request is one, `DELETE /auth/impersonation` ends it - and the auth dependency
under every route refuses the token once its row has been ended (#1044). These
run through the real `get_current_user` with real tokens, because the refusal
lives in the dependency and a test that overrides it tests nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.api.deps import get_current_user
from app.core.audit import set_impersonator
from app.core.config import settings
from app.core.security import create_access_token, verify_token
from app.main import app
from app.services import impersonation as module
from app.services.session import hash_token

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)


class _Account:
    """A user row with every column `MeRead` reads, and nothing a mock invents."""

    def __init__(self, *, email: str, is_app_admin: bool = False) -> None:
        self.id = uuid.uuid4()
        self.email = email
        self.full_name = None
        self.is_active = True
        self.is_app_admin = is_app_admin
        self.avatar_url = None
        self.avatar_color = None
        self.onboarding_completed_at = None
        self.notify_budget_alerts = True
        self.notify_approval_requests = True
        self.notify_usage_reports = True
        self.created_at = NOW
        self.updated_at = None


@pytest.fixture(autouse=True)
def _clean() -> AsyncGenerator[None, None]:
    yield
    set_impersonator(None)
    module._active.set(None)
    app.dependency_overrides.clear()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _row(
    *, session_id: uuid.UUID, target: _Account, admin: _Account, token: str, **overrides: Any
) -> Any:
    row = MagicMock()
    row.id = session_id
    row.user_id = target.id
    row.impersonator_user_id = admin.id
    row.refresh_token_hash = hash_token(token)
    row.is_active = True
    row.expires_at = NOW.replace(year=2999)
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


class TestARequestOnAnImpersonation:
    """The dependency every route shares, driven end to end."""

    def setup_method(self) -> None:
        self.admin = _Account(email="admin@example.com", is_app_admin=True)
        self.target = _Account(email="customer@example.com")
        self.session_id = uuid.uuid4()
        self.token = create_access_token(
            str(self.target.id), act=str(self.admin.id), sid=str(self.session_id)
        )

    def _users(self) -> AsyncMock:
        accounts = {self.admin.id: self.admin, self.target.id: self.target}
        return AsyncMock(side_effect=lambda db, user_id: accounts.get(user_id))

    async def test_a_live_impersonation_reports_itself(self, client: AsyncClient) -> None:
        """What the banner is drawn from: the account is the target's, and the
        request says who is really acting and until when."""
        row = _row(
            session_id=self.session_id, target=self.target, admin=self.admin, token=self.token
        )
        with (
            patch("app.repositories.user.get_by_id", new=self._users()),
            patch("app.repositories.session.get_by_id", new=AsyncMock(return_value=row)),
        ):
            response = await client.get(
                f"{settings.API_V1_STR}/auth/me", headers=_bearer(self.token)
            )

        assert response.status_code == 200
        body = response.json()
        assert body["email"] == self.target.email
        assert body["impersonation"]["session_id"] == str(self.session_id)
        assert body["impersonation"]["impersonator"]["email"] == self.admin.email
        assert body["impersonation"]["expires_at"].startswith("2999-")

    async def test_an_ordinary_session_reports_no_impersonation(self, client: AsyncClient) -> None:
        with (
            patch("app.repositories.user.get_by_id", new=self._users()),
            patch("app.repositories.session.get_by_id", new=AsyncMock()) as lookup,
        ):
            response = await client.get(
                f"{settings.API_V1_STR}/auth/me",
                headers=_bearer(create_access_token(str(self.target.id))),
            )

        assert response.status_code == 200
        assert response.json()["impersonation"] is None
        lookup.assert_not_awaited()

    async def test_an_ended_impersonation_is_refused_with_401(self, client: AsyncClient) -> None:
        """The token is still signed and still inside its hour. The row says no."""
        row = _row(
            session_id=self.session_id,
            target=self.target,
            admin=self.admin,
            token=self.token,
            is_active=False,
        )
        with (
            patch("app.repositories.user.get_by_id", new=self._users()) as users,
            patch("app.repositories.session.get_by_id", new=AsyncMock(return_value=row)),
        ):
            response = await client.get(
                f"{settings.API_V1_STR}/auth/me", headers=_bearer(self.token)
            )

        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Impersonation has ended"
        users.assert_not_awaited()

    async def test_an_expired_impersonation_is_refused_with_401(self, client: AsyncClient) -> None:
        row = _row(
            session_id=self.session_id,
            target=self.target,
            admin=self.admin,
            token=self.token,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        with (
            patch("app.repositories.user.get_by_id", new=self._users()),
            patch("app.repositories.session.get_by_id", new=AsyncMock(return_value=row)),
        ):
            response = await client.get(
                f"{settings.API_V1_STR}/auth/me", headers=_bearer(self.token)
            )

        assert response.status_code == 401

    async def test_a_token_from_before_impersonations_were_sessions_is_refused(
        self, client: AsyncClient
    ) -> None:
        """`act` with no `sid` - the unendable credential this replaces - stops
        working at the upgrade rather than running out its hour."""
        legacy = create_access_token(str(self.target.id), act=str(self.admin.id))
        with patch("app.repositories.user.get_by_id", new=self._users()):
            response = await client.get(f"{settings.API_V1_STR}/auth/me", headers=_bearer(legacy))

        assert response.status_code == 401

    async def test_ending_it_closes_the_row_and_answers_204(
        self, client: AsyncClient, mock_db_session: AsyncMock
    ) -> None:
        row = _row(
            session_id=self.session_id, target=self.target, admin=self.admin, token=self.token
        )
        mock_db_session.add = MagicMock()
        with (
            patch("app.repositories.user.get_by_id", new=self._users()),
            patch("app.repositories.session.get_by_id", new=AsyncMock(return_value=row)),
            patch("app.repositories.session.deactivate", new=AsyncMock()) as deactivate,
        ):
            response = await client.delete(
                f"{settings.API_V1_STR}/auth/impersonation", headers=_bearer(self.token)
            )

        assert response.status_code == 204
        deactivate.assert_awaited_once_with(mock_db_session, self.session_id)
        (entry,) = [call.args[0] for call in mock_db_session.add.call_args_list]
        assert entry.action == "admin.user.impersonation_ended"
        assert entry.actor_user_id == self.admin.id
        assert entry.target_id == str(self.target.id)

    async def test_ending_when_nobody_is_acting_as_anybody_is_refused(
        self, client: AsyncClient
    ) -> None:
        with (
            patch("app.repositories.user.get_by_id", new=self._users()),
            patch("app.repositories.session.deactivate", new=AsyncMock()) as deactivate,
        ):
            response = await client.delete(
                f"{settings.API_V1_STR}/auth/impersonation",
                headers=_bearer(create_access_token(str(self.admin.id))),
            )

        assert response.status_code == 400
        deactivate.assert_not_awaited()

    async def test_the_impersonation_credential_cannot_be_refreshed(
        self, client: AsyncClient
    ) -> None:
        """Posted back as a refresh token, the access token finds its own row by
        hash. Honouring it would mint a plain week-long session as the target."""
        row = _row(
            session_id=self.session_id, target=self.target, admin=self.admin, token=self.token
        )
        with (
            patch(
                "app.repositories.session.get_by_refresh_token_hash",
                new=AsyncMock(return_value=row),
            ),
            patch("app.repositories.session.update_last_used", new=AsyncMock()) as touched,
        ):
            response = await client.post(
                f"{settings.API_V1_STR}/auth/refresh", json={"refresh_token": self.token}
            )

        assert response.status_code == 401
        touched.assert_not_awaited()


class TestStartingOne:
    ENDPOINT = f"{settings.API_V1_STR}/admin/users/{{user_id}}/impersonate"

    async def test_an_app_admin_gets_a_session_not_a_bare_token(
        self, client: AsyncClient, mock_db_session: AsyncMock
    ) -> None:
        admin = _Account(email="admin@example.com", is_app_admin=True)
        target = _Account(email="customer@example.com")
        app.dependency_overrides[get_current_user] = lambda: admin
        mock_db_session.add = MagicMock()
        created: dict[str, Any] = {}

        async def create(db: Any, **kwargs: Any) -> MagicMock:
            created.update(kwargs)
            row = MagicMock()
            row.id = kwargs["session_id"]
            row.expires_at = kwargs["expires_at"]
            return row

        with (
            patch("app.repositories.user.get_by_id", new=AsyncMock(return_value=target)),
            patch("app.repositories.session.create", new=AsyncMock(side_effect=create)),
            patch("app.repositories.deployment_settings.get", new=AsyncMock(return_value=None)),
        ):
            response = await client.post(self.ENDPOINT.format(user_id=target.id))

        assert response.status_code == 200
        body = response.json()
        payload = verify_token(body["access_token"])
        assert payload is not None
        assert payload["sid"] == body["session_id"] == str(created["session_id"])
        assert payload["act"] == str(admin.id)
        assert body["impersonated_user_id"] == str(target.id)
        assert created["impersonator_user_id"] == admin.id

    async def test_somebody_who_is_not_an_app_admin_is_refused(self, client: AsyncClient) -> None:
        member = _Account(email="member@example.com")
        app.dependency_overrides[get_current_user] = lambda: member

        with patch("app.repositories.session.create", new=AsyncMock()) as create:
            response = await client.post(self.ENDPOINT.format(user_id=uuid.uuid4()))

        assert response.status_code == 403
        create.assert_not_awaited()

    async def test_acting_as_yourself_is_refused(self, client: AsyncClient) -> None:
        admin = _Account(email="admin@example.com", is_app_admin=True)
        app.dependency_overrides[get_current_user] = lambda: admin

        with (
            patch("app.repositories.user.get_by_id", new=AsyncMock(return_value=admin)),
            patch("app.repositories.session.create", new=AsyncMock()) as create,
        ):
            response = await client.post(self.ENDPOINT.format(user_id=admin.id))

        assert response.status_code == 400
        create.assert_not_awaited()


class TestTheWebSocketDoor:
    """The chat socket authenticates on its own; the same row decides for it."""

    def setup_method(self) -> None:
        self.admin = _Account(email="admin@example.com", is_app_admin=True)
        self.target = _Account(email="customer@example.com")
        self.session_id = uuid.uuid4()
        self.token = create_access_token(
            str(self.target.id), act=str(self.admin.id), sid=str(self.session_id)
        )

    async def _connect(self, row: Any) -> Any:
        from contextlib import asynccontextmanager

        from app.api.deps import get_current_user_ws

        db = AsyncMock()

        @asynccontextmanager
        async def context() -> AsyncGenerator[AsyncMock, None]:
            yield db

        websocket = MagicMock()
        websocket.headers = {"sec-websocket-protocol": f"access_token.{self.token}, chat"}
        websocket.state = MagicMock()
        accounts = {self.admin.id: self.admin, self.target.id: self.target}
        with (
            patch("app.api.deps.get_db_context", new=context),
            patch("app.repositories.session.get_by_id", new=AsyncMock(return_value=row)),
            patch(
                "app.repositories.user.get_by_id",
                new=AsyncMock(side_effect=lambda db, user_id: accounts.get(user_id)),
            ),
        ):
            return await get_current_user_ws(websocket, access_token=None)

    async def test_a_live_impersonation_opens_the_socket_as_the_target(self) -> None:
        row = _row(
            session_id=self.session_id, target=self.target, admin=self.admin, token=self.token
        )

        user = await self._connect(row)

        assert user is self.target

    async def test_an_ended_impersonation_closes_the_handshake(self) -> None:
        """Closed with the socket's own code rather than an HTTP refusal, which
        Starlette would turn into a 500 on the upgrade."""
        from fastapi import WebSocketException

        row = _row(
            session_id=self.session_id,
            target=self.target,
            admin=self.admin,
            token=self.token,
            is_active=False,
        )

        with pytest.raises(WebSocketException) as closed:
            await self._connect(row)

        assert closed.value.code == 4001
        assert closed.value.reason == "Impersonation has ended"
