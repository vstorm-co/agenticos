"""The message search route binds search to the signed-in reader and tenant."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext
from app.main import app
from app.services.conversation_search import FoundConversation

pytestmark = pytest.mark.anyio

AT = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


@asynccontextmanager
async def _client(
    *, user_id: UUID, organization_id: UUID, search: AsyncMock
) -> AsyncIterator[AsyncClient]:
    """A session in one active organization, with the database service stubbed."""
    from app.api.routes.v1 import conversations

    app.dependency_overrides[deps.get_current_user] = lambda: SimpleNamespace(
        id=user_id, is_app_admin=False
    )
    app.dependency_overrides[deps.get_active_organization] = lambda: SimpleNamespace(
        id=organization_id
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=user_id, organization_id=organization_id, role="member"
    )
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    original = conversations.conversation_search.search
    conversations.conversation_search.search = search
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        conversations.conversation_search.search = original
        app.dependency_overrides.clear()


def _hit() -> FoundConversation:
    return FoundConversation(
        conversation_id=uuid4(),
        message_id=uuid4(),
        thread_root_message_id=uuid4(),
        title="Project notes",
        updated_at=AT,
        matched_at=AT,
        hits=2,
        snippet="the **pricing** decision",
        speaker_role="user",
        speaker_name="Sam",
    )


class TestMessageSearchRoute:
    @pytest.mark.security
    async def test_search_is_literal_tenant_scoped_and_returns_message_target(self) -> None:
        user_id, organization_id = uuid4(), uuid4()
        hit = _hit()
        search = AsyncMock(return_value=[hit])

        async with _client(
            user_id=user_id, organization_id=organization_id, search=search
        ) as client:
            response = await client.get(
                f"{settings.API_V1_STR}/conversations/search/messages",
                params={"query": "  pricing -hobby  "},
            )

        assert response.status_code == 200
        kwargs = search.await_args.kwargs
        assert kwargs == {
            "query": "pricing -hobby",
            "organization_id": organization_id,
            "user_id": user_id,
            "limit": 20,
            "literal": True,
        }
        [result] = response.json()
        assert result["conversation_id"] == str(hit.conversation_id)
        assert result["message_id"] == str(hit.message_id)
        assert result["thread_root_message_id"] == str(hit.thread_root_message_id)
        assert result["snippet"] == hit.snippet

    async def test_overlong_query_is_rejected_before_search(self) -> None:
        search = AsyncMock(return_value=[])
        async with _client(user_id=uuid4(), organization_id=uuid4(), search=search) as client:
            response = await client.get(
                f"{settings.API_V1_STR}/conversations/search/messages",
                params={"query": "x" * 121},
            )

        assert response.status_code == 422
        search.assert_not_awaited()

    async def test_long_single_token_snippet_is_bounded_in_http_response(self) -> None:
        hit = replace(_hit(), snippet="x" * 5000)
        search = AsyncMock(return_value=[hit])
        async with _client(user_id=uuid4(), organization_id=uuid4(), search=search) as client:
            response = await client.get(
                f"{settings.API_V1_STR}/conversations/search/messages",
                params={"query": "x"},
            )

        assert response.status_code == 200
        assert response.json()[0]["snippet"] == "x" * 1200

    async def test_whitespace_does_not_issue_a_search(self) -> None:
        search = AsyncMock(return_value=[])
        async with _client(user_id=uuid4(), organization_id=uuid4(), search=search) as client:
            response = await client.get(
                f"{settings.API_V1_STR}/conversations/search/messages", params={"query": "   "}
            )

        assert response.status_code == 200
        assert response.json() == []
        search.assert_not_awaited()
