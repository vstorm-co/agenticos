"""Control-plane operations always use the connection's own key."""

from unittest.mock import AsyncMock

import e2b
import pytest
from pydantic_ai.workspaces import WorkspaceRef, WorkspaceUnavailableError

from app.agents.capabilities.sandbox import _e2b as module

pytestmark = pytest.mark.anyio


async def test_e2b_create_attach_and_destroy_never_use_the_process_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create, connect, kill = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(e2b.AsyncSandbox, "create", create)
    monkeypatch.setattr(e2b.AsyncSandbox, "connect", connect)
    monkeypatch.setattr(e2b.AsyncSandbox, "kill", kill)
    factory = module.E2BWorkspace(api_key="tenant-key", template="desktop")
    assert "tenant-key" not in repr(factory)
    backend = factory.backend(None)
    assert await backend._create() is create.return_value
    assert create.call_args.kwargs["api_key"] == "tenant-key"
    assert create.call_args.kwargs["lifecycle"] == {"on_timeout": "pause"}
    assert await backend._attach("kept") is connect.return_value
    assert connect.call_args.kwargs["api_key"] == "tenant-key"
    await factory.destroy(WorkspaceRef(provider="e2b", id="kept"))
    kill.assert_awaited_once_with("kept", api_key="tenant-key")


@pytest.mark.parametrize(
    "failure",
    [
        e2b.AuthenticationException("bad"),
        e2b.SandboxException("gone"),
        e2b.ServiceBusyException("busy"),
        TimeoutError("late"),
    ],
)
async def test_e2b_creation_failure_is_explicit(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    monkeypatch.setattr(e2b.AsyncSandbox, "create", AsyncMock(side_effect=failure))
    with pytest.raises(WorkspaceUnavailableError):
        await module.OrgE2BBackend(api_key="key")._create()


@pytest.mark.parametrize(
    "failure",
    [
        e2b.AuthenticationException("bad"),
        e2b.SandboxException("gone"),
        e2b.RateLimitException("busy"),
        e2b.ServiceBusyException("busy"),
        TimeoutError("late"),
    ],
)
async def test_e2b_attach_failure_never_creates_a_replacement(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    create = AsyncMock()
    monkeypatch.setattr(e2b.AsyncSandbox, "create", create)
    monkeypatch.setattr(e2b.AsyncSandbox, "connect", AsyncMock(side_effect=failure))
    with pytest.raises(WorkspaceUnavailableError) as refused:
        await module.OrgE2BBackend(api_key="key")._attach("kept")
    assert "files went" not in str(refused.value)
    create.assert_not_called()
