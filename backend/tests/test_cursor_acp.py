"""Cursor account ACP: negotiated login, scoped choices and explicit human refusal."""

import json

import pytest

from app.agents.capabilities.coding_agent import _acp as acp
from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.services.device_hub import workspace as workspace_module
from tests.test_coding_agent_acp import Computer, ScriptedAgent, _ctx, _local_workspace

pytestmark = pytest.mark.anyio


def model_options(current: str = "account-model") -> list[dict[str, object]]:
    return [
        {
            "id": "model",
            "category": "model",
            "currentValue": current,
            "options": [{"value": "account-model", "name": "Account model"}],
        }
    ]


class CursorAgent(ScriptedAgent):
    def __init__(self, *, fail_on: str | None = None) -> None:
        super().__init__(fail_on=fail_on)

    def on_message(self, message: dict[str, object]) -> None:
        method = message.get("method")
        if method == "authenticate" and self.fail_on != method:
            self.seen.append(message)
            self._result(message, {})
        elif method == "session/set_config_option":
            self.seen.append(message)
            self._result(message, {"configOptions": model_options()})
        else:
            super().on_message(message)
            if method == "initialize" and self.fail_on != method:
                self.out[-1]["result"]["authMethods"] = [{"id": "cursor_login", "name": "Cursor"}]
            if method == "session/new" and self.fail_on != method:
                self.out[-1]["result"]["configOptions"] = model_options()


class CursorComputer(Computer):
    async def call(
        self, session_id: object, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        result = await super().call(session_id, op, args, timeout=timeout)
        if op == "agent.open":
            result.update(auth_method="cursor_login", runtime_name="Cursor")
        return result


async def test_cursor_authenticates_and_discovers_models_without_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = CursorComputer(CursorAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("cursor")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert result["current_model"] == "account-model"
    assert [model["id"] for model in result["models"]] == ["account-model"]
    assert any(
        message.get("method") == "authenticate"
        and message["params"] == {"methodId": "cursor_login"}
        for message in computer.agent.seen
    )
    assert not any(message.get("method") == "session/prompt" for message in computer.agent.seen)
    assert computer.ops[-1] == "agent.close"


async def test_cursor_runs_with_its_account_model_and_reports_its_runtime_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = CursorComputer(CursorAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("cursor", model_id="account-model")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert result["outcome"] == "completed" and result["runtime_name"] == "Cursor"
    assert any(
        message.get("method") == "session/set_config_option" for message in computer.agent.seen
    )
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize("phase", ["authenticate", "session/new", "session/prompt"])
async def test_cursor_refusal_does_not_retry_another_account(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    computer = CursorComputer(CursorAgent(fail_on=phase))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("cursor")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "refused" in result
    assert sum(message.get("method") == phase for message in computer.agent.seen) == 1
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize("method", ["cursor/ask_question", "cursor/create_plan"])
async def test_a_cursor_human_request_is_cancelled_and_never_auto_approved(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    class HumanInput(CursorAgent):
        def on_message(self, message: dict[str, object]) -> None:
            if message.get("method") == "session/prompt":
                self.seen.append(message)
                self.out.append(
                    {
                        "jsonrpc": "2.0",
                        "id": 500,
                        "method": method,
                        "params": {"toolCallId": "human"},
                    }
                )
            else:
                super().on_message(message)

    computer = CursorComputer(HumanInput())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("cursor")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "needs a human answer or plan approval" in result
    assert any(
        message.get("id") == 500 and message.get("result") == {"outcome": {"outcome": "cancelled"}}
        for message in computer.agent.seen
    )
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize(
    "chunk",
    [
        "\n\nPlease sign in to continue",
        "\n\nUpgrade your plan to continue",
        "Add a payment method to continue",
        "Add a payment method to continue.",
        "\n\nError: [unauthenticated] Backend rejected authentication. Reauthenticate.",
    ],
)
async def test_observed_cursor_failure_chunks_cannot_be_reported_as_success(
    monkeypatch: pytest.MonkeyPatch, chunk: str
) -> None:
    class FailureChunk(CursorAgent):
        def on_message(self, message: dict[str, object]) -> None:
            if message.get("method") == "session/prompt":
                self.seen.append(message)
                self.out.extend(
                    [
                        self._update(
                            {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": chunk},
                            }
                        ),
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "result": {"stopReason": "end_turn"},
                        },
                    ]
                )
            else:
                super().on_message(message)

    computer = CursorComputer(FailureChunk())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("cursor")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "requires account sign-in or a billing change" in result
    assert computer.ops[-1] == "agent.close"


def test_an_answer_quoting_an_error_stays_an_answer_for_other_runtimes() -> None:
    update = {
        "sessionUpdate": "agent_message_chunk",
        "content": {"type": "text", "text": "Upgrade your plan to continue"},
    }
    collector = acp._Collector()
    collector.update(update)
    assert collector.said == ["Upgrade your plan to continue"]
    cursor = acp._Collector(cursor_account=True)
    cursor.update(
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "The message says: Upgrade your plan to continue"},
        }
    )
    assert cursor.said
