"""Devin delegates to its account-owned local CLI and negotiates browser auth."""

import json

import pytest

from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.services.device_hub import workspace as workspace_module
from tests.test_coding_agent_acp import Computer, _ctx, _local_workspace
from tests.test_cursor_acp import CursorAgent

pytestmark = pytest.mark.anyio


class DevinAgent(CursorAgent):
    def __init__(self, *, method: str = "devin-browser", fail_on: str | None = None) -> None:
        super().__init__(fail_on=fail_on)
        self.method = method

    def on_message(self, message: dict[str, object]) -> None:
        super().on_message(message)
        if message.get("method") == "initialize" and self.fail_on != "initialize":
            self.out[-1]["result"]["authMethods"] = [{"id": self.method}]


class DevinComputer(Computer):
    async def call(
        self, session_id: object, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        result = await super().call(session_id, op, args, timeout=timeout)
        if op == "agent.open":
            result.update(
                auth_method="devin-browser", runtime_name="Devin", configuration_policy="cli"
            )
        return result


async def test_devin_inspects_its_account_choices_without_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = DevinComputer(DevinAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("devin")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert result["current_model"] == "account-model" and result["configuration_policy"] == "cli"
    assert any(
        m.get("method") == "authenticate" and m["params"] == {"methodId": "devin-browser"}
        for m in computer.agent.seen
    )
    assert not any(m.get("method") == "session/prompt" for m in computer.agent.seen)
    assert computer.ops[-1] == "agent.close"


async def test_devin_runs_a_local_delegated_task_without_changing_cli_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = DevinComputer(DevinAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("devin")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert result["outcome"] == "completed" and result["runtime_name"] == "Devin"
    assert not any(m.get("method") == "session/set_config_option" for m in computer.agent.seen)
    assert computer.ops[-1] == "agent.close"


@pytest.mark.security
async def test_devin_requires_the_advertised_browser_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = DevinComputer(DevinAgent(method="another-account"))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("devin")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "login method" in result
    assert not any(
        m.get("method") in {"authenticate", "session/prompt"} for m in computer.agent.seen
    )
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize("phase", ["initialize", "authenticate", "session/new", "session/prompt"])
async def test_devin_login_entitlement_or_prompt_failure_has_no_account_fallback(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    computer = DevinComputer(DevinAgent(fail_on=phase))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("devin")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "refused" in result
    assert sum(m.get("method") == phase for m in computer.agent.seen) == 1
    assert computer.ops[-1] == "agent.close"


async def test_devin_refuses_an_unverified_model_override_before_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = DevinComputer(DevinAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("devin", model_id="model")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "Choose its model in the CLI" in result
    assert not computer.agent.seen
    assert computer.ops[-1] == "agent.close"
