"""A worker must verify channel access without the API lifespan's registry."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.channel_bot import ChannelBot
from app.db.models.conversation import Conversation
from app.services import channels
from app.services.channels import membership
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.slack import SlackAdapter
from app.services.conversation import ConversationService
from app.services.proactive._personal import PersonalLook

pytestmark = pytest.mark.anyio


@pytest.mark.security
@pytest.mark.parametrize("platform", ["slack", "mattermost"])
@pytest.mark.parametrize("access", ["member", "removed", "unavailable"])
async def test_worker_personal_context_confirms_channel_membership(
    monkeypatch: pytest.MonkeyPatch, platform: str, access: str
) -> None:
    monkeypatch.setattr(channels, "_adapters", {})
    monkeypatch.setattr(membership, "_redis", None)
    monkeypatch.setattr(membership, "unseal_bot_token", lambda bot: "test-token")
    check = AsyncMock(return_value=access == "member")
    if access == "unavailable":
        check.side_effect = httpx.ConnectError("channel unavailable")
    adapter = SlackAdapter if platform == "slack" else MattermostAdapter
    monkeypatch.setattr(adapter, "is_channel_member", check)
    bot = ChannelBot(id=uuid4(), platform=platform)
    conversation = Conversation(id=uuid4())

    async def visible(*args: object, **kwargs: object) -> tuple[list[Conversation], int]:
        allowed = await membership.is_still_member(bot, "room", "person")
        return ([conversation], 1) if allowed else ([], 0)

    monkeypatch.setattr(ConversationService, "list_conversations", visible)
    ctx = AuthContext(organization_id=uuid4(), user_id=uuid4(), role="owner")
    look = PersonalLook(MagicMock(spec=AsyncSession))
    expected = [conversation] if access == "member" else []
    assert await look._conversations(ctx) == expected
    check.assert_awaited_once_with("test-token", "room", "person", api_base_url=None)
    registered = channels.get_adapter(platform)
    assert await look._conversations(ctx) == expected
    assert channels.get_adapter(platform) is registered
