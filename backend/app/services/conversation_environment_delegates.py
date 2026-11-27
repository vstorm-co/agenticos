"""Fence a delegate's actual physical desktop without adopting its parent's capability."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from uuid import UUID

from pydantic_ai.workspaces import Workspace
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.computer_use import ComputerUseConfig
from app.agents.capabilities.computer_use._backends import (
    Capture,
    Computer,
    ComputerFactory,
    ComputerFactoryDecorator,
    NativeAction,
    check_daemon_url,
)
from app.agents.capabilities.computer_use._desktop_apps import App
from app.agents.capabilities.sandbox import WorkspaceIdentity
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import ConflictError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, StorableSecret
from app.db.session import get_db_context
from app.repositories import agent as agents
from app.schemas.project_context import ProjectExecutionTarget
from app.services.agent_registry import AgentRegistryService
from app.services.conversation_environment_driver import EnvironmentDriver
from app.services.conversation_environment_policy import authority, require_environment_run
from app.services.conversation_environment_runtime import resource_key
from app.services.organization_secret import OrganizationSecretService
from app.services.run_project_workspace import RunProjectWorkspace
from app.services.sandbox_workspace import SandboxWorkspaceService

NESTED_DESKTOP_AUTHORITY = "nested_desktop_authority"


@dataclass(frozen=True)
class SharedDesktopWorkspace:
    connection_id: UUID
    scope_key: str
    connection_fingerprint: str
    execution_target: ProjectExecutionTarget = "agent"
    project_id: UUID | None = None


@dataclass(frozen=True)
class NestedDesktopAuthority:
    ctx: AuthContext
    agent_id: UUID
    version_id: UUID
    run_id: UUID
    conversation_id: UUID
    execution_target: ProjectExecutionTarget
    workspace: SharedDesktopWorkspace | None = None
    shares_workspace: bool = True

    def delegated(self, *, shares_workspace: bool) -> NestedDesktopAuthority:
        return self if shares_workspace else replace(self, workspace=None, shares_workspace=False)

    def for_child(
        self,
        spec: AgentSpec,
        secrets: Mapping[UUID, StorableSecret],
        *,
        agent_id: UUID,
        version_id: UUID | None,
    ) -> ComputerFactoryDecorator | None:
        binding = next(
            (item for item in spec.capabilities if item.id == "computer_use" and item.enabled),
            None,
        )
        if binding is None:
            return None
        config = ComputerUseConfig.model_validate(binding.config)
        credential = _credential(secrets.get(binding.secret_id) if binding.secret_id else None)
        if config.desktop == "daemon":
            key = resource_key("daemon", config.daemon_url.rstrip("/"))
        elif config.desktop == "sandbox" or (config.desktop == "auto" and not credential):
            if not self.shares_workspace:
                return None
            key = None
        else:
            return None
        child = _ChildDesktopFactory(
            self, binding, config, _digest(credential), agent_id, version_id, key
        )
        return ComputerFactoryDecorator(child.wrap)


def _credential(secret: StorableSecret | None) -> str:
    return secret.api_key.get_secret_value() if isinstance(secret, ApiKeySecret) else ""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class _PhysicalSelection:
    key: str
    execution_target: ProjectExecutionTarget
    project_id: UUID | None
    project_generation: UUID | None
    connection_fingerprint: str | None


@dataclass(frozen=True)
class _ChildDesktopFactory:
    parent: NestedDesktopAuthority
    binding: CapabilityBindingSpec
    config: ComputerUseConfig
    credential_fingerprint: str
    agent_id: UUID
    version_id: UUID | None
    daemon_key: str | None

    async def resolve(self, db: AsyncSession, workspace: Workspace) -> _PhysicalSelection:
        parent = self.parent
        routing = (
            workspace.desktop_selection()
            if isinstance(workspace, RunProjectWorkspace) and self.daemon_key is None
            else None
        )
        target = parent.execution_target if routing is None else routing.target
        admitted = await authority(
            db,
            parent.ctx,
            conversation_id=parent.conversation_id,
            agent_id=parent.agent_id,
            # Root run authority does not borrow the primary desktop binding.
            # Resolve the child's actual selected project executor separately.
            execution_target="agent",
        )
        if admitted.version_id != parent.version_id:
            raise ConflictError(message="The delegation's published authority changed")
        await require_environment_run(
            db,
            admitted.ctx,
            run_id=parent.run_id,
            conversation_id=parent.conversation_id,
            agent_id=parent.agent_id,
            version_id=parent.version_id,
        )
        if self.version_id is not None:
            await AgentRegistryService(db).get_runnable_spec(admitted.ctx, self.agent_id)
            pinned = await agents.get_version(
                db, self.version_id, organization_id=admitted.ctx.organization_id
            )
            if pinned is None or pinned.agent_id != self.agent_id:
                raise ConflictError(message="The delegated agent version is no longer available")
        secrets = await OrganizationSecretService(db).resolve_for_bindings(
            admitted.ctx, [] if self.binding.secret_id is None else [self.binding.secret_id]
        )
        credential = _credential(
            secrets.get(self.binding.secret_id) if self.binding.secret_id else None
        )
        if _digest(credential) != self.credential_fingerprint:
            raise ConflictError(message="The delegated desktop connection changed")
        if self.daemon_key is not None:
            check_daemon_url(self.config.daemon_url)
            return _PhysicalSelection(self.daemon_key, target, None, None, None)
        service = SandboxWorkspaceService(db)
        current = await service.resolve_live_execution(
            admitted.ctx,
            spec=admitted.spec,
            identity=WorkspaceIdentity(
                organization_id=admitted.ctx.organization_id,
                agent_id=parent.agent_id,
                run_id=parent.run_id,
                conversation_id=parent.conversation_id,
                user_id=str(admitted.ctx.user_id),
                project_id=admitted.conversation.project_id,
            ),
            execution_target=target,
            selected_project_id=None if routing is None else routing.project_id,
            selected_generation=None if routing is None else routing.project_generation,
        )
        fingerprint = service.environment_connection_fingerprint(current.resolved)
        shared = parent.workspace
        selected_project = (
            admitted.conversation.project_id if routing is None else routing.project_id
        )
        original_selected = (
            shared is not None
            and shared.execution_target == target
            and (target == "agent" or shared.project_id == selected_project)
        )
        if (
            original_selected
            and shared is not None
            and (
                current.key != shared.scope_key
                or current.resolved.row.id != shared.connection_id
                or fingerprint != shared.connection_fingerprint
            )
        ):
            raise ConflictError(message="The original shared desktop executor changed")
        if routing is not None and routing.opened is not None:
            opened = routing.opened
            if (
                opened.scope_key != current.key
                or opened.connection_id != current.resolved.row.id
                or opened.connection_fingerprint != fingerprint
            ):
                raise ConflictError(message="The shared desktop connection changed")
        return _PhysicalSelection(
            resource_key(
                "workspace", f"{parent.ctx.organization_id}:{current.resolved.row.id}:{current.key}"
            ),
            target,
            None if routing is None else routing.project_id,
            None if routing is None else routing.project_generation,
            fingerprint,
        )

    def wrap(self, factory: ComputerFactory) -> ComputerFactory:
        async def opened(workspace: Workspace) -> Computer:
            async with get_db_context() as db:
                selected = await self.resolve(db, workspace)

            async def check(db: AsyncSession) -> None:
                if await self.resolve(db, workspace) != selected:
                    raise ConflictError(message="The delegated desktop execution target changed")

            driver = EnvironmentDriver(selected.key, self.parent.ctx, "agent", check)
            try:
                await driver.acquire()
                computer = await factory(workspace)
            except BaseException as failure:
                await _release(driver, failure)
                raise
            return _FencedDelegateComputer(computer, driver)

        return opened


class _FencedDelegateComputer:
    """A legacy delegate view, never provenance for a parent's owned environment."""

    def __init__(self, wrapped: Computer, driver: EnvironmentDriver) -> None:
        self.wrapped, self.driver = wrapped, driver
        self.label = wrapped.label

    async def capture(self) -> Capture:
        await self.driver.require()
        return await self.wrapped.capture()

    async def perform(self, action: NativeAction) -> None:
        await self.driver.require()
        await self.wrapped.perform(action)

    async def apps(self) -> list[App]:
        await self.driver.require()
        return await self.wrapped.apps()

    async def close(self) -> None:
        try:
            await self.wrapped.close()
        except BaseException as failure:
            await _release(self.driver, failure)
            raise
        else:
            await _release(self.driver)


async def _release(driver: EnvironmentDriver, failure: BaseException | None = None) -> None:
    try:
        await driver.close()
    except BaseException as cleanup_failure:
        if failure is None:
            raise
        raise BaseExceptionGroup(
            "The delegated desktop failed and its driver could not be released",
            [failure, cleanup_failure],
        ) from None
