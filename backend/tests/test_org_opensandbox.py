"""Explicit organization credentials and non-destructive OpenSandbox lifecycle."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from opensandbox.exceptions import SandboxException
from opensandbox.transport import RetryPolicy
from pydantic import SecretStr
from pydantic_ai.workspaces import CommandResult, Workspace, WorkspaceRef, WorkspaceUnavailableError
from pydantic_ai_harness.opensandbox_sandbox import OpenSandbox, OpenSandboxBackend
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.sandbox._opensandbox import OpenSandboxWorkspace, OrgOpenSandboxBackend
from app.agents.capabilities.sandbox._recording import RecordingWorkspace
from app.db.models.agent_workspace import AgentWorkspace
from app.services.sandbox_workspace import OpenWorkspace, SandboxWorkspaceService

pytestmark = pytest.mark.anyio


def provider() -> OpenSandboxWorkspace:
    return OpenSandboxWorkspace(
        server_url="https://sandbox.example.test:8443/",
        api_key=SecretStr("organization-key"),
        image="python:3.12-slim",
    )


@pytest.mark.security
def test_connection_uses_the_organization_key_without_environment_fallback(monkeypatch):
    monkeypatch.setenv("OPEN_SANDBOX_API_KEY", "another-organization-key")
    workspace = provider()
    connection = workspace.connection()
    assert connection.api_key == connection.get_api_key() == "organization-key"
    assert connection.domain == "https://sandbox.example.test:8443"
    assert connection.protocol == "https"
    assert connection.use_server_proxy and connection.disable_metrics
    assert connection.retry_policy == RetryPolicy.disabled()
    assert "organization-key" not in repr(workspace)
    assert workspace.provider == "opensandbox"


@pytest.mark.security
@pytest.mark.parametrize("change", ["key", "url", "image"])
def test_invalid_provider_configuration_never_selects_a_global_account(change):
    with pytest.raises(ValueError):
        OpenSandboxWorkspace(
            server_url="ftp://sandbox.example.test"
            if change == "url"
            else "https://sandbox.example.test",
            api_key=SecretStr("" if change == "key" else "organization-key"),
            image=" " if change == "image" else "python:3.12-slim",
        )


def test_creation_and_reattachment_are_distinct_and_lazy():
    workspace = provider()
    fresh = workspace.backend(None)
    assert fresh.ref is None
    ref = WorkspaceRef(provider="opensandbox", id="existing-workspace")
    resumed = workspace.backend(ref)
    assert resumed.ref == ref


@pytest.mark.security
@pytest.mark.parametrize("stage", ["create", "attach"])
@pytest.mark.parametrize(
    "error", [SandboxException("provider-secret"), WorkspaceUnavailableError("provider-secret")]
)
async def test_preparation_errors_do_not_disclose_server_bodies(stage, error):
    backend = provider().backend(None)
    with (
        patch.object(OpenSandboxBackend, f"_{stage}", AsyncMock(side_effect=error)),
        pytest.raises(WorkspaceUnavailableError) as refused,
    ):
        if stage == "create":
            await backend._create()
        else:
            await backend._attach("existing")
    assert "provider-secret" not in str(refused.value)
    if stage == "attach":
        assert "No replacement or empty workspace was created" in str(refused.value)


async def test_command_contract_and_transport_failure_redaction():
    backend = provider().backend(None)
    result = CommandResult(exit_code=0, stdout="ok", stderr="")
    with patch.object(OpenSandboxBackend, "run", AsyncMock(return_value=result)) as run:
        assert await backend.run(["printf", "ok"], env={"LANG": "C"}, timeout=5) == result
    run.assert_awaited_once_with(["printf", "ok"], shell=False, env={"LANG": "C"}, timeout=5)
    with (
        patch.object(
            OpenSandboxBackend, "run", AsyncMock(side_effect=SandboxException("provider-secret"))
        ),
        pytest.raises(WorkspaceUnavailableError) as refused,
    ):
        await backend.run("pwd")
    assert "provider-secret" not in str(refused.value)


async def test_cancellation_and_programming_errors_are_not_masked():
    backend = provider().backend(None)
    for error in (asyncio.CancelledError(), ValueError("programming defect")):
        with (
            patch.object(OpenSandboxBackend, "run", AsyncMock(side_effect=error)),
            pytest.raises(type(error)),
        ):
            await backend.run("pwd")


async def test_destruction_uses_the_recorded_ref_and_reports_failure():
    workspace = provider()
    ref = WorkspaceRef(provider="opensandbox", id="existing")
    with patch.object(OpenSandbox, "destroy", AsyncMock()) as destroy:
        await workspace.destroy(ref)
        destroy.assert_awaited_once_with(ref)
    with (
        patch.object(
            OpenSandbox, "destroy", AsyncMock(side_effect=SandboxException("provider-secret"))
        ),
        pytest.raises(WorkspaceUnavailableError) as refused,
    ):
        await workspace.destroy(ref)
    assert "provider-secret" not in str(refused.value)


@pytest.mark.parametrize(
    "case", ["success", "bad_command", "sdk_error", "no_ref", "cancelled", "cleanup_error"]
)
async def test_probe_always_closes_its_transport_and_cleans_its_own_sandbox(case):
    backend = MagicMock(spec=OrgOpenSandboxBackend)
    ref = WorkspaceRef(provider="opensandbox", id="probe-owned-sandbox")
    backend.ref = None if case == "no_ref" else ref
    backend.run = AsyncMock(
        return_value=CommandResult(
            exit_code=1 if case == "bad_command" else 0,
            stdout="agenticos-opensandbox-ok",
            stderr="",
        )
    )
    backend.aclose = AsyncMock()
    if case == "sdk_error":
        backend.run.side_effect = SandboxException("provider-secret")
    elif case == "cancelled":
        backend.run.side_effect = asyncio.CancelledError()
    with (
        patch.object(OpenSandboxWorkspace, "backend", return_value=backend),
        patch.object(OpenSandboxWorkspace, "destroy", AsyncMock()) as destroy,
    ):
        if case == "cleanup_error":
            destroy.side_effect = WorkspaceUnavailableError("cleanup failed")
        if case in {"bad_command", "sdk_error", "cleanup_error"}:
            with pytest.raises(WorkspaceUnavailableError):
                await provider().probe()
        elif case == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await provider().probe()
        else:
            await provider().probe()
    backend.aclose.assert_awaited_once()
    if case == "no_ref":
        destroy.assert_not_awaited()
    else:
        destroy.assert_awaited_once_with(ref)


@pytest.mark.parametrize("fails", [False, True])
async def test_closing_a_run_closes_the_transport_even_when_settlement_fails(fails):
    service = SandboxWorkspaceService(MagicMock(spec=AsyncSession))
    service._settle_session = AsyncMock(return_value=False)
    service._prune_spills = AsyncMock()
    if fails:
        service._settle_session.side_effect = RuntimeError("database unavailable")
    close = AsyncMock()
    workspace = OpenWorkspace(
        workspace=MagicMock(spec=Workspace),
        kind="service",
        scope="conversation",
        scope_key="own",
        row_id=None,
        close_transport=close,
    )
    result = await service.close(workspace)
    assert (result is not None) == fails
    close.assert_awaited_once()


@pytest.mark.parametrize("stored", [None, "existing"])
async def test_a_lost_workspace_retains_its_ref_until_an_explicit_reset(stored):
    db = MagicMock(spec=AsyncSession)
    row = MagicMock(spec=AgentWorkspace, session_id=stored)
    db.get = AsyncMock(return_value=row)
    service = SandboxWorkspaceService(db)
    ref = WorkspaceRef(provider="opensandbox", id="existing")
    workspace_provider = provider()
    recorder = RecordingWorkspace(
        Workspace(workspace_provider.backend(ref)),
        db=db,
        organization_id=uuid4(),
        session_key="own",
        agent_id=None,
    )
    recorder.lost = True
    opened = OpenWorkspace(
        workspace=recorder,
        kind="service",
        scope="conversation",
        scope_key="own",
        row_id=uuid4(),
        sandbox=workspace_provider,
    )
    with patch(
        "app.services.sandbox_workspace.workspace_repo.record_session", AsyncMock()
    ) as record:
        assert await service._settle_session(opened)
    if stored is None:
        record.assert_awaited_once_with(db, workspace=row, session_id="existing")
    else:
        record.assert_not_awaited()
