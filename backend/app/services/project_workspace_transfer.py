"""Copy and verify project files before activating a new, isolated workspace.

A source remains selected throughout the copy. Each worker attempt owns a fresh
workspace generation, so a process whose lease expired can never alter a copy
that another attempt has activated. The source is retired only after the verified
target has been committed.
"""

import hashlib
import posixpath
from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic_ai.workspaces import Workspace
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AlreadyExistsError,
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.project import Project
from app.db.session import get_worker_db_context
from app.repositories import agent_workspace_repo, member_repo, project_repo, user_repo
from app.repositories import background_job as job_repo
from app.schemas.project import (
    ProjectWorkspaceMoveRead,
    ProjectWorkspaceMoveRequest,
    ProjectWorkspaceProgress,
)
from app.services.access import PROJECT, resolve_access
from app.services.api_key import ApiKeyService
from app.services.background_jobs import enqueue
from app.services.project import ProjectService, _in_platform_folder
from app.services.project_workspace_guard import workspace_move_read
from app.services.sandbox_connection import SandboxConnectionService
from app.services.sandbox_workspace import TOOLING_DIRS, SandboxWorkspaceService
from app.worker.jobs import (
    MOVE_PROJECT_WORKSPACE,
    MoveProjectWorkspacePayload,
    project_move_generation,
)

MAX_ENTRIES = 10_000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True)
class CopyEntry:
    path: str
    directory: bool
    size: int


async def manifest(workspace: Workspace) -> list[CopyEntry]:
    """Enumerate complete user content, refusing links and bounded-memory violations."""
    root = posixpath.normpath(await workspace.working_dir())
    pending = [""]
    found: list[CopyEntry] = []
    total = 0
    seen: set[str] = set()
    while pending:
        parent = pending.pop()
        for entry in await workspace.list_dir(posixpath.join(root, parent)):
            absolute = posixpath.normpath(posixpath.join(root, parent, entry.path))
            relative = posixpath.relpath(absolute, root)
            if _in_platform_folder(relative) or any(
                part in TOOLING_DIRS for part in relative.split("/")
            ):
                continue
            if relative.startswith("../") or relative in ("..", ".") or relative in seen:
                raise BadRequestError(
                    message="The workspace contains an invalid or repeated path", details={}
                )
            seen.add(relative)
            if posixpath.normpath(await workspace.realpath(absolute)) != absolute:
                raise BadRequestError(
                    message="Remove symbolic links before moving this project's files",
                    details={"path": relative},
                )
            info = await workspace.stat(absolute)
            if not info.is_dir and info.size is None:
                raise BadRequestError(
                    message="Cannot measure a source file safely", details={"path": relative}
                )
            size = 0 if info.is_dir else (info.size or 0)
            total += size
            if len(found) >= MAX_ENTRIES or size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise BadRequestError(
                    message="Project transfer supports 10,000 entries, 64 MiB per file and 1 GiB in total",
                    details={},
                )
            found.append(CopyEntry(relative, info.is_dir, size))
            if info.is_dir:
                pending.append(relative)
    return sorted(found, key=lambda entry: entry.path)


