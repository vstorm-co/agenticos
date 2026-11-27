"""New opaque sandboxes retain cleanup ownership when desktop startup fails midway."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr
from pydantic_ai.workspaces import WorkspaceRef

from app.agents.capabilities.computer_use._backends import ComputerError
from app.agents.capabilities.sandbox._e2b import E2BWorkspace
from app.agents.capabilities.sandbox._opensandbox import OpenSandboxWorkspace
from app.services import conversation_environment_runtime as runtime
from tests.test_conversation_environment_runtime import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture(params=["e2b", "opensandbox"])
def opaque(case, request, monkeypatch):
    provider = (
        E2BWorkspace(api_key="test-only-key")
        if request.param == "e2b"
        else OpenSandboxWorkspace(
            server_url="http://provider.invalid",
            api_key=SecretStr("test-only-key"),
            image="desktop",
        )
    )
    opened = replace(case.opened, sandbox=provider)
    runtime.SandboxWorkspaceService.open.return_value = opened
    case.workspace.ref = None
    destroyed = AsyncMock()
    monkeypatch.setattr(type(provider), "destroy", destroyed)
    return case, WorkspaceRef(provider=provider.provider, id="new-opaque-session"), destroyed


@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_new_opaque_startup_journals_exact_observed_ref_before_propagating(
    opaque, cancelled
):
    case, ref, destroyed = opaque

    async def partial(workspace, **_options):
        workspace.ref = ref
        if cancelled:
            raise asyncio.CancelledError()
        raise ComputerError("Desktop startup failed after provider creation")

    runtime.open_sandbox_desktop.side_effect = partial
    with pytest.raises(asyncio.CancelledError if cancelled else ComputerError):
        await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    runtime.workspace_repo.record_live_session.assert_not_awaited()
    runtime.pending_destroy_repo.add.assert_awaited_once()
    receipt = runtime.pending_destroy_repo.add.await_args.kwargs
    assert receipt["ref_id"] == ref.id
    assert receipt["organization_id"] == case.ctx.organization_id
    assert receipt["connection_id"] == case.opened.connection_id
    destroyed.assert_not_awaited()
    case.close.assert_awaited_once()


async def test_failed_cleanup_journal_falls_back_to_destroy_only_new_unpublished_ref(opaque):
    case, ref, destroyed = opaque
    runtime.pending_destroy_repo.add.side_effect = OSError("Cleanup DB unavailable")

    async def partial(workspace, **_options):
        workspace.ref = ref
        raise ComputerError("Original desktop startup failure")

    runtime.open_sandbox_desktop.side_effect = partial
    with pytest.raises(ComputerError, match="Original desktop"):
        await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    destroyed.assert_awaited_once_with(ref)
    case.close.assert_awaited_once()


async def test_failed_existing_shared_workspace_is_never_destroyed_or_reowned(opaque):
    case, ref, destroyed = opaque
    case.workspace.ref = ref
    runtime.open_sandbox_desktop.side_effect = ComputerError("Existing desktop unavailable")
    with pytest.raises(ComputerError):
        await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    runtime.pending_destroy_repo.add.assert_not_awaited()
    destroyed.assert_not_awaited()


async def test_successfully_published_new_shared_workspace_is_retained(opaque):
    case, ref, destroyed = opaque

    async def complete(workspace, **_options):
        workspace.ref = ref
        return case.computer

    runtime.open_sandbox_desktop.side_effect = complete
    await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    assert runtime.workspace_repo.record_live_session.await_args.kwargs["session_id"] == ref.id
    assert case.store.await_args.args[0].workspace_ref == ref
    runtime.pending_destroy_repo.add.assert_not_awaited()
    destroyed.assert_not_awaited()


@pytest.mark.parametrize(
    "journal_timeout,destroy_failure", [(True, None), (False, "error"), (True, "timeout")]
)
async def test_cleanup_failures_and_timeouts_are_visible_without_hiding_startup_error(
    opaque, monkeypatch, caplog, journal_timeout, destroy_failure
):
    import anyio

    case, ref, destroyed = opaque
    original_timeout = anyio.move_on_after

    def short_timeout(seconds, **options):
        return original_timeout(0.01 if seconds in (5, 10) else seconds, **options)

    monkeypatch.setattr(runtime.anyio, "move_on_after", short_timeout)

    async def hang(*_args, **_kwargs):
        await anyio.sleep_forever()

    runtime.pending_destroy_repo.add.side_effect = (
        hang if journal_timeout else OSError("Journal DB failed")
    )
    if destroy_failure == "error":
        destroyed.side_effect = OSError("Provider cleanup failed")
    elif destroy_failure == "timeout":
        destroyed.side_effect = hang

    async def partial(workspace, **_options):
        workspace.ref = ref
        raise ComputerError("Original startup error")

    runtime.open_sandbox_desktop.side_effect = partial
    with pytest.raises(ComputerError, match="Original startup error"):
        await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    assert destroyed.await_count == 1
    messages = [record.message for record in caplog.records]
    if journal_timeout:
        assert "environment_cleanup_journal_timed_out" in messages
    else:
        assert "environment_cleanup_journal_failed" in messages
    if destroy_failure == "timeout":
        assert "environment_provision_cleanup_timed_out" in messages
    elif destroy_failure == "error":
        assert "environment_provision_cleanup_failed" in messages
    assert "test-only-key" not in caplog.text


async def test_cleanup_helper_without_connection_identity_cannot_destroy_arbitrary_ref(opaque):
    case, ref, destroyed = opaque
    opened = replace(case.opened, connection_id=None)
    await runtime._journal_unpublished_sandbox(opened, case.ctx.organization_id, ref)
    runtime.pending_destroy_repo.add.assert_not_awaited()
    destroyed.assert_not_awaited()


async def test_new_opaque_session_losing_workspace_publication_is_journaled_once(opaque):
    case, ref, destroyed = opaque
    runtime.workspace_repo.record_live_session.return_value = False

    async def complete(workspace, **_options):
        workspace.ref = ref
        return case.computer

    runtime.open_sandbox_desktop.side_effect = complete
    with pytest.raises(runtime.EnvironmentNotReady, match="changed while it was starting"):
        await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    runtime.pending_destroy_repo.add.assert_awaited_once()
    assert runtime.pending_destroy_repo.add.await_args.kwargs["ref_id"] == ref.id
    destroyed.assert_not_awaited()
    assert case.store.await_count == 1


async def test_cleanup_helper_never_journals_a_nonopaque_shared_provider(case):
    assert case.opened.sandbox is None
    await runtime._journal_unpublished_sandbox(
        case.opened,
        case.ctx.organization_id,
        WorkspaceRef(provider="sandboxd", id="named-shared-session"),
    )
    runtime.pending_destroy_repo.add.assert_not_awaited()
