"""Scoped private destinations and immutable notification route grants."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_session import ChannelSession
from app.db.models.notification import CHAT_NOTIFICATION_CHANNELS
from app.db.models.notification_route import NotificationRoute
from app.db.models.organization import OrganizationMember
from app.db.models.teams_conversation import TeamsConversation
from app.db.models.user import User

type Destination = tuple[ChannelSession, ChannelBot, ChannelIdentity]


async def teams_reference(
    db: AsyncSession, *, bot: ChannelBot, key: str
) -> TeamsConversation | None:
    result = await db.execute(
        select(TeamsConversation)
        .where(
            TeamsConversation.organization_id == bot.organization_id,
            TeamsConversation.bot_id == bot.id,
            TeamsConversation.key == key,
            TeamsConversation.conversation_type == "personal",
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def destinations(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, session_id: UUID | None = None
) -> list[Destination]:
    query = (
        select(ChannelSession, ChannelBot, ChannelIdentity)
        .join(ChannelBot, ChannelBot.id == ChannelSession.bot_id)
        .join(ChannelIdentity, ChannelIdentity.id == ChannelSession.identity_id)
        .join(User, User.id == ChannelIdentity.user_id)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(
            ChannelBot.organization_id == organization_id,
            OrganizationMember.organization_id == organization_id,
            ChannelIdentity.user_id == user_id,
            User.is_active.is_(True),
            ChannelIdentity.is_active.is_(True),
            ChannelSession.is_active.is_(True),
            ChannelSession.chat_type == "private",
            ChannelBot.is_active.is_(True),
            ChannelBot.platform == ChannelIdentity.platform,
            ChannelBot.platform.in_([channel.value for channel in CHAT_NOTIFICATION_CHANNELS]),
        )
        .order_by(ChannelSession.last_message_at.desc().nulls_last(), ChannelSession.id)
        .limit(100)
        .execution_options(populate_existing=True)
    )
    if session_id is not None:
        query = query.where(ChannelSession.id == session_id)
    result = await db.execute(query)
    return [(session, bot, identity) for session, bot, identity in result.all()]


async def routes(
    db: AsyncSession, *, organization_id: UUID, user_ids: Sequence[UUID]
) -> list[NotificationRoute]:
    result = await db.execute(
        select(NotificationRoute)
        .where(
            NotificationRoute.organization_id == organization_id,
            NotificationRoute.user_id.in_(user_ids),
        )
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


async def current(
    db: AsyncSession, *, route_id: UUID, organization_id: UUID, user_id: UUID, channel: str
) -> NotificationRoute | None:
    result = await db.execute(
        select(NotificationRoute)
        .join(ChannelSession, ChannelSession.id == NotificationRoute.session_id)
        .join(ChannelIdentity, ChannelIdentity.id == ChannelSession.identity_id)
        .join(ChannelBot, ChannelBot.id == ChannelSession.bot_id)
        .where(
            NotificationRoute.id == route_id,
            NotificationRoute.organization_id == organization_id,
            NotificationRoute.user_id == user_id,
            NotificationRoute.channel == channel,
            ChannelIdentity.user_id == user_id,
            NotificationRoute.identity_generation == ChannelIdentity.authorization_generation,
            NotificationRoute.bot_generation == ChannelBot.authorization_generation,
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def replace(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    channel: str,
    destination: Destination | None,
) -> NotificationRoute | None:
    # Delete grants, never repoint them: old pending deliveries lose their FK.
    # Serializing on the person also makes first-time concurrent replacements safe.
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())
    await db.execute(
        delete(NotificationRoute).where(
            NotificationRoute.organization_id == organization_id,
            NotificationRoute.user_id == user_id,
            NotificationRoute.channel == channel,
        )
    )
    if destination is None:
        return None
    session, bot, identity = destination
    route = NotificationRoute(
        organization_id=organization_id,
        user_id=user_id,
        channel=channel,
        session_id=session.id,
        identity_generation=identity.authorization_generation,
        bot_generation=bot.authorization_generation,
    )
    db.add(route)
    await db.flush()
    await db.refresh(route)
    return route
