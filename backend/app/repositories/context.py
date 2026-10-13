"""Context-file repository (PostgreSQL async).

Listing a context file is not a plain org filter: what a member sees depends on
their role scope and on what was shared with them, so `list_visible` takes the
predicate pieces the access layer resolved rather than re-deriving them here -
the same shape `skill_repo` uses.
"""

from typing import Literal
from uuid import UUID

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.context import ContextFile
from app.db.models.resource_grant import Visibility
from app.repositories._search import contains_ci

ContextSort = Literal["name", "updated"]


async def get(db: AsyncSession, context_id: UUID, *, organization_id: UUID) -> ContextFile | None:
    result = await db.execute(
        select(ContextFile).where(
            ContextFile.id == context_id, ContextFile.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def get_by_name(db: AsyncSession, name: str, *, organization_id: UUID) -> ContextFile | None:
    result = await db.execute(
        select(ContextFile).where(
            ContextFile.name == name, ContextFile.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def get_many(
    db: AsyncSession, context_ids: list[UUID], *, organization_id: UUID
) -> dict[UUID, ContextFile]:
    """Fetch several files at once - one query per run, not one per binding."""
    if not context_ids:
        return {}
    result = await db.execute(
        select(ContextFile).where(
            ContextFile.id.in_(context_ids), ContextFile.organization_id == organization_id
        )
    )
    return {file.id: file for file in result.scalars().all()}


async def list_visible(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
    shared_with_me: bool = False,
    search: str | None = None,
    sort: ContextSort = "name",
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[ContextFile], int]:
    """The context files one member may see, filtered and paged, with the total.

    Args:
        see_all: True when the caller's role reaches the whole organization; the
            ownership predicate is then skipped entirely.
        shared_ids: File ids explicitly shared with this member.
        shared_with_me: Narrow to rows deliberately shared with the caller -
            org-visible or explicitly granted, and not their own.

    Search covers the name and the description because those are what a person
    remembers about a file - the body is what the *model* reads, and matching on
    it would return rows whose visible text explains nothing about why they
    matched. Sorting by "updated" falls back to `created_at`, which is never
    null, so a file written and never edited still sorts by when it arrived.
    """
    where = [ContextFile.organization_id == organization_id]
    if shared_with_me:
        where.append(
            and_(
                or_(
                    ContextFile.visibility == Visibility.ORG.value,
                    ContextFile.id.in_(shared_ids) if shared_ids else false(),
                ),
                ContextFile.owner_user_id.is_distinct_from(user_id),
            )
        )
    elif not see_all:
        where.append(
            or_(
                ContextFile.owner_user_id == user_id,
                ContextFile.visibility == Visibility.ORG.value,
                ContextFile.id.in_(shared_ids) if shared_ids else false(),
            )
        )
    if search:
        where.append(
            or_(
                contains_ci(ContextFile.name, search),
                contains_ci(ContextFile.description, search),
            )
        )

    order_by = (
        (
            func.coalesce(ContextFile.updated_at, ContextFile.created_at).desc(),
            ContextFile.name.asc(),
        )
        if sort == "updated"
        else (ContextFile.name.asc(),)
    )
    items = await db.execute(
        select(ContextFile).where(*where).order_by(*order_by).offset(skip).limit(limit)
    )
    total = await db.scalar(select(func.count(ContextFile.id)).where(*where))
    return list(items.scalars().all()), total or 0


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    owner_user_id: UUID | None,
    name: str,
    description: str | None,
    content: str,
    content_format: str,
    mode: str,
    visibility: str = Visibility.PRIVATE.value,
) -> ContextFile:
    file = ContextFile(
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        name=name,
        description=description,
        content=content,
        format=content_format,
        mode=mode,
        visibility=visibility,
    )
    db.add(file)
    await db.flush()
    await db.refresh(file)
    return file


async def update(db: AsyncSession, *, file: ContextFile, update_data: dict) -> ContextFile:
    for field, value in update_data.items():
        setattr(file, field, value)
    db.add(file)
    await db.flush()
    await db.refresh(file)
    return file


async def delete(db: AsyncSession, file: ContextFile) -> None:
    await db.delete(file)
    await db.flush()
