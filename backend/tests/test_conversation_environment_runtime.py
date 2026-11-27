"""Provider adapters preserve original target/ref and settle partial provisioning."""

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.workspaces import (
    Workspace,
    WorkspaceError,
    WorkspaceRef,
    WorkspaceUnavailableError,
)

from app.agents.capabilities.browser_use import WebBrowserConfig
from app.agents.capabilities.browser_use._page import BrowserTarget
from app.agents.capabilities.computer_use import ComputerUseConfig
from app.agents.capabilities.computer_use._backends import ComputerError
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import ConflictError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.conversation import Conversation
from app.db.models.sandbox_connection import SandboxConnection
from app.services import conversation_environment_runtime as runtime
from app.services.conversation_environment_policy import (
    BrowserEnvironmentSettings,
    DesktopEnvironmentSettings,
    EnvironmentAuthority,
    EnvironmentNotReady,
)
from app.services.conversation_environment_resources import (
    BrowserEnvironmentResource,
    DesktopEnvironmentResource,
)
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService
from app.services.sandbox_workspace import OpenWorkspace
from app.worker.jobs import ConversationEnvironmentPayload

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def case(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    conversation = Conversation(
        id=uuid4(), organization_id=ctx.organization_id, user_id=ctx.user_id
    )
    agent = Agent(id=uuid4(), organization_id=ctx.organization_id, name="Desktop", slug="desktop")
    connection_id, workspace_id, env_id = uuid4(), uuid4(), uuid4()
    spec = AgentSpec(
        name="Desktop",
        instructions="Use the computer",
        capabilities=[
            CapabilityBindingSpec(
                id="sandbox",
                config={
                    "backend": "service",
                    "session_scope": "conversation",
                    "connection_id": str(connection_id),
                },
            )
        ],
    )
    admitted = EnvironmentAuthority(ctx, conversation, agent, uuid4(), spec, "agent", None)
    browser = BrowserEnvironmentSettings(
        admitted,
        WebBrowserConfig(session_lifetime="conversation"),
        "fingerprint",
        "http://browser:9222",
        None,
    )
    desktop = DesktopEnvironmentSettings(
        admitted,
        ComputerUseConfig(desktop="sandbox", session_lifetime="conversation"),
        "fingerprint",
        "private-token",
    )
    workspace = MagicMock(spec=Workspace)
    workspace.ref = WorkspaceRef(provider=f"sandboxd:{connection_id}", id="original-session")
    workspace.working_dir = AsyncMock(return_value="/workspace")
    close = AsyncMock()
    opened = OpenWorkspace(
        workspace=workspace,
        kind="service",
        scope="conversation",
        scope_key="same-authorized-key",
        row_id=workspace_id,
        connection_id=connection_id,
        close_transport=close,
        connection_fingerprint="current-connection",
    )
    db = AsyncMock()

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(runtime, "get_worker_db_context", session)
    monkeypatch.setattr(runtime.SandboxWorkspaceService, "open", AsyncMock(return_value=opened))
    monkeypatch.setattr(
        runtime.SandboxWorkspaceService, "open_for_environment", AsyncMock(return_value=opened)
    )
    monkeypatch.setattr(
        runtime.SandboxWorkspaceService, "attach_live_environment", AsyncMock(return_value=opened)
    )
    monkeypatch.setattr(
        SandboxConnectionService,
        "resolve",
        AsyncMock(
            return_value=ResolvedConnection(
                SandboxConnection(
                    id=connection_id,
                    organization_id=ctx.organization_id,
                    kind="sandboxd",
                    base_url="http://sandbox:8080",
                    secure_access=False,
                ),
                "private-token",
            )
        ),
    )
    monkeypatch.setattr(runtime.workspace_repo, "record_live_session", AsyncMock(return_value=True))
    monkeypatch.setattr(runtime.pending_destroy_repo, "add", AsyncMock())
    computer = AsyncMock()
    computer.label = "Retained desktop"
    monkeypatch.setattr(runtime, "open_sandbox_desktop", AsyncMock(return_value=computer))
    store = AsyncMock(return_value=True)
    calls = []

    @asynccontextmanager
    async def drive(key):
        calls.append(("acquired", key))
        try:
            yield
        finally:
            calls.append(("released", key))

    resource = DesktopEnvironmentResource(
        environment_id=env_id,
        organization_id=ctx.organization_id,
        backend="sandbox",
        workspace_id=workspace_id,
        connection_id=connection_id,
        workspace_ref=workspace.ref,
        connection_fingerprint="current-connection",
        workspace_root="/workspace",
        width=1280,
        height=800,
    )
    return SimpleNamespace(
        ctx=ctx,
        browser=browser,
        desktop=desktop,
        workspace=workspace,
        opened=opened,
        close=close,
        db=db,
        computer=computer,
        store=store,
        drive=drive,
        calls=calls,
        resource=resource,
        payload=ConversationEnvironmentPayload(
            environment_id=env_id, organization_id=ctx.organization_id, revision=1
        ),
    )


async def test_initial_browser_hands_context_to_a_live_guard_only_after_journaling(
    case, monkeypatch
):
    from app.services import conversation_environment_browser as guards

    target = BrowserTarget(context_id="owned-context", target_id="same-page")

    async def retain(resolved, payload, *, start_url, keep):
        assert payload == case.payload and start_url is None
        await keep(target)
        return target

    monkeypatch.setattr(guards, "retain_tab", retain)
    await runtime.provision(case.browser, case.payload, case.store, case.drive)
    resource, key = case.store.await_args.args
    assert resource.tabs == {"main": target}
    assert resource.environment_id == case.payload.environment_id
    assert key == runtime.resource_key("browser", "http://browser:9222:owned-context")
    case.store.return_value = False
    with pytest.raises(ConflictError):
        await runtime.provision(case.browser, case.payload, case.store, case.drive)


async def test_shared_desktop_is_journaled_and_physically_leased_before_startup(case):
    async def start(workspace, **_options):
        assert case.calls[0][0] == "acquired"
        assert case.store.await_count == 1
        assert workspace is case.workspace
        return case.computer

    runtime.open_sandbox_desktop.side_effect = start
    await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    assert [action for action, _ in case.calls] == ["acquired", "released"]
    assert case.store.await_count == 2
    stored = case.store.await_args.args[0]
    assert stored.workspace_ref == case.workspace.ref
    assert stored.workspace_root == "/workspace"
    assert stored.workspace_id == case.opened.row_id
    assert (
        runtime.workspace_repo.record_live_session.await_args.kwargs["session_id"]
        == "original-session"
    )
    case.close.assert_awaited_once()


async def test_failed_shared_startup_releases_driver_and_transport_without_claiming_ready(case):
    runtime.open_sandbox_desktop.side_effect = ComputerError("No desktop runtime")
    with pytest.raises(ComputerError):
        await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    assert [action for action, _ in case.calls] == ["acquired", "released"]
    assert case.store.await_count == 1
    runtime.workspace_repo.record_live_session.assert_not_awaited()
    case.close.assert_awaited_once()


async def test_end_during_provision_prevents_touching_the_gui(case):
    case.store.return_value = False
    with pytest.raises(ConflictError):
        await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    runtime.open_sandbox_desktop.assert_not_awaited()
    case.close.assert_awaited_once()


@pytest.mark.parametrize("scope", ["run", "channel"])
async def test_manual_desktop_does_not_fabricate_a_run_or_channel_workspace(case, scope):
    spec = case.desktop.authority.spec.model_copy(
        update={
            "capabilities": [
                CapabilityBindingSpec(
                    id="sandbox", config={"backend": "service", "session_scope": scope}
                )
            ]
        }
    )
    resolved = replace(case.desktop, authority=replace(case.desktop.authority, spec=spec))
    with pytest.raises(EnvironmentNotReady) as caught:
        await runtime.provision(resolved, case.payload, case.store, case.drive)
    assert caught.value.refusal.code == "backend_not_supported"
    runtime.SandboxWorkspaceService.open.assert_not_awaited()


async def test_real_run_scoped_desktop_carries_the_actual_producer_identity(case):
    run_id = uuid4()
    spec = case.desktop.authority.spec.model_copy(
        update={
            "capabilities": [
                CapabilityBindingSpec(
                    id="sandbox", config={"backend": "service", "session_scope": "run"}
                )
            ]
        }
    )
    resolved = replace(
        case.desktop,
        config=ComputerUseConfig(desktop="sandbox", session_lifetime="run"),
        authority=replace(case.desktop.authority, spec=spec, producer_run_id=run_id),
    )
    await runtime.provision(resolved, case.payload, case.store, case.drive)
    assert runtime.SandboxWorkspaceService.open.await_args.kwargs["identity"].run_id == run_id


@pytest.mark.parametrize(
    "failure", ["directory", "unavailable", "provider", "missing_ref", "missing_row"]
)
async def test_desktop_attach_fails_closed_instead_of_using_a_replacement(case, failure):
    resource = case.resource
    if failure == "directory":
        case.workspace.working_dir.return_value = "/other-workspace"
    elif failure == "unavailable":
        case.workspace.working_dir.side_effect = WorkspaceUnavailableError("lost reference")
    elif failure == "provider":
        case.workspace.working_dir.side_effect = WorkspaceError("provider refused the attachment")
    elif failure == "missing_ref":
        resource = resource.model_copy(update={"workspace_ref": None})
    else:
        resource = resource.model_copy(update={"workspace_id": None})
    with pytest.raises(EnvironmentNotReady):
        async with runtime.open_view(resource, case.desktop):
            pytest.fail("An invalid original workspace must never become a desktop view")
    if failure not in ("missing_ref", "missing_row"):
        case.close.assert_awaited_once()
    runtime.open_sandbox_desktop.assert_not_awaited()


async def test_existing_desktop_attaches_exact_provider_ref_without_turn_admission_or_reset(case):
    async with runtime.open_view(case.resource, case.desktop) as view:
        assert isinstance(view, runtime.DesktopEnvironmentView)
    call = runtime.SandboxWorkspaceService.attach_live_environment.await_args
    assert call.kwargs["ref"] == case.resource.workspace_ref
    assert call.kwargs["workspace_id"] == case.resource.workspace_id
    runtime.SandboxWorkspaceService.open.assert_not_awaited()
    runtime.open_sandbox_desktop.assert_not_awaited()
    case.close.assert_awaited_once()


async def test_browser_attach_uses_exact_target_without_navigation_or_sign_in_copy(
    case, monkeypatch
):
    target = BrowserTarget(context_id="original-context", target_id="original-target")
    resource = BrowserEnvironmentResource(
        environment_id=case.payload.environment_id,
        organization_id=case.ctx.organization_id,
        cdp_url="http://browser:9222",
        tabs={"main": target},
    )
    calls = []

    @asynccontextmanager
    async def page(**options):
        calls.append(options)
        yield AsyncMock()

    monkeypatch.setattr(runtime, "open_page", page)
    async with runtime.open_view(resource, case.browser) as view:
        assert isinstance(view, runtime.BrowserEnvironmentView)
    assert calls[0]["retained"] == target and calls[0]["start_url"] is None
    assert "sign_ins" not in calls[0]
    resource.tabs.clear()
    with pytest.raises(EnvironmentNotReady):
        async with runtime.open_view(resource, case.browser):
            pytest.fail("No target means no replacement browser")


async def test_private_resource_kind_mismatch_is_controlled(case):
    with pytest.raises(EnvironmentNotReady):
        async with runtime.open_view(case.resource, case.browser):
            pytest.fail("A desktop may not be presented as a browser")


async def test_disposal_deduplicates_browser_contexts_and_never_purges_shared_files(
    case, monkeypatch
):
    target = BrowserTarget(context_id="same-context", target_id="page-a")
    resource = BrowserEnvironmentResource(
        environment_id=case.payload.environment_id,
        organization_id=case.ctx.organization_id,
        cdp_url="http://browser:9222",
        tabs={"a": target, "b": target.model_copy(update={"target_id": "page-b"})},
    )
    destroy = AsyncMock()
    monkeypatch.setattr(runtime, "dispose_browser_target", destroy)
    await runtime.dispose(resource)
    assert destroy.await_count == 1
    await runtime.dispose(case.resource)
    assert destroy.await_count == 1


@pytest.mark.parametrize("backend", ["daemon", "e2b"])
async def test_standalone_provider_is_owned_and_closed_only_at_the_right_boundary(
    case, monkeypatch, backend
):
    config = ComputerUseConfig(
        desktop=backend, daemon_url="http://desktop:8765", session_lifetime="conversation"
    )
    configured = replace(case.desktop, config=config)
    if backend == "daemon":
        factory = MagicMock(return_value=case.computer)
        monkeypatch.setattr(runtime, "DaemonComputer", factory)
        await runtime.provision(configured, case.payload, case.store, case.drive)
        case.computer.capture.assert_awaited_once()
        case.computer.close.assert_awaited_once()
        resource = case.store.await_args.args[0]
        assert resource.backend == "daemon"
        case.computer.close.reset_mock()
        async with runtime.open_view(resource, configured):
            pass
        case.computer.close.assert_awaited_once()
    else:
        provider = MagicMock()
        provider.destroy = AsyncMock()
        factory = MagicMock(return_value=provider)
        monkeypatch.setattr(runtime, "E2BWorkspace", factory)
        monkeypatch.setattr(runtime, "Workspace", MagicMock(return_value=case.workspace))
        case.workspace.ref = WorkspaceRef(provider="e2b", id="owned-separate-desktop")
        await runtime.provision(configured, case.payload, case.store, case.drive)
        resource = case.store.await_args.args[0]
        assert resource.backend == "e2b" and resource.workspace_ref == case.workspace.ref
        provider.destroy.assert_not_awaited()
        async with runtime.open_view(resource, configured):
            pass
        assert provider.backend.call_args.args[0] == case.workspace.ref
        await runtime.dispose(resource)
        provider.destroy.assert_awaited_once_with(case.workspace.ref)
    runtime.SandboxWorkspaceService.open.assert_not_awaited()


@pytest.mark.parametrize("journal_fails", [False, True])
async def test_failed_e2b_capture_destroys_known_resource_even_when_journaling_fails(
    case, monkeypatch, journal_fails
):
    provider = MagicMock()
    provider.destroy = AsyncMock()
    monkeypatch.setattr(runtime, "E2BWorkspace", MagicMock(return_value=provider))
    monkeypatch.setattr(runtime, "Workspace", MagicMock(return_value=case.workspace))
    case.workspace.ref = WorkspaceRef(provider="e2b", id="failed-created-desktop")
    case.computer.capture.side_effect = ComputerError("No first picture")
    if journal_fails:
        case.store.side_effect = OSError("Database temporarily unavailable")
    with pytest.raises(ComputerError, match="No first picture"):
        await runtime.provision(
            replace(case.desktop, config=ComputerUseConfig(desktop="e2b")),
            case.payload,
            case.store,
            case.drive,
        )
    provider.destroy.assert_awaited_once_with(case.workspace.ref)


async def test_browser_and_desktop_pictures_do_not_confuse_navigation_or_input_space(case):
    import io

    from PIL import Image

    from app.agents.browser_events import BrowserCommand
    from app.agents.capabilities.computer_use._backends import Capture

    page = AsyncMock()
    page.location.return_value = ("https://example.com/", "Current page")
    page.screenshot.return_value = "data:image/jpeg;base64,AA=="
    browser_view = runtime.BrowserEnvironmentView(page)
    picture = await runtime.picture(browser_view)
    assert picture.navigable and picture.url == "https://example.com/"
    await runtime.perform(
        browser_view, BrowserCommand(type="navigate", url="https://example.com/next")
    )
    page.navigate.assert_awaited_once_with("https://example.com/next")
    image = io.BytesIO()
    Image.new("RGB", (1280, 800), "navy").save(image, format="PNG")
    case.computer.capture.return_value = Capture(image=image.getvalue(), width=1280, height=800)
    desktop_view = runtime.DesktopEnvironmentView(case.computer, 1280, 800)
    with pytest.raises(ComputerError):
        await runtime.perform(desktop_view, BrowserCommand(type="click", x=640, y=400))
    picture = await runtime.picture(desktop_view)
    assert (
        not picture.navigable
        and picture.url is None
        and picture.image.startswith("data:image/jpeg;base64,")
    )
    await runtime.perform(desktop_view, BrowserCommand(type="click", x=640, y=400))
    action = case.computer.perform.await_args.args[0]
    assert action.x == 640 and action.y == 400
    with pytest.raises(ComputerError):
        await runtime.perform(
            desktop_view, BrowserCommand(type="navigate", url="https://example.com/")
        )
    with pytest.raises(ComputerError):
        await runtime.perform(desktop_view, BrowserCommand(type="type"))


async def test_provider_start_runs_outside_the_admission_transaction_and_journals_before_ready(
    case, monkeypatch
):
    from app.services import conversation_environment_driver
    from app.services.conversation_environments import ConversationEnvironmentService

    active = []

    @asynccontextmanager
    async def session():
        active.append(True)
        try:
            yield case.db
        finally:
            active.pop()

    monkeypatch.setattr(runtime, "get_worker_db_context", session)
    monkeypatch.setattr(
        ConversationEnvironmentService, "claim", AsyncMock(return_value=case.desktop)
    )
    monkeypatch.setattr(
        ConversationEnvironmentService, "store_resource", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(ConversationEnvironmentService, "ready", AsyncMock(return_value=True))
    monkeypatch.setattr(ConversationEnvironmentService, "failed", AsyncMock())
    closed = []

    class Driver:
        def __init__(self, _key, _ctx, _control, check):
            self.check = check

        async def acquire(self):
            async with session() as db:
                await self.check(db)

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(conversation_environment_driver, "EnvironmentDriver", Driver)

    async def provision(resolved, payload, store, drive, *, attempt):
        assert attempt == 1
        assert not active and resolved is case.desktop and payload == case.payload
        async with drive("physical"):
            assert await store(case.resource, "physical")
        ConversationEnvironmentService.ready.assert_not_awaited()

    monkeypatch.setattr(runtime, "provision", provision)
    await runtime.start_environment(case.payload, attempt=1)
    assert closed == [True]
    ConversationEnvironmentService.store_resource.assert_awaited_once_with(
        case.payload, 1, case.resource, "physical"
    )
    ConversationEnvironmentService.ready.assert_awaited_once_with(case.payload, 1)
    ConversationEnvironmentService.failed.assert_not_awaited()


async def test_stale_provision_admission_never_contacts_any_provider(case, monkeypatch):
    from app.services.conversation_environments import ConversationEnvironmentService

    monkeypatch.setattr(ConversationEnvironmentService, "claim", AsyncMock(return_value=None))
    provision = AsyncMock()
    monkeypatch.setattr(runtime, "provision", provision)
    await runtime.start_environment(case.payload, attempt=1)
    provision.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    [
        ComputerError("First picture failed"),
        EnvironmentNotReady("backend_not_supported", "Unsupported manual scope"),
    ],
)
async def test_provision_failure_settles_a_typed_reason_without_replaying_provider_effects(
    case, monkeypatch, failure
):
    from app.services.conversation_environments import ConversationEnvironmentService

    monkeypatch.setattr(
        ConversationEnvironmentService, "claim", AsyncMock(return_value=case.desktop)
    )
    monkeypatch.setattr(ConversationEnvironmentService, "failed", AsyncMock())
    monkeypatch.setattr(runtime, "provision", AsyncMock(side_effect=failure))
    with pytest.raises(type(failure)):
        await runtime.start_environment(case.payload, attempt=1)
    reason = (
        failure.refusal.code if isinstance(failure, EnvironmentNotReady) else "provisioning_failed"
    )
    ConversationEnvironmentService.failed.assert_awaited_once_with(case.payload, reason=reason)
    assert runtime.provision.await_count == 1


async def test_database_failure_during_settlement_cannot_replace_caller_cancellation(
    case, monkeypatch, caplog
):
    import asyncio

    from app.services.conversation_environments import ConversationEnvironmentService

    monkeypatch.setattr(
        ConversationEnvironmentService, "claim", AsyncMock(return_value=case.desktop)
    )
    monkeypatch.setattr(
        ConversationEnvironmentService,
        "failed",
        AsyncMock(side_effect=OSError("Database unreachable")),
    )
    monkeypatch.setattr(runtime, "provision", AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await runtime.start_environment(case.payload, attempt=1)
    assert "environment_provision_settlement_failed" in caplog.text


@pytest.mark.parametrize("missing", [True, False])
async def test_provider_guard_rechecks_current_admission_fingerprint(case, monkeypatch, missing):
    from app.services.conversation_environments import ConversationEnvironmentService

    monkeypatch.setattr(
        ConversationEnvironmentService,
        "claim",
        AsyncMock(return_value=None if missing else case.desktop),
    )
    with pytest.raises(ConflictError):
        await runtime._check_provision(case.db, case.payload, 1, "different-fingerprint")
