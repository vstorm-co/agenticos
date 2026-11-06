"""Leaving a conversation shared with you, and changing a share, through the app."""

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


async def test_the_owner_changes_a_share_and_gets_it_back(shares: AsyncMock) -> None:
    share_id = uuid4()
    shares.change_permission = AsyncMock(
        return_value=SimpleNamespace(
            id=share_id,
            conversation_id=CONVERSATION_ID,
            shared_by=CALLER.id,
            shared_with=uuid4(),
            share_token=None,
            permission="edit",
            created_at=datetime.now(UTC),
        )
    )

    async with _client() as client:
        response = await client.patch(
            f"{settings.API_V1_STR}/conversations/{CONVERSATION_ID}/shares/{share_id}",
            json={"permission": "edit"},
        )

    assert response.status_code == 200
    assert response.json()["permission"] == "edit"
    assert shares.change_permission.await_args.args == (CONVERSATION_ID, share_id, CALLER.id)
    assert shares.change_permission.await_args.kwargs == {"permission": "edit"}


@pytest.mark.security
async def test_a_permission_the_api_does_not_know_is_refused(shares: AsyncMock) -> None:
    async with _client() as client:
        response = await client.patch(
            f"{settings.API_V1_STR}/conversations/{CONVERSATION_ID}/shares/{uuid4()}",
            json={"permission": "owner"},
        )

    assert response.status_code == 422
    shares.change_permission.assert_not_awaited()
