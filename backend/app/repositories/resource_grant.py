"""ResourceGrant repository (PostgreSQL async)."""

from uuid import UUID

from sqlalchemy import ColumnElement, Delete, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.group import Group, GroupMember
from app.db.models.resource_grant import GRANT_ORDER, GrantLevel, ResourceGrant


async def _delete_rows(db: AsyncSession, statement: Delete) -> int:
    """Run a DELETE and report how many rows it removed.

    Both callers want that number and neither can read it off the declared type:
    `AsyncSession.execute` is typed to return `Result`, which has no
    `rowcount`, while a DML statement actually returns SQLAlchemy's
    `CursorResult`, which does. There is no overload to narrow on, so the one
    suppression that costs lives here rather than at each call site.
    """
    result = await db.execute(statement)
    await db.flush()
    return result.rowcount  # ty: ignore[unresolved-attribute]


def _reaches_member(organization_id: UUID, subject_user_id: UUID) -> ColumnElement[bool]:
    """A grant made to this person, or to a group of this organization they are in.

    The group half is a subquery rather than a list of ids read beforehand, so a
    membership removed in the same transaction is gone from the very next check
    and nothing about a group's size decides how large the statement is. It is
    scoped to `organization_id` on the group as well as on the grant: a grant row
    names a group, and a group from another tenant must reach nobody here even if
    a row somehow pointed at one.
    """
    groups_of_member = (
        select(GroupMember.group_id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.user_id == subject_user_id, Group.organization_id == organization_id)
    )
    return or_(
        ResourceGrant.subject_user_id == subject_user_id,
        ResourceGrant.subject_group_id.in_(groups_of_member),
    )


async def get_level(
    db: AsyncSession,
    *,
    organization_id: UUID,
    subject_user_id: UUID,
    resource_type: str,
    resource_id: UUID,
) -> GrantLevel | None:
    """The best level this member holds on one resource, directly or through a group.

    A person can reach a row by several grants at once - their own, and one per
    group it was shared with - and the answer is the highest of them, for the
    same reason effective access is `max(role scope, grant)`: sharing more never
    means reaching less.
    """
    result = await db.execute(
        select(ResourceGrant.level).where(
            ResourceGrant.organization_id == organization_id,
            ResourceGrant.resource_type == resource_type,
            ResourceGrant.resource_id == resource_id,
            _reaches_member(organization_id, subject_user_id),
        )
    )
    levels = [GrantLevel(level) for level in result.scalars().all()]
    return max(levels, key=GRANT_ORDER.__getitem__) if levels else None


async def list_shared_ids(
    db: AsyncSession,
    *,
    organization_id: UUID,
    subject_user_id: UUID,
    resource_type: str,
    minimum_level: GrantLevel = GrantLevel.READ,
) -> list[UUID]:
    """Ids of one resource type shared with this member at `minimum_level` or above.

    Used to widen a listing query: a member sees their own rows plus these.
    Grants made to a group the member is in count exactly as their own do, and a
    row reached twice is listed once.
    """
    allowed = [
        level.value for level, rank in GRANT_ORDER.items() if rank >= GRANT_ORDER[minimum_level]
    ]
    result = await db.execute(
        select(ResourceGrant.resource_id)
        .where(
            ResourceGrant.organization_id == organization_id,
            ResourceGrant.resource_type == resource_type,
            ResourceGrant.level.in_(allowed),
            _reaches_member(organization_id, subject_user_id),
        )
        .distinct()
    )
    return list(result.scalars().all())


async def list_for_resource(
    db: AsyncSession,
    *,
    organization_id: UUID,
    resource_type: str,
    resource_id: UUID,
) -> list[ResourceGrant]:
    """Every grant on one resource - the Sharing panel's list."""
    result = await db.execute(
        select(ResourceGrant)
        .where(
            ResourceGrant.organization_id == organization_id,
            ResourceGrant.resource_type == resource_type,
            ResourceGrant.resource_id == resource_id,
        )
        .order_by(ResourceGrant.created_at.asc())
    )
    return list(result.scalars().all())


