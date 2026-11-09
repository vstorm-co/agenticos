"""One installation per project and owner, serialized by the project's row lock."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project_tracking import ProjectTracking


async def get(
    db: AsyncSession, *, organization_id: UUID, project_id: UUID, user_id: UUID
) -> ProjectTracking | None:
    return await db.scalar(
        select(ProjectTracking).where(
            ProjectTracking.organization_id == organization_id,
            ProjectTracking.project_id == project_id,
            ProjectTracking.user_id == user_id,
        )
    )


async def create(db: AsyncSession, *, tracking: ProjectTracking) -> ProjectTracking:
    db.add(tracking)
    await db.flush()
    await db.refresh(tracking)
    return tracking
