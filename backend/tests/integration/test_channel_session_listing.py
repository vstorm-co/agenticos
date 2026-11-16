"""Listing a bot's sessions reads the bot through the caller's organization."""

import uuid

import pytest

from app.core.exceptions import NotFoundError
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_session import ChannelSession
from app.db.models.organization import Organization
from app.db.models.user import User
from app.services.channel_bot import ChannelBotService

pytestmark = pytest.mark.anyio


async def _org(db) -> Organization:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@acme.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(), name="Acme", slug=uuid.uuid4().hex[:12], created_by_user_id=user.id
    )
    db.add(org)
    await db.flush()
    return org


async def test_another_organizations_bot_lists_no_sessions(db) -> None:
    org_a, org_b = await _org(db), await _org(db)
    bot = ChannelBot(
        organization_id=org_a.id,
        platform="telegram",
        name="Support",
        token_encrypted="sealed",
        secret_key_version=1,
    )
    db.add(bot)
    await db.flush()
    identity = ChannelIdentity(platform="telegram", platform_user_id="u-1")
    db.add(identity)
    await db.flush()
    db.add(ChannelSession(bot_id=bot.id, identity_id=identity.id, platform_chat_id="chat-1"))
    await db.flush()

    with pytest.raises(NotFoundError):
        await ChannelBotService(db, organization_id=org_b.id).list_sessions(bot.id)

    items, total = await ChannelBotService(db, organization_id=org_a.id).list_sessions(bot.id)
    assert len(items) == 1
    assert total == 1
