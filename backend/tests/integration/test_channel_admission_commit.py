"""A new channel conversation must precede an independent MCP credential write."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.api_key import ApiKey
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import channel_session_repo
from app.services import api_key as api_key_module
from app.services.channels import router as router_module
from app.services.channels.base import IncomingMessage
from app.services.channels.router import ChannelMessageRouter

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "commit_fails", [False, True], ids=["first-and-followup", "failed-admission"]
)
async def test_first_and_followup_turns_can_mint_conversation_bound_credentials(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, commit_fails: bool
) -> None:
    user = User(id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="unused")
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid4(), name="Channel admission", slug=uuid4().hex, created_by_user_id=user.id
    )
    db.add(org)
    await db.flush()
    agent = Agent(
        id=uuid4(), organization_id=org.id, name="Assistant", slug="assistant", draft_spec={}
    )
    bot = ChannelBot(
        id=uuid4(),
        organization_id=org.id,
        platform="mattermost",
        name="Assistant",
        token_encrypted="unused",
        access_policy={},
    )
    identity = ChannelIdentity(
        id=uuid4(), platform="mattermost", platform_user_id="sender", user_id=user.id
    )
    db.add_all([agent, bot, identity])
    await db.commit()
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    incoming = IncomingMessage(
        platform="mattermost",
        bot_id=str(bot.id),
        platform_chat_id="room:thread",
        platform_user_id="sender",
        chat_type="private",
        text="hello",
        addressed=True,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def independent_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session
            await session.commit()

    seen: list[UUID] = []

    async def prepare_credential(_self: object, _bot: ChannelBot, **_kwargs: object) -> bool:
        session = await channel_session_repo.get_by_bot_and_chat(
            db, bot_id=bot.id, platform_chat_id=incoming.platform_chat_id
        )
        assert session is not None and session.conversation_id is not None
        token = await api_key_module.mint_for_run(
            ctx, agent_id=agent.id, conversation_id=session.conversation_id
        )
        assert token is not None
        async with factory() as reader:
            keys = list((await reader.scalars(select(ApiKey))).all())
            assert keys and all(
                key.source_conversation_id == session.conversation_id for key in keys
            )
        seen.append(session.conversation_id)
        return True

    monkeypatch.setattr(api_key_module, "get_db_context", independent_session)
    monkeypatch.setattr(
        router_module.channel_bot_repo, "get_for_inbound", AsyncMock(return_value=bot)
    )
    monkeypatch.setattr(ChannelMessageRouter, "_resolve_identity", AsyncMock(return_value=identity))
    monkeypatch.setattr(ChannelMessageRouter, "_handle_command", AsyncMock(return_value=None))
    monkeypatch.setattr(
        ChannelMessageRouter, "_sender_is_active_member", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(ChannelMessageRouter, "_check_rate_limit", AsyncMock())
    monkeypatch.setattr(router_module.ChannelPrompts, "reply", prepare_credential)
    router = ChannelMessageRouter()
    if commit_fails:
        monkeypatch.setattr(
            db, "commit", AsyncMock(side_effect=RuntimeError("admission not saved"))
        )
        with pytest.raises(RuntimeError, match="admission not saved"):
            await router._route_inner(incoming, db)
        assert seen == []
        async with factory() as reader:
            assert list((await reader.scalars(select(ApiKey))).all()) == []
        return
    await router._route_inner(incoming, db)
    await router._route_inner(incoming, db)
    assert len(seen) == 2 and seen[0] == seen[1]
