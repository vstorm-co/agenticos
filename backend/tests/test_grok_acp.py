"""Grok cached account auth is explicit and cannot negotiate an API-key alternative."""

import json

import pytest

from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.services.device_hub import workspace as workspace_module
from tests.test_coding_agent_acp import Computer, _ctx, _local_workspace
from tests.test_cursor_acp import CursorAgent

pytestmark = pytest.mark.anyio


class GrokAgent(CursorAgent):
    def __init__(self, *, methods: list[str] | None = None, fail_on: str | None = None) -> None:
        super().__init__(fail_on=fail_on)
        self.methods = ["cached_token"] if methods is None else methods

    def on_message(self, message: dict[str, object]) -> None:
        super().on_message(message)
        if message.get("method") == "initialize":
            self.out[-1]["result"]["authMethods"] = [
                {"id": method, "name": method} for method in self.methods
            ]


class GrokComputer(Computer):
    async def call(
        self, session_id: object, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        result = await super().call(session_id, op, args, timeout=timeout)
        if op == "agent.open":
            result.update(auth_method="cached_token", runtime_name="Grok")
        return result


async def test_grok_discovers_models_with_cached_headless_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = GrokComputer(GrokAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("grok")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert result["current_model"] == "account-model"
    auth = [m for m in computer.agent.seen if m.get("method") == "authenticate"]
    assert len(auth) == 1 and auth[0]["params"] == {
        "methodId": "cached_token",
        "_meta": {"headless": True},
    }
    assert not any(m.get("method") == "session/prompt" for m in computer.agent.seen)
    assert computer.ops[-1] == "agent.close"


async def test_grok_delegates_one_task_without_importing_its_token_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = GrokComputer(GrokAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("grok", model_id="account-model")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert result["outcome"] == "completed" and result["runtime_name"] == "Grok"
    assert computer.ops[-1] == "agent.close"


@pytest.mark.security
@pytest.mark.parametrize(
    "methods", [[], ["xai.api_key"], ["cached_token", "xai.api_key"], ["grok.com"]]
)
async def test_grok_refuses_an_unconfirmed_account_only_auth_contract(
    monkeypatch: pytest.MonkeyPatch, methods: list[str]
) -> None:
    computer = GrokComputer(GrokAgent(methods=methods))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("grok")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "login method" in result or "API-key authentication to be disabled" in result
    assert not any(
        m.get("method") in {"session/prompt", "authenticate"} for m in computer.agent.seen
    )
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize("phase", ["authenticate", "session/prompt"])
async def test_a_grok_login_or_quota_refusal_does_not_select_an_alternate_method(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    computer = GrokComputer(GrokAgent(fail_on=phase))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("grok")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "refused" in result
    assert sum(m.get("method") == phase for m in computer.agent.seen) == 1
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize("human", [True, False])
async def test_grok_human_question_or_empty_answer_is_not_success(
    monkeypatch: pytest.MonkeyPatch, human: bool
) -> None:
    class StoppedGrok(GrokAgent):
        def on_message(self, message: dict[str, object]) -> None:
            if message.get("method") != "session/prompt":
                super().on_message(message)
                return
            self.seen.append(message)
            if human:
                self.out.append(
                    {"jsonrpc": "2.0", "id": 500, "method": "x.ai/ask_user_question", "params": {}}
                )
            else:
                self._result(message, {"stopReason": "end_turn"})

    computer = GrokComputer(StoppedGrok())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("grok")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert ("needs a human answer" if human else "returned no answer") in result
    if human:
        assert any(
            m.get("id") == 500 and m.get("result") == {"outcome": "cancelled"}
            for m in computer.agent.seen
        )
    assert computer.ops[-1] == "agent.close"


async def test_grok_key_mode_negotiates_the_explicit_key_without_cached_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class KeyComputer(Computer):
        async def call(
            self, session_id: object, op: str, args: dict[str, object], *, timeout: float
        ) -> dict[str, object]:
            result = await super().call(session_id, op, args, timeout=timeout)
            if op == "agent.open":
                result.update(auth_method="xai.api_key", runtime_name="Grok API key")
            return result

    computer = KeyComputer(GrokAgent(methods=["xai.api_key", "cached_token"]))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("grok-key", model_id="account-model")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Inspect")
    )
    assert result["outcome"] == "completed"
    auth = [message for message in computer.agent.seen if message.get("method") == "authenticate"]
    assert [message["params"] for message in auth] == [
        {"methodId": "xai.api_key", "_meta": {"headless": True}}
    ]
