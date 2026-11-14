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
