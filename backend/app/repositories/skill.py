"""Skill repository (PostgreSQL async)."""

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.skill import Skill, SkillResource


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


async def list_for_org(
    db: AsyncSession,
    *,
    organization_id: UUID,
    search: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Skill], int]:
    """One organization's skills, filtered and paged, with the unpaged total.

    The total is what a pager needs and a page cannot supply: "showing 50 of 50"
    and "50 of 380" are the same list until somebody counts the rest.

    Search covers the name and the description because those are the two things
    a person remembers about a skill - the body is what the *model* reads, and
    matching on it would return rows whose visible text explains nothing about
    why they matched.
    """
    where = [Skill.organization_id == organization_id]
    if search:
        safe = search.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        where.append(
            or_(
                Skill.name.ilike(f"%{safe}%", escape="\\"),
                Skill.description.ilike(f"%{safe}%", escape="\\"),
            )
        )

    items = await db.execute(
        select(Skill).where(*where).order_by(Skill.name.asc()).offset(skip).limit(limit)
    )
    total = await db.scalar(select(func.count(Skill.id)).where(*where))
    return list(items.scalars().all()), total or 0


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    owner_user_id: UUID | None,
    name: str,
    description: str,
    content: str,
) -> Skill:
    skill = Skill(
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        name=name,
        description=description,
        content=content,
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
