"""Kimi uses its own login and leaves CLI model defaults untouched."""

import json

import pytest

from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.services.device_hub import workspace as workspace_module
from tests.test_coding_agent_acp import Computer, _ctx, _local_workspace
from tests.test_cursor_acp import CursorAgent

pytestmark = pytest.mark.anyio


class KimiAgent(CursorAgent):
    def __init__(
        self, *, method: str = "login", human: bool = False, fail_on: str | None = None
    ) -> None:
        super().__init__(fail_on=fail_on)
        self.method = method
        self.human = human

    def on_message(self, message: dict[str, object]) -> None:
        if message.get("method") == "session/prompt" and self.human:
            self.seen.append(message)
            self.out.append(
                {
                    "jsonrpc": "2.0",
                    "id": 500,
                    "method": "session/request_permission",
                    "params": {
                        "toolCall": {"title": "AskUserQuestion"},
                        "options": [
                            {
                                "optionId": "q0_opt_0",
                                "kind": "allow_once",
                                "name": "Delete everything",
                            }
                        ],
                    },
                }
            )
            return
        super().on_message(message)
        if message.get("method") == "initialize":
            self.out[-1]["result"]["authMethods"] = [{"id": self.method, "type": "terminal"}]


class KimiComputer(Computer):
    async def call(
        self, session_id: object, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        result = await super().call(session_id, op, args, timeout=timeout)
        if op == "agent.open":
            result.update(auth_method="login", runtime_name="Kimi Code", configuration_policy="cli")
        return result


async def test_kimi_checks_login_and_inspects_without_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = KimiComputer(KimiAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("kimi")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert result["current_model"] == "account-model" and result["configuration_policy"] == "cli"
    assert any(
        m.get("method") == "authenticate" and m["params"] == {"methodId": "login"}
        for m in computer.agent.seen
    )
    assert not any(m.get("method") == "session/prompt" for m in computer.agent.seen)
    assert computer.ops[-1] == "agent.close"


async def test_kimi_runs_configured_model_without_setting_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = KimiComputer(KimiAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("kimi")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert result["outcome"] == "completed" and result["runtime_name"] == "Kimi Code"
    assert not any(m.get("method") == "session/set_config_option" for m in computer.agent.seen)
    assert computer.ops[-1] == "agent.close"


@pytest.mark.security
async def test_kimi_does_not_answer_a_human_question_as_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = KimiComputer(KimiAgent(human=True))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("kimi")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "needs a human answer" in result
    assert any(
        m.get("id") == 500 and m.get("result") == {"outcome": {"outcome": "cancelled"}}
        for m in computer.agent.seen
    )
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize("phase", ["authenticate", "session/prompt"])
async def test_kimi_refusal_does_not_select_another_provider(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    computer = KimiComputer(KimiAgent(fail_on=phase))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("kimi")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "refused" in result
    assert sum(m.get("method") == phase for m in computer.agent.seen) == 1
    assert computer.ops[-1] == "agent.close"


@pytest.mark.security
async def test_kimi_refuses_unknown_auth_method_before_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = KimiComputer(KimiAgent(method="api-key"))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("kimi")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "login method" in result
    assert not any(
        m.get("method") in {"authenticate", "session/prompt"} for m in computer.agent.seen
    )
    assert computer.ops[-1] == "agent.close"


async def test_kimi_model_override_is_refused_before_protocol_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = KimiComputer(KimiAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("kimi", model_id="account-model")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "Choose its model in the CLI" in result
    assert not computer.agent.seen
    assert computer.ops[-1] == "agent.close"
