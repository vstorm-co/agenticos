"""Folder repository (PostgreSQL async) - #2124."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.db.models.artifact import Artifact
from app.db.models.context import ContextFile
from app.db.models.folder import Folder
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.skill import Skill


@dataclass(frozen=True)
class FolderScope:
    """Which folder a listing shows (#2124).

    `folder_id` None is the top level, which also holds whatever sits in a
    folder the reader cannot see - something shared with them directly, filed
    somewhere they are not in the audience of - so it is not lost.
    """

    folder_id: UUID | None
    visible: frozenset[UUID]


def in_folder(
    column: InstrumentedAttribute[UUID | None], scope: FolderScope
) -> ColumnElement[bool]:
    """The predicate a listing adds to show one folder's contents."""
    if scope.folder_id is not None:
        return column == scope.folder_id
    if not scope.visible:
        # No folder in sight: everything the reader may see is at their top level.
        return true()
    return or_(column.is_(None), column.not_in(scope.visible))


Filed = type[Artifact] | type[ContextFile] | type[KnowledgeBase] | type[Skill]

# The table each kind of folder holds.
_TABLES: dict[str, Filed] = {
    "artifact": Artifact,
    "context": ContextFile,
    "collection": KnowledgeBase,
    "skill": Skill,
}


async def get(db: AsyncSession, *, organization_id: UUID, folder_id: UUID) -> Folder | None:
    """One folder of this organization, or None - another tenant's is None too."""
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def list_for_kind(db: AsyncSession, *, organization_id: UUID, kind: str) -> list[Folder]:
    """Every folder of one kind in this organization, by name."""
    result = await db.execute(
        select(Folder)
        .where(Folder.organization_id == organization_id, Folder.kind == kind)
        .order_by(Folder.name.asc())
    )
    return list(result.scalars().all())


async def children(db: AsyncSession, *, organization_id: UUID, folder_id: UUID) -> list[Folder]:
    """The folders directly inside one folder."""
    result = await db.execute(
        select(Folder).where(
            Folder.organization_id == organization_id, Folder.parent_id == folder_id
        )
    )
    return list(result.scalars().all())


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    kind: str,
    parent_id: UUID | None,
    name: str,
    owner_user_id: UUID | None,
    visibility: str,
) -> Folder:
    folder = Folder(
        organization_id=organization_id,
        kind=kind,
        parent_id=parent_id,
        name=name,
        owner_user_id=owner_user_id,
        visibility=visibility,
    )
    db.add(folder)
    await db.flush()
    await db.refresh(folder)
    return folder


async def update_folder(
    db: AsyncSession, *, folder: Folder, update_data: dict[str, object]
) -> Folder:
    for field, value in update_data.items():
        setattr(folder, field, value)
    db.add(folder)
    await db.flush()
    await db.refresh(folder)
    return folder


async def delete(db: AsyncSession, *, folder: Folder) -> None:
    await db.delete(folder)
    await db.flush()


async def sync_contents_visibility(
    db: AsyncSession, *, organization_id: UUID, kind: str, folder_id: UUID, visibility: str
) -> None:
    """Write a folder's visibility onto everything filed directly in it."""
    table = _TABLES[kind]
    await db.execute(
        update(table)
        .where(table.organization_id == organization_id, table.folder_id == folder_id)
        .values(visibility=visibility)
    )
    await db.flush()


async def move_contents(
    db: AsyncSession,
    *,
    organization_id: UUID,
    kind: str,
    from_folder_id: UUID,
    to_folder_id: UUID | None,
) -> None:
    """Refile everything in one folder - resources and subfolders - into another."""
    table = _TABLES[kind]
    await db.execute(
        update(table)
        .where(table.organization_id == organization_id, table.folder_id == from_folder_id)
        .values(folder_id=to_folder_id)
    )
    await db.execute(
        update(Folder)
        .where(Folder.organization_id == organization_id, Folder.parent_id == from_folder_id)
        .values(parent_id=to_folder_id)
    )
    await db.flush()


async def counts(db: AsyncSession, *, organization_id: UUID, kind: str) -> dict[UUID, int]:
    """How many resources each folder of a kind holds directly, by folder id."""
    table = _TABLES[kind]
    result = await db.execute(
        select(table.folder_id, func.count())
        .where(table.organization_id == organization_id, table.folder_id.is_not(None))
        .group_by(table.folder_id)
    )
    return {folder_id: count for folder_id, count in result.all() if folder_id is not None}
