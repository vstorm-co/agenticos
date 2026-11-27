"""The same published binding authority for idle and agent-owned environments."""

import hashlib
import json
from dataclasses import dataclass, field
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.browser_use import (
    BROWSER_CAPABILITY_ID,
    WebBrowserConfig,
    cdp_endpoint,
    validate_cdp_url,
)
from app.agents.capabilities.browser_use._route import BrowserRoute, route_for
from app.agents.capabilities.computer_use import (
    COMPUTER_USE_ID,
    ComputerUseConfig,
    validate_daemon_url,
)
from app.agents.spec import AgentSpec
from app.core.config import settings
from app.core.exceptions import AuthenticationError, AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret
from app.db.models.agent import Agent
from app.db.models.conversation import Conversation
from app.db.models.project import Project
from app.repositories import member as member_repo
from app.repositories import user as user_repo
from app.schemas.conversation_environment import (
    ConversationEnvironmentKind,
    ConversationEnvironmentRefusal,
    ConversationEnvironmentRefusalCode,
)
from app.schemas.project_context import ProjectExecutionTarget
from app.services.agent_registry import AgentRegistryService
from app.services.conversation import ConversationService
from app.services.organization_secret import OrganizationSecretService
from app.services.project import ProjectService
from app.services.sandbox_connection import SandboxConnectionService
from app.services.sandbox_workspace import SandboxWorkspaceService, project_sandbox, sandbox_config


class EnvironmentNotReady(BadRequestError):
    """A configured environment cannot currently be opened, without hiding access failures."""

    def __init__(self, code: ConversationEnvironmentRefusalCode, message: str) -> None:
        super().__init__(message=message, details={"reason": code})
        self.refusal = ConversationEnvironmentRefusal(code=code, message=message)


@dataclass(frozen=True)
class EnvironmentAuthority:
    ctx: AuthContext
    conversation: Conversation
    agent: Agent
    version_id: UUID
    spec: AgentSpec
    execution_target: ProjectExecutionTarget
    project: Project | None
    producer_run_id: UUID | None = None


@dataclass(frozen=True)
class BrowserEnvironmentSettings:
    authority: EnvironmentAuthority
    config: WebBrowserConfig
    fingerprint: str
    cdp_url: str = field(repr=False)
    route: BrowserRoute | None = field(repr=False)


@dataclass(frozen=True)
class DesktopEnvironmentSettings:
    authority: EnvironmentAuthority
    config: ComputerUseConfig
    fingerprint: str
    credential: str = field(repr=False)


type EnvironmentSettings = BrowserEnvironmentSettings | DesktopEnvironmentSettings


async def current_actor(db: AsyncSession, organization_id: UUID, user_id: UUID) -> AuthContext:
    """Re-establish the signed-in owner; an API key never inherits their manual session."""
    member = await member_repo.get_active(db, organization_id=organization_id, user_id=user_id)
    user = await user_repo.get_by_id(db, user_id)
    if member is None or user is None or not user.is_active:
        raise AuthenticationError(message="The environment owner no longer has access")
    return AuthContext(
        user_id=user_id,
        organization_id=organization_id,
        role=member.role,
        is_app_admin=user.is_app_admin,
    )


async def authority(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    conversation_id: UUID,
    agent_id: UUID,
    execution_target: ProjectExecutionTarget = "agent",
) -> EnvironmentAuthority:
    if ctx.user_id is None or ctx.api_key_id is not None or ctx.subject_is_publisher_fallback:
        raise AuthorizationError(message="A manual environment belongs to a signed-in person")
    ctx = await current_actor(db, ctx.organization_id, ctx.user_id)
    conversation = await ConversationService(db).get_conversation(
        conversation_id,
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        for_write=True,
        turn=True,
        include_favourite=False,
        ctx=ctx,
    )
    if conversation.user_id != ctx.user_id:
        raise AuthorizationError(
            message="Only the conversation owner can open its private environment"
        )
    try:
        agent, spec, version_id = await AgentRegistryService(db).get_runnable_spec(ctx, agent_id)
    except BadRequestError as exc:
        raise EnvironmentNotReady(
            "capability_not_enabled",
            "Choose an available published agent before opening its environment.",
        ) from exc
    except ValidationError as exc:
        raise EnvironmentNotReady(
            "connection_unavailable", "Republish this agent with valid environment settings."
        ) from exc
    project = await ProjectService(db).for_run(ctx, conversation_id)
    if execution_target == "project" and (project is None or project.backend != "service"):
        raise EnvironmentNotReady(
            "workspace_unavailable",
            "Choose a project with a configured executor before opening its desktop.",
        )
    return EnvironmentAuthority(
        ctx=ctx,
        conversation=conversation,
        agent=agent,
        version_id=version_id,
        spec=spec,
        execution_target=execution_target,
        project=project,
    )


