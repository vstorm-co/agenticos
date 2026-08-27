"""Starring a conversation, through the app.

The star is the **reader's**, and the whole design follows from that: it is a row
per `(user_id, conversation_id)`, it is authorized as a read rather than a write,
and the flag a listing answers with is the caller's rather than the row's (#929).

What is pinned here is the wiring - which service call each verb makes, that both
are idempotent, and that a caller who cannot see the thread cannot star it.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
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
ENDPOINT = f"{settings.API_V1_STR}/conversations/{CONVERSATION_ID}/favourite"


class _User:
    def __init__(self) -> None:
        self.id = uuid4()
        self.email = "kacper@example.com"
        self.is_app_admin = False
        self.is_active = True
        self.created_at = datetime.now(UTC)


class _Conversation:
    """Enough of a row for `ConversationRead` to serialize it."""

    def __init__(self, *, is_favourite: bool) -> None:
        self.id = CONVERSATION_ID
        self.title = "Rota cover"
        self.user_id = uuid4()
        self.organization_id = uuid4()
        self.is_archived = False
        self.is_favourite = is_favourite
        self.agents: list[Any] = []
        self.created_at = datetime.now(UTC)
        self.updated_at = None


class _Organization:
    def __init__(self) -> None:
        self.id = uuid4()


@pytest.fixture
async def service() -> AsyncGenerator[AsyncMock, None]:
    caller = _User()
    app.dependency_overrides[get_current_user] = lambda: caller
    organization = _Organization()
    app.dependency_overrides[get_active_organization] = lambda: organization
    # The read of a trigger's run-log needs it: without a context
    # `_may_read_trigger_log` answers false, and a conversation the caller may
    # read through `runs:view` would be one they could not star.
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


async def test_starring_asks_for_the_star_and_answers_with_the_row(service: AsyncMock) -> None:
    service.set_favourite = AsyncMock(return_value=_Conversation(is_favourite=True))

    async with _client() as client:
        response = await client.post(ENDPOINT)

    assert response.status_code == 200
    assert response.json()["is_favourite"] is True
    assert service.set_favourite.await_args.kwargs["favourite"] is True


async def test_unstarring_is_the_same_call_the_other_way(service: AsyncMock) -> None:
    """A DELETE that answers with the row rather than 204: the sidebar
    re-renders one item and would otherwise have to guess what it now says."""
    service.set_favourite = AsyncMock(return_value=_Conversation(is_favourite=False))

    async with _client() as client:
        response = await client.delete(ENDPOINT)

    assert response.status_code == 200
    assert response.json()["is_favourite"] is False
    assert service.set_favourite.await_args.kwargs["favourite"] is False


async def test_both_carry_the_caller_and_the_active_organization(service: AsyncMock) -> None:
    """The star is one person's in one tenant. Neither may come off the row."""
    service.set_favourite = AsyncMock(return_value=_Conversation(is_favourite=True))

    async with _client() as client:
        await client.post(ENDPOINT)

    kwargs = service.set_favourite.await_args.kwargs
    assert kwargs["user_id"] is not None
    assert kwargs["organization_id"] is not None
    # And the context, which is what lets a trigger's run-log be starred at all.
    assert kwargs["ctx"] is not None
    assert service.set_favourite.await_args.args[0] == CONVERSATION_ID


async def test_a_thread_the_caller_cannot_see_is_missing(service: AsyncMock) -> None:
    """Reported as missing rather than forbidden, like every other read of one:
    "you may not star this" tells somebody in another tenant that it exists."""
    service.set_favourite = AsyncMock(side_effect=NotFoundError(message="Conversation not found"))

    async with _client() as client:
        response = await client.post(ENDPOINT)

    assert response.status_code == 404
