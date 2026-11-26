"""A run's project selection with live authorization and per-operation persistence.

The original workspace stays owned by the runner. Project operations attach and
flush within their own transaction; no session or project lock survives a tool
call, and a revoked grant cannot survive in a cached workspace handle.
"""

import asyncio
import json
import posixpath
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256
from typing import Literal
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
from pydantic_ai_backends import FileInfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.audience import RunAudience
from app.core.exceptions import (
    AppException,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.project import Project
from app.db.session import get_db_context
from app.services.access import member_context
from app.services.api_key import ApiKeyService
from app.services.channels.attachments import workspace_snapshot
from app.services.project_workspace_guard import project_for_workspace
from app.services.sandbox_workspace import (
    OpenWorkspace,
    SandboxWorkspaceService,
    WorkspaceFlushFailure,
    browsable,
)

MAX_TRANSFER_BYTES = 8 * 1024 * 1024


class RunProjectWorkspace(Workspace):
    """One selector per top-level run; approval resumes restore only the project id."""

    def __init__(
        self,
        original: Workspace | None,
        ctx: AuthContext,
        *,
        require_project: Callable[[Project], None] | None = None,
        audience: RunAudience,
        granted_scopes: frozenset[str],
        conversation_project_id: UUID | None = None,
        original_scope: str | None = None,
        allow_project_execution: bool = True,
        shell_tools_enabled: bool = True,
        execution_target_pin: Literal["agent", "project"] | None = None,
        open_agent_executor: Callable[[AsyncSession, AuthContext], Awaitable[OpenWorkspace | None]]
        | None = None,
        agent_execution_available: bool | None = None,
        admitted_actor: AuthContext | None = None,
    ) -> None:
        super().__init__(original or Workspace(_UnavailableWorkspace()))
        self.original = original
        self.ctx = ctx
        self.require_project = require_project
        self.audience = audience
        self.granted_scopes = granted_scopes
        self.conversation_project_id = conversation_project_id
        self.original_scope = original_scope
        self.allow_project_execution = allow_project_execution
        self.shell_tools_enabled = shell_tools_enabled
        self.execution_target_pin = execution_target_pin
        self.open_agent_executor = open_agent_executor
        self.agent_execution_available = (
            agent_execution_available
            if agent_execution_available is not None
            else original is not None and isinstance(original.backend, SupportsCommands)
        )
        self.project_context_observed = False
        self.delegation_context_pinned = False
        self._closed = False
        self._pinned_view = False
        self._lifecycle_owner: RunProjectWorkspace = self
        self.admitted_actor = admitted_actor
        self.agent_workspace: OpenWorkspace | None = None
        self.agent_workspace_at_start: set[str] | None = None
        self._agent_initialization = asyncio.Lock()
        self.initialize_project: (
            Callable[[AsyncSession], Awaitable[Callable[[], None] | None]] | None
        ) = None
        self._project_initialization = asyncio.Lock()
        self._project_initialized = False
        self.imported_paths: dict[Literal["agent", "project"], set[str]] = {
            "agent": set(),
            "project": set(),
        }
        self.origins: dict[UUID, dict[str, str]] = {}
        self.execution_target: Literal["agent", "project"] = "agent"
        self.project_generation: UUID | None = None
        self.project_id: UUID | None = None
        self._read_versions: dict[tuple[UUID, str], bytes] = {}
        self._require_continuation_reads = False
        self.workspace = self

    def snapshot_for_delegate(self) -> Workspace:
        """Pin this delegation's targets; the root retains executor cleanup and journals."""

        self._require_open()
        self.delegation_context_pinned = True

        async def shared_executor(_db: AsyncSession, _actor: AuthContext) -> OpenWorkspace | None:
            async with self._open_agent():
                return self.agent_workspace

        selected = RunProjectWorkspace(
            self.original,
            self.ctx,
            require_project=self.require_project,
            audience=self.audience,
            granted_scopes=self.granted_scopes,
            conversation_project_id=self.conversation_project_id,
            original_scope=self.original_scope,
            allow_project_execution=self.allow_project_execution,
            shell_tools_enabled=self.shell_tools_enabled,
            execution_target_pin=self.execution_target_pin,
            open_agent_executor=shared_executor if self.open_agent_executor is not None else None,
            agent_execution_available=self.agent_execution_available,
            admitted_actor=self.admitted_actor,
        )
        selected.restore(
            self.project_id,
            self.project_generation,
            self.execution_target,
            self.project_context_observed,
            delegation_context_pinned=True,
            require_fresh_reads=self._require_continuation_reads,
        )
        selected._pinned_view = True
        selected._lifecycle_owner = self._lifecycle_owner
        selected.origins = self.origins
        selected._read_versions = dict(self._read_versions)
        return selected.workspace

    @property
    def backend(self) -> WorkspaceBackend:
        # Native computer tools must still see their provider before selection.
        return (
            self.original.backend
            if self.project_id is None
            and self.original is not None
            and self.open_agent_executor is None
            and not self._lifecycle_owner._closed
            and not self._pinned_view
            and not (self.project_context_observed and self.original_scope in ("agent", "channel"))
            else self
        )

    @property
    def platform(self) -> Literal["posix", "windows"]:
        return (
            "posix"
            if self.execution_target == "project" or self.original is None
            else self.original.platform
        )

    @property
    def ref(self) -> WorkspaceRef | None:
        # A routing handle is never a portable authority to either filesystem.
        return None

    async def _actor(
        self, db: AsyncSession, *, project_scope: bool = True, admitted: bool = False
    ) -> AuthContext:
        if project_scope and "projects:read" not in self.granted_scopes:
            raise AuthorizationError(message="Project access is disabled for this run.", details={})
        original = self.admitted_actor if admitted and self.admitted_actor is not None else self.ctx
        user_id = original.user_id
        if user_id is None or original.subject_is_publisher_fallback:
            raise AuthorizationError(message="Select a project as a connected organization member.")
        if original.api_key_id is not None:
            current = await ApiKeyService(db).context_for_key(
                original.api_key_id, organization_id=original.organization_id
            )
            if current.user_id != original.user_id:
                raise AuthorizationError(
                    message="The run's credential no longer belongs to its original issuer.",
                    details={},
                )
            original = replace(
                original,
                role=current.role,
                is_app_admin=current.is_app_admin,
                key_scopes=current.key_scopes,
                key_internal=current.key_internal,
            )
        member = await member_context(db, organization_id=original.organization_id, user_id=user_id)
        if member is None:
            raise AuthorizationError(message="Your organization membership is no longer active")
        return replace(original, role=member.role, is_app_admin=member.is_app_admin)

    async def _project(self, db: AsyncSession, project_id: UUID) -> tuple[AuthContext, Project]:
        ctx = await self._actor(db, admitted=project_id == self.conversation_project_id)
        if (not self.audience.private or self.audience.shared_transcript) and (
            project_id != self.conversation_project_id or not self.audience.private
        ):
            raise AuthorizationError(
                message="Use a private conversation to read another project. The audience here has not been granted access.",
                details={"project_id": project_id},
            )
        project = await project_for_workspace(db, ctx, project_id)
        if self.require_project is not None:
            self.require_project(project)
        return ctx, project

    def _require_open(self) -> None:
        if self._lifecycle_owner._closed:
            raise WorkspaceUnavailableError(
                "This run's workspace is closed. Start a new turn; delegated tools cannot reopen it after cleanup."
            )

    @asynccontextmanager
    async def _open(self) -> AsyncGenerator[Workspace]:
        self._require_open()
        project_id = self._require_selection()
        owner = self._lifecycle_owner
        if owner.initialize_project is not None and project_id == self.conversation_project_id:
            async with owner._project_initialization:
                self._require_open()
                if not owner._project_initialized:
                    async with get_db_context() as setup_db:
                        try:
                            _, project = await self._project(setup_db, project_id)
                            if self.project_generation != project.workspace_generation:
                                raise ConcurrentChangeError(
                                    message="This project workspace changed. Select the project again before using its files or commands.",
                                    details={"project_id": project_id},
                                )
                            self._require_open()
                            settled = await owner.initialize_project(setup_db)
                        except AppException as error:
                            raise PermissionError(error.message) from error
                    if settled is not None:
                        settled()
                    owner._project_initialized = True
                    self._require_open()
        async with get_db_context() as db:
            try:
                ctx, project = await self._project(db, project_id)
                self._require_open()
                if self.project_generation != project.workspace_generation:
                    raise ConcurrentChangeError(
                        message="This project workspace changed. Select the project again before using its files or commands.",
                        details={"project_id": project_id},
                    )
                service = SandboxWorkspaceService(db)
                opened = await service.open_project(ctx, project)
                if opened.row_id is not None:
                    self.origins[opened.row_id] = {
                        "kind": "project",
                        "workspace_id": str(opened.row_id),
                        "project_id": str(project.id),
                    }
            except AppException as error:
                raise PermissionError(error.message) from error
            try:
                self._require_open()
                yield opened.workspace
            finally:
                failure = await service.close(opened)
                if failure is not None:
                    raise WorkspaceUnavailableError(failure.error.message)

    def _require_pinned_context(
        self, project_id: UUID | None, execution_target: Literal["agent", "project"]
    ) -> None:
        if self.execution_target_pin is not None and execution_target != self.execution_target_pin:
            raise AuthorizationError(
                message="The user explicitly selected this run's executor. Start a new turn to change it; project context cannot override that choice.",
                details={},
            )
        if self.delegation_context_pinned and (
            project_id != self.project_id or execution_target != self.execution_target
        ):
            raise AuthorizationError(
                message="Delegated work has pinned this run's project context and executor. Finish it and start a new turn to change targets; approval and question continuations keep the original target.",
                details={},
            )

    async def select(self, project_id: UUID | None) -> str:
        self._require_open()
        self._require_pinned_context(
            project_id, "agent" if project_id is None else self.execution_target
        )
        if project_id is None:
            self.project_id = None
            self.project_generation = None
            self.execution_target = "agent"
            return "Cleared the project context and restored agent execution. The conversation has not moved."
        if self.execution_target == "project" and self.project_id != project_id:
            raise AuthorizationError(
                message="Clear project context or choose agent execution before selecting another project, then explicitly choose the new project executor if needed.",
                details={},
            )
        # Selection itself opens no container. Each later operation resolves the
        # current generation, membership and grant again before attaching.
        async with get_db_context() as db:
            _, project = await self._project(db, project_id)
            name, backend = project.name, project.backend
            generation = project.workspace_generation
            description, instructions = project.description, project.instructions
        self._require_open()
        self._require_pinned_context(project_id, self.execution_target)
        if self.delegation_context_pinned and generation != self.project_generation:
            raise ConcurrentChangeError(
                message="The delegated workspace generation changed. Restart this run before selecting it again.",
                details={},
            )
        self.project_id = project_id
        self.project_generation = generation
        self.project_context_observed = True
        return json.dumps(
            {
                "kind": "project_workspace_selection",
                "project_id": str(project_id),
                "name": name,
                "backend": backend,
                "workspace_generation": str(generation),
                "description": description,
                "instructions": instructions,
                "instructions_usage": "Project reference guidance applies within the agent and platform rules; it grants no additional tools or resource access.",
                "execution_target": self.execution_target,
                "project_execution_available": backend == "service"
                and self.allow_project_execution
                and self.shell_tools_enabled,
                "agent_execution_available": self.agent_execution_available
                and not (
                    self.project_context_observed and self.original_scope in ("agent", "channel")
                ),
                "message": "Explicit project file tools use this project. Generic file tools and commands keep the selected executor. No files were copied or mounted; transfer selected files explicitly when another executor needs them.",
            }
        )

    async def search(self, query: str, limit: int = 10) -> str:
        """Search only projects this run may disclose and select, without opening a runtime."""
        from app.services.project import ProjectService

        self._require_open()
        if not self.audience.private or self.audience.shared_transcript:
            raise AuthorizationError(
                message="Search projects in a private conversation; this audience has no project discovery grant.",
                details={},
            )
        async with get_db_context() as db:
            ctx = await self._actor(db)
            page = await ProjectService(db).list_projects(ctx, search=query, limit=limit)
            items: list[dict[str, str | bool | None]] = []
            for item in page.items:
                try:
                    _, project = await self._project(db, item.id)
                except AuthorizationError, NotFoundError:
                    continue
                items.append(
                    {
                        "id": str(project.id),
                        "name": project.name,
                        "description": project.description,
                        "backend": project.backend,
                    }
                )
        return json.dumps(
            {
                "items": items,
                "page_limit": limit,
                "message": "Select a returned project ID; project names alone do not grant access. If not found, refine the search.",
            }
        )

    def initialize(
        self, project: Project, *, execution_target: Literal["agent", "project"]
    ) -> None:
        """Initialize from the runner's already authorized conversation project, without I/O."""
        if project.id != self.conversation_project_id:
            raise ValueError("The initial project must be the admitted conversation project")
        self.project_id = project.id
        self.project_generation = project.workspace_generation
        self.execution_target = execution_target
        self.project_context_observed = True

    def restore(
        self,
        project_id: UUID | None,
        generation: UUID | None,
        execution_target: Literal["agent", "project"] | None,
        project_context_observed: bool = False,
        delegation_context_pinned: bool = False,
        require_fresh_reads: bool = False,
    ) -> None:
        """Restore server-owned checkpoint terms; authorization is checked on the next operation."""
        self.project_context_observed = (
            self.project_context_observed or project_context_observed or project_id is not None
        )
        self.delegation_context_pinned = self.delegation_context_pinned or delegation_context_pinned
        self._require_continuation_reads = self._require_continuation_reads or require_fresh_reads
        if execution_target is None:
            # Older parks recorded only the selector. Require reselection of such
            # a dynamic project before exposing a potentially moved workspace.
            if project_id is not None:
                self.project_id, self.project_generation = project_id, None
                self.execution_target = "project"
            return
        self.project_id, self.project_generation = project_id, generation
        self.execution_target = execution_target

    def _require_selection(self) -> UUID:
        if self.project_id is None:
            raise AuthorizationError(message="Select a project before using its files.", details={})
        return self.project_id

    @staticmethod
    async def _file_path(workspace: Workspace, path: str, *, create: bool = False) -> str:
        from app.services.project import project_path

        relative = project_path(path)
        paths = workspace.paths
        candidate = await workspace.resolve(relative)
        suffix: list[str] = []
        while True:
            try:
                resolved = await workspace.realpath(candidate)
                break
            except FileNotFoundError:
                if not create:
                    raise
                parent, leaf = paths.dirname(candidate), paths.basename(candidate)
                if parent == candidate:
                    raise
                suffix.insert(0, leaf)
                candidate = parent
        canonical = paths.join(resolved, *suffix)
        try:
            normalized = paths.relpath(canonical, await workspace.working_dir())
        except ValueError as error:
            raise BadRequestError(
                message="Choose a path inside the workspace.", details={}
            ) from error
        project_path(
            normalized.replace("\\", "/") if workspace.platform == "windows" else normalized
        )
        return relative

    async def files(self, path: str = ".") -> str:
        self._require_selection()
        async with self._open() as workspace:
            relative = "." if path in (".", "/", "") else await self._file_path(workspace, path)
            entries = await workspace.list_dir(relative)
            described: list[FileInfo] = [
                {
                    "name": entry.name,
                    "path": posixpath.join(relative, entry.name),
                    "is_dir": entry.is_dir,
                    "size": entry.size,
                }
                for entry in entries
            ]
            visible = browsable(described)
        return json.dumps(
            {
                "items": [
                    {
                        "name": str(entry["path"]).rsplit("/", 1)[-1],
                        "type": "directory" if entry.get("is_dir") else "file",
                        "size": entry.get("size"),
                    }
                    for entry in visible[:100]
                ],
                "truncated": len(visible) > 100,
                "namespace": "project",
            }
        )

    async def read_file(self, path: str) -> str:
        project_id = self._require_selection()
        async with self._open() as workspace:
            relative = await self._file_path(workspace, path)
            metadata = await workspace.stat(relative)
            if metadata.is_dir or metadata.size is None or metadata.size > 256_000:
                raise BadRequestError(
                    message="This file is not bounded text: it is a directory, has unknown size or exceeds 256 KB. Download or process it explicitly instead.",
                    details={"path": path},
                )
            data = await workspace.read_bytes(relative)
            if len(data) > 256_000:
                raise BadRequestError(
                    message="This file grew beyond the text tool's limit. Read a smaller file instead.",
                    details={"path": path},
                )
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as error:
                raise BadRequestError(
                    message="This file is not UTF-8 text. Use an explicitly configured document or binary workflow; no OCR was started.",
                    details={"path": path},
                ) from error
            self._read_versions[(project_id, await self._version_path(workspace, relative))] = (
                sha256(data).digest()
            )
        return json.dumps(
            {
                "path": relative,
                "namespace": "project",
                "content": text,
                "bytes": len(data),
                "sha256": sha256(data).hexdigest(),
            }
        )

    async def write_file(self, path: str, content: str) -> str:
        project_id = self._require_selection()
        if "projects:write" not in self.granted_scopes:
            raise AuthorizationError(
                message="Project writes are disabled for this run.", details={}
            )
        data = content.encode("utf-8")
        if len(data) > 256_000:
            raise BadRequestError(
                message="The text is too large for this tool; write a smaller file.",
                details={"path": path},
            )
        async with self._open() as workspace:
            relative = await self._file_path(workspace, path, create=True)
            await self._refuse_changed(workspace, relative)
            await workspace.write_bytes(relative, data)
            self._read_versions[(project_id, await self._version_path(workspace, relative))] = (
                sha256(data).digest()
            )
        return json.dumps({"path": relative, "namespace": "project", "saved": True})

    async def select_execution(self, target: Literal["agent", "project"]) -> str:
        """Select a command target without moving or copying files."""
        self._require_open()
        self._require_pinned_context(self.project_id, target)
        if not self.shell_tools_enabled:
            raise AuthorizationError(
                message="This agent has no enabled Sandbox command tools.", details={}
            )
        if target == "agent":
            if self.project_context_observed and self.original_scope in ("agent", "channel"):
                raise AuthorizationError(
                    message="This agent executor is shared with a wider audience. Use an isolated agent workspace or the project's executor.",
                    details={},
                )
            if not self.agent_execution_available:
                raise AuthorizationError(
                    message="This agent has no command execution workspace.", details={}
                )
        else:
            if not self.allow_project_execution:
                raise AuthorizationError(
                    message="Local computer access is active. Keep agent execution or start a server-only turn before choosing the project executor.",
                    details={},
                )
            if self.project_id is None:
                raise AuthorizationError(
                    message="Select a project before choosing its executor.", details={}
                )
            async with get_db_context() as db:
                _, project = await self._project(db, self.project_id)
                if project.backend != "service":
                    raise AuthorizationError(
                        message="This project stores files only and cannot execute commands.",
                        details={},
                    )
                if self.project_generation != project.workspace_generation:
                    raise ConcurrentChangeError(
                        message="Select this project again after its workspace changed.", details={}
                    )
        self._require_open()
        self._require_pinned_context(self.project_id, target)
        self.execution_target = target
        return json.dumps(
            {
                "execution_target": target,
                "message": "Commands and generic file tools use this executor. Explicit project tools still use the project. No files were copied or mounted.",
            }
        )

    @asynccontextmanager
    async def _open_files(self) -> AsyncGenerator[Workspace]:
        """Generic files and commands share one executor; project tools stay explicit."""
        self._require_open()
        if self.execution_target == "project":
            async with self._open() as workspace:
                yield workspace
            return
        async with self._open_agent_files() as workspace:
            yield workspace

    @asynccontextmanager
    async def _open_agent_files(self) -> AsyncGenerator[Workspace]:
        """Agent files retain current selected-project authority without changing targets."""
        self._require_open()
        if self.project_id is not None:
            async with get_db_context() as db:
                try:
                    _, project = await self._project(db, self.project_id)
                    if project.workspace_generation != self.project_generation:
                        raise ConcurrentChangeError(
                            message="Select this project again after its workspace changed.",
                            details={},
                        )
                except AppException as error:
                    raise PermissionError(error.message) from error
        async with self._open_agent() as workspace:
            yield workspace

    @staticmethod
    async def _overflow_path(workspace: Workspace, path: str, *, create: bool = False) -> str:
        """Only the reserved spill tree, including canonical parents of new files."""
        from app.agents.capabilities.tool_output_limits import OVERFLOW_PREFIX

        paths = workspace.paths
        root = await workspace.working_dir()
        candidate = await workspace.resolve(path)
        current = candidate
        suffix: list[str] = []
        while True:
            try:
                canonical = paths.join(await workspace.realpath(current), *suffix)
                break
            except FileNotFoundError:
                if not create:
                    raise
                parent, leaf = paths.dirname(current), paths.basename(current)
                if parent == current:
                    raise
                suffix.insert(0, leaf)
                current = parent
        for absolute in (candidate, canonical):
            try:
                relative = paths.relpath(absolute, root).replace("\\", "/")
            except ValueError as error:
                raise FileNotFoundError("Unknown tool output handle") from error
            if not relative.startswith(f"{OVERFLOW_PREFIX}/"):
                raise FileNotFoundError("Unknown tool output handle")
        return candidate

    async def write_overflow(self, path: str, data: bytes, *, spill_log: list[str] | None) -> str:
        """Spill to Agent regardless of the currently selected command target."""
        async with self._open_agent_files() as workspace:
            handle = await self._overflow_path(workspace, path, create=True)
            self._require_open()
            await workspace.write_bytes(handle, data)
            opened = self._lifecycle_owner.agent_workspace
            journal = spill_log if opened is None else opened.spills
            if journal is not None:
                journal.append(handle)
            return handle

    async def read_overflow(self, handle: str) -> bytes:
        """Read a spill from its stable Agent origin, never the current Project target."""
        async with self._open_agent_files() as workspace:
            selected = await self._overflow_path(workspace, handle)
            self._require_open()
            return await workspace.read_bytes(selected)

    @staticmethod
    async def _transfer_bytes(workspace: Workspace, path: str) -> bytes:
        metadata = await workspace.stat(path)
        if metadata.is_dir or metadata.size is None or not 0 <= metadata.size <= MAX_TRANSFER_BYTES:
            raise BadRequestError(
                message="Transfer one file of known size, at most 8 MiB.", details={}
            )
        data = await workspace.read_bytes(path)
        if len(data) > MAX_TRANSFER_BYTES:
            raise BadRequestError(
                message="The file grew beyond the 8 MiB transfer limit.", details={}
            )
        return data

    async def transfer_file(
        self,
        direction: Literal["to_agent", "from_agent"],
        project_path: str,
        agent_path: str,
        expected_sha256: str | None = None,
    ) -> str:
        """Transfer selected bytes directly, without model text or implicit writeback.

        An existing destination requires its current digest. This detects an
        observed conflict; arbitrary shell writes are not transactionally locked.
        Paths are relative to their workspace roots and confined after resolving
        existing symlinks. The executor choice is unchanged.
        """
        selected = self._require_selection()
        generation = self.project_generation
        if expected_sha256 is not None and (
            len(expected_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha256)
        ):
            raise BadRequestError(
                message="The destination digest must be a SHA-256 hex digest.", details={}
            )
        if direction == "from_agent" and "projects:write" not in self.granted_scopes:
            raise AuthorizationError(
                message="Project writes are disabled for this run.", details={}
            )
        async with self._open() as project, self._open_agent() as agent:
            project_file = await self._file_path(
                project, project_path, create=direction == "from_agent"
            )
            if posixpath.isabs(agent_path) or "\\" in agent_path or ":" in agent_path:
                raise BadRequestError(
                    message="Choose a relative agent path inside its workspace.", details={}
                )
            agent_file = await self._file_path(agent, agent_path, create=direction == "to_agent")
            source, source_path, destination, destination_path = (
                (project, project_file, agent, agent_file)
                if direction == "to_agent"
                else (agent, agent_file, project, project_file)
            )
            data = await self._transfer_bytes(source, source_path)
            present = await destination.exists(destination_path)
            if present:
                if expected_sha256 is None:
                    raise ConcurrentChangeError(
                        message="The destination exists. Read its current SHA-256 before replacing it.",
                        details={},
                    )
                current = await self._transfer_bytes(destination, destination_path)
                if sha256(current).hexdigest() != expected_sha256:
                    raise ConcurrentChangeError(
                        message="The destination changed; no file was replaced.", details={}
                    )
            elif expected_sha256 is not None:
                raise ConcurrentChangeError(
                    message="The expected destination no longer exists.", details={}
                )
            if direction == "from_agent":
                await self._refuse_changed(project, project_file)
            imported = await self._imported_path_spellings(destination, destination_path)
            self._require_open()
            if self.project_id != selected or self.project_generation != generation:
                raise ConcurrentChangeError(
                    message="Project selection changed during transfer. Retry with the current project.",
                    details={},
                )
            self._lifecycle_owner.imported_paths[
                "agent" if direction == "to_agent" else "project"
            ].update(imported)
            await destination.write_bytes(destination_path, data)
            digest = sha256(data).hexdigest()
            if (
                sha256(await self._transfer_bytes(destination, destination_path)).hexdigest()
                != digest
            ):
                raise ConcurrentChangeError(
                    message="The destination changed while verifying the transfer.", details={}
                )
            self._read_versions[(selected, await self._version_path(project, project_file))] = (
                sha256(data).digest()
            )
            actual_agent_path = await agent.resolve(agent_file)
        return json.dumps(
            {
                "direction": direction,
                "project_id": str(selected),
                "project_path": project_file,
                "agent_path": agent_file,
                "agent_absolute_path": actual_agent_path,
                "bytes": len(data),
                "sha256": digest,
                "message": "Transferred the selected file bytes. This is not a shared mount; later edits are not synchronized.",
            }
        )

    @staticmethod
    async def _imported_path_spellings(workspace: Workspace, path: str) -> set[str]:
        absolute = await workspace.resolve(path)
        canonical = await RunProjectWorkspace._version_path(workspace, path)
        root = await workspace.working_dir()
        paths = workspace.paths
        relative = paths.relpath(canonical, root)
        return {path, absolute, canonical, relative, paths.join(".", relative)}

    def outbound_baseline(
        self, kind: Literal["agent", "project"], before: set[str] | None
    ) -> set[str] | None:
        """Imports are inputs, not newly authored automatic attachments."""
        return None if before is None else before | self._lifecycle_owner.imported_paths[kind]

    async def working_dir(self) -> str:
        async with self._open_files() as workspace:
            return await workspace.working_dir()

    async def read_bytes(self, path: str) -> bytes:
        async with self._open_files() as workspace:
            data = await workspace.read_bytes(path)
            if self.project_id is not None and self.execution_target == "project":
                self._read_versions[
                    (self.project_id, await self._version_path(workspace, path))
                ] = sha256(data).digest()
            return data

    @staticmethod
    async def _version_path(workspace: Workspace, path: str) -> str:
        try:
            return await workspace.realpath(path)
        except FileNotFoundError:
            return await workspace.resolve(path)

    async def _refuse_changed(self, workspace: Workspace, path: str) -> None:
        project_id = self._require_selection()
        previous = self._read_versions.get((project_id, await self._version_path(workspace, path)))
        if previous is None:
            if self._require_continuation_reads and await workspace.exists(path):
                raise WorkspaceUnavailableError(
                    "Read the current project file again after continuation before changing it."
                )
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
        if self.execution_target == "project" and "projects:write" not in self.granted_scopes:
            raise PermissionError("Project writes are disabled for this run.")
        async with self._open_files() as workspace:
            if self.execution_target == "project":
                await self._refuse_changed(workspace, path)
            await workspace.write_bytes(path, data)
            if self.project_id is not None and self.execution_target == "project":
                self._read_versions[
                    (self.project_id, await self._version_path(workspace, path))
                ] = sha256(data).digest()

    async def stat(self, path: str) -> FileEntry:
        async with self._open_files() as workspace:
            return await workspace.stat(path)

    async def list_dir(self, path: str) -> Sequence[FileEntry]:
        async with self._open_files() as workspace:
            return await workspace.list_dir(path)

    async def make_dir(self, path: str) -> None:
        if self.execution_target == "project" and "projects:write" not in self.granted_scopes:
            raise PermissionError("Project writes are disabled for this run.")
        async with self._open_files() as workspace:
            await workspace.make_dir(path)

    async def remove(self, path: str) -> None:
        if self.execution_target == "project" and "projects:write" not in self.granted_scopes:
            raise PermissionError("Project writes are disabled for this run.")
        async with self._open_files() as workspace:
            if self.execution_target == "project":
                await self._refuse_changed(workspace, path)
            version_path = await self._version_path(workspace, path)
            await workspace.remove(path)
            if self.project_id is not None and self.execution_target == "project":
                self._read_versions.pop((self.project_id, version_path), None)

    async def exists(self, path: str) -> bool:
        async with self._open_files() as workspace:
            return await workspace.exists(path)

    async def realpath(self, path: str) -> str:
        async with self._open_files() as workspace:
            return await workspace.realpath(path)

    @asynccontextmanager
    async def _open_agent(self) -> AsyncGenerator[Workspace]:
        self._require_open()
        if self.project_context_observed and self.original_scope in ("agent", "channel"):
            raise WorkspaceUnavailableError(
                "This agent workspace is shared with a wider audience. Use an isolated agent workspace or the project's executor."
            )
        if self.open_agent_executor is None:
            if self.original is None:
                raise WorkspaceUnavailableError(
                    "This agent has no workspace. Select a project for file work."
                )
            yield self.original
            return
        async with self._agent_initialization:
            created = self.agent_workspace is None
            async with get_db_context() as db:
                actor = await self._actor(
                    db, project_scope=False, admitted=self.conversation_project_id is not None
                )
                self._require_open()
                opened = self.agent_workspace
                if opened is None:
                    opened = await self.open_agent_executor(db, actor)
                    if opened is None:
                        raise WorkspaceUnavailableError(
                            "This agent has no workspace. Project files do not grant an executor."
                        )
                    if self._lifecycle_owner._closed:
                        failure = await SandboxWorkspaceService(db).close(opened)
                        if failure is not None:
                            raise WorkspaceUnavailableError(failure.error.message)
                        self._require_open()
                    self.agent_workspace = opened
                    if opened.row_id is not None:
                        self.origins[opened.row_id] = {
                            "kind": "agent",
                            "workspace_id": str(opened.row_id),
                        }
            if created:
                self.agent_workspace_at_start = await workspace_snapshot(opened.workspace)
        self._require_open()
        yield opened.workspace

    def stop_admission(self) -> None:
        """Fence subsequent delegated operations before the root scans or closes providers."""
        self._lifecycle_owner._closed = True

    async def close_agent(self, *, keep_spills: bool) -> WorkspaceFlushFailure | None:
        """The runner closes the independent executor only after collecting its output."""
        self.stop_admission()
        opened, self.agent_workspace = self.agent_workspace, None
        if opened is None:
            return None
        async with get_db_context() as db:
            return await SandboxWorkspaceService(db).close(opened, keep_spills=keep_spills)

    async def run(
        self,
        command: WorkspaceCommand,
        *,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        if self.execution_target == "agent":
            if not self.agent_execution_available:
                raise WorkspaceUnavailableError(
                    "The agent workspace stores files only or is unavailable; select a command-capable project explicitly."
                )
            if self.project_id is not None:
                async with get_db_context() as db:
                    try:
                        _, project = await self._project(db, self.project_id)
                        if self.project_generation != project.workspace_generation:
                            raise ConcurrentChangeError(
                                message="Select this project again after its workspace changed.",
                                details={},
                            )
                    except AppException as error:
                        raise PermissionError(error.message) from error
            async with self._open_agent() as workspace:
                return await workspace.run(command, shell=shell, env=env, timeout=timeout, cwd=cwd)
        if self.project_id is None:
            raise WorkspaceUnavailableError("Select a project before executing commands there.")
        async with self._open() as workspace:
            if not isinstance(workspace.backend, SupportsCommands):
                raise WorkspaceUnavailableError(
                    "This project stores files only and cannot run shell commands."
                )
            return await workspace.run(command, shell=shell, env=env, timeout=timeout, cwd=cwd)


class _UnavailableWorkspace:
    """An absent agent workspace is a refusal, never an empty substitute file store."""

    @property
    def ref(self) -> WorkspaceRef | None:
        return None

    async def working_dir(self) -> str:
        raise WorkspaceUnavailableError(
            "This agent has no workspace. Select an accessible project to work on its files."
        )
