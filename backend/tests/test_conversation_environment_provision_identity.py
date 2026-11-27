"""Provisioning journals the executor identity actually opened, not a later configuration."""

from dataclasses import replace

import pytest

from app.services import conversation_environment_runtime as runtime
from app.services.conversation_environment_policy import EnvironmentNotReady
from app.services.sandbox_connection import SandboxConnectionService
from tests.test_conversation_environment_runtime import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_journal_keeps_original_opened_identity_without_resolving_a_new_credential(case):
    case.opened.connection_fingerprint = "captured-connection-A"
    SandboxConnectionService.resolve.return_value = replace(
        SandboxConnectionService.resolve.return_value, token="newly-rotated-credential-B"
    )
    await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    resources = [call.args[0] for call in case.store.await_args_list]
    assert resources and all(
        resource.connection_fingerprint == "captured-connection-A" for resource in resources
    )
    SandboxConnectionService.resolve.assert_not_awaited()
    runtime.open_sandbox_desktop.assert_awaited_once()


async def test_unknown_opened_identity_refuses_before_provider_start_and_closes_transport(case):
    case.opened.connection_fingerprint = None
    with pytest.raises(EnvironmentNotReady):
        await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    SandboxConnectionService.resolve.assert_not_awaited()
    runtime.open_sandbox_desktop.assert_not_awaited()
    case.store.assert_not_awaited()
    case.close.assert_awaited_once()
