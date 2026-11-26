"""Launch-only settings never issue a CLI operation that persists user defaults."""

import json

import pytest

from app.agents.capabilities.coding_agent import _acp as acp
from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.agents.capabilities.external_acp._catalog import session_catalog
from app.services.device_hub import workspace as workspace_module
from tests.test_coding_agent_acp import Computer, ScriptedPipe, _ctx, _local_workspace, _nothing
from tests.test_cursor_acp import CursorAgent

pytestmark = pytest.mark.anyio


class LaunchComputer(Computer):
    async def call(
        self, session_id: object, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        result = await super().call(session_id, op, args, timeout=timeout)
        if op == "agent.open":
            result.update(configuration_policy="launch")
        return result


async def test_delegation_sends_the_launch_model_and_never_writes_cli_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = LaunchComputer(CursorAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    report = json.loads(
        await ExternalAcp("launch", model_id="account-model")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Inspect")
    )
    assert report["outcome"] == "completed"
    assert computer.arguments[0][1]["runtime_model"] == "account-model"
    assert not any(
        message.get("method") in {"session/set_config_option", "session/set_model"}
        for message in computer.agent.seen
    )


@pytest.mark.parametrize("model,effort", [("different-model", None), ("account-model", "high")])
@pytest.mark.security
async def test_launch_settings_are_confirmed_before_a_prompt(
    model: str, effort: str | None
) -> None:
    agent = CursorAgent()
    pipe = ScriptedPipe(agent)
    with pytest.raises(acp.AcpError, match=r"launch model|at launch"):
        await acp.run_task(
            pipe,
            harness="custom",
            access="edit",
            root="/w",
            task="Inspect",
            timeout_seconds=1,
            shown=_nothing,
            model=model,
            effort=effort,
            configuration_policy="launch",
        )
    assert not any(message.get("method") == "session/prompt" for message in agent.seen)
    assert pipe.closed


async def test_launch_default_model_needs_no_configuration_write() -> None:
    agent = CursorAgent()
    report = await acp.run_task(
        ScriptedPipe(agent),
        harness="custom",
        access="edit",
        root="/w",
        task="Inspect",
        timeout_seconds=1,
        shown=_nothing,
        configuration_policy="launch",
    )
    assert report.outcome == "completed"
    assert not any(message.get("method") == "session/set_config_option" for message in agent.seen)


def test_legacy_acp_models_are_discovered_and_acknowledged() -> None:
    opened = {
        "models": {
            "currentModelId": "kimi,thinking",
            "availableModels": [{"modelId": "kimi,thinking", "name": "Kimi thinking"}],
        }
    }
    catalog = session_catalog(opened)
    assert catalog.models_exposed and catalog.current_model == "kimi,thinking"
    assert catalog.models[0].id == "kimi,thinking"
    assert acp.current_session_model(opened) == "kimi,thinking"


@pytest.mark.parametrize(
    "models",
    [
        None,
        {},
        {"availableModels": "bad"},
        {"availableModels": [None]},
        {"currentModelId": 2, "availableModels": []},
        {"currentModelId": "missing", "availableModels": []},
    ],
)
def test_malformed_legacy_models_are_refused(models: object) -> None:
    if models is None:
        assert session_catalog({"models": models}).models == []
    else:
        with pytest.raises(acp.AcpError):
            session_catalog({"models": models})
