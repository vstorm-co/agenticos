"""Qwen subscription starts from CLI-owned login without mutating auth settings."""

import json

import pytest

from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.services.device_hub import workspace as workspace_module
from tests.test_coding_agent_acp import Computer, _ctx, _local_workspace
from tests.test_cursor_acp import CursorAgent

pytestmark = pytest.mark.anyio


class QwenAgent(CursorAgent):
    def on_message(self, message: dict[str, object]) -> None:
        super().on_message(message)
        if message.get("method") == "initialize" and self.fail_on != "initialize":
            # Current Qwen ACP advertises only openai even for a subscription startup.
            self.out[-1]["result"]["authMethods"] = [{"id": "openai"}]


class QwenComputer(Computer):
    async def call(
        self, session_id: object, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        result = await super().call(session_id, op, args, timeout=timeout)
        if op == "agent.open":
            result.update(runtime_name="Qwen subscription", configuration_policy="cli")
        return result


async def test_qwen_subscription_inspects_without_reauthenticating_or_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = QwenComputer(QwenAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("qwen-subscription")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert result["current_model"] == "account-model" and result["configuration_policy"] == "cli"
    assert not any(
        m.get("method") in {"authenticate", "session/prompt", "session/set_config_option"}
        for m in computer.agent.seen
    )
    assert computer.ops[-1] == "agent.close"


async def test_qwen_runs_configured_subscription_without_switching_auth_or_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = QwenComputer(QwenAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("qwen-subscription")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert result["outcome"] == "completed" and result["runtime_name"] == "Qwen subscription"
    assert not any(
        m.get("method") in {"authenticate", "session/set_config_option"}
        for m in computer.agent.seen
    )
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize("phase", ["initialize", "session/new", "session/prompt"])
async def test_qwen_subscription_refusal_does_not_fall_back_to_api_auth(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    computer = QwenComputer(QwenAgent(fail_on=phase))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("qwen-subscription")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "refused" in result
    assert not any(m.get("method") == "authenticate" for m in computer.agent.seen)
    assert sum(m.get("method") == phase for m in computer.agent.seen) == 1
    assert computer.ops[-1] == "agent.close"


async def test_qwen_model_override_is_refused_without_submitting_a_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = QwenComputer(QwenAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("qwen-subscription", model_id="api-provider-model")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "Choose its model in the CLI" in result
    assert not computer.agent.seen
    assert computer.ops[-1] == "agent.close"
