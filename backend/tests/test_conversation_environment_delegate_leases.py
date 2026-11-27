"""Nested desktop tools lease the selected executor before touching its actual GUI."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.audience import RunAudience
from app.agents.browser_events import OwnedEnvironmentView
from app.agents.capabilities.computer_use._actions import TypeText
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import AuthorizationError, ConflictError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret
from app.services import conversation_environment_delegates as delegates
from app.services import conversation_environment_driver as drivers
from app.services.run_project_workspace import RunProjectWorkspace
from tests.workspaces import document_workspace

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def case(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    parent = delegates.NestedDesktopAuthority(ctx, uuid4(), uuid4(), uuid4(), uuid4(), "agent")
    child_id, version_id, secret_id = uuid4(), uuid4(), uuid4()
    binding = CapabilityBindingSpec(
        id="computer_use", secret_id=secret_id, config={"desktop": "sandbox"}
    )
    child = AgentSpec(name="Delegate", capabilities=[binding])
    secret = ApiKeySecret(api_key="delegate-token")
    db = MagicMock()
    transactions = []

    @asynccontextmanager
    async def session():
        transactions.append("enter")
        yield db
        transactions.append("commit")

    monkeypatch.setattr(delegates, "get_db_context", session)
    monkeypatch.setattr(drivers, "get_db_context", session)
    admitted = SimpleNamespace(
        ctx=ctx,
        version_id=parent.version_id,
        spec=AgentSpec(name="Root executor"),
        conversation=SimpleNamespace(project_id=None),
    )
    auth = AsyncMock(return_value=admitted)
    producer = AsyncMock()
    registry = SimpleNamespace(get_runnable_spec=AsyncMock())
    version = AsyncMock(return_value=SimpleNamespace(agent_id=child_id))
    secrets = SimpleNamespace(resolve_for_bindings=AsyncMock(return_value={secret_id: secret}))
    connection = SimpleNamespace(id=uuid4())
    current = SimpleNamespace(key="actual-agent-scope", resolved=SimpleNamespace(row=connection))
    service = SimpleNamespace(
        resolve_live_execution=AsyncMock(return_value=current),
        environment_connection_fingerprint=MagicMock(return_value="connection-generation"),
    )
    monkeypatch.setattr(delegates, "authority", auth)
    monkeypatch.setattr(delegates, "require_environment_run", producer)
    monkeypatch.setattr(delegates, "AgentRegistryService", lambda _: registry)
    monkeypatch.setattr(delegates.agents, "get_version", version)
    monkeypatch.setattr(delegates, "OrganizationSecretService", lambda _: secrets)
    monkeypatch.setattr(delegates, "SandboxWorkspaceService", lambda _: service)
    claim = AsyncMock(return_value=True)
    renew = AsyncMock(return_value=True)
    release = AsyncMock()
    monkeypatch.setattr(drivers.environments, "claim_driver", claim)
    monkeypatch.setattr(drivers.environments, "renew_driver", renew)
    monkeypatch.setattr(drivers.environments, "release_driver", release)
    computer = SimpleNamespace(
        label="Child GUI",
        capture=AsyncMock(return_value=b"frame"),
        perform=AsyncMock(),
        apps=AsyncMock(return_value=[]),
        close=AsyncMock(),
    )

    async def open_computer(workspace):
        assert transactions[-1] == "commit"
        assert claim.await_count == 1
        return computer

    factory = AsyncMock(side_effect=open_computer)
    decorator = parent.for_child(
        child, {secret_id: secret}, agent_id=child_id, version_id=version_id
    )
    assert decorator is not None
    return SimpleNamespace(**locals())


async def test_claim_commits_before_start_and_every_operation_renews_own_token(case):
    view = await case.decorator.wrap(case.factory)(document_workspace())
    try:
        assert not isinstance(view, OwnedEnvironmentView)
        assert view.label == "Child GUI"
        assert await view.capture() == b"frame"
        action = TypeText(text="hello")
        await view.perform(action)
        assert await view.apps() == []
        assert case.renew.await_count == 3
        case.computer.perform.assert_awaited_once_with(action)
        expected = delegates.resource_key(
            "workspace", f"{case.ctx.organization_id}:{case.connection.id}:{case.current.key}"
        )
        assert case.claim.await_args.args[1] == expected
        assert case.claim.await_args.kwargs["control"] == "agent"
        token = case.claim.await_args.kwargs["token"]
        assert all(call.kwargs["token"] == token for call in case.renew.await_args_list)
    finally:
        await view.close()
    case.computer.close.assert_awaited_once()
    assert case.release.await_args.kwargs["token"] == token


async def test_human_owned_screen_refuses_before_provider_start(case):
    case.claim.return_value = False
    with pytest.raises(ConflictError, match="already being controlled"):
        await case.decorator.wrap(case.factory)(document_workspace())
    case.factory.assert_not_awaited()
    case.release.assert_awaited_once()


@pytest.mark.parametrize("boundary", ["auth", "producer", "version", "secret", "connection"])
async def test_fresh_authority_refusal_happens_before_claim_and_start(case, boundary):
    if boundary in {"auth", "producer"}:
        getattr(case, boundary).side_effect = AuthorizationError(message="Revoked")
    elif boundary == "version":
        case.version.return_value = None
    elif boundary == "secret":
        case.secrets.resolve_for_bindings.return_value = {
            case.secret_id: ApiKeySecret(api_key="rotated-token")
        }
    else:
        case.service.resolve_live_execution.side_effect = ConflictError(
            message="Connection revoked"
        )
    with pytest.raises((AuthorizationError, ConflictError)):
        await case.decorator.wrap(case.factory)(document_workspace())
    case.claim.assert_not_awaited()
    case.factory.assert_not_awaited()


async def test_root_version_change_and_wrong_child_version_do_not_borrow_authority(case):
    case.admitted.version_id = uuid4()
    with pytest.raises(ConflictError, match="published authority changed"):
        await case.decorator.wrap(case.factory)(document_workspace())
    case.admitted.version_id = case.parent.version_id
    case.version.return_value.agent_id = uuid4()
    with pytest.raises(ConflictError, match="no longer available"):
        await case.decorator.wrap(case.factory)(document_workspace())
    case.factory.assert_not_awaited()


@pytest.mark.parametrize("operation", ["capture", "perform", "apps"])
@pytest.mark.parametrize("refusal", ["membership", "lease", "executor"])
async def test_later_refusal_stops_each_provider_operation(case, operation, refusal):
    view = await case.decorator.wrap(case.factory)(document_workspace())
    try:
        if refusal == "membership":
            case.auth.side_effect = AuthorizationError(message="Member removed")
        elif refusal == "lease":
            case.renew.return_value = False
        else:
            case.current.key = "other-executor"
        with pytest.raises((AuthorizationError, ConflictError)):
            await getattr(view, operation)(
                *([TypeText(text="blocked")] if operation == "perform" else [])
            )
        getattr(case.computer, operation).assert_not_awaited()
    finally:
        await view.close()


@pytest.mark.parametrize("cancel", [False, True])
async def test_partial_provider_start_releases_driver_and_preserves_failure(case, cancel):
    failure = asyncio.CancelledError() if cancel else RuntimeError("Provider startup failed")
    case.factory.side_effect = failure
    with pytest.raises(type(failure)) as caught:
        await case.decorator.wrap(case.factory)(document_workspace())
    assert caught.value is failure
    case.release.assert_awaited_once()


async def test_provider_and_release_failures_remain_independently_visible(case):
    provider_failure = RuntimeError("Provider startup failed")
    release_failure = OSError("Database release failed")
    case.factory.side_effect = provider_failure
    case.release.side_effect = release_failure
    with pytest.raises(BaseExceptionGroup) as caught:
        await case.decorator.wrap(case.factory)(document_workspace())
    assert caught.value.exceptions == (provider_failure, release_failure)


@pytest.mark.parametrize("release_fails", [False, True])
async def test_transport_close_failure_still_releases_driver(case, release_fails):
    view = await case.decorator.wrap(case.factory)(document_workspace())
    failure = RuntimeError("Transport detach failed")
    case.computer.close.side_effect = failure
    if release_fails:
        case.release.side_effect = OSError("Release failed")
    with pytest.raises(BaseExceptionGroup if release_fails else RuntimeError) as caught:
        await view.close()
    case.release.assert_awaited_once()
    if release_fails:
        assert caught.value.exceptions[0] is failure
    else:
        assert caught.value is failure


async def test_actual_project_selector_uses_selected_executor_without_ref_or_provider_admission(
    case,
):
    workspace = RunProjectWorkspace(
        document_workspace(),
        case.ctx,
        audience=RunAudience(user_id=case.ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
    )
    workspace.project_id, workspace.project_generation = uuid4(), uuid4()
    workspace.execution_target = "project"
    assert workspace.ref is None
    view = await case.decorator.wrap(case.factory)(workspace)
    try:
        kwargs = case.service.resolve_live_execution.await_args.kwargs
        assert kwargs["execution_target"] == "project"
        assert kwargs["selected_project_id"] == workspace.project_id
        assert kwargs["selected_generation"] == workspace.project_generation
        assert case.auth.await_args.kwargs["execution_target"] == "agent"
        assert workspace.agent_workspace is None
        workspace.execution_target = "agent"
        with pytest.raises(ConflictError, match="execution target changed"):
            await view.capture()
        case.computer.capture.assert_not_awaited()
    finally:
        await view.close()


@pytest.mark.parametrize(
    "mode,credential,shared,expected",
    [
        ("sandbox", False, True, True),
        ("sandbox", False, False, False),
        ("auto", False, True, True),
        ("auto", True, True, False),
        ("e2b", True, True, False),
        ("local", False, True, False),
        ("daemon", True, False, True),
    ],
)
async def test_only_actual_shared_or_daemon_desktop_requires_nested_driver(
    case, mode, credential, shared, expected
):
    parent = case.parent.delegated(shares_workspace=shared)
    binding = CapabilityBindingSpec(
        id="computer_use",
        config={"desktop": mode, "daemon_url": "https://desktop.example"},
        secret_id=case.secret_id,
    )
    child = AgentSpec(name="Child", capabilities=[binding])
    result = parent.for_child(
        child,
        {case.secret_id: case.secret} if credential else {},
        agent_id=case.child_id,
        version_id=None,
    )
    assert (result is not None) is expected


@pytest.mark.parametrize("changed", ["scope", "connection", "fingerprint"])
async def test_original_shared_executor_identity_cannot_silently_change(case, changed):
    origin = delegates.SharedDesktopWorkspace(
        case.connection.id, case.current.key, "connection-generation"
    )
    parent = delegates.replace(case.parent, workspace=origin)
    decorator = parent.for_child(
        case.child, {case.secret_id: case.secret}, agent_id=case.child_id, version_id=None
    )
    if changed == "scope":
        case.current.key = "another-scope"
    elif changed == "connection":
        case.connection.id = uuid4()
    else:
        case.service.environment_connection_fingerprint.return_value = "new-configuration"
    with pytest.raises(ConflictError, match="original shared desktop executor changed"):
        await decorator.wrap(case.factory)(document_workspace())
    case.factory.assert_not_awaited()
    case.claim.assert_not_awaited()


async def test_daemon_uses_child_address_and_fresh_credential_without_workspace_lookup(
    case, monkeypatch
):
    child = AgentSpec(
        name="Daemon",
        capabilities=[
            CapabilityBindingSpec(
                id="computer_use",
                secret_id=case.secret_id,
                config={"desktop": "daemon", "daemon_url": "https://child.example/"},
            )
        ],
    )
    checked = MagicMock()
    monkeypatch.setattr(delegates, "check_daemon_url", checked)
    decorator = case.parent.for_child(
        child, {case.secret_id: case.secret}, agent_id=case.child_id, version_id=None
    )
    view = await decorator.wrap(case.factory)(document_workspace())
    try:
        assert case.claim.await_args.args[1] == delegates.resource_key(
            "daemon", "https://child.example"
        )
        checked.assert_called_with("https://child.example/")
        case.service.resolve_live_execution.assert_not_awaited()
        case.registry.get_runnable_spec.assert_not_awaited()
        await view.capture()
        assert checked.call_count == 3
    finally:
        await view.close()


@pytest.mark.parametrize("disabled", [False, True])
async def test_child_without_enabled_desktop_does_not_gain_one_from_parent(case, disabled):
    bindings = [CapabilityBindingSpec(id="computer_use", enabled=False)] if disabled else []
    assert (
        case.parent.for_child(
            AgentSpec(name="No desktop", capabilities=bindings),
            {},
            agent_id=case.child_id,
            version_id=None,
        )
        is None
    )


async def test_successful_transport_close_does_not_hide_release_failure(case):
    view = await case.decorator.wrap(case.factory)(document_workspace())
    failure = OSError("Release failed")
    case.release.side_effect = failure
    with pytest.raises(OSError) as caught:
        await view.close()
    assert caught.value is failure
    case.computer.close.assert_awaited_once()


@pytest.mark.parametrize("changed", [False, True])
async def test_already_opened_actual_agent_executor_keeps_its_original_connection_fence(
    case, changed
):
    from app.services.sandbox_workspace import OpenWorkspace

    workspace = RunProjectWorkspace(
        document_workspace(),
        case.parent.ctx,
        audience=RunAudience(user_id=case.parent.ctx.user_id),
        granted_scopes=frozenset(),
        open_agent_executor=AsyncMock(),
    )
    workspace.agent_workspace = OpenWorkspace(
        workspace=document_workspace(),
        kind="service",
        scope="conversation",
        scope_key=case.current.key,
        row_id=uuid4(),
        connection_id=case.connection.id,
        connection_fingerprint="rotated" if changed else "connection-generation",
    )
    assert workspace.ref is None
    if changed:
        with pytest.raises(ConflictError, match="shared desktop connection changed"):
            await case.decorator.wrap(case.factory)(workspace)
        case.factory.assert_not_awaited()
    else:
        view = await case.decorator.wrap(case.factory)(workspace)
        await view.close()
    workspace.open_agent_executor.assert_not_awaited()
