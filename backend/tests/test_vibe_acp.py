"""Vibe browser auth is key-backed; credential status is sanitized, never guessed."""

import json

import pytest

from app.agents.capabilities.coding_agent import _acp as acp
from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.services.device_hub import workspace as workspace_module
from tests.test_coding_agent_acp import Computer, ScriptedPipe, _ctx, _local_workspace, _nothing
from tests.test_cursor_acp import CursorAgent

pytestmark = pytest.mark.anyio


class VibeAgent(CursorAgent):
    def __init__(self, *, status: object = None, refuse: str | None = None) -> None:
        super().__init__(fail_on=refuse)
        self.status = (
            status
            if status is not None
            else {"authenticated": True, "authState": "os_keyring", "signOutAvailable": True}
        )

    def on_message(self, message: dict[str, object]) -> None:
        if message.get("method") == "_auth/status":
            self.seen.append(message)
            if self.fail_on == "_auth/status":
                self.out.append({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601}})
            else:
                self.out.append({"jsonrpc": "2.0", "id": message["id"], "result": self.status})
        else:
            super().on_message(message)
            if message.get("method") == "initialize":
                self.out[-1]["result"]["authMethods"] = [
                    {"id": "browser-auth", "name": "Mistral sign-in"}
                ]


class VibeComputer(Computer):
    async def call(
        self, session_id: object, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        result = await super().call(session_id, op, args, timeout=timeout)
        if op == "agent.open":
            result.update(
                auth_method="browser-auth", runtime_name="Mistral Vibe", configuration_policy="cli"
            )
        return result


@pytest.mark.security
@pytest.mark.parametrize(
    "state,source,logout",
    [
        ("os_keyring", "os_keyring", True),
        ("vibe_home_env_file", "cli_file", True),
        ("process_env", "environment", False),
    ],
)
async def test_vibe_reports_actual_key_source_without_exposing_identity_or_secrets(
    monkeypatch: pytest.MonkeyPatch, state: str, source: str, logout: bool
) -> None:
    computer = VibeComputer(
        VibeAgent(
            status={
                "authenticated": True,
                "authState": state,
                "signOutAvailable": logout,
                "token": "must-not-leak",
                "accountEmail": "private@example.test",
                "configError": "private config",
            }
        )
    )
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("vibe")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    catalog = json.loads(result)
    assert catalog["configuration_policy"] == "cli"
    assert catalog["credentials"] == {
        "kind": "api_key",
        "source": source,
        "sign_out_available": logout,
    }
    assert (
        "must-not-leak" not in result
        and "private@" not in result
        and "private config" not in result
    )
    assert not any(message.get("method") == "session/prompt" for message in computer.agent.seen)
    assert computer.ops[-1] == "agent.close"


async def test_vibe_task_records_credential_facts_in_its_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = VibeComputer(VibeAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("vibe")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert result["outcome"] == "completed"
    assert result["credentials"]["source"] == "os_keyring"
    assert result["runtime_name"] == "Mistral Vibe"
    assert computer.ops[-1] == "agent.close"


@pytest.mark.security
@pytest.mark.parametrize(
    "status",
    [
        {},
        {"authenticated": "true", "authState": "os_keyring", "signOutAvailable": True},
        {"authenticated": True, "authState": "future", "signOutAvailable": True},
        {"authenticated": False, "authState": "signed_out", "signOutAvailable": False},
        {"authenticated": True, "authState": "auth_not_required", "signOutAvailable": False},
        {"authenticated": True, "authState": "unsupported_provider", "signOutAvailable": False},
    ],
)
async def test_vibe_refuses_unknown_or_unavailable_credentials_before_inference(
    monkeypatch: pytest.MonkeyPatch, status: object
) -> None:
    computer = VibeComputer(VibeAgent(status=status))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("vibe")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "credential" in result
    assert not any(message.get("method") == "session/prompt" for message in computer.agent.seen)
    assert computer.ops[-1] == "agent.close"


async def test_vibe_without_its_status_contract_fails_instead_of_guessing_billing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = VibeComputer(VibeAgent(refuse="_auth/status"))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("vibe")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert "refused" in result and computer.ops[-1] == "agent.close"


async def test_vibe_model_selection_cannot_rewrite_the_native_cli_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = VibeComputer(VibeAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("vibe", model_id="account-model")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "manages model settings" in result
    assert not computer.agent.seen
    assert computer.ops[-1] == "agent.close"


async def test_older_vibe_desktop_replies_still_preserve_cli_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Older(VibeComputer):
        async def call(
            self, session_id: object, op: str, args: dict[str, object], *, timeout: float
        ) -> dict[str, object]:
            result = await super().call(session_id, op, args, timeout=timeout)
            if op == "agent.open":
                result.pop("configuration_policy")
            return result

    computer = Older(VibeAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("vibe", model_id="account-model")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "manages model settings" in result and not computer.agent.seen
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize("policy", ["unknown", [], None])
async def test_an_unknown_native_configuration_policy_refuses_discovery(
    monkeypatch: pytest.MonkeyPatch, policy: object
) -> None:
    class Unknown(VibeComputer):
        async def call(
            self, session_id: object, op: str, args: dict[str, object], *, timeout: float
        ) -> dict[str, object]:
            result = await super().call(session_id, op, args, timeout=timeout)
            if op == "agent.open":
                result["configuration_policy"] = policy
            return result

    computer = Unknown(VibeAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("vibe")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert "unsupported configuration policy" in result and computer.ops[-1] == "agent.close"


async def test_cli_configuration_policy_also_refuses_reasoning_overrides() -> None:
    agent = VibeAgent()
    pipe = ScriptedPipe(agent)
    with pytest.raises(acp.AcpError, match="manages model settings"):
        await acp.run_task(
            pipe,
            harness="custom",
            access="edit",
            root="/w",
            task="Fix the test",
            timeout_seconds=1,
            shown=_nothing,
            effort="high",
            configuration_policy="cli",
        )
    assert not agent.seen and pipe.closed
