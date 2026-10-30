"""Desktop sessions use the tenant's E2B key and release resources on every exit."""

from unittest.mock import AsyncMock, MagicMock

import anyio
import anyio.lowlevel
import pytest
from pydantic_ai.workspaces import Workspace, WorkspaceRef

from app.agents.capabilities.computer_use import _backends as module
from app.agents.capabilities.computer_use._actions import Wait

pytestmark = pytest.mark.anyio


def rig(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, MagicMock, MagicMock, AsyncMock, MagicMock]:
    provider = MagicMock(destroy=AsyncMock())
    workspace = MagicMock(ref=WorkspaceRef(provider="e2b", id="desktop-1"))
    desktop = MagicMock(
        capture=AsyncMock(return_value=module.Capture(image=b"frame", width=800, height=600)),
        perform=AsyncMock(),
        apps=AsyncMock(return_value=[]),
    )
    opening = AsyncMock(return_value=desktop)
    factory = MagicMock(return_value=provider)
    monkeypatch.setattr(module, "E2BWorkspace", factory)
    monkeypatch.setattr(module, "Workspace", MagicMock(return_value=workspace))
    monkeypatch.setattr(module, "open_sandbox_desktop", opening)
    return provider, workspace, desktop, opening, factory


async def test_the_desktop_uses_the_tenants_key_and_releases_its_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, workspace, desktop, opening, factory = rig(monkeypatch)
    computer = await module.open_e2b_desktop("tenant-key", width=800, height=600)
    factory.assert_called_once_with(api_key="tenant-key", template="desktop")
    opening.assert_awaited_once_with(workspace, width=800, height=600)
    image = await computer.capture()
    assert image is desktop.capture.return_value
    action = Wait(seconds=1)
    await computer.perform(action)
    desktop.perform.assert_awaited_once_with(action)
    assert await computer.apps() is desktop.apps.return_value
    await computer.close()
    provider.destroy.assert_awaited_once_with(workspace.ref)


async def test_an_e2b_desktop_needs_an_explicit_key(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, _, _, _, _ = rig(monkeypatch)
    with pytest.raises(module.ComputerError, match="E2B key"):
        await module.open_e2b_desktop("", width=800, height=600)
    provider.backend.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [module.ComputerError("not ready"), RuntimeError("bug")],
    ids=["startup-refused", "startup-bug"],
)
async def test_failed_startup_preserves_its_cause_even_if_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException, caplog: pytest.LogCaptureFixture
) -> None:
    provider, workspace, _, opening, _ = rig(monkeypatch)
    opening.side_effect = failure
    provider.destroy.side_effect = RuntimeError("cleanup unavailable")
    with pytest.raises(type(failure)) as raised:
        await module.open_e2b_desktop("tenant-key", width=800, height=600)
    assert raised.value is failure
    provider.destroy.assert_awaited_once_with(workspace.ref)
    assert "e2b desktop not killed" in caplog.text


async def test_cleanup_is_bounded_and_unopened_sessions_need_no_destroy(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    provider, workspace, desktop, _, _ = rig(monkeypatch)
    workspace.ref = None
    computer = module.E2BComputer(provider, workspace, desktop)
    await computer.close()
    provider.destroy.assert_not_called()
    workspace.ref = WorkspaceRef(provider="e2b", id="desktop-1")
    monkeypatch.setattr(module, "E2B_CLEANUP_SECONDS", 0)

    async def blocked(_ref: WorkspaceRef) -> None:
        await anyio.sleep_forever()

    provider.destroy.side_effect = blocked
    await computer.close()
    assert "e2b desktop cleanup timed out" in caplog.text


async def test_cancelling_startup_still_finishes_resource_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, workspace, _, opening, _ = rig(monkeypatch)
    cleaned = anyio.Event()

    async def waiting(_workspace: Workspace, *, width: int, height: int) -> module.Computer:
        assert (width, height) == (800, 600)
        await anyio.sleep_forever()

    async def destroy(_ref: WorkspaceRef) -> None:
        await anyio.lowlevel.checkpoint()
        cleaned.set()

    opening.side_effect = waiting
    provider.destroy.side_effect = destroy
    with anyio.CancelScope() as stopped:
        stopped.cancel()
        await module.open_e2b_desktop("tenant-key", width=800, height=600)
    assert stopped.cancelled_caught
    assert cleaned.is_set()
    provider.destroy.assert_awaited_once_with(workspace.ref)
