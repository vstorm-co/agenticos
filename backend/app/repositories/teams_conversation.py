"""Teams conversations a bot has been in, and the service each lives on (#1985)."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_bot import ChannelBot
from app.db.models.teams_conversation import TeamsConversation


async def record(
    db: AsyncSession,
    *,
    organization_id: UUID,
    bot_id: UUID,
    key: str,
    conversation_id: str,
    service_url: str,
    tenant_id: str | None,
    conversation_type: str,
    name: str | None,
) -> None:
    """Remember where a conversation lives, as of the activity that just arrived.

    One upsert, because two activities from one conversation arrive together
    whenever somebody types quickly. A later activity overwrites the service -
    Teams moves a conversation between regions - and keeps a name it already
    had when this one carries none.
    """
    now = datetime.now(UTC)
    statement = insert(TeamsConversation).values(
        organization_id=organization_id,
        bot_id=bot_id,
        key=key,
        conversation_id=conversation_id,
        service_url=service_url,
        tenant_id=tenant_id,
        conversation_type=conversation_type,
        name=name,
        last_activity_at=now,
    )
    await db.execute(
        statement.on_conflict_do_update(
            constraint="uq_teams_conversation_bot_key",
            set_={
                "service_url": statement.excluded.service_url,
                "tenant_id": statement.excluded.tenant_id,
                "name": func.coalesce(statement.excluded.name, TeamsConversation.name),
                "last_activity_at": now,
                "updated_at": now,
            },
        )
    )


async def get_by_key(db: AsyncSession, key: str) -> TeamsConversation | None:
    """Any bot's record of a conversation - the conversation and its service are the same for all."""
    result = await db.execute(
        select(TeamsConversation)
        .where(TeamsConversation.key == key)
        .order_by(TeamsConversation.last_activity_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


SHARED_TYPES = ("channel", "groupChat")
"""The conversations a trigger may post into. A personal chat is somebody's own,
and a trigger another member set up has no business writing there."""


async def get_shared(
    db: AsyncSession, conversation_id: UUID, *, organization_id: UUID
) -> TeamsConversation | None:
    """A team channel or group chat of this organization's, or None."""
    result = await db.execute(
        select(TeamsConversation).where(
            TeamsConversation.id == conversation_id,
            TeamsConversation.organization_id == organization_id,
            TeamsConversation.conversation_type.in_(SHARED_TYPES),
        )
    )
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, conversation_id: UUID) -> TeamsConversation | None:
    return await db.get(TeamsConversation, conversation_id)


async def list_shared(db: AsyncSession, *, organization_id: UUID) -> list[TeamsConversation]:
    """The channels and group chats an active bot of the organization is in, latest first."""
    result = await db.execute(
        select(TeamsConversation)
        .join(ChannelBot, ChannelBot.id == TeamsConversation.bot_id)
        .where(
            TeamsConversation.organization_id == organization_id,
            TeamsConversation.conversation_type.in_(SHARED_TYPES),
            ChannelBot.is_active.is_(True),
        )
        .order_by(TeamsConversation.last_activity_at.desc())
    )
    return list(result.scalars().all())
