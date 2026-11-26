"""Muse's native SDK bridge reports credential facts without account material."""

import json

import pytest

from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.services.device_hub import workspace as workspace_module
from tests.test_coding_agent_acp import Computer, _ctx, _local_workspace
from tests.test_vibe_acp import VibeAgent

pytestmark = pytest.mark.anyio


class MuseAgent(VibeAgent):
    def on_message(self, message: dict[str, object]) -> None:
        super().on_message(message)
        if message.get("method") == "initialize":
            self.out[-1]["result"]["authMethods"] = [{"id": "muse-cli", "name": "Muse"}]
        if (
            self.out
            and isinstance(last := self.out[-1].get("result"), dict)
            and "stopReason" in last
        ):
            self.out.insert(
                -1,
                self._update(
                    {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "Authoritative final answer"},
                        "_meta": {"agenticosFinalAnswer": True},
                    }
                ),
            )


class MuseComputer(Computer):
    async def call(
        self, session_id: object, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        result = await super().call(session_id, op, args, timeout=timeout)
        if op == "agent.open":
            result.update(auth_method="muse-cli", runtime_name="Muse")
        return result


@pytest.mark.parametrize(
    "state,kind,source",
    [
        ("envKey", "api_key", "environment"),
        ("apiKey", "api_key", "cli_file"),
        ("accountLogin", "oauth", "cli_file"),
    ],
)
@pytest.mark.parametrize("tool", ["inspect_acp_agent", "run_acp_agent"])
async def test_muse_reports_effective_credential_lane_without_tokens_or_account_label(
    monkeypatch: pytest.MonkeyPatch, state: str, kind: str, source: str, tool: str
) -> None:
    computer = MuseComputer(
        MuseAgent(
            status={
                "state": state,
                "credentialRequired": True,
                "token": "secret-token",
                "label": "private@example.test",
            }
        )
    )
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    function = ExternalAcp("muse").get_toolset().tools[tool].function
    ctx = _ctx(_local_workspace(), [])
    result = (
        await function(ctx, task="Investigate") if tool == "run_acp_agent" else await function(ctx)
    )
    assert "secret-token" not in result and "private@example" not in result
    report = json.loads(result)
    if tool == "run_acp_agent":
        assert report["answer"] == "Authoritative final answer"
    assert report["credentials"] == {"kind": kind, "source": source, "sign_out_available": False}
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize(
    "status",
    [
        {"state": "loggedOut", "credentialRequired": True},
        {"state": "accountLogin", "credentialRequired": False},
        {"state": "new-source", "credentialRequired": True},
        {"state": "envKey", "credentialRequired": "true"},
        {},
    ],
)
async def test_missing_unknown_or_keyless_credentials_refuse_before_prompt(
    monkeypatch: pytest.MonkeyPatch, status: dict[str, object]
) -> None:
    computer = MuseComputer(MuseAgent(status=status))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("muse")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), task="Work")
    )
    assert "Muse" in result
    assert not any(message.get("method") == "session/prompt" for message in computer.agent.seen)
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize("state", ["envKey", "apiKey", "accountLogin"])
async def test_explicit_api_key_mode_cannot_fall_back_to_a_stored_credential(state: str) -> None:
    from app.agents.capabilities.coding_agent._acp import AcpError, Conversation, _Collector
    from app.agents.capabilities.external_acp._credentials import probe_credentials
    from tests.test_coding_agent_acp import ScriptedPipe, _nothing

    conversation = Conversation(
        ScriptedPipe(MuseAgent(status={"state": state, "credentialRequired": True})),
        access="edit",
        collector=_Collector(),
        shown=_nothing,
    )
    if state == "envKey":
        credentials = await probe_credentials(conversation, "muse-api-key")
        assert credentials is not None and credentials.source == "environment"
    else:
        with pytest.raises(AcpError, match="required environment API key"):
            await probe_credentials(conversation, "muse-api-key")
