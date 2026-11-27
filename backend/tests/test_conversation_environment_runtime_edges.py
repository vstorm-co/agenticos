"""Provider refusal paths never acquire or substitute an unavailable workspace."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from app.agents.capabilities.computer_use._backends import ComputerError
from app.agents.capabilities.sandbox._recording import RecordingWorkspace
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import ConflictError
from app.services import conversation_environment_runtime as runtime
from app.services.conversation_environment_policy import EnvironmentNotReady
from tests.test_conversation_environment_runtime import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_provider_that_created_no_identity_is_refused_without_destroy_guess(case):
    case.workspace.ref = None
    with pytest.raises(ComputerError, match="identity"):
        runtime._known_ref(case.workspace)


async def test_daemon_admission_ended_during_capture_closes_transport(case, monkeypatch):
    monkeypatch.setattr(runtime, "DaemonComputer", lambda *_args: case.computer)
    config = case.desktop.config.model_copy(update={"desktop": "daemon"})
    case.store.return_value = False
    with pytest.raises(ConflictError):
        await runtime.provision(
            replace(case.desktop, config=config), case.payload, case.store, case.drive
        )
    case.computer.close.assert_awaited_once()


@pytest.mark.parametrize("config", [{}, {"backend": "local"}])
async def test_missing_service_sandbox_never_opens_an_executor(case, config):
    capabilities = [] if not config else [CapabilityBindingSpec(id="sandbox", config=config)]
    authority = replace(
        case.desktop.authority, spec=AgentSpec(name="Desktop", capabilities=capabilities)
    )
    with pytest.raises(EnvironmentNotReady, match="container-backed"):
        await runtime.provision(
            replace(case.desktop, authority=authority), case.payload, case.store, case.drive
        )
    runtime.SandboxWorkspaceService.open.assert_not_awaited()


@pytest.mark.parametrize("missing", ["all", "row_id", "connection_id"])
async def test_missing_workspace_identity_fails_before_provider_start(case, missing):
    runtime.SandboxWorkspaceService.open_for_environment.return_value = (
        None if missing == "all" else replace(case.opened, **{missing: None})
    )
    with pytest.raises(EnvironmentNotReady, match="retained workspace"):
        await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    runtime.open_sandbox_desktop.assert_not_awaited()


async def test_project_desktop_uses_authorized_project_workspace_and_unwraps_recording(
    case, monkeypatch
):
    from app.services import project_workspace_guard

    project = object()
    guard = AsyncMock(return_value=project)
    monkeypatch.setattr(project_workspace_guard, "project_for_workspace", guard)
    wrapped = RecordingWorkspace(
        case.workspace,
        db=case.db,
        organization_id=case.ctx.organization_id,
        session_key="project",
        agent_id=case.desktop.authority.agent.id,
    )
    opened = replace(case.opened, workspace=wrapped, close_transport=None)
    monkeypatch.setattr(
        runtime.SandboxWorkspaceService, "open_project", AsyncMock(return_value=opened)
    )
    resolved = replace(
        case.desktop, authority=replace(case.desktop.authority, execution_target="project")
    )
    await runtime.provision(resolved, case.payload, case.store, case.drive)
    assert runtime.open_sandbox_desktop.await_args.args[0] is case.workspace
    runtime.SandboxWorkspaceService.open.assert_not_awaited()
    runtime.SandboxWorkspaceService.open_project.assert_awaited_once_with(case.ctx, project)


@pytest.mark.parametrize("lost", [None, "replacement"])
async def test_existing_workspace_identity_must_survive_desktop_start(case, lost):
    async def changed(workspace, **_options):
        workspace.ref = None if lost is None else replace(case.workspace.ref, id=lost)
        return case.computer

    runtime.open_sandbox_desktop.side_effect = changed
    with pytest.raises(EnvironmentNotReady, match="original desktop"):
        await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    runtime.workspace_repo.record_live_session.assert_not_awaited()


async def test_canonical_workspace_losing_publication_is_refused(case):
    runtime.workspace_repo.record_live_session.return_value = False
    with pytest.raises(EnvironmentNotReady, match="changed while"):
        await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    runtime.pending_destroy_repo.add.assert_not_awaited()


async def test_ended_environment_cannot_publish_the_new_desktop_handle(case):
    case.store.side_effect = [True, False]
    with pytest.raises(ConflictError):
        await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    case.close.assert_awaited_once()


async def test_standalone_start_failure_without_provider_identity_does_not_guess_a_destroy_target(
    case, monkeypatch
):
    from unittest.mock import MagicMock

    provider = MagicMock()
    provider.destroy = AsyncMock()
    monkeypatch.setattr(runtime, "E2BWorkspace", MagicMock(return_value=provider))
    monkeypatch.setattr(runtime, "Workspace", MagicMock(return_value=case.workspace))
    case.workspace.ref = None
    runtime.open_sandbox_desktop.side_effect = ComputerError("Provider refused before creating")
    configured = replace(
        case.desktop, config=case.desktop.config.model_copy(update={"desktop": "e2b"})
    )
    with pytest.raises(ComputerError, match="before creating"):
        await runtime.provision(configured, case.payload, case.store, case.drive)
    provider.destroy.assert_not_awaited()
    case.store.assert_not_awaited()
