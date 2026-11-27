"""Manual desktop admission uses canonical retained keys without inventing an agent run."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.capabilities.computer_use import ComputerUseConfig
from app.agents.capabilities.sandbox import WorkspaceIdentity
from app.agents.capabilities.sandbox import _identity as identities
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.conversation import Conversation
from app.db.models.sandbox_connection import SandboxConnection
from app.services import sandbox_workspace as workspaces
from app.services import workspace_turn_guard as turn_guard
from app.services.conversation_environment_policy import (
    DesktopEnvironmentSettings,
    EnvironmentAuthority,
)
from app.services.conversation_environments import ConversationEnvironmentService
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService
from app.worker.jobs import ConversationEnvironmentPayload
from tests.workspaces import document_workspace

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def case(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    agent = Agent(id=uuid4(), organization_id=ctx.organization_id)
    conversation = Conversation(
        id=uuid4(), organization_id=ctx.organization_id, user_id=ctx.user_id
    )
    connection = SandboxConnection(
        id=uuid4(),
        organization_id=ctx.organization_id,
        kind="sandboxd",
        base_url="http://sandbox.invalid",
        default_runtime=None,
        secure_access=False,
    )
    spec = AgentSpec(
        name="Desktop",
        capabilities=[
            CapabilityBindingSpec(
                id="sandbox",
                config={
                    "backend": "service",
                    "session_scope": "conversation",
                    "connection_id": str(connection.id),
                    "runtime": "desktop",
                },
            )
        ],
    )
    authority = EnvironmentAuthority(ctx, conversation, agent, uuid4(), spec, "agent", None)
    resolved = DesktopEnvironmentSettings(
        authority,
        ComputerUseConfig(desktop="sandbox", session_lifetime="conversation"),
        "binding-fingerprint",
        "",
    )
    payload = ConversationEnvironmentPayload(
        environment_id=uuid4(), organization_id=ctx.organization_id, revision=1
    )
    db = AsyncMock()
    service = workspaces.SandboxWorkspaceService(db)
    claim = AsyncMock(return_value=resolved)
    monkeypatch.setattr(ConversationEnvironmentService, "claim", claim)
    provider = SimpleNamespace(
        provider="state", backend=MagicMock(return_value=document_workspace().backend)
    )
    monkeypatch.setattr(
        workspaces.SandboxWorkspaceService,
        "_service_capability",
        staticmethod(lambda *args, **kwargs: provider),
    )
    connection_reader = AsyncMock(return_value=ResolvedConnection(connection, "provider-token"))
    monkeypatch.setattr(SandboxConnectionService, "resolve", connection_reader)
    monkeypatch.setattr(
        SandboxConnectionService, "supports_project_filesystem", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(workspaces.workspace_repo, "get_by_key", AsyncMock(return_value=None))
    rows = []

    async def create(db, **kwargs):
        row = AgentWorkspace(id=uuid4(), **kwargs)
        rows.append(row)
        return row

    create_row = AsyncMock(side_effect=create)
    monkeypatch.setattr(workspaces.workspace_repo, "create", create_row)
    hold = AsyncMock(return_value=True)
    running = AsyncMock(return_value=False)
    monkeypatch.setattr(turn_guard, "try_hold_subject", hold)
    monkeypatch.setattr(turn_guard.run_repo, "has_running_in_conversation", running)
    monkeypatch.setattr(turn_guard.change_repo, "has_pending_revert", AsyncMock(return_value=False))
    return SimpleNamespace(**locals())


def configure_scope(case, scope):
    case.spec.capabilities[0].config["session_scope"] = scope


@pytest.mark.parametrize("scope", ["conversation", "user", "agent"])
async def test_actual_service_uses_same_canonical_key_as_run_without_a_fake_run(case, scope):
    configure_scope(case, scope)
    opened = await case.service.open_for_environment(case.payload, 3)
    identity = WorkspaceIdentity(
        organization_id=case.ctx.organization_id,
        agent_id=case.agent.id,
        run_id=uuid4(),
        conversation_id=case.conversation.id,
        user_id=str(case.ctx.user_id),
    )
    assert opened.scope_key == identities.scope_key(
        identity, scope, "service", case.connection.id, "desktop"
    )
    assert opened.scope == scope
    case.claim.assert_awaited_once_with(case.payload, 3)
    assert case.rows and case.rows[0].agent_id == case.agent.id
    assert case.create_row.await_args.kwargs["scope_key"] == opened.scope_key
    assert case.authority.producer_run_id is None
    assert opened.workspace.run_id is None
    case.db.add.assert_not_called()
    if scope == "conversation":
        assert case.running.await_args.kwargs["excluding"] is None
    else:
        case.hold.assert_not_awaited()
    with pytest.raises(identities.WorkspaceScopeUnavailable, match="without an agent's run"):
        identities.scope_key(
            replace(identity, run_id=None), scope, "service", case.connection.id, "desktop"
        )


@pytest.mark.parametrize("scope", ["run", "channel"])
async def test_manual_retained_admission_refuses_ephemeral_scope_before_provider(case, scope):
    configure_scope(case, scope)
    with pytest.raises(BadRequestError):
        await case.service.open_for_environment(case.payload, 3)
    case.connection_reader.assert_not_awaited()
    case.provider.backend.assert_not_called()
    case.create_row.assert_not_awaited()


@pytest.mark.parametrize("refused", [False, True])
async def test_fresh_owned_claim_is_required_before_any_workspace_admission(case, refused):
    if refused:
        case.claim.side_effect = AuthorizationError(message="Owner access revoked")
    else:
        case.claim.return_value = None
    with pytest.raises((AuthorizationError, BadRequestError)):
        await case.service.open_for_environment(case.payload, 3)
    case.connection_reader.assert_not_awaited()
    case.provider.backend.assert_not_called()
    case.create_row.assert_not_awaited()


async def test_active_conversation_writer_refuses_manual_preparation_before_provider(case):
    case.running.return_value = True
    with pytest.raises(AlreadyExistsError):
        await case.service.open_for_environment(case.payload, 3)
    case.provider.backend.assert_not_called()
    case.create_row.assert_not_awaited()


async def test_actual_desktop_provision_admits_manual_workspace_and_leases_before_start(
    case, monkeypatch
):
    from contextlib import asynccontextmanager

    from app.services import conversation_environment_runtime as runtime

    @asynccontextmanager
    async def session():
        yield case.db

    held = []

    @asynccontextmanager
    async def drive(key):
        held.append(key)
        try:
            yield
        finally:
            held.pop()

    async def setup_desktop(workspace, **kwargs):
        assert held
        assert case.rows
        assert case.claim.await_count == 1
        assert case.authority.producer_run_id is None

    factory = AsyncMock(side_effect=setup_desktop)
    store = AsyncMock(return_value=True)
    monkeypatch.setattr(runtime, "get_worker_db_context", session)
    monkeypatch.setattr(runtime, "open_sandbox_desktop", factory)
    monkeypatch.setattr(runtime.workspace_repo, "record_live_session", AsyncMock(return_value=True))
    await runtime.provision(case.resolved, case.payload, store, drive, attempt=3)
    case.claim.assert_awaited_once_with(case.payload, 3)
    factory.assert_awaited_once()
    resource = store.await_args.args[0]
    assert resource.workspace_id == case.rows[0].id
    assert resource.environment_id == case.payload.environment_id
    assert resource.workspace_ref.id == "doc"
    assert not held
    case.db.add.assert_not_called()


async def ready_observer(case, monkeypatch):
    from app.services.conversation import ConversationService
    from app.services.conversation_environment_resources import DesktopEnvironmentResource

    opened = await case.service.open_for_environment(case.payload, 3)
    resource = DesktopEnvironmentResource(
        environment_id=case.payload.environment_id,
        organization_id=case.ctx.organization_id,
        backend="sandbox",
        workspace_id=opened.row_id,
        workspace_ref=opened.workspace.ref,
        connection_id=opened.connection_id,
        connection_fingerprint=opened.connection_fingerprint,
        width=1280,
        height=800,
    )
    live = AsyncMock(
        return_value=(SimpleNamespace(id=case.payload.environment_id), case.resolved, resource)
    )
    monkeypatch.setattr(ConversationEnvironmentService, "live", live)
    monkeypatch.setattr(
        ConversationService, "get_conversation", AsyncMock(return_value=case.conversation)
    )
    monkeypatch.setattr(workspaces.workspace_repo, "get", AsyncMock(return_value=case.rows[0]))
    case.rows[0].session_id = opened.workspace.ref.id
    identity = WorkspaceIdentity(
        organization_id=case.ctx.organization_id,
        agent_id=case.agent.id,
        run_id=None,
        conversation_id=case.conversation.id,
        user_id=str(case.ctx.user_id),
    )
    return SimpleNamespace(opened=opened, identity=identity, resource=resource, live=live)


async def attach(case, ready, *, environment_id=True):
    return await case.service.attach_live_environment(
        case.ctx,
        spec=case.spec,
        identity=ready.identity,
        execution_target="agent",
        workspace_id=ready.opened.row_id,
        ref=ready.opened.workspace.ref,
        connection_fingerprint=ready.opened.connection_fingerprint,
        environment_id=case.payload.environment_id if environment_id else None,
    )


async def test_ready_manual_observer_uses_live_owner_validation_and_same_physical_key(
    case, monkeypatch
):
    ready = await ready_observer(case, monkeypatch)
    attached = await attach(case, ready)
    assert attached.scope_key == ready.opened.scope_key
    assert attached.workspace.ref == ready.opened.workspace.ref
    ready.live.assert_awaited_once()
    assert ready.live.await_args.args[:4] == (
        case.ctx,
        case.conversation.id,
        case.payload.environment_id,
        "agent",
    )
    assert case.claim.await_count == 1


@pytest.mark.parametrize(
    "changed", ["organization_id", "agent_id", "user_id", "workspace", "authority"]
)
async def test_ready_observer_refuses_changed_identity_or_revoked_owner_before_provider(
    case, monkeypatch, changed
):
    ready = await ready_observer(case, monkeypatch)
    case.provider.backend.reset_mock()
    if changed == "authority":
        ready.live.side_effect = AuthorizationError(message="Membership revoked")
    elif changed == "workspace":
        ready.resource.workspace_id = uuid4()
    else:
        ready.identity = replace(
            ready.identity, **{changed: str(uuid4()) if changed == "user_id" else uuid4()}
        )
    with pytest.raises((NotFoundError, AuthorizationError)):
        await attach(case, ready)
    case.provider.backend.assert_not_called()


async def test_no_environment_id_cannot_bypass_generic_run_admission(case, monkeypatch):
    ready = await ready_observer(case, monkeypatch)
    case.provider.backend.reset_mock()
    with pytest.raises(BadRequestError, match="without an agent's run"):
        await attach(case, ready, environment_id=False)
    ready.live.assert_not_awaited()
    case.provider.backend.assert_not_called()


@pytest.mark.parametrize(
    "missing", ["agent_id", "conversation_id", "user_id", "run_id", "namespace"]
)
async def test_retained_key_validates_complete_manual_identity_without_relaxing_run_rules(
    case, missing
):
    identity = WorkspaceIdentity(
        organization_id=case.ctx.organization_id,
        agent_id=case.agent.id,
        run_id=None,
        conversation_id=case.conversation.id,
        user_id=str(case.ctx.user_id),
    )
    value = uuid4() if missing in ("run_id", "namespace") else None
    with pytest.raises(BadRequestError):
        case.service._retained_key(replace(identity, **{missing: value}), "conversation", "service")


@pytest.mark.parametrize("changed", ["producer", "target", "owner", "backend", "missing_binding"])
async def test_manual_entrypoint_does_not_accept_other_admission_contracts(case, changed):
    if changed == "backend":
        case.spec.capabilities[0].config["backend"] = "state"
    elif changed == "missing_binding":
        case.spec.capabilities.clear()
    else:
        authority = replace(
            case.authority,
            **{"producer_run_id": uuid4()}
            if changed == "producer"
            else {"execution_target": "project"}
            if changed == "target"
            else {"ctx": replace(case.ctx, user_id=None)},
        )
        case.claim.return_value = replace(case.resolved, authority=authority)
    with pytest.raises(BadRequestError):
        await case.service.open_for_environment(case.payload, 3)
    case.connection_reader.assert_not_awaited()
    case.provider.backend.assert_not_called()


@pytest.mark.parametrize(
    "mode,credential", [("daemon", "token"), ("e2b", "token"), ("auto", "token"), ("local", "")]
)
async def test_different_desktop_provider_cannot_admit_the_shared_sandbox(case, mode, credential):
    case.claim.return_value = replace(
        case.resolved, config=ComputerUseConfig(desktop=mode), credential=credential
    )
    with pytest.raises(BadRequestError, match="does not use this retained executor"):
        await case.service.open_for_environment(case.payload, 3)
    case.connection_reader.assert_not_awaited()
    case.provider.backend.assert_not_called()


@pytest.mark.parametrize("proof", ["configuration", "resource", "provider"])
async def test_ready_observer_cannot_substitute_browser_or_independent_desktop_proof(
    case, monkeypatch, proof
):
    from app.agents.capabilities.browser_use import WebBrowserConfig
    from app.services.conversation_environment_policy import BrowserEnvironmentSettings
    from app.services.conversation_environment_resources import BrowserEnvironmentResource

    ready = await ready_observer(case, monkeypatch)
    configured, resource = case.resolved, ready.resource
    if proof == "configuration":
        configured = BrowserEnvironmentSettings(
            case.authority, WebBrowserConfig(), "fingerprint", "http://browser.invalid", None
        )
    elif proof == "resource":
        resource = BrowserEnvironmentResource(
            environment_id=case.payload.environment_id,
            organization_id=case.ctx.organization_id,
            cdp_url="http://browser.invalid",
        )
    else:
        resource = resource.model_copy(update={"backend": "e2b"})
    ready.live.return_value = (
        SimpleNamespace(id=case.payload.environment_id),
        configured,
        resource,
    )
    case.provider.backend.reset_mock()
    with pytest.raises(NotFoundError, match="manual desktop identity changed"):
        await attach(case, ready)
    case.provider.backend.assert_not_called()


@pytest.mark.parametrize("scope", ["run", "channel", "project"])
async def test_manual_key_refuses_non_retained_scope_in_both_identity_and_service(case, scope):
    identity = WorkspaceIdentity(
        organization_id=case.ctx.organization_id,
        agent_id=case.agent.id,
        conversation_id=case.conversation.id,
        user_id=str(case.ctx.user_id),
        run_id=None,
    )
    with pytest.raises(identities.WorkspaceScopeUnavailable, match="persistent workspace scope"):
        identities.retained_scope_key(identity, scope, "service")
    with pytest.raises(BadRequestError, match="persistent workspace scope"):
        case.service._retained_key(identity, scope, "service")
