"""Workflow files and whether a run may read one (#1791)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import ResourceRef, ResourceRefKind


async def create(
    db: AsyncSession,
    *,
    file_id: UUID,
    organization_id: UUID,
    workflow_run_id: UUID,
    producing_node_run_id: UUID | None,
    storage_path: str,
    content_type: str,
    byte_size: int,
    filename: str | None,
) -> WorkflowFile:
    row = WorkflowFile(
        id=file_id,
        organization_id=organization_id,
        workflow_run_id=workflow_run_id,
        producing_node_run_id=producing_node_run_id,
        storage_path=storage_path,
        content_type=content_type,
        byte_size=byte_size,
        filename=filename,
    )
    db.add(row)
    await db.flush()
    return row


async def get(db: AsyncSession, file_id: UUID, *, organization_id: UUID) -> WorkflowFile | None:
    """One file, in one organization - never a lookup by id alone."""
    result = await db.execute(
        select(WorkflowFile).where(
            WorkflowFile.id == file_id, WorkflowFile.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def get_for_run(
    db: AsyncSession, file_id: UUID, *, organization_id: UUID, workflow_run_id: UUID
) -> WorkflowFile | None:
    """A file `workflow_run_id` may read: one it made, or one it was started with.

    "Started with" is a `FileRef` its graph named, recorded as a `ResourceRef`
    when the run was admitted - checked then against what the graph's author may
    see. A file another run made and nobody handed this one answers `None`,
    exactly like a file in another organization, so an id is no key.
    """
    row = await get(db, file_id, organization_id=organization_id)
    if row is None:
        return None
    if row.workflow_run_id == workflow_run_id:
        return row
    imported = await db.execute(
        select(ResourceRef.id).where(
            ResourceRef.workflow_run_id == workflow_run_id,
            ResourceRef.kind == ResourceRefKind.FILE.value,
            ResourceRef.ref["file_id"].astext == str(file_id),
        )
    )
    return row if imported.first() is not None else None


async def list_for_run(
    db: AsyncSession, *, workflow_run_id: UUID, organization_id: UUID
) -> list[WorkflowFile]:
    """The files one run made, oldest first."""
    result = await db.execute(
        select(WorkflowFile)
        .where(
            WorkflowFile.workflow_run_id == workflow_run_id,
            WorkflowFile.organization_id == organization_id,
        )
        .order_by(WorkflowFile.created_at, WorkflowFile.id)
    )
    return list(result.scalars().all())
