"""Console message search keeps the existing readable-transcript boundary."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.conversation_search import FoundConversation

pytestmark = pytest.mark.anyio
PERSON, ORG, THREAD = uuid4(), uuid4(), uuid4()
ENDPOINT = f"{settings.API_V1_STR}/conversations/search"


@asynccontextmanager
async def caller(role: str = OrgRoleName.MEMBER) -> AsyncIterator[AsyncClient]:
    ctx = AuthContext(user_id=PERSON, organization_id=ORG, role=role)
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides[deps.get_db_session] = lambda: AsyncMock()
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_current_user] = lambda: SimpleNamespace(id=PERSON)
    app.dependency_overrides[deps.get_active_organization] = lambda: SimpleNamespace(id=ORG)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)


async def test_message_search_serializes_the_indexed_excerpt_for_the_current_reader() -> None:
    result = FoundConversation(
        conversation_id=THREAD,
        title="Travel plans",
        updated_at=datetime(2026, 11, 19, tzinfo=UTC),
        hits=2,
        snippet="Visit **Warsaw** <script>plain text</script>",
        speaker_role="user",
        speaker_name=None,
        message_id=uuid4(),
        thread_root_message_id=None,
        matched_at=datetime(2026, 11, 19, tzinfo=UTC),
    )
    search = AsyncMock(return_value=[result])
    with patch("app.services.conversation_search.search", new=search):
        async with caller() as client:
            response = await client.get(ENDPOINT, params={"query": "Warsaw", "limit": 12})
    assert response.status_code == 200
    assert response.json()["items"][0] == {
        "conversation_id": str(THREAD),
        "title": "Travel plans",
        "updated_at": "2026-11-19T00:00:00+00:00",
        "hits": 2,
        "snippet": result.snippet,
        "speaker_role": "user",
        "speaker_name": None,
    }
    search.assert_awaited_once_with(query="Warsaw", organization_id=ORG, user_id=PERSON, limit=12)


@pytest.mark.security
async def test_message_search_refuses_a_caller_without_agent_read_permission() -> None:
    search = AsyncMock(return_value=[])
    with patch("app.services.conversation_search.search", new=search):
        async with caller(role="") as client:
            response = await client.get(ENDPOINT, params={"query": "private"})
    assert response.status_code == 403
    search.assert_not_awaited()


@pytest.mark.parametrize(
    "params", [{"query": ""}, {"query": "x" * 501}, {"query": "x", "limit": 51}]
)
async def test_message_search_bounds_the_query_and_result_window(
    params: dict[str, str | int],
) -> None:
    search = AsyncMock(return_value=[])
    with patch("app.services.conversation_search.search", new=search):
        async with caller() as client:
            response = await client.get(ENDPOINT, params=params)
    assert response.status_code == 422
    search.assert_not_awaited()
