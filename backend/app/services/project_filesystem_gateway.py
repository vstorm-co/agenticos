"""Authorize each live filesystem RPC against its original run and current Project."""

import errno
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.project import Project
from app.db.models.project_filesystem import ProjectFilesystemBinding, ProjectFilesystemLease
from app.repositories import agent_run as run_repo
from app.repositories import conversation as conversation_repo
from app.repositories import conversation_share as share_repo
from app.repositories import project_filesystem_bindings as binding_repo
from app.schemas.project_filesystem import (
    FsEntry,
    FsFailure,
    FsList,
    FsRename,
    FsRequest,
    FsResponse,
    FsStat,
    FsSuccess,
)
from app.schemas.project_filesystem_authority import ProjectFilesystemAuthority
from app.services.project_filesystem import ProjectFilesystemService
from app.services.project_filesystem_bindings import ProjectFilesystemBindingService
from app.services.routine_authority import RoutineAuthority
from app.services.run_project_workspace import ProjectRunAuthority


class ProjectFilesystemGateway:
    """Map immutable lease directories to fresh, authoritative Project operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.bindings = ProjectFilesystemBindingService(db)

    async def perform(
        self, binding_id: UUID, token: SecretStr | None, request: FsRequest
    ) -> FsResponse:
        binding = await self.bindings.authenticate(binding_id, token)
        if request.path in ("", ".", "/"):
            return await self._root(binding, request)
        parsed = _lease_path(request.path)
        if parsed is None:
            return FsFailure(errno=errno.ENOENT, message="No such Project filesystem directory")
        lease_id, relative = parsed
        lease = await binding_repo.lease_for_binding(self.db, binding=binding, lease_id=lease_id)
        if lease is None:
            return FsFailure(
                errno=errno.ESTALE, message="The Project filesystem directory is stale"
            )
        actor, project, authority = await self.authorize(binding, lease)
        if isinstance(request, FsRename):
            destination = _lease_path(request.destination)
            if destination is None or destination[0] != lease.id:
                return FsFailure(
                    errno=errno.EXDEV, message="Move files within the same Project directory"
                )
            selected = request.model_copy(update={"path": relative, "destination": destination[1]})
        else:
            selected = request.model_copy(update={"path": relative})
        result = await ProjectFilesystemService(self.db).perform(
            actor,
            project.id,
            lease.workspace_generation,
            selected,
            writable="projects:write" in authority.granted_scopes,
        )
        return _prefix_result(result, lease.id)

    async def _root(self, binding: ProjectFilesystemBinding, request: FsRequest) -> FsResponse:
        if isinstance(request, FsStat):
            return FsSuccess(entry=_root_entry(binding))
        if not isinstance(request, FsList):
            return FsFailure(
                errno=errno.EROFS, message="The filesystem root is managed by the platform"
            )
        entries: list[FsEntry] = []
        for lease in await binding_repo.live_leases(
            self.db, binding=binding, now=datetime.now(UTC)
        ):
            try:
                await self.authorize(binding, lease)
            except AuthenticationError, AuthorizationError, ConcurrentChangeError, NotFoundError:
                # Root listings expose only currently authorized run directories.
                continue
            entries.append(
                FsEntry(
                    path=str(lease.id),
                    is_dir=True,
                    size=0,
                    mode=0o755,
                    modified_at=lease.created_at,
                )
            )
        return FsSuccess(entries=entries)

    async def authorize(
        self, binding: ProjectFilesystemBinding, lease: ProjectFilesystemLease
    ) -> tuple[AuthContext, Project, ProjectFilesystemAuthority]:
        if lease.revoked_at is not None or (
            lease.environment_id is None and lease.expires_at <= datetime.now(UTC)
        ):
            raise AuthorizationError(message="The Project filesystem lease expired", details={})
        authority = ProjectFilesystemAuthority.model_validate_json(lease.authority_json)
        if (
            authority.actor.organization_id != binding.organization_id
            or authority.actor.user_id != lease.actor_id
        ):
            raise AuthorizationError(
                message="The Project filesystem admission is invalid", details={}
            )
        if lease.environment_id is not None:
            from app.services.conversation_environment_project_files import authorize

            await self._conversation(binding, authority)
            return await authorize(self.db, binding, lease, authority)
        if lease.run_id is None:
            raise AuthorizationError(message="The Project filesystem lease has no run")
        run = await run_repo.get_run(self.db, lease.run_id, organization_id=binding.organization_id)
        if (
            run is None
            or run.status != RunStatus.RUNNING.value
            or run.user_id != lease.actor_id
            or run.conversation_id != binding.conversation_id
        ):
            raise AuthorizationError(
                message="This Project filesystem run is no longer active", details={}
            )
        await self._conversation(binding, authority)
        actor, project = await ProjectRunAuthority(
            ctx=authority.actor,
            audience=authority.audience,
            granted_scopes=authority.granted_scopes,
            conversation_project_id=authority.conversation_project_id,
        ).project(self.db, lease.project_id)
        if project.workspace_generation != lease.workspace_generation:
            raise ConcurrentChangeError(
                message="The Project filesystem generation changed", details={}
            )
        await self._routine(actor, run, project)
        return actor, project, authority

    async def _conversation(
        self, binding: ProjectFilesystemBinding, authority: ProjectFilesystemAuthority
    ) -> None:
        if authority.conversation_id != binding.conversation_id:
            raise AuthorizationError(message="The filesystem conversation changed", details={})
        if binding.conversation_id is None:
            return
        conversation = await conversation_repo.get_conversation_by_id(
            self.db, binding.conversation_id, fresh=True
        )
        if (
            conversation is None
            or conversation.organization_id != binding.organization_id
            or conversation.project_id != authority.conversation_project_id
        ):
            raise AuthorizationError(
                message="The filesystem conversation is no longer available", details={}
            )
        if authority.conversation_project_id is None and (
            conversation.user_id != authority.actor.user_id
            or await share_repo.has_edit_share(
                self.db, conversation.id, organization_id=binding.organization_id
            )
        ):
            raise AuthorizationError(
                message="Use an isolated private conversation for Project files", details={}
            )

    async def _routine(self, actor: AuthContext, run: AgentRun, project: Project) -> None:
        routine = await RoutineAuthority.capture(self.db, actor, agent_id=run.agent_id, run=run)
        if routine is not None:
            routine.require_project(project)


def _lease_path(value: str) -> tuple[UUID, str] | None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\x00" in value or not path.parts:
        return None
    try:
        lease_id = UUID(path.parts[0])
    except ValueError:
        return None
    if path.parts[0] != str(lease_id):
        return None
    return lease_id, str(PurePosixPath(*path.parts[1:]))


def _root_entry(binding: ProjectFilesystemBinding) -> FsEntry:
    return FsEntry(path=".", is_dir=True, size=0, mode=0o755, modified_at=binding.created_at)


def _prefix_result(response: FsResponse, lease_id: UUID) -> FsResponse:
    if not isinstance(response, FsSuccess):
        return response
    updates: dict[str, FsEntry | list[FsEntry]] = {}
    if response.entry is not None:
        entry = response.entry
        updates["entry"] = entry.model_copy(update={"path": _prefixed_path(lease_id, entry.path)})
    if response.entries is not None:
        updates["entries"] = [
            entry.model_copy(update={"path": _prefixed_path(lease_id, entry.path)})
            for entry in response.entries
        ]
    return response.model_copy(update=updates)


def _prefixed_path(lease_id: UUID, path: str) -> str:
    return str(lease_id) if path in ("", ".", "/") else f"{lease_id}/{path.lstrip('/')}"
