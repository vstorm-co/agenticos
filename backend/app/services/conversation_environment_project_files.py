"""Authorize a retained desktop's separate, immutable Project filesystem path.

A filesystem request never keeps the environment alive. Its current environment
expiry, published binding and private executor are checked on every operation.
"""

from collections.abc import Mapping
from uuid import UUID

from pydantic_ai.workspaces import CommandResult, Workspace, WorkspaceCommand
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.audience import RunAudience
from app.agents.capabilities.computer_use import COMPUTER_USE_ID, ComputerUseConfig
from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    ExternalServiceError,
)
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, StorableSecret
from app.db.models.conversation_environment import ConversationEnvironment
from app.db.models.project import Project
from app.db.models.project_filesystem import ProjectFilesystemBinding, ProjectFilesystemLease
from app.repositories import agent_workspace as workspaces
from app.repositories import conversation_environment as environments
from app.schemas.project_filesystem import FsFailure
from app.schemas.project_filesystem_authority import ProjectFilesystemAuthority
from app.services.agent_registry import DEFAULT_GRANTED_SCOPES
from app.services.conversation_environment_policy import (
    DesktopEnvironmentSettings,
    EnvironmentNotReady,
)
from app.services.conversation_environment_resources import DesktopEnvironmentResource
from app.services.conversation_environments import ConversationEnvironmentService
from app.services.project_filesystem import ProjectFilesystemService
from app.services.run_project_workspace import ProjectRunAuthority
from app.services.sandbox_workspace import SandboxWorkspaceService, sandbox_config
from app.worker.jobs import ConversationEnvironmentPayload


async def starting(
    db: AsyncSession,
    *,
    binding: ProjectFilesystemBinding,
    payload: ConversationEnvironmentPayload,
    attempt: int,
    project_id: UUID,
    generation: UUID | None,
) -> tuple[ConversationEnvironment, ProjectFilesystemAuthority]:
    """Admit a path before GUI startup, without admitting any filesystem RPC yet."""
    service = ConversationEnvironmentService(db)
    configured = await service.claim(payload, attempt)
    row = await environments.for_worker(db, payload.environment_id)
    if not isinstance(configured, DesktopEnvironmentSettings) or row is None:
        raise AuthorizationError(message="The desktop Project mount admission expired")
    resource = service.resource(row, binding.organization_id)
    if not isinstance(resource, DesktopEnvironmentResource):
        raise AuthorizationError(message="This environment has no desktop workspace")
    await _workspace(db, binding, configured, resource, ready=False)
    authority = _authority(configured, project_id)
    await _project(db, authority, project_id, generation)
    if "projects:write" in authority.granted_scopes:
        support = await ProjectFilesystemService(db).exclusive_create_support(
            authority.actor, project_id, generation, writable=True
        )
        if isinstance(support, FsFailure):
            raise ExternalServiceError(
                message="The desktop Project filesystem cannot support a live writable mount",
                details={"errno": support.errno, "reason": support.message},
            )
    return row, authority


async def authorize(
    db: AsyncSession,
    binding: ProjectFilesystemBinding,
    lease: ProjectFilesystemLease,
    authority: ProjectFilesystemAuthority,
) -> tuple[AuthContext, Project, ProjectFilesystemAuthority]:
    """Fresh READY authority; old run status cannot revive or revoke this path."""
    if lease.environment_id is None or binding.conversation_id is None:
        raise AuthorizationError(message="The desktop Project mount has no owned environment")
    try:
        _, configured, resource = await ConversationEnvironmentService(db).live(
            authority.actor, binding.conversation_id, lease.environment_id, "agent"
        )
    except EnvironmentNotReady as exc:
        raise AuthorizationError(
            message="The desktop Project environment is no longer live"
        ) from exc
    if (
        not isinstance(configured, DesktopEnvironmentSettings)
        or not isinstance(resource, DesktopEnvironmentResource)
        or resource.project_lease_id != lease.id
    ):
        raise AuthorizationError(message="The desktop Project mount identity changed")
    await _workspace(db, binding, configured, resource, ready=True)
    current = _authority(configured, lease.project_id)
    # Role changes are reauthorized below rather than trusting stored role.
    if current.model_copy(update={"actor": authority.actor}) != authority:
        raise AuthorizationError(message="The desktop Project admission changed")
    actor, project = await _project(db, current, lease.project_id, lease.workspace_generation)
    return actor, project, current


def _authority(
    configured: DesktopEnvironmentSettings, project_id: UUID
) -> ProjectFilesystemAuthority:
    owner = configured.authority
    if owner.ctx.user_id is None or owner.conversation.project_id != project_id:
        raise AuthorizationError(message="The desktop has no matching owned Project")
    return ProjectFilesystemAuthority(
        actor=owner.ctx,
        audience=RunAudience(user_id=owner.ctx.user_id, shared_transcript=True),
        granted_scopes=DEFAULT_GRANTED_SCOPES & frozenset({"projects:read", "projects:write"}),
        conversation_id=owner.conversation.id,
        conversation_project_id=project_id,
    )


async def _project(
    db: AsyncSession,
    authority: ProjectFilesystemAuthority,
    project_id: UUID,
    generation: UUID | None,
) -> tuple[AuthContext, Project]:
    actor, project = await ProjectRunAuthority(
        ctx=authority.actor,
        audience=authority.audience,
        granted_scopes=authority.granted_scopes,
        conversation_project_id=authority.conversation_project_id,
    ).project(db, project_id)
    if project.workspace_generation != generation:
        raise ConcurrentChangeError(message="The desktop Project filesystem generation changed")
    return actor, project


