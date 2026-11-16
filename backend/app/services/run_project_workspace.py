"""A run's project selection with live authorization and per-operation persistence.

The original workspace stays owned by the runner. Project operations attach and
flush within their own transaction; no session or project lock survives a tool
call, and a revoked grant cannot survive in a cached workspace handle.
"""

import json
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256
from uuid import UUID

from pydantic_ai.messages import WorkspaceRef
from pydantic_ai.workspaces import (
    CommandResult,
    FileEntry,
    SupportsCommands,
    Workspace,
    WorkspaceBackend,
    WorkspaceCommand,
    WorkspaceUnavailableError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, AuthorizationError
from app.core.permissions import AuthContext
from app.db.models.project import Project
from app.db.session import get_db_context
from app.services.access import member_context
from app.services.project_workspace_guard import project_for_workspace
from app.services.sandbox_workspace import SandboxWorkspaceService


class RunProjectWorkspace(Workspace):
    """One selector per top-level run; approval resumes restore only the project id."""

    def __init__(
        self,
        original: Workspace,
        ctx: AuthContext,
        *,
        require_project: Callable[[Project], None] | None = None,
    ) -> None:
        super().__init__(original)
        self.original = original
        self.ctx = ctx
        self.require_project = require_project
        self.project_id: UUID | None = None
        self._read_versions: dict[tuple[UUID, str], bytes] = {}
        self.workspace = Workspace(self)

    @property
    def backend(self) -> WorkspaceBackend:
        # Native computer tools must still see their provider before selection.
        return self.original.backend if self.project_id is None else self

    @property
    def ref(self) -> WorkspaceRef | None:
        # A routing handle is never a portable authority to either filesystem.
        return None

    async def _project(self, db: AsyncSession, project_id: UUID) -> tuple[AuthContext, Project]:
        if self.ctx.user_id is None or self.ctx.subject_is_publisher_fallback:
            raise AuthorizationError(message="Select a project as a connected organization member.")
        member = await member_context(
            db, organization_id=self.ctx.organization_id, user_id=self.ctx.user_id
        )
        if member is None:
            raise AuthorizationError(message="Your organization membership is no longer active")
        ctx = replace(self.ctx, role=member.role, is_app_admin=member.is_app_admin)
        project = await project_for_workspace(db, ctx, project_id)
        if self.require_project is not None:
            self.require_project(project)
        return ctx, project

    @asynccontextmanager
    async def _open(self) -> AsyncGenerator[Workspace]:
        project_id = self.project_id
        if project_id is None:
            yield self.original
            return
        async with get_db_context() as db:
            try:
                ctx, project = await self._project(db, project_id)
                service = SandboxWorkspaceService(db)
                opened = await service.open_project(ctx, project)
            except AppException as error:
                raise PermissionError(error.message) from error
            try:
                yield opened.workspace
            finally:
                failure = await service.close(opened)
                if failure is not None:
                    raise WorkspaceUnavailableError(failure.error.message)

    async def select(self, project_id: UUID | None) -> str:
        if project_id is None:
            self.project_id = None
            return "Restored the original workspace. The conversation has not moved."
        # Selection itself opens no container. Each later operation resolves the
        # current generation, membership and grant again before attaching.
        async with get_db_context() as db:
            _, project = await self._project(db, project_id)
            name, backend = project.name, project.backend
        self.project_id = project_id
        return json.dumps(
            {
                "kind": "project_workspace_selection",
                "project_id": str(project_id),
                "name": name,
                "backend": backend,
                "message": "File and shell tools now use this project until the run ends. No conversation history or private files were copied.",
            }
        )

    async def working_dir(self) -> str:
        async with self._open() as workspace:
            return await workspace.working_dir()

    async def read_bytes(self, path: str) -> bytes:
        async with self._open() as workspace:
            data = await workspace.read_bytes(path)
            if self.project_id is not None:
                self._read_versions[(self.project_id, await workspace.resolve(path))] = sha256(
                    data
                ).digest()
            return data

    async def _refuse_changed(self, workspace: Workspace, path: str) -> None:
        project_id = self.project_id
        if project_id is None:
            return
        previous = self._read_versions.get((project_id, await workspace.resolve(path)))
        if previous is None:
            return
        try:
            current = sha256(await workspace.read_bytes(path)).digest()
        except FileNotFoundError:
            current = None
        if current != previous:
            raise WorkspaceUnavailableError(
                "This project file changed since it was read. Read it again before changing it."
            )

    async def write_bytes(self, path: str, data: bytes) -> None:
        async with self._open() as workspace:
            await self._refuse_changed(workspace, path)
            await workspace.write_bytes(path, data)
            if self.project_id is not None:
                self._read_versions[(self.project_id, await workspace.resolve(path))] = sha256(
                    data
                ).digest()

    async def stat(self, path: str) -> FileEntry:
        async with self._open() as workspace:
            return await workspace.stat(path)

    async def list_dir(self, path: str) -> Sequence[FileEntry]:
        async with self._open() as workspace:
            return await workspace.list_dir(path)

    async def make_dir(self, path: str) -> None:
        async with self._open() as workspace:
            await workspace.make_dir(path)

    async def remove(self, path: str) -> None:
        async with self._open() as workspace:
            await self._refuse_changed(workspace, path)
            await workspace.remove(path)
            if self.project_id is not None:
                self._read_versions.pop((self.project_id, await workspace.resolve(path)), None)

    async def exists(self, path: str) -> bool:
        async with self._open() as workspace:
            return await workspace.exists(path)

    async def realpath(self, path: str) -> str:
        async with self._open() as workspace:
            return await workspace.realpath(path)

    async def run(
        self,
        command: WorkspaceCommand,
        *,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        async with self._open() as workspace:
            if not isinstance(workspace.backend, SupportsCommands):
                raise WorkspaceUnavailableError(
                    "This workspace stores files only and cannot run shell commands."
                )
            return await workspace.run(command, shell=shell, env=env, timeout=timeout, cwd=cwd)
