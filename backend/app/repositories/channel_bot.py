"""ChannelBot repository (PostgreSQL async)."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_bot import ChannelBot
from app.services.channels.base import DEFAULT_ACCESS_POLICY


async def get_for_inbound(db: AsyncSession, bot_id: UUID) -> ChannelBot | None:
    """Get a bot by ID without an organization filter.

    Deliberately unscoped: an inbound webhook or poll carries no organization
    context - the bot row *is* where the org comes from. Management code must
    use :func:`get_for_org` instead so a bot cannot be read across tenants.
    """
    return await db.get(ChannelBot, bot_id)


async def get_for_org(
    db: AsyncSession,
    bot_id: UUID,
    *,
    organization_id: UUID,
) -> ChannelBot | None:
    """Get a bot by ID within one organization."""
    result = await db.execute(
        select(ChannelBot).where(
            ChannelBot.id == bot_id,
            ChannelBot.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_platform(
    db: AsyncSession,
    platform: str,
    *,
    organization_id: UUID,
    skip: int = 0,
    limit: int = 50,
) -> list[ChannelBot]:
    """Get an organization's bots for a given platform with pagination."""
    result = await db.execute(
        select(ChannelBot)
        .where(
            ChannelBot.platform == platform,
            ChannelBot.organization_id == organization_id,
        )
        .order_by(ChannelBot.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_active_polling_bots(db: AsyncSession, platform: str) -> list[ChannelBot]:
    """Get all active polling bots for a given platform, across every organization.

    Deliberately unscoped: the poller is a background worker serving the whole
    deployment, not a request made by a member of one organization. Each bot it
    returns still carries its own `organization_id`.
    """
    result = await db.execute(
        select(ChannelBot).where(
            ChannelBot.platform == platform,
            ChannelBot.is_active.is_(True),
            ChannelBot.webhook_mode.is_(False),
        )
    )
    return list(result.scalars().all())


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    platform: str,
    name: str,
    token_encrypted: str,
    secret_key_version: int,
    webhook_mode: bool = False,
    webhook_url: str | None = None,
    api_base_url: str | None = None,
    webhook_secret_encrypted: str | None = None,
    access_policy: dict | None = None,
    slack_signing_secret_encrypted: str | None = None,
    slack_app_token_encrypted: str | None = None,
) -> ChannelBot:
    """Create a new channel bot owned by an organization."""
    bot = ChannelBot(
        organization_id=organization_id,
        platform=platform,
        name=name,
        token_encrypted=token_encrypted,
        secret_key_version=secret_key_version,
        webhook_mode=webhook_mode,
        webhook_url=webhook_url,
        api_base_url=api_base_url,
        webhook_secret_encrypted=webhook_secret_encrypted,
        access_policy=access_policy or dict(DEFAULT_ACCESS_POLICY),
        slack_signing_secret_encrypted=slack_signing_secret_encrypted,
        slack_app_token_encrypted=slack_app_token_encrypted,
    )
    db.add(bot)
    await db.flush()
    await db.refresh(bot)
    return bot


async def update(
    db: AsyncSession,
    *,
    db_bot: ChannelBot,
    update_data: dict,
) -> ChannelBot:
    """Update a channel bot."""
    for field, value in update_data.items():
        setattr(db_bot, field, value)
    db.add(db_bot)
    await db.flush()
    await db.refresh(db_bot)
    return db_bot


async def delete(db: AsyncSession, bot_id: UUID, *, organization_id: UUID) -> bool:
    """Delete one organization's bot. Returns True if deleted, False if not found."""
    bot = await get_for_org(db, bot_id, organization_id=organization_id)
    if not bot:
        return False
    await db.delete(bot)
    await db.flush()
    return True


async def count(db: AsyncSession, *, organization_id: UUID) -> int:
    """Count an organization's channel bots."""
    result = await db.scalar(
        select(func.count())
        .select_from(ChannelBot)
        .where(ChannelBot.organization_id == organization_id)
    )
    return result or 0


async def list_for_org(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skip: int = 0,
    limit: int = 50,
) -> list[ChannelBot]:
    """List an organization's channel bots with pagination."""
    result = await db.execute(
        select(ChannelBot)
        .where(ChannelBot.organization_id == organization_id)
        .order_by(ChannelBot.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())
