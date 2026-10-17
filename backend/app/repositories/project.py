"""Projects: data access. Who may see one is decided by the service."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy import update as update_rows
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.project import Project
from app.db.models.resource_grant import Visibility
from app.repositories._search import contains_ci


async def get(db: AsyncSession, project_id: UUID, *, organization_id: UUID) -> Project | None:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def list_visible(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
    search: str | None = None,
    only_ids: Sequence[UUID] | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Project], int]:
    """The projects one member may see, most recently changed first, with the total.

    The rule `resolve_access` applies one row at a time: everything for a role
    that reaches the organization, otherwise their own, the organization's and
    those shared with them.
    """
    where = [Project.organization_id == organization_id]
    if not see_all:
        where.append(
            or_(
                Project.owner_user_id == user_id,
                Project.visibility == Visibility.ORG.value,
                Project.id.in_(shared_ids) if shared_ids else false(),
            )
        )
    if search:
        where.append(
            or_(contains_ci(Project.name, search), contains_ci(Project.description, search))
        )
    if only_ids is not None:
        where.append(Project.id.in_(only_ids))
    items = await db.execute(
        select(Project)
        .where(*where)
        .order_by(func.coalesce(Project.updated_at, Project.created_at).desc(), Project.name)
        .offset(skip)
        .limit(limit)
    )
    total = await db.scalar(select(func.count(Project.id)).where(*where))
    return list(items.scalars().all()), total or 0


async def chat_activity(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, project_ids: Sequence[UUID]
) -> dict[UUID, tuple[int, datetime | None]]:
    """How many of one person's chats each project holds, and when the last was active.

    The person's own: a project shares files and instructions, never what
    somebody asked in it.
    """
    if not project_ids:
        return {}
    result = await db.execute(
        select(
            Conversation.project_id,
            func.count(Conversation.id),
            func.max(func.coalesce(Conversation.updated_at, Conversation.created_at)),
        )
        .where(
            Conversation.organization_id == organization_id,
            Conversation.user_id == user_id,
            Conversation.project_id.in_(project_ids),
            Conversation.is_archived.is_(False),
        )
        .group_by(Conversation.project_id)
    )
    return {
        project_id: (count, last)
        for project_id, count, last in result.all()
        if project_id is not None
    }


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    owner_user_id: UUID | None,
    name: str,
    description: str | None,
    instructions: str,
    default_agent_id: UUID | None,
    backend: str,
    visibility: str = Visibility.PRIVATE.value,
) -> Project:
    project = Project(
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        name=name,
        description=description,
        instructions=instructions,
        default_agent_id=default_agent_id,
        backend=backend,
        visibility=visibility,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


async def update(db: AsyncSession, *, project: Project, update_data: dict[str, Any]) -> Project:
    for field, value in update_data.items():
        setattr(project, field, value)
    await db.flush()
    await db.refresh(project)
    return project


async def delete(db: AsyncSession, project: Project) -> None:
    await db.delete(project)
    await db.flush()


async def detach_conversations(db: AsyncSession, *, project: Project) -> None:
    """Leave a deleted project's chats as ordinary ones - the foreign key does too,
    and doing it here keeps the session's own rows in step with the database."""
    await db.execute(
        update_rows(Conversation)
        .where(
            and_(
                Conversation.organization_id == project.organization_id,
                Conversation.project_id == project.id,
            )
        )
        .values(project_id=None)
    )
