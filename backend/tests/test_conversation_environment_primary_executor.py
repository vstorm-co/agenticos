"""Owned desktop startup must use the executor this real run actually opened."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.audience import RunAudience
from app.agents.capabilities.computer_use import ComputerUseConfig
from app.db.models.project import Project
from app.services import conversation_environment_agent as adapter
from app.services.conversation_environment_delegates import SharedDesktopWorkspace
from app.services.conversation_environment_policy import (
    DesktopEnvironmentSettings,
    EnvironmentNotReady,
)
from app.services.conversation_environment_resources import DesktopEnvironmentResource
from app.services.run_project_workspace import RunProjectWorkspace
from app.services.sandbox_workspace import OpenWorkspace
from tests.test_conversation_environment_agent_coordinator import case as case
from tests.workspaces import document_workspace

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def primary(case, monkeypatch):
    owner = case.owner
    owner.kind = "desktop"
    case.row.kind = "desktop"
    connection_id = uuid4()
    captured = SharedDesktopWorkspace(connection_id, "actual-executor", "captured-A")
    owner.workspace = captured
    configured = DesktopEnvironmentSettings(
        case.resolved.authority,
        ComputerUseConfig(desktop="sandbox", session_lifetime="conversation"),
        "fingerprint",
        "",
        connection_fingerprint="captured-A",
    )
    resource = DesktopEnvironmentResource(
        environment_id=case.row.id,
        organization_id=owner.ctx.organization_id,
        backend="sandbox",
        width=1280,
        height=800,
    )
    case.service.live.return_value = case.row, configured, resource
    case.service.read.return_value = case.state(kind="desktop")
    monkeypatch.setattr(adapter, "authority", AsyncMock(return_value=configured.authority))
    settings = AsyncMock(return_value=configured)
    monkeypatch.setattr(adapter, "settings_for", settings)
    monkeypatch.setattr(adapter, "legacy_run_desktop", AsyncMock(return_value=False))
    selected = SimpleNamespace(
        key=captured.scope_key, resolved=SimpleNamespace(row=SimpleNamespace(id=connection_id))
    )
    resolver = AsyncMock(return_value=selected)
    fingerprint = MagicMock(return_value="captured-A")
    monkeypatch.setattr(
        adapter,
        "SandboxWorkspaceService",
        lambda _: SimpleNamespace(
            resolve_live_execution=resolver, environment_connection_fingerprint=fingerprint
        ),
    )
    return SimpleNamespace(
        case=case,
        owner=owner,
        captured=captured,
        configured=configured,
        settings=settings,
        selected=selected,
        resolver=resolver,
        fingerprint=fingerprint,
    )


@pytest.mark.parametrize("target", ["agent", "project"])
@pytest.mark.parametrize("state", ["not_started", "ready"])
async def test_captured_executor_A_cannot_start_or_adopt_fresh_executor_B(primary, target, state):
    p = primary
    p.owner.target = target
    p.owner.workspace = replace(p.captured, execution_target=target)
    admitted = replace(p.configured.authority, execution_target=target)
    if target == "project":
        admitted = replace(admitted, project=Project(id=uuid4(), workspace_generation=uuid4()))
    adapter.authority.return_value = admitted
    p.settings.return_value = replace(
        p.configured, authority=admitted, connection_fingerprint="fresh-B"
    )
    p.fingerprint.return_value = "fresh-B"
    p.case.service.read.return_value = p.case.state(state=state)
    with pytest.raises(EnvironmentNotReady, match="original desktop executor changed"):
        await p.owner.acquire()
    p.case.service.read.assert_not_awaited()
    p.case.service.ensure.assert_not_awaited()
    adapter.runtime.start_environment.assert_not_awaited()
    p.case.driver.acquire.assert_not_awaited()


@pytest.mark.parametrize("changed", ["connection", "key", "resolved_fingerprint"])
async def test_fresh_resolution_cannot_substitute_another_physical_executor(primary, changed):
    p = primary
    if changed == "connection":
        p.selected.resolved.row.id = uuid4()
    elif changed == "key":
        p.selected.key = "another-scope"
    else:
        p.fingerprint.return_value = "fresh-B"
    with pytest.raises(EnvironmentNotReady):
        await p.owner.acquire()
    p.case.service.ensure.assert_not_awaited()
    adapter.runtime.start_environment.assert_not_awaited()


@pytest.mark.parametrize("state", ["not_started", "ready"])
async def test_configuration_flip_after_precheck_is_refused_before_provider_start(primary, state):
    p = primary
    p.case.service.read.return_value = p.case.state(state=state)
    p.case.row.source_run_id = p.owner.run_id
    p.case.row.fingerprint = "new-admission-snapshot"
    with pytest.raises(EnvironmentNotReady, match="admitted desktop executor changed"):
        await p.owner.acquire()
    assert p.case.service.ensure.await_count == (state == "not_started")
    adapter.runtime.start_environment.assert_not_awaited()
    p.case.driver.acquire.assert_not_awaited()


async def test_matching_ready_executor_is_adopted_without_starting_another_provider(primary):
    p = primary
    try:
        assert await p.owner.acquire()
        p.case.driver.acquire.assert_awaited_once()
        p.case.service.ensure.assert_not_awaited()
        adapter.runtime.start_environment.assert_not_awaited()
    finally:
        await p.owner.finish()


def routing(primary, *, opened=True):
    p = primary
    workspace = RunProjectWorkspace(
        document_workspace(),
        p.owner.ctx,
        audience=RunAudience(user_id=p.owner.ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
        open_agent_executor=AsyncMock(),
        agent_execution_available=True,
    )
    if opened:
        workspace.agent_workspace = OpenWorkspace(
            workspace=document_workspace(),
            kind="service",
            scope="conversation",
            scope_key=p.captured.scope_key,
            row_id=uuid4(),
            connection_id=p.captured.connection_id,
            connection_fingerprint=p.captured.connection_fingerprint,
        )
    return workspace


@pytest.mark.parametrize("opened", [False, True])
async def test_actual_nominal_routing_captures_lazy_executor_only_when_it_exists(primary, opened):
    p = primary
    p.owner.workspace = None
    workspace = routing(p, opened=opened)
    assert workspace.ref is None
    p.owner.load = AsyncMock(side_effect=RuntimeError("Reached owned resource load"))
    fallback = AsyncMock()
    with pytest.raises(RuntimeError, match="Reached owned resource load"):
        await p.owner.wrap_computer(fallback)(workspace)
    assert p.owner._routing_workspace is workspace
    assert p.resolver.await_count == int(opened)
    p.case.driver.acquire.assert_awaited_once()
    p.case.service.ensure.assert_not_awaited()
    fallback.assert_not_awaited()


async def test_routed_lazy_executor_A_refuses_fresh_B_before_provider(primary):
    p = primary
    p.owner.workspace = None
    workspace = routing(p)
    p.settings.return_value = replace(p.configured, connection_fingerprint="fresh-B")
    p.fingerprint.return_value = "fresh-B"
    fallback = AsyncMock()
    with pytest.raises(EnvironmentNotReady, match="original desktop executor changed"):
        await p.owner.wrap_computer(fallback)(workspace)
    fallback.assert_not_awaited()
    p.case.service.ensure.assert_not_awaited()
    adapter.runtime.start_environment.assert_not_awaited()


@pytest.mark.parametrize("missing", ["connection_id", "connection_fingerprint"])
async def test_routed_executor_with_unknown_identity_cannot_start_desktop(primary, missing):
    p = primary
    workspace = routing(p)
    setattr(workspace.agent_workspace, missing, None)
    with pytest.raises(EnvironmentNotReady, match="no captured identity"):
        await p.owner.wrap_computer(AsyncMock())(workspace)
    p.resolver.assert_not_awaited()
    p.case.service.ensure.assert_not_awaited()
    adapter.runtime.start_environment.assert_not_awaited()


async def test_routing_target_change_refuses_before_ensure_or_factory(primary):
    p = primary
    workspace = routing(p)
    workspace.execution_target = "project"
    with pytest.raises(EnvironmentNotReady, match="execution target changed"):
        await p.owner.wrap_computer(AsyncMock())(workspace)
    p.resolver.assert_not_awaited()
    p.case.service.ensure.assert_not_awaited()


async def test_independent_daemon_does_not_borrow_primary_sandbox_identity(primary):
    p = primary
    p.settings.return_value = replace(
        p.configured, config=ComputerUseConfig(desktop="daemon"), connection_fingerprint=None
    )
    try:
        assert await p.owner.acquire()
        p.resolver.assert_not_awaited()
        p.case.driver.acquire.assert_awaited_once()
        p.case.service.ensure.assert_not_awaited()
    finally:
        await p.owner.finish()


async def test_project_directory_fourth_argument_keeps_the_actual_lazy_opened_executor(
    primary, monkeypatch
):
    from app.services import conversation_environment_project_files as files

    p = primary
    project = Project(id=uuid4(), workspace_generation=uuid4())
    admitted = replace(p.configured.authority, project=project)
    monkeypatch.setattr(adapter, "authority", AsyncMock(return_value=admitted))
    p.owner.environment_id = p.case.row.id
    p.owner.acquire = AsyncMock(return_value=True)
    lookup = AsyncMock(return_value=f"/project/{uuid4()}")
    monkeypatch.setattr(files, "directory", lookup)
    opened = routing(p).agent_workspace
    assert (
        await p.owner.project_directory(uuid4(), project.id, project.workspace_generation, opened)
        == lookup.return_value
    )
    assert p.owner._opened_workspace is opened


async def test_captured_legacy_ephemeral_executor_keeps_original_factory_without_manual_settings(
    primary, monkeypatch
):
    p = primary
    monkeypatch.setattr(adapter, "legacy_run_desktop", AsyncMock(return_value=True))
    p.settings.side_effect = AssertionError("manual settings must not run for legacy fallback")
    fallback = AsyncMock()
    original = document_workspace()
    result = await p.owner.wrap_computer(fallback)(original)
    assert result is fallback.return_value
    fallback.assert_awaited_once_with(original)
    p.settings.assert_not_awaited()
    p.case.service.ensure.assert_not_awaited()
    adapter.runtime.start_environment.assert_not_awaited()
