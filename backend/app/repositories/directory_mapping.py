"""DirectoryGroupMapping repository (PostgreSQL async)."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.directory_mapping import DirectoryGroupMapping
from app.db.models.organization import Organization


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    external_group: str,
    role: str,
    group_id: UUID | None,
    created_by_user_id: UUID | None,
) -> DirectoryGroupMapping:
    mapping = DirectoryGroupMapping(
        organization_id=organization_id,
        external_group=external_group,
        role=role,
        group_id=group_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(mapping)
    await db.flush()
    await db.refresh(mapping)
    return mapping


async def get(
    db: AsyncSession, *, organization_id: UUID, mapping_id: UUID
) -> DirectoryGroupMapping | None:
    result = await db.execute(
        select(DirectoryGroupMapping).where(
            DirectoryGroupMapping.id == mapping_id,
            DirectoryGroupMapping.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_external_group(
    db: AsyncSession, *, organization_id: UUID, external_group: str
) -> DirectoryGroupMapping | None:
    result = await db.execute(
        select(DirectoryGroupMapping).where(
            DirectoryGroupMapping.organization_id == organization_id,
            DirectoryGroupMapping.external_group == external_group,
        )
    )
    return result.scalar_one_or_none()


async def list_for_org(db: AsyncSession, organization_id: UUID) -> list[DirectoryGroupMapping]:
    """Every mapping one organization holds, in the order they were made."""
    result = await db.execute(
        select(DirectoryGroupMapping)
        .where(DirectoryGroupMapping.organization_id == organization_id)
        .order_by(DirectoryGroupMapping.created_at, DirectoryGroupMapping.id)
    )
    return list(result.scalars().all())


async def list_for_group(db: AsyncSession, *, group_id: UUID) -> list[DirectoryGroupMapping]:
    """Every mapping that places people in one group."""
    result = await db.execute(
        select(DirectoryGroupMapping).where(DirectoryGroupMapping.group_id == group_id)
    )
    return list(result.scalars().all())


async def list_matching(
    db: AsyncSession, *, external_groups: Collection[str]
) -> list[DirectoryGroupMapping]:
    """Every mapping, in any organization, naming one of these directory groups.

    A personal organization is excluded in the query even though the service
    refuses to create a mapping for one: a personal organization is its
    creator's alone, and a sign-in that joined somebody else to it would be a
    breach whichever way the row got there.

    `external_groups` must already be case-folded - the column is stored that way.
    """
    if not external_groups:
        return []
    result = await db.execute(
        select(DirectoryGroupMapping)
        .join(Organization, Organization.id == DirectoryGroupMapping.organization_id)
        .where(
            DirectoryGroupMapping.external_group.in_(list(external_groups)),
            Organization.is_personal.is_(False),
        )
        .order_by(DirectoryGroupMapping.organization_id, DirectoryGroupMapping.id)
    )
    return list(result.scalars().all())


async def delete_mapping(db: AsyncSession, mapping: DirectoryGroupMapping) -> None:
    await db.delete(mapping)
    await db.flush()
