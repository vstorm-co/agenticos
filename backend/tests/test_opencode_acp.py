"""OpenCode owns provider credentials; Go never borrows another model namespace."""

import json

import pytest

from app.agents.capabilities.coding_agent import _acp as acp
from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.agents.capabilities.external_acp._catalog import inspect_session, session_catalog
from app.services.device_hub import workspace as workspace_module
from tests.test_coding_agent_acp import (
    Computer,
    ScriptedAgent,
    ScriptedPipe,
    _ctx,
    _local_workspace,
    _run,
)

pytestmark = pytest.mark.anyio


def options(current: str = "opencode/free-model") -> list[dict[str, object]]:
    return [
        {
            "id": "model",
            "category": "model",
            "currentValue": current,
            "options": [
                {"value": "opencode/free-model", "name": "Free model"},
                {"value": "opencode-go/paid-model", "name": "Go model"},
                {"value": "custom/my-model", "name": "Custom model"},
            ],
        }
    ]


class OpenCodeAgent(ScriptedAgent):
    def __init__(
        self, *, current: str = "opencode/free-model", delayed: bool = False, refuse: bool = False
    ) -> None:
        super().__init__()
        self.current = current
        self.delayed = delayed
        self.refuse = refuse

    def on_message(self, message: dict[str, object]) -> None:
        method = message.get("method")
        if method == "session/set_config_option":
            self.seen.append(message)
            self.out.append(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {"configOptions": options("opencode-go/paid-model")},
                }
            )
        elif method == "session/prompt" and self.refuse:
            self.seen.append(message)
            self.out.append(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32000, "message": "No subscription"},
                }
            )
        else:
            super().on_message(message)
            if method == "session/new":
                self.out[-1]["result"]["configOptions"] = (
                    [] if self.delayed else options(self.current)
                )
                if self.delayed:
                    self.out.append(
                        self._update(
                            {
                                "sessionUpdate": "config_option_update",
                                "configOptions": options(self.current),
                            }
                        )
                    )


