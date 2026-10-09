"""Disconnecting a portal, the admin-consent link, and the callback's named refusal.

The permission each route demands is `tests/api/test_platform_routes.py`'s; what
is asserted here is the wiring - which service call a request reaches and the
shape it answers with. The service is a mock: its behaviour is
`tests/test_mcp_connections.py`'s to prove.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.mcp_oauth import OAuthError
from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.mcp_connection import AdminConsentRequired

pytestmark = pytest.mark.anyio

ORG = f"{settings.API_V1_STR}/mcp-connections"
CALLBACK = f"{settings.API_V1_STR}/me/mcp-connections/oauth/callback"


@pytest.fixture
def service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def client(
    service: MagicMock, mock_db_session: Any, mock_redis: MagicMock
) -> Iterator[Callable[[], AbstractAsyncContextManager[AsyncClient]]]:
    user = MagicMock()
    user.id = uuid.uuid4()
    context = AuthContext(user_id=user.id, organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)
    app.dependency_overrides[deps.get_db_session] = lambda: mock_db_session
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_mcp_connection_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


async def test_disconnecting_a_portal_answers_204(client, service: MagicMock) -> None:
    service.disconnect_portal = AsyncMock()

    async with client() as opened:
        response = await opened.delete(f"{ORG}/portals/microsoft")

    assert response.status_code == 204
    assert service.disconnect_portal.await_args.kwargs["portal_key"] == "microsoft"


async def test_disconnecting_a_portal_nobody_connected_is_a_404(client, service: MagicMock) -> None:
    service.disconnect_portal = AsyncMock(
        side_effect=NotFoundError(message="This portal is not connected")
    )

    async with client() as opened:
        response = await opened.delete(f"{ORG}/portals/google")

    assert response.status_code == 404


async def test_the_admin_consent_link_is_answered_as_a_url(client, service: MagicMock) -> None:
    link = "https://login.microsoftonline.com/contoso/v2.0/adminconsent?client_id=x"
    service.microsoft_admin_consent_url = AsyncMock(return_value=link)

    async with client() as opened:
        response = await opened.get(f"{ORG}/portals/microsoft/admin-consent")

    assert response.status_code == 200
    assert response.json() == {"url": link}


async def test_a_consent_only_an_administrator_can_give_is_named(
    client, service: MagicMock
) -> None:
    """So the card can say who has to act, rather than only showing a sentence."""
    service.oauth_callback = AsyncMock(
        side_effect=AdminConsentRequired("Your administrator has to approve this app")
    )

    async with client() as opened:
        response = await opened.post(CALLBACK, json={"state": "s", "code": "c"})

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["failure"] == "admin_consent_required"


async def test_any_other_refusal_names_no_failure(client, service: MagicMock) -> None:
    service.oauth_callback = AsyncMock(side_effect=OAuthError("Microsoft refused"))

    async with client() as opened:
        response = await opened.post(CALLBACK, json={"state": "s", "code": "c"})

    assert response.json()["ok"] is False
    assert response.json()["failure"] is None
