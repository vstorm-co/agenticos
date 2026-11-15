"""A session's three-way merge of a fork with main."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.skill_merge import SkillMerge


async def create(db: AsyncSession, *, organization_id: UUID, merge: SkillMerge) -> SkillMerge:
    merge.organization_id = organization_id
    db.add(merge)
    await db.flush()
    await db.refresh(merge)
    return merge


async def for_run(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID, lock: bool = False
) -> SkillMerge | None:
    statement = select(SkillMerge).where(
        SkillMerge.run_id == run_id, SkillMerge.organization_id == organization_id
    )
    if lock:
        # A locked read is taken to write on, so it replaces what the session holds.
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(statement)).scalar_one_or_none()


async def update(db: AsyncSession, *, merge: SkillMerge, values: dict[str, Any]) -> SkillMerge:
    for field, value in values.items():
        setattr(merge, field, value)
    await db.flush()
    await db.refresh(merge)
    return merge
