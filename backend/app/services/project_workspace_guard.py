"""The write barrier shared by project file requests and agent workspace opens."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.background_job import BackgroundJob
from app.db.models.project import Project
from app.repositories import background_job as job_repo
from app.repositories import project_repo
from app.schemas.project import ProjectWorkspaceMoveRead, ProjectWorkspaceProgress
from app.services.access import PROJECT, resolve_access
from app.worker.jobs import MoveProjectWorkspacePayload, project_move_generation


async def require_available(db: AsyncSession, project: Project) -> None:
    if project.workspace_move_job_id is None:
        return
    job = await job_repo.get(db, project.workspace_move_job_id)
    if job is not None and job.status in ("queued", "running"):
        raise AlreadyExistsError(
            message="This project's files are being moved. Wait for the transfer to finish.",
            details={"job_id": str(job.id)},
        )


async def project_for_workspace(
    db: AsyncSession, ctx: AuthContext, project_id: UUID | None
) -> Project:
    if project_id is None:
        raise NotFoundError(message="Project not found", details={})
    project = await project_repo.get(
        db, project_id, organization_id=ctx.organization_id, for_update=True
    )
    if project is None or not await resolve_access(
        db, ctx, project, Perm.PROJECTS_USE, resource_type=PROJECT
    ):
        raise NotFoundError(message="Project not found", details={"project_id": str(project_id)})
    await require_available(db, project)
    return project


def workspace_move_read(
    job: BackgroundJob | None, project: Project
) -> ProjectWorkspaceMoveRead | None:
    if job is None:
        return None
    payload = MoveProjectWorkspacePayload.model_validate(job.payload)
    applied = any(
        project.workspace_generation == project_move_generation(payload.transfer_id, attempt)
        for attempt in range(1, job.max_attempts + 1)
    )
    progress = ProjectWorkspaceProgress.model_validate(job.result or {})
    return ProjectWorkspaceMoveRead(
        job_id=job.id,
        status="succeeded" if applied else job.status,
        target_name=payload.target_name,
        copied_files=progress.copied_files,
        total_files=progress.total_files,
        copied_bytes=progress.copied_bytes,
    )
