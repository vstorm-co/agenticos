"""Skill repository (PostgreSQL async).

Listing a skill is not a plain org filter: what a member sees depends on their
role scope and on what was shared with them, so `list_visible` takes the
predicate pieces the access layer resolved rather than re-deriving them here.
"""

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.resource_grant import Visibility
from app.db.models.skill import Skill, SkillResource
from app.repositories._search import contains_ci

# How a listing may be ordered: by name, or by when a skill last changed.
SkillSort = Literal["name", "updated"]


async def get(db: AsyncSession, skill_id: UUID, *, organization_id: UUID) -> Skill | None:
    result = await db.execute(
        select(Skill).where(Skill.id == skill_id, Skill.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def get_by_name(db: AsyncSession, name: str, *, organization_id: UUID) -> Skill | None:
    result = await db.execute(
        select(Skill).where(Skill.name == name, Skill.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def get_many(
    db: AsyncSession, skill_ids: list[UUID], *, organization_id: UUID
) -> dict[UUID, Skill]:
    """Fetch several skills at once - one query per run, not one per binding."""
    if not skill_ids:
        return {}
    result = await db.execute(
        select(Skill).where(Skill.id.in_(skill_ids), Skill.organization_id == organization_id)
    )
    return {skill.id: skill for skill in result.scalars().all()}


async def list_visible(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
    shared_with_me: bool = False,
    search: str | None = None,
    categories: Sequence[str] | None = None,
    sort: SkillSort = "name",
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Skill], int]:
    """The skills one member may see, filtered and paged, with the unpaged total.

    Args:
        see_all: True when the caller's role reaches the whole organization;
            the ownership predicate is then skipped entirely.
        shared_ids: Skill ids explicitly shared with this member.
        shared_with_me: Narrow to rows deliberately shared with the caller -
            org-visible or explicitly granted, and not their own - whatever
            the role's scope.

    The total is what a pager needs and a page cannot supply: "showing 50 of 50"
    and "50 of 380" are the same list until somebody counts the rest.

    Search covers the name and the description because those are the two things
    a person remembers about a skill - the body is what the *model* reads, and
    matching on it would return rows whose visible text explains nothing about
    why they matched. A category, by contrast, is a shelf: it matches exactly
    or not at all.

    Sorting by "updated" falls back to `created_at` because `updated_at` is
    null until the first edit - a skill written yesterday and never touched is
    more recent than one rewritten last month, and a null sorted last would
    say otherwise.
    """
    where = [Skill.organization_id == organization_id]
    if shared_with_me:
        where.append(
            and_(
                or_(
                    Skill.visibility == Visibility.ORG.value,
                    Skill.id.in_(shared_ids) if shared_ids else false(),
                ),
                # IS DISTINCT FROM, not !=: an ownerless row is not the caller's.
                Skill.owner_user_id.is_distinct_from(user_id),
            )
        )
    elif not see_all:
        # The same predicate every shared resource here uses: mine, the
        # organization's, or one explicitly shared with me. A team-visible
        # skill nobody granted is deliberately invisible - "team" means named
        # members, not everybody.
        where.append(
            or_(
                Skill.owner_user_id == user_id,
                Skill.visibility == Visibility.ORG.value,
                Skill.id.in_(shared_ids) if shared_ids else false(),
            )
        )
    if search:
        where.append(
            or_(
                contains_ci(Skill.name, search),
                contains_ci(Skill.description, search),
            )
        )
    if categories:
        # Several shelves at once: the filter is a multi-select, and a row
        # matches any of the picked categories.
        where.append(Skill.category.in_(categories))

    order_by = (
        (func.coalesce(Skill.updated_at, Skill.created_at).desc(), Skill.name.asc())
        if sort == "updated"
        else (Skill.name.asc(),)
    )
    items = await db.execute(
        select(Skill).where(*where).order_by(*order_by).offset(skip).limit(limit)
    )
    total = await db.scalar(select(func.count(Skill.id)).where(*where))
    return list(items.scalars().all()), total or 0


async def list_categories(db: AsyncSession, *, organization_id: UUID) -> list[str]:
    """Every distinct category in one organization, for the listing's filter.

    Independent of paging and search on purpose: a chip that disappears because
    the current page happens not to show its skills is a filter nobody can use
    to get back.
    """
    result = await db.execute(
        select(Skill.category)
        .where(Skill.organization_id == organization_id, Skill.category.is_not(None))
        .distinct()
        .order_by(Skill.category.asc())
    )
    return [category for category in result.scalars().all() if category is not None]


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    owner_user_id: UUID | None,
    name: str,
    description: str,
    content: str,
    category: str | None = None,
) -> Skill:
    skill = Skill(
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        name=name,
        description=description,
        content=content,
        category=category,
    )
    db.add(skill)
    await db.flush()
    await db.refresh(skill)
    return skill


async def update(db: AsyncSession, *, skill: Skill, update_data: dict) -> Skill:
    for field, value in update_data.items():
        setattr(skill, field, value)
    db.add(skill)
    await db.flush()
    await db.refresh(skill)
    return skill


async def delete(db: AsyncSession, skill: Skill) -> None:
    await db.delete(skill)
    await db.flush()


async def get_resource(
    db: AsyncSession, resource_id: UUID, *, skill_id: UUID
) -> SkillResource | None:
    """One of a skill's files, scoped to the skill that owns it.

    Scoped rather than looked up by id alone: the caller has already proved it
    may reach the *skill*, and a resource id that belongs to another one must
    not be readable through it.
    """
    result = await db.execute(
        select(SkillResource).where(
            SkillResource.id == resource_id, SkillResource.skill_id == skill_id
        )
    )
    return result.scalar_one_or_none()


async def get_resource_by_name(
    db: AsyncSession, name: str, *, skill_id: UUID
) -> SkillResource | None:
    result = await db.execute(
        select(SkillResource).where(SkillResource.skill_id == skill_id, SkillResource.name == name)
    )
    return result.scalar_one_or_none()


async def create_resource(
    db: AsyncSession,
    *,
    skill_id: UUID,
    name: str,
    description: str | None,
    content: str,
) -> SkillResource:
    resource = SkillResource(skill_id=skill_id, name=name, description=description, content=content)
    db.add(resource)
    await db.flush()
    await db.refresh(resource)
    return resource


async def update_resource(
    db: AsyncSession, *, resource: SkillResource, update_data: dict
) -> SkillResource:
    for field, value in update_data.items():
        setattr(resource, field, value)
    db.add(resource)
    await db.flush()
    await db.refresh(resource)
    return resource


async def delete_resource(db: AsyncSession, resource: SkillResource) -> None:
    await db.delete(resource)
    await db.flush()
