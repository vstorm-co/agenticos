"""Projects: data access. Who may see one is decided by the service."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy import delete as delete_rows
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


async def get_many(
    db: AsyncSession, project_ids: Sequence[UUID], *, organization_id: UUID
) -> list[Project]:
    """Resolve a batch inside one tenant before resource authorization."""
    if not project_ids:
        return []
    result = await db.execute(
        select(Project).where(
            Project.organization_id == organization_id, Project.id.in_(project_ids)
        )
    )
    return list(result.scalars().all())


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


async def visible_ids(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
) -> list[UUID]:
    """Every project one member may see, by id - `list_visible`'s rule, unpaged."""
    where = [Project.organization_id == organization_id]
    if not see_all:
        where.append(
            or_(
                Project.owner_user_id == user_id,
                Project.visibility == Visibility.ORG.value,
                Project.id.in_(shared_ids) if shared_ids else false(),
            )
        )
    result = await db.execute(select(Project.id).where(*where))
    return list(result.scalars().all())


async def chat_activity(
    db: AsyncSession, *, organization_id: UUID, project_ids: Sequence[UUID]
) -> dict[UUID, tuple[int, datetime | None]]:
    """How many chats each project holds, whoever started them, and when the last moved.

    Everybody's: a project's chats are its members' to read and continue, so a
    card counting only the reader's own would disagree with the list it opens.
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
    sandbox_connection_id: UUID | None = None,
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
        sandbox_connection_id=sandbox_connection_id,
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


async def names_on_connection(
    db: AsyncSession, *, organization_id: UUID, connection_id: UUID, limit: int = 5
) -> list[str]:
    """The names of the projects whose containers run on one sandbox connection."""
    result = await db.execute(
        select(Project.name)
        .where(
            Project.organization_id == organization_id,
            Project.sandbox_connection_id == connection_id,
        )
        .order_by(Project.name)
        .limit(limit)
    )
    return list(result.scalars().all())


async def delete(db: AsyncSession, project: Project) -> None:
    await db.delete(project)
    await db.flush()


async def ownerless_chat_ids(db: AsyncSession, *, project: Project) -> list[UUID]:
    """The chats :func:`detach_conversations` deletes rather than detaches."""
    result = await db.execute(
        select(Conversation.id).where(
            Conversation.organization_id == project.organization_id,
            Conversation.project_id == project.id,
            Conversation.user_id.is_(None),
        )
    )
    return list(result.scalars().all())


async def detach_conversations(db: AsyncSession, *, project: Project) -> None:
    """Leave a deleted project's chats as ordinary ones - the foreign key does too,
    and doing it here keeps the session's own rows in step with the database.

    Except a chat whose starter's account is gone: the project was its only way
    in, and outside it nobody could list or open it again, so it goes with the
    project rather than stay behind unreachable.
    """
    await db.execute(
        delete_rows(Conversation).where(
            Conversation.organization_id == project.organization_id,
            Conversation.project_id == project.id,
            Conversation.user_id.is_(None),
        )
    )
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
