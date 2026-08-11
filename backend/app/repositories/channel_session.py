"""ChannelSession repository (PostgreSQL async)."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_session import ChannelSession


async def get_by_id(db: AsyncSession, session_id: UUID) -> ChannelSession | None:
    """Get a channel session by ID."""
    return await db.get(ChannelSession, session_id)


async def get_by_bot_and_chat(
    db: AsyncSession,
    bot_id: UUID,
    platform_chat_id: str,
) -> ChannelSession | None:
    """Get an active session by bot + chat ID."""
    result = await db.execute(
        select(ChannelSession).where(
            ChannelSession.bot_id == bot_id,
            ChannelSession.platform_chat_id == platform_chat_id,
        )
    )
    return result.scalar_one_or_none()


async def bots_by_identity(
    db: AsyncSession, *, identity_ids: list[UUID]
) -> dict[UUID, list[ChannelBot]]:
    """Which bots each of these chat accounts has actually talked to.

    One grouped query for a whole panel rather than one per row, the same shape
    as `agent_exposure.active_surfaces_for_agents`. A `ChannelIdentity` is keyed
    on the platform and the account, never on a bot - so the only record of
    *where* an account has been used is the sessions hanging off it, and this is
    that record.

    Identities with no session are simply absent from the result: an account
    that was linked and never used is a real state, and the panel says so
    rather than inventing a place for it.

    **Two queries, and the pairs are deduplicated on ids alone.** One chat
    account has a session per chat, so a person in eight channels of one bot
    produces eight rows for one place - but `SELECT DISTINCT` over the joined
    bot row asks Postgres to compare every column of it, and `access_policy`
    and `usage_reporting` are `json`, which has no equality operator. The whole
    endpoint answered a 500 on a real database while every unit test passed,
    because they mock the repository. So the pairs are distinct, and the bots
    are loaded by id afterwards.
    """
    if not identity_ids:
        return {}
    pairs = await db.execute(
        select(ChannelSession.identity_id, ChannelSession.bot_id)
        .where(ChannelSession.identity_id.in_(identity_ids))
        .distinct()
    )
    by_identity: dict[UUID, list[UUID]] = {}
    for identity_id, bot_id in pairs.all():
        by_identity.setdefault(identity_id, []).append(bot_id)
    if not by_identity:
        return {}

    bots = await db.execute(
        select(ChannelBot)
        .where(ChannelBot.id.in_({bot_id for ids in by_identity.values() for bot_id in ids}))
        .order_by(ChannelBot.name)
    )
    named = {bot.id: bot for bot in bots.scalars().all()}
    # Ordered by name here rather than in SQL, and filtered to what the second
    # query actually returned: a bot deleted between the two takes its sessions
    # with it, and rendering a place from a row that no longer exists is a 500
    # on somebody's profile page.
    found = {
        identity_id: sorted(
            (named[bot_id] for bot_id in ids if bot_id in named), key=lambda bot: bot.name
        )
        for identity_id, ids in by_identity.items()
    }
    return {identity_id: bots for identity_id, bots in found.items() if bots}


async def create(
    db: AsyncSession,
    *,
    bot_id: UUID,
    identity_id: UUID,
    platform_chat_id: str,
    chat_type: str = "private",
    conversation_id: UUID | None = None,
) -> ChannelSession:
    """Create a new channel session."""
    session = ChannelSession(
        bot_id=bot_id,
        identity_id=identity_id,
        platform_chat_id=platform_chat_id,
        chat_type=chat_type,
        conversation_id=conversation_id,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def update(
    db: AsyncSession,
    *,
    db_session: ChannelSession,
    update_data: dict,
) -> ChannelSession:
    """Update a channel session."""
    for field, value in update_data.items():
        setattr(db_session, field, value)
    db.add(db_session)
    await db.flush()
    await db.refresh(db_session)
    return db_session


async def list_by_bot(
    db: AsyncSession,
    bot_id: UUID,
    *,
    skip: int = 0,
    limit: int = 50,
) -> list[ChannelSession]:
    """List sessions for a specific bot with pagination."""
    result = await db.execute(
        select(ChannelSession)
        .where(ChannelSession.bot_id == bot_id)
        .order_by(ChannelSession.last_message_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_by_bot(db: AsyncSession, bot_id: UUID) -> int:
    """Count sessions for a specific bot."""
    result = await db.scalar(
        select(func.count()).select_from(ChannelSession).where(ChannelSession.bot_id == bot_id)
    )
    return result or 0


async def touch(db: AsyncSession, db_session: ChannelSession) -> ChannelSession:
    """Record activity on this chat, and that it had a turn.

    One statement for both: the turn counter exists so a bot can say "every tenth
    message" without counting a table that grows forever, and a counter written
    by a second `UPDATE` would be a second thing to forget.
    """
    db_session.last_message_at = datetime.now(UTC)
    db_session.turn_count = (db_session.turn_count or 0) + 1
    db.add(db_session)
    await db.flush()
    await db.refresh(db_session)
    return db_session
