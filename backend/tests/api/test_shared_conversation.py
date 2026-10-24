"""Opening a conversation by its share link, with no account.

The route declared a flat `ConversationReadWithMessages` while the service - and
the console's `/shared/[token]` page - spoke `{conversation, share}`, so every
open of a share link answered 500. The failed validation also printed the
response, share token and all, into the server log.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_conversation_share_service, get_db_session
from app.core.config import settings
from app.main import app
from app.services.conversation_share import ConversationShareService

pytestmark = pytest.mark.anyio

TOKEN = "s3cr3t-share-token-0123456789abcdefghijklmn"
ENDPOINT = f"{settings.API_V1_STR}/conversations/shared/{TOKEN}"
MODULE = "app.services.conversation_share"


def _share() -> MagicMock:
    share = MagicMock()
    share.id = uuid4()
    share.conversation_id = uuid4()
    share.permission = "view"
    share.share_token = TOKEN
    return share


def _conversation() -> MagicMock:
    message = MagicMock()
    message.id = uuid4()
    message.role = "user"
    message.content = "Publish the weekly report."
    message.created_at = datetime.now(UTC)
    conv = MagicMock()
    conv.id = uuid4()
    conv.title = "Weekly report"
    conv.project_id = None
    conv.messages = [message]
    return conv


@pytest.fixture
async def shares() -> AsyncGenerator[None]:
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    app.dependency_overrides[get_conversation_share_service] = lambda: ConversationShareService(
        AsyncMock()
    )
    yield
    app.dependency_overrides.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.security
async def test_a_share_link_opens_the_conversation_without_echoing_its_token(shares: None):
    share, conv = _share(), _conversation()
    with (
        patch(f"{MODULE}.conversation_share_repo.get_by_token", AsyncMock(return_value=share)),
        patch(f"{MODULE}.conversation_repo.get_conversation_by_id", AsyncMock(return_value=conv)),
    ):
        async with _client() as client:
            response = await client.get(ENDPOINT)

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["title"] == "Weekly report"
    assert [m["content"] for m in body["conversation"]["messages"]] == [
        "Publish the weekly report."
    ]
    assert body["share"] == {"id": str(share.id), "permission": "view"}
    # Whoever holds the link already has the token; the answer need not repeat it.
    assert TOKEN not in response.text


async def test_an_unknown_link_is_not_found(shares: None):
    with patch(f"{MODULE}.conversation_share_repo.get_by_token", AsyncMock(return_value=None)):
        async with _client() as client:
            response = await client.get(ENDPOINT)

    assert response.status_code == 404
