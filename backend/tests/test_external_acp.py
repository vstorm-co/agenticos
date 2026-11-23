"""Desktop ACP registration IDs never become server-supplied executables."""

import json

import pytest
from pydantic import ValidationError

from app.agents.capabilities import CapabilityBinding, CapabilityBuildContext
from app.agents.capabilities.external_acp import ExternalAcpConfig, _build
from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.agents.subagent_events import SubagentEvent
from app.services.device_hub import workspace as workspace_module
from tests.test_coding_agent_acp import Computer, ScriptedAgent, _ctx, _local_workspace

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"agent_id": "../cmd"},
        {"agent_id": "Upper"},
        {"agent_id": "-bad"},
        {"agent_id": "a" * 49},
        {"agent_id": "ok", "command": "sh"},
        {"agent_id": "ok", "access": "read_only"},
        {"agent_id": "ok", "timeout_minutes": 0},
    ],
)
def test_configuration_refuses_commands_read_only_claims_and_invalid_ids(
    config: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ExternalAcpConfig.model_validate(config)


def test_builder_has_no_implicit_program_or_credential() -> None:
    config = ExternalAcpConfig(agent_id="my-agent", timeout_minutes=2)
    built = _build(
        CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="external_acp"), config=config
        )
    )
    assert built.agent_id == "my-agent" and built.timeout_seconds == 120
    assert set(built.get_toolset().tools) == {"run_acp_agent", "inspect_acp_agent"}
    assert "does not promise read-only" in built.get_instructions()
    with pytest.raises(ValidationError):
        _build(
            CapabilityBuildContext(
                binding=CapabilityBinding(capability_id="external_acp"), config=None
            )
        )


async def test_custom_task_uses_shared_acp_lifecycle_with_only_registration_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = Computer(ScriptedAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    frames: list[SubagentEvent] = []
    ctx = _ctx(_local_workspace(), frames)
    keys: list[str] = []
    for identifier in ("first", "second"):
        computer = Computer(ScriptedAgent())
        monkeypatch.setattr(workspace_module._hub, "call", computer.call)
        tool = ExternalAcp(identifier).get_toolset().tools["run_acp_agent"]
        answer = await tool.function(ctx, "Investigate the repository")
        report = json.loads(answer)
        assert report["harness"] == "custom" and report["outcome"] == "completed"
        assert report["answer"] == "Done."
        launch = computer.arguments[0][1]
        assert launch["agent"] == "custom" and launch["custom_agent_id"] == identifier
        assert set(launch) == {
            "agent",
            "custom_agent_id",
            "accepted_protocols",
            "supports_auth_modes",
            "supports_model_constraints",
            "supports_configuration_policy",
            "resume_key",
            "fresh_session",
            "root",
            "mode",
            "work_context",
        }
        keys.append(launch["resume_key"])
        assert computer.ops[-1] == "agent.close"
        new = next(
            message for message in computer.agent.seen if message.get("method") == "session/new"
        )
        assert new["params"] == {"cwd": "/w", "mcpServers": []}
    assert keys[0] != keys[1]
    assert frames[0].harness == "custom"
    assert frames[-1].status == "completed"


async def test_missing_desktop_and_invalid_session_never_start_a_program(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = Computer(ScriptedAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    tool = ExternalAcp("agent").get_toolset().tools["run_acp_agent"]
    assert "This computer" in await tool.function(_ctx(None, []), "Do work")
    ctx = _ctx(None, [])
    ctx.retry = ctx.max_retries
    assert "session name" in await tool.function(ctx, "Do work", session="bad name")
    assert computer.ops == []


@pytest.mark.parametrize("version", [2, True, "1", None])
async def test_wrong_acp_protocol_fails_and_closes_the_process(
    monkeypatch: pytest.MonkeyPatch,
    version: object,
) -> None:
    class WrongVersion(ScriptedAgent):
        def on_message(self, message: dict[str, object]) -> None:
            super().on_message(message)
            if message.get("method") == "initialize":
                self.out[-1]["result"]["protocolVersion"] = version

    computer = Computer(WrongVersion())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    tool = ExternalAcp("agent").get_toolset().tools["run_acp_agent"]
    result = await tool.function(_ctx(_local_workspace(), []), "Do work")
    assert "protocol version 1" in result
    assert computer.ops[-1] == "agent.close"
    assert not any(message.get("method") == "session/new" for message in computer.agent.seen)


async def test_invalid_session_steers_while_a_retry_remains() -> None:
    from pydantic_ai import ModelRetry

    tool = ExternalAcp("agent").get_toolset().tools["run_acp_agent"]
    with pytest.raises(ModelRetry, match="session name"):
        await tool.function(_ctx(None, []), "Do work", session="bad name")


@pytest.mark.security
@pytest.mark.parametrize("method", ["unrecognized", "gemini-api-key", [], {}])
async def test_a_desktop_authentication_requirement_is_never_silently_ignored(
    method: object,
) -> None:
    from app.agents.capabilities.coding_agent import _acp as acp
    from tests.test_coding_agent_acp import FakeDevice

    device = FakeDevice([], opened={"id": "process", "auth_method": method})
    with pytest.raises(acp.AcpError, match="unsupported authentication"):
        await acp.DevicePipe(device, "custom", custom_agent_id="agent").open()
    assert device.calls[-1] == ("agent.close", {"id": "process"})
