"""Marking a conversation read, through the app.

The mark is the **reader's**, as a favourite is: a row per `(user_id,
conversation_id)`, authorized as a read. What is pinned here is the wiring - the
service call, its caller and tenant, and that a thread the caller cannot see is
missing.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    get_active_organization,
    get_auth_context,
    get_conversation_service,
    get_current_user,
    get_db_session,
)
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

CONVERSATION_ID = uuid4()
ENDPOINT = f"{settings.API_V1_STR}/conversations/{CONVERSATION_ID}/read"


class _User:
    def __init__(self) -> None:
        self.id = uuid4()
        self.email = "kacper@example.com"
        self.is_app_admin = False
        self.is_active = True
        self.created_at = datetime.now(UTC)


class _Organization:
    def __init__(self) -> None:
        self.id = uuid4()


@pytest.fixture
async def service() -> AsyncGenerator[AsyncMock]:
    caller = _User()
    app.dependency_overrides[get_current_user] = lambda: caller
    organization = _Organization()
    app.dependency_overrides[get_active_organization] = lambda: organization
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=caller.id, organization_id=organization.id, role=str(OrgRoleName.MEMBER)
    )
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    conversations = AsyncMock()
    app.dependency_overrides[get_conversation_service] = lambda: conversations
    yield conversations
    app.dependency_overrides.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_marking_read_carries_the_caller_and_answers_no_content(service: AsyncMock) -> None:
    service.mark_read = AsyncMock(return_value=None)

    async with _client() as client:
        response = await client.post(ENDPOINT)

    assert response.status_code == 204
    kwargs = service.mark_read.await_args.kwargs
    assert kwargs["user_id"] is not None
    assert kwargs["organization_id"] is not None
    assert kwargs["ctx"] is not None
    assert service.mark_read.await_args.args[0] == CONVERSATION_ID


async def test_a_thread_the_caller_cannot_see_is_missing(service: AsyncMock) -> None:
    service.mark_read = AsyncMock(side_effect=NotFoundError(message="Conversation not found"))

    async with _client() as client:
        response = await client.post(ENDPOINT)

    assert response.status_code == 404