class OpenCodeComputer(Computer):
    def __init__(self, agent: ScriptedAgent, *, go: bool = False) -> None:
        super().__init__(agent)
        self.go = go

    async def call(
        self, session_id: object, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        result = await super().call(session_id, op, args, timeout=timeout)
        if op == "agent.open":
            result.update(
                runtime_name="OpenCode Go" if self.go else "OpenCode", refresh_catalog=True
            )
            if self.go:
                result["model_prefix"] = "opencode-go/"
        return result


async def test_opencode_discovers_a_delayed_provider_catalog_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = OpenCodeComputer(OpenCodeAgent(delayed=True))
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("opencode")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert [model["id"] for model in result["models"]] == [
        "opencode/free-model",
        "opencode-go/paid-model",
        "custom/my-model",
    ]
    assert not result["refresh_pending"]
    assert not any(message.get("method") == "session/prompt" for message in computer.agent.seen)
    assert computer.ops[-1] == "agent.close"


async def test_go_catalog_filters_other_providers_without_replacing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = OpenCodeComputer(OpenCodeAgent(delayed=True), go=True)
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("opencode-go")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert [model["id"] for model in result["models"]] == ["opencode-go/paid-model"]
    assert result["model_prefix"] == "opencode-go/" and result["current_model"] is None
    assert all("api_key" not in args and "env" not in args for _, args in computer.arguments)


@pytest.mark.parametrize("model", [None, "opencode/free-model", "custom/my-model", "opencode-go/"])
async def test_go_refuses_a_non_go_or_unknown_primary_model_before_inference(
    monkeypatch: pytest.MonkeyPatch, model: str | None
) -> None:
    computer = OpenCodeComputer(OpenCodeAgent(), go=True)
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("opencode-go", model_id=model)
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "requires an opencode-go primary model" in result
    assert not any(message.get("method") == "session/prompt" for message in computer.agent.seen)
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize("model", [None, "opencode-go/paid-model"])
async def test_go_runs_only_the_explicit_or_already_selected_go_model(
    monkeypatch: pytest.MonkeyPatch, model: str | None
) -> None:
    computer = OpenCodeComputer(OpenCodeAgent(current="opencode-go/paid-model"), go=True)
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = json.loads(
        await ExternalAcp("opencode-go", model_id=model)
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert result["outcome"] == "completed" and result["runtime_name"] == "OpenCode Go"
    assert computer.ops[-1] == "agent.close"


async def test_a_rejected_go_request_does_not_retry_a_free_or_paid_api_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = OpenCodeComputer(
        OpenCodeAgent(current="opencode-go/paid-model", refuse=True), go=True
    )
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("opencode-go")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "refused" in result
    assert (
        len(
            [
                message
                for message in computer.agent.seen
                if message.get("method") == "session/prompt"
            ]
        )
        == 1
    )
    assert not any(
        message.get("method") == "session/set_config_option" for message in computer.agent.seen
    )


async def test_an_empty_catalog_times_out_as_pending_instead_of_claiming_no_models() -> None:
    class Empty(OpenCodeAgent):
        def on_message(self, message: dict[str, object]) -> None:
            super().on_message(message)
            if message.get("method") == "session/new":
                self.out[-1]["result"]["configOptions"] = []

    pipe = ScriptedPipe(Empty())
    result = await inspect_session(
        pipe,
        root="/w",
        auth_method=None,
        timeout_seconds=1,
        wait_for_updates=True,
        refresh_seconds=0,
    )
    assert result.refresh_pending and result.models == [] and pipe.closed


def test_the_first_config_option_in_a_category_has_acp_priority() -> None:
    first = options("opencode-go/paid-model")[0]
    other = options()[0]
    result = session_catalog({"configOptions": [first, other]})
    assert result.current_model == "opencode-go/paid-model"


@pytest.mark.parametrize("result", [[], "unexpected", 1])
async def test_malformed_protocol_results_fail_with_cleanup(result: object) -> None:
    class Broken(ScriptedAgent):
        def on_message(self, message: dict[str, object]) -> None:
            super().on_message(message)
            if message.get("method") == "initialize":
                self.out[-1]["result"] = result

    pipe = ScriptedPipe(Broken())
    with pytest.raises(acp.AcpError, match="non-object"):
        await inspect_session(pipe, root="/w", auth_method=None, timeout_seconds=1)
    assert pipe.closed


async def test_a_missing_stop_reason_is_not_reported_as_a_completed_task() -> None:
    class NoStopReason(ScriptedAgent):
        def on_message(self, message: dict[str, object]) -> None:
            if message.get("method") == "session/prompt":
                self.seen.append(message)
                self.out.append({"jsonrpc": "2.0", "id": message["id"], "result": {}})
            else:
                super().on_message(message)

    with pytest.raises(acp.AcpError, match="did not report"):
        await _run(NoStopReason())


async def test_go_refuses_a_model_change_acknowledged_as_another_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class WrongModel(OpenCodeAgent):
        def on_message(self, message: dict[str, object]) -> None:
            super().on_message(message)
            if message.get("method") == "session/set_config_option":
                self.out[-1]["result"]["configOptions"] = options("custom/my-model")

    computer = OpenCodeComputer(WrongModel(), go=True)
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("opencode-go", model_id="opencode-go/paid-model")
        .get_toolset()
        .tools["run_acp_agent"]
        .function(_ctx(_local_workspace(), []), "Fix the test")
    )
    assert "did not confirm" in result
    assert not any(message.get("method") == "session/prompt" for message in computer.agent.seen)
    assert computer.ops[-1] == "agent.close"


async def test_an_unknown_native_model_constraint_closes_the_pipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FutureConstraint(OpenCodeComputer):
        async def call(
            self, session_id: object, op: str, args: dict[str, object], *, timeout: float
        ) -> dict[str, object]:
            result = await super().call(session_id, op, args, timeout=timeout)
            if op == "agent.open":
                result["model_prefix"] = "unknown/"
            return result

    computer = FutureConstraint(OpenCodeAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("opencode")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert "unsupported model constraints" in result and computer.ops[-1] == "agent.close"


async def test_go_catalog_keeps_choices_for_its_current_go_model() -> None:
    result = await inspect_session(
        ScriptedPipe(OpenCodeAgent(current="opencode-go/paid-model")),
        root="/w",
        auth_method=None,
        timeout_seconds=1,
        model_prefix="opencode-go/",
    )
    assert result.current_model == "opencode-go/paid-model"


@pytest.mark.parametrize(
    "opened",
    [
        None,
        {},
        {"configOptions": [None]},
        {"configOptions": [{"category": "model", "currentValue": 1}]},
    ],
)
def test_no_default_model_is_inferred_from_missing_or_malformed_settings(
    opened: dict[str, object] | None,
) -> None:
    assert acp.current_session_model(opened) is None
