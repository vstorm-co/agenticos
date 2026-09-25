"""Group and GroupMember repository (PostgreSQL async)."""

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.group import Group, GroupMember
from app.db.models.organization import MembershipSource
from app.db.models.user import User


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    name: str,
    description: str | None,
    created_by_user_id: UUID | None,
) -> Group:
    group = Group(
        organization_id=organization_id,
        name=name,
        description=description,
        created_by_user_id=created_by_user_id,
    )
    db.add(group)
    await db.flush()
    await db.refresh(group)
    return group


async def get(db: AsyncSession, *, organization_id: UUID, group_id: UUID) -> Group | None:
    """One group, only when it belongs to `organization_id`.

    The organization is part of the lookup rather than checked afterwards, so a
    group id from another tenant reads exactly like one that does not exist.
    """
    result = await db.execute(
        select(Group).where(Group.id == group_id, Group.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def get_by_name(db: AsyncSession, *, organization_id: UUID, name: str) -> Group | None:
    result = await db.execute(
        select(Group).where(Group.organization_id == organization_id, Group.name == name)
    )
    return result.scalar_one_or_none()


async def list_for_org(db: AsyncSession, organization_id: UUID) -> list[tuple[Group, int]]:
    """Every group in the organization with how many members it has, by name.

    Unpaged: a group is created by hand, so an organization has tens of them,
    and the sharing picker needs all of them at once.
    """
    members = (
        select(GroupMember.group_id, func.count(GroupMember.id).label("members"))
        .group_by(GroupMember.group_id)
        .subquery()
    )
    result = await db.execute(
        select(Group, func.coalesce(members.c.members, 0))
        .outerjoin(members, members.c.group_id == Group.id)
        .where(Group.organization_id == organization_id)
        .order_by(Group.name, Group.id)
    )
    return [(row[0], int(row[1])) for row in result.all()]


async def get_names(
    db: AsyncSession, *, organization_id: UUID, group_ids: list[UUID]
) -> dict[UUID, str]:
    """Group names by id, for a listing that stores ids and shows names."""
    if not group_ids:
        return {}
    result = await db.execute(
        select(Group.id, Group.name).where(
            Group.organization_id == organization_id, Group.id.in_(group_ids)
        )
    )
    return dict(result.tuples().all())


async def update(db: AsyncSession, group: Group, *, name: str, description: str | None) -> Group:
    group.name = name
    group.description = description
    await db.flush()
    await db.refresh(group)
    return group


async def delete_group(db: AsyncSession, group: Group) -> None:
    await db.delete(group)
    await db.flush()


async def count_members(db: AsyncSession, group_id: UUID) -> int:
    result = await db.execute(
        select(func.count(GroupMember.id)).where(GroupMember.group_id == group_id)
    )
    return int(result.scalar_one())


async def list_members(
    db: AsyncSession, group_id: UUID
) -> list[tuple[GroupMember, str, str | None]]:
    """(membership, email, full name) for every member of one group, by address."""
    result = await db.execute(
        select(GroupMember, User.email, User.full_name)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id)
        .order_by(User.email, GroupMember.id)
    )
    return [(row[0], row[1], row[2]) for row in result.all()]


async def get_member_row(
    db: AsyncSession, *, group_id: UUID, user_id: UUID
) -> tuple[GroupMember, str, str | None] | None:
    """One (membership, email, full name) row, the shape `list_members` returns."""
    result = await db.execute(
        select(GroupMember, User.email, User.full_name)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
    )
    row = result.one_or_none()
    return (row[0], row[1], row[2]) if row is not None else None


async def get_member(db: AsyncSession, *, group_id: UUID, user_id: UUID) -> GroupMember | None:
    result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def add_member(
    db: AsyncSession,
    *,
    group_id: UUID,
    user_id: UUID,
    source: MembershipSource,
    added_by_user_id: UUID | None,
) -> GroupMember:
    member = GroupMember(
        group_id=group_id,
        user_id=user_id,
        source=source.value,
        added_by_user_id=added_by_user_id,
    )
    db.add(member)
    await db.flush()
    await db.refresh(member)
    return member


async def set_member_source(
    db: AsyncSession, member: GroupMember, *, source: MembershipSource
) -> GroupMember:
    member.source = source.value
    await db.flush()
    await db.refresh(member)
    return member


async def remove_member(db: AsyncSession, member: GroupMember) -> None:
    await db.delete(member)
    await db.flush()


async def list_memberships_in_org(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> list[GroupMember]:
    """Every group membership this person holds inside one organization."""
    result = await db.execute(
        select(GroupMember)
        .join(Group, Group.id == GroupMember.group_id)
        .where(Group.organization_id == organization_id, GroupMember.user_id == user_id)
    )
    return list(result.scalars().all())


async def organizations_with_directory_groups(db: AsyncSession, *, user_id: UUID) -> list[UUID]:
    """The organizations in which the directory sync put this person in some group."""
    result = await db.execute(
        select(Group.organization_id)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(
            GroupMember.user_id == user_id,
            GroupMember.source == MembershipSource.DIRECTORY.value,
        )
        .distinct()
    )
    return list(result.scalars().all())


async def delete_memberships_in_org(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> None:
    """Take a person out of every group in an organization they are leaving.

    The groups belong to the organization and the membership row to the person,
    so neither foreign key cascades when only the membership between them ends.
    """
    in_org = select(Group.id).where(Group.organization_id == organization_id)
    await db.execute(
        delete(GroupMember).where(GroupMember.user_id == user_id, GroupMember.group_id.in_(in_org))
    )
    await db.flush()
