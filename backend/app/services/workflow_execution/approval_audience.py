"""Resolve approval teams without turning a missing group into unrestricted access."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Perm, role_has
from app.repositories import group as group_repo


async def group_approvers(
    db: AsyncSession, *, organization_id: UUID, group_ids: list[UUID]
) -> set[UUID]:
    """Resolve current active members who independently hold approval authority."""
    members = await group_repo.audience_members(
        db, organization_id=organization_id, group_ids=group_ids
    )
    return {user_id for user_id, role in members if role_has(role, Perm.APPROVALS_DECIDE)}


async def groups_deciding_through(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> set[str]:
    """The groups through which this person may decide: every group of theirs in the
    organization, while they are active and hold approval authority, otherwise none."""
    group_ids = [
        member.group_id
        for member in await group_repo.list_memberships_in_org(
            db, organization_id=organization_id, user_id=user_id
        )
    ]
    if user_id not in await group_approvers(
        db, organization_id=organization_id, group_ids=group_ids
    ):
        return set()
    return {str(group_id) for group_id in group_ids}


async def check_groups(
    db: AsyncSession, *, organization_id: UUID, group_ids: tuple[UUID, ...]
) -> list[tuple[str, str]]:
    """Publishing may name only groups inside the workflow's organization."""
    names = await group_repo.get_names(
        db, organization_id=organization_id, group_ids=list(group_ids)
    )
    return [
        (f"approver_groups.{index}", "This group is not in the organization")
        for index, group_id in enumerate(group_ids)
        if group_id not in names
    ]
