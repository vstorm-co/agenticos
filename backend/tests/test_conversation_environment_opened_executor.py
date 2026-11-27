"""Provider startup uses the executor identity checked by its admitted settings."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from app.agents.capabilities.computer_use import ComputerUseConfig
from app.services import conversation_environment_runtime as runtime
from app.services.conversation_environment_policy import EnvironmentNotReady
from tests.test_conversation_environment_runtime import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_expected_executor_A_cannot_start_actual_opened_executor_B(case):
    configured = replace(case.desktop, connection_fingerprint="expected-A")
    case.opened.connection_fingerprint = "opened-B"
    with pytest.raises(EnvironmentNotReady):
        await runtime.provision(configured, case.payload, case.store, case.drive)
    case.store.assert_not_awaited()
    assert case.calls == []
    runtime.open_sandbox_desktop.assert_not_awaited()
    case.close.assert_awaited_once()


async def test_matching_expected_and_opened_executor_preserves_the_actual_identity(case):
    configured = replace(case.desktop, connection_fingerprint="expected-A")
    case.opened.connection_fingerprint = "expected-A"
    await runtime.provision(configured, case.payload, case.store, case.drive)
    assert case.store.await_count == 2
    assert all(
        call.args[0].connection_fingerprint == "expected-A" for call in case.store.await_args_list
    )
    assert [action for action, _ in case.calls] == ["acquired", "released"]
    runtime.open_sandbox_desktop.assert_awaited_once()
    case.close.assert_awaited_once()


async def test_independent_daemon_does_not_require_a_sandbox_connection_identity(case, monkeypatch):
    configured = replace(
        case.desktop,
        config=ComputerUseConfig(desktop="daemon", daemon_url="http://daemon.invalid"),
        connection_fingerprint=None,
    )
    computer = AsyncMock()
    monkeypatch.setattr(runtime, "DaemonComputer", lambda *args: computer)
    await runtime.provision(configured, case.payload, case.store, case.drive)
    computer.capture.assert_awaited_once()
    computer.close.assert_awaited_once()
    assert case.store.await_args.args[0].backend == "daemon"
    runtime.SandboxWorkspaceService.open_for_environment.assert_not_awaited()
    runtime.open_sandbox_desktop.assert_not_awaited()
    case.close.assert_not_awaited()
