"""Typed metadata on the same tenant-owned Project workspace row as its files."""

import errno
from datetime import datetime
from uuid import UUID

from pydantic import JsonValue, TypeAdapter
from pydantic_ai_backends import FileData
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_workspace import AgentWorkspace
from app.schemas.project_filesystem import FsStoredAttributes

_METADATA = TypeAdapter(dict[str, FsStoredAttributes])
_JSON = TypeAdapter(dict[str, JsonValue])
_FILES = TypeAdapter(dict[str, FileData])


async def metadata(
    db: AsyncSession, workspace_id: UUID, *, organization_id: UUID
) -> tuple[AgentWorkspace, dict[str, FsStoredAttributes]]:
    row = await db.scalar(
        select(AgentWorkspace)
        .where(
            AgentWorkspace.id == workspace_id,
            AgentWorkspace.organization_id == organization_id,
            AgentWorkspace.scope == "project",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise FileNotFoundError(errno.ENOENT, "Project workspace disappeared")
    return row, _METADATA.validate_python(row.filesystem_metadata or {})


async def save_metadata(
    db: AsyncSession, row: AgentWorkspace, values: dict[str, FsStoredAttributes]
) -> None:
    row.filesystem_metadata = _JSON.validate_python(_METADATA.dump_python(values, mode="json"))
    await db.flush()


async def save_file_timestamp(
    db: AsyncSession, row: AgentWorkspace, path: str, modified_at: datetime
) -> None:
    """Persist intentional setattr; ordinary workspace flush ignores timestamp-only changes."""
    files = _FILES.validate_python(row.files or {})
    files[path] = {**files[path], "modified_at": modified_at.isoformat()}
    row.files = files
    row.version += 1
    await db.flush()
    await db.refresh(row)
