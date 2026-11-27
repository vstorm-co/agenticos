"""Retained Project mounts refuse mismatched ownership before filesystem/provider work."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.workspaces import CommandResult

from app.agents.capabilities.computer_use import ComputerUseConfig
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    ExternalServiceError,
)
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret
from app.db.models.agent import Agent
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.conversation import Conversation
from app.db.models.conversation_environment import ConversationEnvironment
from app.db.models.project import Project
from app.db.models.project_filesystem import ProjectFilesystemBinding, ProjectFilesystemLease
from app.schemas.project_filesystem import FsFailure, FsSuccess
from app.services import conversation_environment_project_files as module
from app.services.conversation_environment_policy import (
    DesktopEnvironmentSettings,
    EnvironmentAuthority,
    EnvironmentNotReady,
)
from app.services.conversation_environment_resources import (
    BrowserEnvironmentResource,
    DesktopEnvironmentResource,
)
from app.worker.jobs import ConversationEnvironmentPayload
from tests.workspaces import document_workspace

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def case(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    project = Project(id=uuid4(), organization_id=ctx.organization_id, workspace_generation=uuid4())
    conversation = Conversation(
        id=uuid4(), organization_id=ctx.organization_id, user_id=ctx.user_id, project_id=project.id
    )
    agent = Agent(id=uuid4(), organization_id=ctx.organization_id)
    spec = AgentSpec(
        name="Desktop",
        capabilities=[
            CapabilityBindingSpec(
                id="sandbox", config={"backend": "service", "session_scope": "conversation"}
            ),
            CapabilityBindingSpec(
                id="computer_use", config={"desktop": "sandbox", "session_lifetime": "conversation"}
            ),
        ],
    )
    configured = DesktopEnvironmentSettings(
        EnvironmentAuthority(ctx, conversation, agent, uuid4(), spec, "agent", project),
        ComputerUseConfig(desktop="sandbox", session_lifetime="conversation"),
        "environment-fingerprint",
        "",
    )
    binding = ProjectFilesystemBinding(
        id=uuid4(),
        organization_id=ctx.organization_id,
        connection_id=uuid4(),
        workspace_id=uuid4(),
        conversation_id=conversation.id,
        session_name="canonical-desktop",
    )
    workspace = AgentWorkspace(
        id=binding.workspace_id,
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        connection_id=binding.connection_id,
        conversation_id=conversation.id,
        scope="conversation",
        backend="service",
        scope_key=binding.session_name,
        session_id="provider-session",
    )
    row = ConversationEnvironment(
        id=uuid4(),
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        agent_id=agent.id,
        state="starting",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    lease = ProjectFilesystemLease(
        id=uuid4(),
        organization_id=ctx.organization_id,
        binding_id=binding.id,
        project_id=project.id,
        workspace_generation=project.workspace_generation,
        environment_id=row.id,
        actor_id=ctx.user_id,
    )
    from pydantic_ai.workspaces import WorkspaceRef

    resource = DesktopEnvironmentResource(
        environment_id=row.id,
        organization_id=ctx.organization_id,
        backend="sandbox",
        workspace_id=workspace.id,
        connection_id=binding.connection_id,
        connection_fingerprint="opened-connection",
        workspace_ref=WorkspaceRef(provider="test", id=workspace.session_id),
        project_lease_id=lease.id,
        width=1280,
        height=800,
    )
    payload = ConversationEnvironmentPayload(
        environment_id=row.id, organization_id=ctx.organization_id, revision=1
    )
    db = AsyncMock()
    service = SimpleNamespace(
        claim=AsyncMock(return_value=configured),
        resource=MagicMock(return_value=resource),
        live=AsyncMock(return_value=(row, configured, resource)),
    )
    monkeypatch.setattr(module, "ConversationEnvironmentService", lambda _: service)
    reader = AsyncMock(return_value=workspace)
    monkeypatch.setattr(module.workspaces, "get", reader)
    monkeypatch.setattr(module.environments, "for_worker", AsyncMock(return_value=row))
    connections = SimpleNamespace(
        resolve=AsyncMock(return_value=object()),
        supports_project_filesystem=AsyncMock(return_value=True),
    )
    workspace_service = SimpleNamespace(
        connections=connections,
        environment_connection_fingerprint=MagicMock(return_value="opened-connection"),
    )
    monkeypatch.setattr(module, "SandboxWorkspaceService", lambda _: workspace_service)
    project_reader = AsyncMock(return_value=(ctx, project))
    monkeypatch.setattr(
        module, "ProjectRunAuthority", lambda **kwargs: SimpleNamespace(project=project_reader)
    )
    support = AsyncMock(return_value=FsSuccess())
    monkeypatch.setattr(
        module,
        "ProjectFilesystemService",
        lambda _: SimpleNamespace(exclusive_create_support=support),
    )
    authority = module._authority(configured, project.id)
    return SimpleNamespace(**locals())


async def test_starting_keeps_project_and_workspace_checks_before_admission(case):
    row, authority = await module.starting(
        case.db,
        binding=case.binding,
        payload=case.payload,
        attempt=2,
        project_id=case.project.id,
        generation=case.project.workspace_generation,
    )
    assert row is case.row and authority == case.authority
    case.service.claim.assert_awaited_once_with(case.payload, 2)
    case.support.assert_awaited_once_with(
        case.ctx, case.project.id, case.project.workspace_generation, writable=True
    )


@pytest.mark.parametrize("missing", ["claim", "row", "resource"])
async def test_starting_requires_actual_claim_and_desktop_resource_before_provider(
    case, monkeypatch, missing
):
    if missing == "claim":
        case.service.claim.return_value = None
    elif missing == "row":
        monkeypatch.setattr(module.environments, "for_worker", AsyncMock(return_value=None))
    else:
        case.service.resource.return_value = BrowserEnvironmentResource(
            environment_id=case.row.id,
            organization_id=case.ctx.organization_id,
            cdp_url="http://browser.invalid",
        )
    with pytest.raises(AuthorizationError):
        await module.starting(
            case.db,
            binding=case.binding,
            payload=case.payload,
            attempt=2,
            project_id=case.project.id,
            generation=case.project.workspace_generation,
        )
    case.reader.assert_not_awaited()


async def test_unavailable_writable_filesystem_refuses_before_creating_mount(case):
    case.support.return_value = FsFailure(
        errno=95, message="Storage cannot persist exclusive create"
    )
    with pytest.raises(ExternalServiceError):
        await module.starting(
            case.db,
            binding=case.binding,
            payload=case.payload,
            attempt=1,
            project_id=case.project.id,
            generation=case.project.workspace_generation,
        )


@pytest.mark.parametrize(
    "changed",
    [
        "revoked",
        "target",
        "tenant",
        "conversation",
        "owner",
        "resource_tenant",
        "provider",
        "workspace",
        "connection",
        "fingerprint",
        "sandbox_missing",
        "state_backend",
        "shared_scope",
        "desktop",
        "auto_credential",
    ],
)
async def test_workspace_preconditions_refuse_before_repository_or_connection_io(case, changed):
    configured = case.configured
    if changed == "revoked":
        case.binding.revoked_at = datetime.now(UTC)
    elif changed == "target":
        configured = replace(
            configured, authority=replace(configured.authority, execution_target="project")
        )
    elif changed == "tenant":
        case.binding.organization_id = uuid4()
    elif changed == "conversation":
        case.binding.conversation_id = uuid4()
    elif changed == "owner":
        case.conversation.user_id = uuid4()
    elif changed == "resource_tenant":
        case.resource.organization_id = uuid4()
    elif changed == "provider":
        case.resource.backend = "e2b"
    elif changed == "workspace":
        case.resource.workspace_id = uuid4()
    elif changed == "connection":
        case.resource.connection_id = uuid4()
    elif changed == "fingerprint":
        case.resource.connection_fingerprint = None
    elif changed == "sandbox_missing":
        case.spec.capabilities.clear()
    elif changed == "state_backend":
        case.spec.capabilities[0].config["backend"] = "state"
    elif changed == "shared_scope":
        case.spec.capabilities[0].config["session_scope"] = "agent"
    elif changed == "desktop":
        configured = replace(configured, config=ComputerUseConfig(desktop="daemon"))
    else:
        configured = replace(
            configured, config=ComputerUseConfig(desktop="auto"), credential="cloud-desktop-key"
        )
    with pytest.raises(AuthorizationError):
        await module._workspace(case.db, case.binding, configured, case.resource, ready=True)
    case.reader.assert_not_awaited()
    case.connections.resolve.assert_not_awaited()


@pytest.mark.parametrize(
    "changed",
    [
        "missing",
        "no_id",
        "backend",
        "scope",
        "conversation",
        "agent",
        "connection",
        "key",
        "ref_missing",
        "ref_changed",
        "fingerprint",
        "unsupported",
        "disabled",
    ],
)
async def test_actual_executor_identity_is_rechecked_before_filesystem_use(case, changed):
    if changed == "missing":
        case.reader.return_value = None
    elif changed == "no_id":
        case.binding.workspace_id = case.resource.workspace_id = None
    elif changed == "backend":
        case.workspace.backend = "state"
    elif changed == "scope":
        case.workspace.scope = "agent"
    elif changed == "conversation":
        case.workspace.conversation_id = uuid4()
    elif changed == "agent":
        case.workspace.agent_id = uuid4()
    elif changed == "connection":
        case.workspace.connection_id = uuid4()
    elif changed == "key":
        case.workspace.scope_key = "different-session"
    elif changed == "ref_missing":
        case.resource.workspace_ref = None
    elif changed == "ref_changed":
        case.workspace.session_id = "replacement-session"
    elif changed == "fingerprint":
        case.workspace_service.environment_connection_fingerprint.return_value = "rotated"
    elif changed == "unsupported":
        case.connections.supports_project_filesystem.return_value = False
    else:
        case.connections.resolve.side_effect = BadRequestError(message="Disabled connection")
    with pytest.raises(AuthorizationError):
        await module._workspace(case.db, case.binding, case.configured, case.resource, ready=True)


async def test_provisional_workspace_can_be_journaled_before_provider_returns_ref(case):
    case.resource.workspace_ref = None
    await module._workspace(case.db, case.binding, case.configured, case.resource, ready=False)


@pytest.mark.parametrize("missing", ["environment", "conversation"])
async def test_ready_authority_never_falls_back_to_run_identity(case, missing):
    if missing == "environment":
        case.lease.environment_id = None
    else:
        case.binding.conversation_id = None
    with pytest.raises(AuthorizationError):
        await module.authorize(case.db, case.binding, case.lease, case.authority)
    case.service.live.assert_not_awaited()


async def test_fresh_expiry_becomes_controlled_mount_refusal(case):
    case.service.live.side_effect = EnvironmentNotReady("environment_expired", "Expired")
    with pytest.raises(AuthorizationError) as caught:
        await module.authorize(case.db, case.binding, case.lease, case.authority)
    assert isinstance(caught.value.__cause__, EnvironmentNotReady)


async def test_changed_snapshot_cannot_gain_new_project_scopes(case):
    authority = case.authority.model_copy(update={"granted_scopes": frozenset({"projects:read"})})
    with pytest.raises(AuthorizationError, match="admission changed"):
        await module.authorize(case.db, case.binding, case.lease, authority)
    case.project_reader.assert_not_awaited()


@pytest.mark.parametrize("missing", ["owner", "project"])
async def test_no_owner_or_different_project_cannot_construct_authority(case, missing):
    configured = (
        replace(
            case.configured,
            authority=replace(case.configured.authority, ctx=replace(case.ctx, user_id=None)),
        )
        if missing == "owner"
        else case.configured
    )
    with pytest.raises(AuthorizationError):
        module._authority(configured, uuid4() if missing == "project" else case.project.id)


async def test_project_generation_mismatch_refuses_without_fallback(case):
    with pytest.raises(ConcurrentChangeError):
        await module._project(case.db, case.authority, case.project.id, uuid4())


@pytest.mark.parametrize("shell", [False, True])
async def test_project_desktop_wrapper_keeps_bytes_and_pins_environment_without_mutating_input(
    monkeypatch, shell
):
    original = document_workspace()
    await original.write_bytes("data.bin", b"\x00\xff")
    run = AsyncMock(return_value=CommandResult(exit_code=0, stdout="ok", stderr=""))
    monkeypatch.setattr(original, "run", run)
    lease_id = uuid4()
    wrapped = module.ProjectDesktopWorkspace(original, lease_id)
    environment = {"PROJECT_DIR": "untrusted", "OTHER": "preserved"}
    await wrapped.run("launch app", shell=shell, env=environment, timeout=5, cwd="/workspace")
    run.assert_awaited_once_with(
        "launch app",
        shell=shell,
        env={"PROJECT_DIR": f"/project/{lease_id}", "OTHER": "preserved"},
        timeout=5,
        cwd="/workspace",
    )
    assert environment["PROJECT_DIR"] == "untrusted"
    assert await wrapped.read_bytes("data.bin") == b"\x00\xff"


@pytest.mark.parametrize("missing", ["binding", "scope", "project"])
async def test_prepare_does_not_issue_a_mount_without_a_private_project_executor(case, missing):
    configured = (
        replace(case.configured, authority=replace(case.configured.authority, project=None))
        if missing == "project"
        else case.configured
    )
    result = await module.prepare(
        configured,
        case.resource,
        binding_id=None if missing == "binding" else case.binding.id,
        scope="agent" if missing == "scope" else "conversation",
        payload=case.payload,
        attempt=1,
    )
    assert result is None
    assert case.resource.project_lease_id == case.lease.id


async def test_prepare_publishes_path_only_after_lease_transaction_acknowledgement(
    case, monkeypatch
):
    import app.db.session as sessions
    from app.services.project_filesystem_bindings import ProjectFilesystemBindingService

    case.resource.project_lease_id = None
    events = []

    @asynccontextmanager
    async def session():
        events.append("begin")
        yield case.db
        assert case.resource.project_lease_id is None
        events.append("commit")

    issue = AsyncMock(return_value=SimpleNamespace(id=case.lease.id))
    monkeypatch.setattr(sessions, "get_worker_db_context", session)
    monkeypatch.setattr(ProjectFilesystemBindingService, "issue_environment_lease", issue)
    result = await module.prepare(
        case.configured,
        case.resource,
        binding_id=case.binding.id,
        scope="conversation",
        payload=case.payload,
        attempt=3,
    )
    assert events == ["begin", "commit"] and result == case.lease.id
    assert case.resource.project_lease_id == case.lease.id
    assert issue.await_args.kwargs["attempt"] == 3


@pytest.mark.parametrize(
    "variant,expected",
    [
        ("sandbox", True),
        ("auto", True),
        ("keyed_auto", False),
        ("run", False),
        ("agent_scope", False),
        ("state", False),
        ("no_sandbox", False),
        ("no_desktop", False),
        ("disabled", False),
        ("daemon", False),
    ],
)
async def test_eligible_configuration_is_effect_free_and_preserves_legacy_modes(
    case, variant, expected
):
    spec = case.spec.model_copy(deep=True)
    secrets = {}
    if variant in ("auto", "keyed_auto", "daemon"):
        spec.capabilities[1].config["desktop"] = "daemon" if variant == "daemon" else "auto"
        if variant == "keyed_auto":
            identity = uuid4()
            spec.capabilities[1].secret_id = identity
            secrets[identity] = ApiKeySecret(api_key="private-cloud-key")
    elif variant == "run":
        spec.capabilities[1].config["session_lifetime"] = "run"
    elif variant == "agent_scope":
        spec.capabilities[0].config["session_scope"] = "agent"
    elif variant == "state":
        spec.capabilities[0].config["backend"] = "state"
    elif variant == "no_sandbox":
        spec.capabilities.pop(0)
    elif variant == "no_desktop":
        spec.capabilities.pop()
    elif variant == "disabled":
        spec.capabilities[1].enabled = False
    assert module.retained_project_mount(spec, secrets) is expected
    case.connections.resolve.assert_not_awaited()


async def test_readonly_deployment_scope_admits_without_a_write_support_probe(case, monkeypatch):
    monkeypatch.setattr(module, "DEFAULT_GRANTED_SCOPES", frozenset({"projects:read"}))
    _, authority = await module.starting(
        case.db,
        binding=case.binding,
        payload=case.payload,
        attempt=2,
        project_id=case.project.id,
        generation=case.project.workspace_generation,
    )
    assert authority.granted_scopes == frozenset({"projects:read"})
    case.support.assert_not_awaited()
