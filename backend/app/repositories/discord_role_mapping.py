"""DiscordRoleMapping repository (PostgreSQL async)."""

from uuid import UUID

from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.discord_role_mapping import DiscordRoleMapping
from app.db.models.group import Group, GroupMember
from app.db.models.organization import MembershipSource, Organization, OrganizationMember


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    channel_bot_id: UUID,
    guild_id: str,
    discord_role_id: str,
    guild_name: str,
    discord_role_name: str,
    group_id: UUID,
    role: str | None,
    created_by_user_id: UUID | None,
) -> DiscordRoleMapping:
    mapping = DiscordRoleMapping(
        organization_id=organization_id,
        channel_bot_id=channel_bot_id,
        guild_id=guild_id,
        discord_role_id=discord_role_id,
        guild_name=guild_name,
        discord_role_name=discord_role_name,
        group_id=group_id,
        role=role,
        created_by_user_id=created_by_user_id,
    )
    db.add(mapping)
    await db.flush()
    await db.refresh(mapping)
    return mapping


async def get(
    db: AsyncSession, *, channel_bot_id: UUID, mapping_id: UUID
) -> DiscordRoleMapping | None:
    result = await db.execute(
        select(DiscordRoleMapping).where(
            DiscordRoleMapping.id == mapping_id,
            DiscordRoleMapping.channel_bot_id == channel_bot_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_role(
    db: AsyncSession, *, channel_bot_id: UUID, guild_id: str, discord_role_id: str
) -> DiscordRoleMapping | None:
    result = await db.execute(
        select(DiscordRoleMapping).where(
            DiscordRoleMapping.channel_bot_id == channel_bot_id,
            DiscordRoleMapping.guild_id == guild_id,
            DiscordRoleMapping.discord_role_id == discord_role_id,
        )
    )
    return result.scalar_one_or_none()


async def list_for_bot(db: AsyncSession, *, channel_bot_id: UUID) -> list[DiscordRoleMapping]:
    """Every mapping one bot holds, in the order they were made."""
    result = await db.execute(
        select(DiscordRoleMapping)
        .where(DiscordRoleMapping.channel_bot_id == channel_bot_id)
        .order_by(DiscordRoleMapping.created_at, DiscordRoleMapping.id)
    )
    return list(result.scalars().all())


async def list_for_group(db: AsyncSession, *, group_id: UUID) -> list[DiscordRoleMapping]:
    """Every mapping that places people in one group, across the organization's bots."""
    result = await db.execute(
        select(DiscordRoleMapping)
        .where(DiscordRoleMapping.group_id == group_id)
        .order_by(DiscordRoleMapping.created_at, DiscordRoleMapping.id)
    )
    return list(result.scalars().all())


async def list_for_org(db: AsyncSession, *, organization_id: UUID) -> list[DiscordRoleMapping]:
    """Every mapping of every Discord bot in one organization.

    A personal organization is excluded in the query even though the service
    refuses to create a mapping for one: a personal organization is its
    creator's alone, and a Discord role that joined somebody else to it would be
    a breach whichever way the row got there.
    """
    result = await db.execute(
        select(DiscordRoleMapping)
        .join(Organization, Organization.id == DiscordRoleMapping.organization_id)
        .where(
            DiscordRoleMapping.organization_id == organization_id,
            Organization.is_personal.is_(False),
        )
        .order_by(DiscordRoleMapping.channel_bot_id, DiscordRoleMapping.id)
    )
    return list(result.scalars().all())


async def synced_people(
    db: AsyncSession, *, organization_id: UUID | None = None, user_id: UUID | None = None
) -> list[tuple[UUID, UUID]]:
    """Every `(organization_id, user_id)` holding a membership or a group the Discord sync placed.

    The people a periodic check has to look at again: whoever left the server or
    lost the role stops speaking to the bot, so their next turn never comes.
    Narrowed to one organization or one person when either is given.
    """
    discord = MembershipSource.DISCORD.value
    members = select(OrganizationMember.organization_id, OrganizationMember.user_id).where(
        OrganizationMember.source == discord
    )
    in_groups = (
        select(Group.organization_id, GroupMember.user_id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.source == discord)
    )
    if organization_id is not None:
        members = members.where(OrganizationMember.organization_id == organization_id)
        in_groups = in_groups.where(Group.organization_id == organization_id)
    if user_id is not None:
        members = members.where(OrganizationMember.user_id == user_id)
        in_groups = in_groups.where(GroupMember.user_id == user_id)
    result = await db.execute(union(members, in_groups))
    return [(row[0], row[1]) for row in result.all()]


async def delete_mapping(db: AsyncSession, mapping: DiscordRoleMapping) -> None:
    await db.delete(mapping)
    await db.flush()
