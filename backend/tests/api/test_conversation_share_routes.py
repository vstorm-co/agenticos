"""Removing a conversation somebody shared with you from your chats, through the app."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_conversation_share_service, get_current_user, get_db_session
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.main import app

pytestmark = pytest.mark.anyio

CONVERSATION_ID = uuid4()
ENDPOINT = f"{settings.API_V1_STR}/conversations/{CONVERSATION_ID}/shared-with-me"
CALLER = SimpleNamespace(
    id=uuid4(),
    email="nina@example.com",
    is_app_admin=False,
    is_active=True,
    created_at=datetime.now(UTC),
)


@pytest.fixture
async def shares() -> AsyncGenerator[AsyncMock]:
    app.dependency_overrides[get_current_user] = lambda: CALLER
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    service = AsyncMock()
    app.dependency_overrides[get_conversation_share_service] = lambda: service
    yield service
    app.dependency_overrides.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_the_caller_leaves_their_own_share(shares: AsyncMock) -> None:
    async with _client() as client:
        response = await client.delete(ENDPOINT)

    assert response.status_code == 204
    shares.leave.assert_awaited_once_with(CONVERSATION_ID, CALLER.id)


async def test_a_conversation_never_shared_with_the_caller_is_missing(shares: AsyncMock) -> None:
    shares.leave = AsyncMock(side_effect=NotFoundError(message="Conversation not shared with you"))

    async with _client() as client:
        response = await client.delete(ENDPOINT)

    assert response.status_code == 404