class ProjectWorkspaceTransferService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def queue(
        self, ctx: AuthContext, project_id: UUID, data: ProjectWorkspaceMoveRequest
    ) -> ProjectWorkspaceMoveRead:
        project = await ProjectService(self.db).get(ctx, project_id, perm=Perm.PROJECTS_EDIT)
        if await project_repo.has_active_runs(
            self.db, project_id=project.id, organization_id=ctx.organization_id
        ):
            raise AlreadyExistsError(
                message="Wait for the project's active runs and decisions to finish before moving its files",
                details={},
            )
        source = await agent_workspace_repo.get_for_project(
            self.db, organization_id=ctx.organization_id, project_id=project.id
        )
        source_connection_id = (
            source.connection_id if source is not None else project.sandbox_connection_id
        )
        target_id = data.sandbox_connection_id
        # Serialize target edits/deletion against registering this transfer.
        connections = SandboxConnectionService(self.db)
        for connection_id in sorted(
            {item for item in (source_connection_id, target_id) if item is not None}
        ):
            await connections.get(ctx, connection_id, for_update=True)
        if data.backend == "state":
            if target_id is not None:
                raise BadRequestError(
                    message="Stored files do not use a sandbox connection", details={}
                )
            name = "Stored files"
        else:
            if not ctx.has(Perm.CONNECTIONS_VIEW):
                raise AuthorizationError(
                    message="You cannot choose a sandbox connection", details={}
                )
            if target_id is None:
                raise BadRequestError(message="Choose a sandbox connection", details={})
            connection = await SandboxConnectionService(self.db).get(ctx, target_id)
            if not connection.is_active:
                raise BadRequestError(message="Choose an active sandbox connection", details={})
            name = connection.name
        if project.backend == data.backend and project.sandbox_connection_id == target_id:
            raise BadRequestError(message="This project already uses that workspace", details={})
        payload = MoveProjectWorkspacePayload(
            transfer_id=uuid4(),
            project_id=project.id,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            api_key_id=ctx.api_key_id,
            source_backend="state" if project.backend == "state" else "service",
            source_connection_id=source_connection_id,
            source_generation=project.workspace_generation,
            source_workspace_id=source.id if source else None,
            target_backend=data.backend,
            target_connection_id=target_id,
            target_runtime=None,
            target_name=name,
        )
        job_id = await enqueue(
            self.db,
            MOVE_PROJECT_WORKSPACE,
            payload,
            organization_id=ctx.organization_id,
            dedupe_key=f"project-workspace:{project.id}",
            dedupe_active=True,
            concurrency_key=f"project-workspace:{project.id}",
        )
        if job_id is None:
            raise AlreadyExistsError(
                message="This project already has a transfer queued", details={}
            )
        project.workspace_move_job_id = job_id
        await self.db.flush()
        return ProjectWorkspaceMoveRead(job_id=job_id, status="queued", target_name=name)

    async def context(self, payload: MoveProjectWorkspacePayload) -> AuthContext:
        if payload.api_key_id is not None:
            return await ApiKeyService(self.db).context_for_key(
                payload.api_key_id, organization_id=payload.organization_id
            )
        membership = await member_repo.get_active(
            self.db, organization_id=payload.organization_id, user_id=payload.user_id
        )
        user = await user_repo.get_by_id(self.db, payload.user_id)
        if membership is None or user is None or not user.is_active:
            raise AuthenticationError(
                message="The person who requested the transfer no longer has access"
            )
        return AuthContext(
            user_id=payload.user_id,
            organization_id=payload.organization_id,
            role=membership.role,
            is_app_admin=user.is_app_admin,
        )

    async def run(
        self, payload: MoveProjectWorkspacePayload, *, attempt: int
    ) -> ProjectWorkspaceProgress:
        ctx = await self.context(payload)
        project = await project_repo.get(
            self.db, payload.project_id, organization_id=payload.organization_id
        )
        if project is None or not await resolve_access(
            self.db, ctx, project, Perm.PROJECTS_EDIT, resource_type=PROJECT
        ):
            raise AuthorizationError(
                message="You can no longer move this project's files", details={}
            )
        job = (
            await job_repo.get(self.db, project.workspace_move_job_id)
            if project.workspace_move_job_id
            else None
        )
        if (
            job is None
            or MOVE_PROJECT_WORKSPACE.load(job.payload).transfer_id != payload.transfer_id
        ):
            raise AlreadyExistsError(message="This transfer has been replaced", details={})
        state = workspace_move_read(job, project)
        if state is not None and state.status == "succeeded":
            return ProjectWorkspaceProgress(
                copied_files=state.copied_files,
                total_files=state.total_files,
                copied_bytes=state.copied_bytes,
            )
        if project.workspace_generation != payload.source_generation:
            raise AlreadyExistsError(message="The project's workspace changed", details={})
        if payload.target_connection_id is not None:
            connection = await SandboxConnectionService(self.db).get(
                ctx, payload.target_connection_id
            )
            if not connection.is_active or not ctx.has(Perm.CONNECTIONS_VIEW):
                raise AuthorizationError(
                    message="The target sandbox is no longer available to you", details={}
                )
        generation = project_move_generation(payload.transfer_id, attempt)
        target = Project(
            id=project.id,
            organization_id=project.organization_id,
            backend=payload.target_backend,
            sandbox_connection_id=payload.target_connection_id,
            runtime=payload.target_runtime,
            workspace_generation=generation,
        )
        service = SandboxWorkspaceService(self.db)
        source_project = Project(
            id=project.id,
            organization_id=project.organization_id,
            backend=payload.source_backend,
            sandbox_connection_id=payload.source_connection_id,
            runtime=project.runtime,
            workspace_generation=payload.source_generation,
        )
        source = await service.open_project(ctx, source_project)
        destination = None
        progress = ProjectWorkspaceProgress()
        try:
            destination = await service.open_project(ctx, target)
            if await manifest(destination.workspace):
                raise BadRequestError(
                    message="The private transfer destination is not empty", details={}
                )
            entries = await manifest(source.workspace)
            progress.total_files = sum(not entry.directory for entry in entries)
            await self._progress(job.id, attempt, progress)
            origin = await source.workspace.working_dir()
            dest = await destination.workspace.working_dir()
            digests: dict[str, str] = {}
            for entry in entries:
                to_path = posixpath.join(dest, entry.path)
                if entry.directory:
                    await destination.workspace.make_dir(to_path)
                    continue
                data = await source.workspace.read_bytes(posixpath.join(origin, entry.path))
                if len(data) != entry.size or len(data) > MAX_FILE_BYTES:
                    raise BadRequestError(
                        message="A source file changed during the transfer",
                        details={"path": entry.path},
                    )
                await destination.workspace.write_bytes(to_path, data)
                digests[entry.path] = hashlib.sha256(data).hexdigest()
                progress.copied_files += 1
                progress.copied_bytes += len(data)
                await self._progress(job.id, attempt, progress)
            for path, digest in digests.items():
                for workspace, root in ((source.workspace, origin), (destination.workspace, dest)):
                    if (
                        hashlib.sha256(
                            await workspace.read_bytes(posixpath.join(root, path))
                        ).hexdigest()
                        != digest
                    ):
                        raise BadRequestError(
                            message="Project file verification failed; the source is unchanged",
                            details={"path": path},
                        )
            if entries != await manifest(source.workspace) or entries != await manifest(
                destination.workspace
            ):
                raise BadRequestError(
                    message="Project contents changed during verification", details={}
                )
        finally:
            try:
                failure = await service.close(destination)
                if failure is not None:
                    raise failure.error
            finally:
                failure = await service.close(source)
                if failure is not None:
                    raise failure.error
        # Lock ordering matches queue/file writes: project, then job. A cancelled
        # or reclaimed attempt has no authority to publish its external copy.
        current = await project_repo.get(
            self.db, project.id, organization_id=ctx.organization_id, for_update=True
        )
        fenced = await job_repo.lock_workspace_attempt(self.db, job.id, attempt=attempt)
        fresh_ctx = await self.context(payload)
        if (
            current is None
            or fenced is None
            or current.workspace_move_job_id != job.id
            or not await resolve_access(
                self.db, fresh_ctx, current, Perm.PROJECTS_EDIT, resource_type=PROJECT
            )
        ):
            raise AlreadyExistsError(message="This transfer no longer owns the project", details={})
        current.backend = payload.target_backend
        current.sandbox_connection_id = payload.target_connection_id
        current.runtime = payload.target_runtime
        current.workspace_generation = generation
        fenced.result = progress.model_dump(mode="json")
        if source.row_id is not None:
            await service.retire_project_source(
                fresh_ctx, source_id=source.row_id, project_id=current.id
            )
        await self.db.flush()
        return progress

    @staticmethod
    async def _progress(job_id: UUID, attempt: int, progress: ProjectWorkspaceProgress) -> None:
        async with get_worker_db_context() as db:
            if not await job_repo.workspace_move_progress(
                db, job_id, attempt=attempt, result=progress.model_dump(mode="json")
            ):
                raise AlreadyExistsError(message="This transfer's lease expired", details={})