async def upsert(
    db: AsyncSession,
    *,
    organization_id: UUID,
    subject_user_id: UUID,
    resource_type: str,
    resource_id: UUID,
    level: GrantLevel,
    created_by_user_id: UUID | None = None,
) -> ResourceGrant:
    """Share a resource with a member, replacing any existing level."""
    result = await db.execute(
        select(ResourceGrant).where(
            ResourceGrant.organization_id == organization_id,
            ResourceGrant.subject_user_id == subject_user_id,
            ResourceGrant.resource_type == resource_type,
            ResourceGrant.resource_id == resource_id,
        )
    )
    grant = result.scalar_one_or_none()
    if grant is None:
        grant = ResourceGrant(
            organization_id=organization_id,
            subject_user_id=subject_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            level=level.value,
            created_by_user_id=created_by_user_id,
        )
        db.add(grant)
    else:
        grant.level = level.value
    await db.flush()
    await db.refresh(grant)
    return grant


async def revoke(
    db: AsyncSession,
    *,
    organization_id: UUID,
    subject_user_id: UUID,
    resource_type: str,
    resource_id: UUID,
) -> bool:
    """Remove a share. Returns True if one existed."""
    removed = await _delete_rows(
        db,
        delete(ResourceGrant).where(
            ResourceGrant.organization_id == organization_id,
            ResourceGrant.subject_user_id == subject_user_id,
            ResourceGrant.resource_type == resource_type,
            ResourceGrant.resource_id == resource_id,
        ),
    )
    return bool(removed)


async def upsert_for_group(
    db: AsyncSession,
    *,
    organization_id: UUID,
    subject_group_id: UUID,
    resource_type: str,
    resource_id: UUID,
    level: GrantLevel,
    created_by_user_id: UUID | None = None,
) -> ResourceGrant:
    """Share a resource with a group, replacing any existing level."""
    result = await db.execute(
        select(ResourceGrant).where(
            ResourceGrant.organization_id == organization_id,
            ResourceGrant.subject_group_id == subject_group_id,
            ResourceGrant.resource_type == resource_type,
            ResourceGrant.resource_id == resource_id,
        )
    )
    grant = result.scalar_one_or_none()
    if grant is None:
        grant = ResourceGrant(
            organization_id=organization_id,
            subject_group_id=subject_group_id,
            resource_type=resource_type,
            resource_id=resource_id,
            level=level.value,
            created_by_user_id=created_by_user_id,
        )
        db.add(grant)
    else:
        grant.level = level.value
    await db.flush()
    await db.refresh(grant)
    return grant


async def revoke_for_group(
    db: AsyncSession,
    *,
    organization_id: UUID,
    subject_group_id: UUID,
    resource_type: str,
    resource_id: UUID,
) -> bool:
    """Stop sharing with a group. Returns True if a share existed."""
    removed = await _delete_rows(
        db,
        delete(ResourceGrant).where(
            ResourceGrant.organization_id == organization_id,
            ResourceGrant.subject_group_id == subject_group_id,
            ResourceGrant.resource_type == resource_type,
            ResourceGrant.resource_id == resource_id,
        ),
    )
    return bool(removed)


async def delete_for_resource(
    db: AsyncSession,
    *,
    organization_id: UUID,
    resource_type: str,
    resource_id: UUID,
) -> int:
    """Drop every grant on a resource.

    Called when the resource itself is deleted: the grant table is generic and
    carries no foreign key to the target, so nothing cascades on its behalf.
    """
    return await _delete_rows(
        db,
        delete(ResourceGrant).where(
            ResourceGrant.organization_id == organization_id,
            ResourceGrant.resource_type == resource_type,
            ResourceGrant.resource_id == resource_id,
        ),
    )


async def count_for_resources(
    db: AsyncSession,
    *,
    organization_id: UUID,
    resource_type: str,
    resource_ids: list[UUID],
) -> dict[UUID, int]:
    """How many people and groups each resource is explicitly shared with.

    One grouped query for a whole page rather than one per row: a listing that
    wants to say "shared with 3" for twenty secrets would otherwise issue twenty
    counts. Resources with no grants are simply absent from the result.
    """
    if not resource_ids:
        return {}
    result = await db.execute(
        select(ResourceGrant.resource_id, func.count())
        .where(
            ResourceGrant.organization_id == organization_id,
            ResourceGrant.resource_type == resource_type,
            ResourceGrant.resource_id.in_(resource_ids),
        )
        .group_by(ResourceGrant.resource_id)
    )
    # dict() over the rows rather than `row.count` attribute reads: a column
    # named `count` shadows the Row sequence method as far as a type checker
    # can tell, even though SQLAlchemy resolves it to the value at run time.
    return dict(result.tuples().all())
