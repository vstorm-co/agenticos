"""Cline owns account/key transport and never implicitly selects another provider."""

import json

import pytest

from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.services.device_hub import workspace as workspace_module
from tests.test_coding_agent_acp import Computer, _ctx, _local_workspace
from tests.test_cursor_acp import CursorAgent

pytestmark = pytest.mark.anyio


class ClineAgent(CursorAgent):
    def on_message(self, message: dict[str, object]) -> None:
        super().on_message(message)
        if message.get("method") == "initialize":
            self.out[-1]["result"]["authMethods"] = [{"id": "cline", "name": "Cline"}]


class ClineComputer(Computer):
    def __init__(self, agent: ClineAgent, *, api_key_mode: bool = False) -> None:
        super().__init__(agent)
        self.api_key_mode = api_key_mode

    async def call(
        self, session_id: object, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        result = await super().call(session_id, op, args, timeout=timeout)
        if op == "agent.open":
            result.update(runtime_name="Cline API key" if self.api_key_mode else "Cline")
            if not self.api_key_mode:
                result["auth_method"] = "cline"
        return result


@pytest.mark.parametrize("api_key_mode", [False, True])
async def test_cline_discovers_the_session_catalog_without_copying_credentials(
    monkeypatch: pytest.MonkeyPatch, api_key_mode: bool
) -> None:
    computer = ClineComputer(ClineAgent(), api_key_mode=api_key_mode)
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("cline")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert result["current_model"] == "account-model"
    authentication = [
        message for message in computer.agent.seen if message.get("method") == "authenticate"
    ]
    assert len(authentication) == (0 if api_key_mode else 1)
    if authentication:
        assert authentication[0]["params"] == {"methodId": "cline"}
    assert not any(message.get("method") == "session/prompt" for message in computer.agent.seen)
    assert all("env" not in args and "api_key" not in args for _, args in computer.arguments)
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize("api_key_mode", [False, True])
async def test_cline_streams_an_account_or_key_task_with_native_tool_steps(
    monkeypatch: pytest.MonkeyPatch, api_key_mode: bool
) -> None:
    computer = ClineComputer(ClineAgent(), api_key_mode=api_key_mode)
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("cline", model_id="account-model")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert result["outcome"] == "completed" and result["answer"] == "Done."
    assert result["runtime_name"] == ("Cline API key" if api_key_mode else "Cline")
    assert computer.agent.replied == {"outcome": {"outcome": "selected", "optionId": "ok"}}
    assert computer.ops[-1] == "agent.close"


@pytest.mark.security
@pytest.mark.parametrize("api_key_mode", [False, True])
async def test_cline_quota_or_credential_refusal_is_not_retried_through_a_saved_account(
    monkeypatch: pytest.MonkeyPatch, api_key_mode: bool
) -> None:
    computer = ClineComputer(ClineAgent(fail_on="session/prompt"), api_key_mode=api_key_mode)
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("cline")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "refused" in result
    assert sum(message.get("method") == "session/prompt" for message in computer.agent.seen) == 1
    assert computer.ops[-1] == "agent.close"
