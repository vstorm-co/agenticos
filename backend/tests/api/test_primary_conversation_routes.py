"""The primary-conversation route, wired (#2575)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

PERSON, ORG, AGENT, CONVERSATION = uuid4(), uuid4(), uuid4(), uuid4()


@asynccontextmanager
async def _client() -> AsyncIterator[AsyncClient]:
    ctx = AuthContext(user_id=PERSON, organization_id=ORG, role=OrgRoleName.VIEWER)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_a_viewer_opens_their_own_conversation_with_an_agent() -> None:
    opened = AsyncMock(return_value=CONVERSATION)
    with patch("app.services.primary_conversation.PrimaryConversationService.open", new=opened):
        async with _client() as client:
            response = await client.post(
                f"{settings.API_V1_STR}/agents/{AGENT}/primary-conversation"
            )

    assert response.status_code == 200
    assert response.json() == {"conversation_id": str(CONVERSATION)}
    assert opened.await_args.args[1] == AGENT


async def test_an_agent_the_caller_cannot_see_is_a_404() -> None:
    refused = AsyncMock(side_effect=NotFoundError(message="Agent not found"))
    with patch("app.services.primary_conversation.PrimaryConversationService.open", new=refused):
        async with _client() as client:
            response = await client.post(
                f"{settings.API_V1_STR}/agents/{AGENT}/primary-conversation"
            )

    assert response.status_code == 404
