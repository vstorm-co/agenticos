"""Leaving a conversation shared with you, and changing a share, through the app."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    get_active_organization,
    get_conversation_share_service,
    get_current_user,
    get_db_session,
)
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


ORGANIZATION = SimpleNamespace(id=uuid4())


@pytest.fixture
async def shares() -> AsyncGenerator[AsyncMock]:
    app.dependency_overrides[get_current_user] = lambda: CALLER
    app.dependency_overrides[get_active_organization] = lambda: ORGANIZATION
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
    shares.leave.assert_awaited_once_with(
        CONVERSATION_ID, CALLER.id, organization_id=ORGANIZATION.id
    )


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
    assert shares.change_permission.await_args.kwargs == {
        "permission": "edit",
        "organization_id": ORGANIZATION.id,
    }


@pytest.mark.security
async def test_the_shared_list_is_the_active_organizations(shares: AsyncMock) -> None:
    shares.list_shared_with_me = AsyncMock(return_value=([], 0))

    async with _client() as client:
        response = await client.get(f"{settings.API_V1_STR}/conversations/shared-with-me")

    assert response.status_code == 200
    assert shares.list_shared_with_me.await_args.kwargs["organization_id"] == ORGANIZATION.id


@pytest.mark.security
async def test_a_permission_the_api_does_not_know_is_refused(shares: AsyncMock) -> None:
    async with _client() as client:
        response = await client.patch(
            f"{settings.API_V1_STR}/conversations/{CONVERSATION_ID}/shares/{uuid4()}",
            json={"permission": "owner"},
        )

    assert response.status_code == 422
    shares.change_permission.assert_not_awaited()


@pytest.mark.security
async def test_share_permissions_cannot_be_changed_from_another_organization(
    shares: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.repositories import conversation_repo, conversation_share_repo
    from app.services.conversation_share import ConversationShareService

    row = SimpleNamespace(user_id=CALLER.id, organization_id=uuid4())
    share = SimpleNamespace(
        id=uuid4(),
        conversation_id=CONVERSATION_ID,
        shared_by=CALLER.id,
        shared_with=uuid4(),
        share_token=None,
        permission="edit",
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(conversation_repo, "get_conversation_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(conversation_share_repo, "get_by_id", AsyncMock(return_value=share))
    monkeypatch.setattr(conversation_share_repo, "set_permission", AsyncMock(return_value=share))
    real = ConversationShareService(AsyncMock())
    app.dependency_overrides[get_conversation_share_service] = lambda: real
    async with _client() as client:
        response = await client.patch(
            f"{settings.API_V1_STR}/conversations/{CONVERSATION_ID}/shares/{share.id}",
            json={"permission": "edit"},
        )
    assert response.status_code == 404


@pytest.mark.security
async def test_share_fanout_limit_returns_429_with_the_retry_interval(shares: AsyncMock) -> None:
    from app.core.exceptions import RateLimitError

    shares.share_conversation.side_effect = RateLimitError(
        message="Too many shares", details={"retry_after_seconds": 23}
    )
    async with _client() as client:
        response = await client.post(
            f"{settings.API_V1_STR}/conversations/{CONVERSATION_ID}/shares",
            json={"shared_with": str(uuid4())},
        )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "23"