async def legacy_run_desktop(db: AsyncSession, admitted: EnvironmentAuthority) -> bool:
    """Keep ephemeral run/channel executors on their existing per-run tool factory."""
    sandbox = (
        project_sandbox(admitted.project)
        if admitted.execution_target == "project" and admitted.project is not None
        else sandbox_config(admitted.spec)
    )
    if sandbox is None or sandbox.session_scope not in ("run", "channel"):
        return False
    binding = next(
        (
            item
            for item in admitted.spec.capabilities
            if item.id == COMPUTER_USE_ID and item.enabled
        ),
        None,
    )
    if binding is None:
        return False
    try:
        config = ComputerUseConfig.model_validate(binding.config)
    except ValidationError as exc:
        raise EnvironmentNotReady(
            "connection_unavailable", "Check this agent's desktop settings."
        ) from exc
    if config.session_lifetime != "run" or config.desktop not in ("sandbox", "auto"):
        return False
    if config.desktop == "auto" and binding.secret_id is not None:
        secrets = await OrganizationSecretService(db).resolve_for_bindings(
            admitted.ctx, [binding.secret_id]
        )
        secret = secrets.get(binding.secret_id)
        if isinstance(secret, ApiKeySecret) and secret.api_key.get_secret_value():
            return False
    return True


async def settings_for(
    db: AsyncSession,
    admitted: EnvironmentAuthority,
    kind: ConversationEnvironmentKind,
) -> EnvironmentSettings:
    capability = BROWSER_CAPABILITY_ID if kind == "browser" else COMPUTER_USE_ID
    binding = next(
        (item for item in admitted.spec.capabilities if item.id == capability and item.enabled),
        None,
    )
    if binding is None:
        raise EnvironmentNotReady(
            "capability_not_enabled", "Enable this environment on the selected agent."
        )
    secrets = await OrganizationSecretService(db).resolve_for_bindings(
        admitted.ctx,
        [binding.secret_id] if binding.secret_id is not None else [],
    )
    secret = secrets.get(binding.secret_id) if binding.secret_id is not None else None
    credential = secret.api_key.get_secret_value() if isinstance(secret, ApiKeySecret) else ""
    sandbox = (
        project_sandbox(admitted.project)
        if kind == "desktop"
        and admitted.execution_target == "project"
        and admitted.project is not None
        else sandbox_config(admitted.spec)
        if kind == "desktop"
        else None
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "binding": binding.model_dump(mode="json"),
                "execution_target": admitted.execution_target,
                "credential": credential,
                "sandbox": sandbox.model_dump(mode="json") if sandbox is not None else None,
                "project_generation": str(admitted.project.workspace_generation)
                if admitted.project is not None
                else None,
                "project_id": str(admitted.conversation.project_id)
                if admitted.conversation.project_id
                else None,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    try:
        if kind == "browser":
            config = WebBrowserConfig.model_validate(binding.config)
            if config.connection == "local":
                raise EnvironmentNotReady(
                    "local_device_required", "Open this browser through your paired desktop app."
                )
            validate_cdp_url(config)
            route = route_for(
                connection=config.connection,
                proxy_url=config.proxy_url,
                hosted_url=config.hosted_url,
                hosted_key_param=config.hosted_key_param,
                timezone=config.timezone,
                locale=config.locale,
                credential=credential or None,
            )
            endpoint = cdp_endpoint(config)
            if (config.connection == "hosted" and not credential) or (
                not endpoint and (route is None or route.remote_url is None)
            ):
                raise EnvironmentNotReady(
                    "connection_unavailable",
                    "Configure this agent's browser connection and vault key.",
                )
            effective_proxy = (
                None
                if route is not None and route.remote_url is not None
                else route.proxy_server
                if route is not None and route.proxy_server is not None
                else settings.BROWSER_EGRESS_PROXY or None
            )
            fingerprint = hashlib.sha256(
                json.dumps(
                    {"binding": fingerprint, "endpoint": endpoint, "egress_proxy": effective_proxy},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            return BrowserEnvironmentSettings(admitted, config, fingerprint, endpoint, route)
        desktop = ComputerUseConfig.model_validate(binding.config)
        if desktop.desktop == "local":
            raise EnvironmentNotReady(
                "local_device_required", "Open this computer through your paired desktop app."
            )
        validate_daemon_url(desktop)
        if desktop.desktop in ("daemon", "e2b") and not credential:
            raise EnvironmentNotReady(
                "connection_unavailable", "Configure this agent's desktop connection and vault key."
            )
        if desktop.desktop == "sandbox" or (desktop.desktop == "auto" and not credential):
            if sandbox is None or sandbox.backend != "service":
                raise EnvironmentNotReady(
                    "workspace_unavailable",
                    "Configure a container-backed executor for this desktop.",
                )
            if sandbox.session_scope in ("run", "channel"):
                raise EnvironmentNotReady(
                    "backend_not_supported",
                    "Manual desktop preparation needs a conversation-, user-, agent- or project-scoped executor.",
                )
            try:
                connection = await SandboxConnectionService(db).resolve(
                    admitted.ctx, sandbox.connection_id, ensure_default=False
                )
            except BadRequestError as exc:
                raise EnvironmentNotReady(
                    "connection_unavailable", "The configured desktop executor is unavailable."
                ) from exc
            connection_fingerprint = SandboxWorkspaceService.environment_connection_fingerprint(
                connection
            )
            fingerprint = hashlib.sha256(
                f"{fingerprint}:{connection_fingerprint}".encode()
            ).hexdigest()
        return DesktopEnvironmentSettings(admitted, desktop, fingerprint, credential)
    except (ValidationError, ValueError) as exc:
        raise EnvironmentNotReady(
            "connection_unavailable",
            "Check this agent's environment settings and the deployment allowlist.",
        ) from exc