async def _workspace(
    db: AsyncSession,
    binding: ProjectFilesystemBinding,
    configured: DesktopEnvironmentSettings,
    resource: DesktopEnvironmentResource,
    *,
    ready: bool,
) -> None:
    owner = configured.authority
    sandbox = sandbox_config(owner.spec)
    if (
        binding.revoked_at is not None
        or owner.execution_target != "agent"
        or owner.ctx.organization_id != binding.organization_id
        or owner.conversation.id != binding.conversation_id
        or owner.conversation.user_id != owner.ctx.user_id
        or resource.organization_id != binding.organization_id
        or resource.backend != "sandbox"
        or resource.workspace_id != binding.workspace_id
        or resource.connection_id != binding.connection_id
        or resource.connection_fingerprint is None
        or sandbox is None
        or sandbox.backend != "service"
        or sandbox.session_scope != "conversation"
        or configured.config.desktop not in ("sandbox", "auto")
        or (configured.config.desktop == "auto" and bool(configured.credential))
    ):
        raise AuthorizationError(message="Project mounts need this private conversation desktop")
    workspace = (
        await workspaces.get(db, binding.workspace_id, organization_id=binding.organization_id)
        if binding.workspace_id is not None
        else None
    )
    service = SandboxWorkspaceService(db)
    try:
        connection = await service.connections.resolve(
            owner.ctx, binding.connection_id, ensure_default=False
        )
    except BadRequestError as exc:
        raise AuthorizationError(message="The desktop Project connection is unavailable") from exc
    if (
        workspace is None
        or workspace.backend != "service"
        or workspace.scope != "conversation"
        or workspace.conversation_id != owner.conversation.id
        or workspace.agent_id != owner.agent.id
        or workspace.connection_id != binding.connection_id
        or workspace.scope_key != binding.session_name
        or (
            ready
            and (
                resource.workspace_ref is None or workspace.session_id != resource.workspace_ref.id
            )
        )
        or service.environment_connection_fingerprint(connection) != resource.connection_fingerprint
        or not await service.connections.supports_project_filesystem(connection)
    ):
        raise AuthorizationError(message="The original desktop Project executor changed")


async def directory(
    db: AsyncSession,
    *,
    ctx: AuthContext,
    environment_id: UUID,
    binding_id: UUID,
    project_id: UUID,
    generation: UUID | None,
) -> str:
    """Return the READY GUI path for exactly this run's selected Project."""
    from app.repositories import project_filesystem_bindings as bindings
    from app.services.project_filesystem_gateway import ProjectFilesystemGateway

    binding = await bindings.binding_by_id(db, binding_id)
    lease = await bindings.environment_lease(
        db, binding_id=binding_id, environment_id=environment_id
    )
    if (
        binding is None
        or lease is None
        or binding.organization_id != ctx.organization_id
        or lease.actor_id != ctx.user_id
        or lease.project_id != project_id
        or lease.workspace_generation != generation
    ):
        raise AuthorizationError(message="The retained desktop uses a different Project mount")
    await ProjectFilesystemGateway(db).authorize(binding, lease)
    return f"/project/{lease.id}"


class ProjectDesktopWorkspace(Workspace):
    """Preserve the same Project path in GUI startup and later app launches."""

    def __init__(self, workspace: Workspace, lease_id: UUID) -> None:
        super().__init__(workspace)
        self.wrapped = workspace
        self.project_directory = f"/project/{lease_id}"

    async def run(
        self,
        command: WorkspaceCommand,
        *,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        environment = dict(env or {})
        environment["PROJECT_DIR"] = self.project_directory
        return await self.wrapped.run(
            command, shell=shell, env=environment, timeout=timeout, cwd=cwd
        )


async def prepare(
    configured: DesktopEnvironmentSettings,
    resource: DesktopEnvironmentResource,
    *,
    binding_id: UUID | None,
    scope: str,
    payload: ConversationEnvironmentPayload,
    attempt: int,
) -> UUID | None:
    """Issue before GUI startup, without opening a second workspace or fake run."""
    project = configured.authority.project
    if binding_id is None or scope != "conversation" or project is None:
        return None
    from app.db.session import get_worker_db_context
    from app.services.project_filesystem_bindings import ProjectFilesystemBindingService

    async with get_worker_db_context() as db:
        lease = await ProjectFilesystemBindingService(db).issue_environment_lease(
            binding_id=binding_id,
            payload=payload,
            attempt=attempt,
            project_id=project.id,
            generation=project.workspace_generation,
        )
    resource.project_lease_id = lease.id
    return lease.id


def retained_project_mount(spec: AgentSpec, secrets: Mapping[UUID, StorableSecret]) -> bool:
    """Select only private-conversation sandbox GUI retention, without provider I/O."""
    sandbox = sandbox_config(spec)
    binding = next(
        (item for item in spec.capabilities if item.id == COMPUTER_USE_ID and item.enabled), None
    )
    if (
        sandbox is None
        or sandbox.backend != "service"
        or sandbox.session_scope != "conversation"
        or binding is None
    ):
        return False
    config = ComputerUseConfig.model_validate(binding.config)
    secret = secrets.get(binding.secret_id) if binding.secret_id is not None else None
    return config.session_lifetime == "conversation" and (
        config.desktop == "sandbox"
        or (
            config.desktop == "auto"
            and not (isinstance(secret, ApiKeySecret) and secret.api_key.get_secret_value())
        )
    )
