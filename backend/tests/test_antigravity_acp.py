"""Antigravity's public ACP contract, with account tests tracked separately."""

import json

import pytest

from app.agents.capabilities.coding_agent._acp import AcpError
from app.agents.capabilities.external_acp import ExternalAcpConfig
from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.agents.capabilities.external_acp._catalog import session_catalog
from app.services.device_hub import workspace as workspace_module
from tests.test_coding_agent_acp import Computer, ScriptedAgent, _ctx, _local_workspace

pytestmark = pytest.mark.anyio

OPTIONS: list[dict[str, object]] = [
    {
        "id": "model",
        "category": "model",
        "currentValue": "account-model",
        "options": [
            {"value": "account-model", "name": "Account model"},
            {"group": "Other", "options": [{"value": "another-model", "name": "Another model"}]},
        ],
    },
    {
        "id": "thinking",
        "category": "thought_level",
        "currentValue": "high",
        "options": [
            {"value": "high", "name": "High"},
            {"value": "low", "name": "Low"},
        ],
    },
]


class AntigravityAgent(ScriptedAgent):
    def __init__(self, *, refuse_login: bool = False, advertise_login: bool = True) -> None:
        super().__init__()
        self.refuse_login = refuse_login
        self.advertise_login = advertise_login

    def on_message(self, message: dict[str, object]) -> None:
        method = message.get("method")
        if method == "authenticate":
            self.seen.append(message)
            self.out.append(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    **(
                        {"error": {"code": -32000, "message": "Authentication required"}}
                        if self.refuse_login
                        else {"result": {}}
                    ),
                }
            )
        elif method == "session/set_config_option":
            self.seen.append(message)
            self.out.append({"jsonrpc": "2.0", "id": message["id"], "result": {}})
        else:
            super().on_message(message)
            if method == "initialize":
                self.out[-1]["result"]["authMethods"] = (
                    [{"id": "oauth-personal", "name": "Google personal"}]
                    if self.advertise_login
                    else []
                )
            elif method == "session/new":
                self.out[-1]["result"]["configOptions"] = OPTIONS


class AntigravityComputer(Computer):
    async def call(
        self, session_id: object, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        result = await super().call(session_id, op, args, timeout=timeout)
        if op == "agent.open":
            result["auth_method"] = "oauth-personal"
            result["runtime_name"] = "Antigravity"
        return result


async def test_discovery_authenticates_personal_account_without_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = AntigravityComputer(AntigravityAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    tool = ExternalAcp("antigravity").get_toolset().tools["inspect_acp_agent"]
    result = json.loads(await tool.function(_ctx(_local_workspace(), [])))
    assert result["models_exposed"] is True
    assert [model["id"] for model in result["models"]] == ["account-model", "another-model"]
    assert result["current_effort"] == "high"
    methods = [message.get("method") for message in computer.agent.seen]
    assert methods == ["initialize", "authenticate", "session/new"]
    assert computer.agent.seen[1]["params"] == {"methodId": "oauth-personal"}
    assert computer.ops[-1] == "agent.close"


async def test_task_honors_native_personal_mode_and_explicit_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computer = AntigravityComputer(AntigravityAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    tool = ExternalAcp("antigravity", model_id="another-model").get_toolset().tools["run_acp_agent"]
    result = json.loads(await tool.function(_ctx(_local_workspace(), []), "Inspect the repository"))
    assert result["outcome"] == "completed"
    assert result["runtime_name"] == "Antigravity"
    messages = computer.agent.seen
    assert next(message for message in messages if message.get("method") == "authenticate")[
        "params"
    ] == {"methodId": "oauth-personal"}
    selected = next(
        message for message in messages if message.get("method") == "session/set_config_option"
    )
    assert selected["params"] == {"sessionId": "s-1", "configId": "model", "value": "another-model"}
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize("refuse_login,advertise_login", [(True, True), (False, False)])
async def test_login_failure_does_not_switch_account_or_billing_mode(
    monkeypatch: pytest.MonkeyPatch, refuse_login: bool, advertise_login: bool
) -> None:
    computer = AntigravityComputer(
        AntigravityAgent(refuse_login=refuse_login, advertise_login=advertise_login)
    )
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    tool = ExternalAcp("antigravity").get_toolset().tools["inspect_acp_agent"]
    result = await tool.function(_ctx(_local_workspace(), []))
    assert "agy acp --login" in result
    assert not any(
        message.get("method") in {"session/new", "session/prompt"}
        for message in computer.agent.seen
    )
    assert computer.ops[-1] == "agent.close"


async def test_discovery_requires_a_desktop_workspace() -> None:
    result = (
        await ExternalAcp("agent").get_toolset().tools["inspect_acp_agent"].function(_ctx(None, []))
    )
    assert "This computer" in result


@pytest.mark.parametrize(
    "opened",
    [
        {"configOptions": None},
        {"configOptions": [{"category": "model", "options": None}]},
        {"configOptions": [{"category": "model", "options": [1]}]},
        {"configOptions": [{"category": "model", "options": [{"value": "", "name": "Empty"}]}]},
        {"configOptions": [{"category": "model", "options": [{"value": "m", "name": "x" * 257}]}]},
        {
            "configOptions": [
                {"category": "model", "options": [{"value": "m", "name": "Model"}] * 2}
            ]
        },
        {
            "configOptions": [
                {
                    "category": "model",
                    "options": [{"value": str(i), "name": "Model"} for i in range(129)],
                }
            ]
        },
        {"configOptions": [{"category": "model", "options": [{"options": [{"options": []}]}]}]},
        {"configOptions": [{"category": "model", "options": [{"options": None}]}]},
        {"configOptions": [{"category": "model", "currentValue": "missing", "options": []}]},
    ],
)
def test_catalog_refuses_invalid_ambiguous_or_unbounded_options(opened: dict[str, object]) -> None:
    with pytest.raises(AcpError):
        session_catalog(opened)


def test_absent_model_settings_are_distinct_from_an_empty_entitled_catalog() -> None:
    absent = session_catalog({"configOptions": [None, {"category": []}, {"category": "other"}]})
    assert not absent.models_exposed
    empty = session_catalog({"configOptions": [{"category": "model", "options": []}]})
    assert empty.models_exposed and empty.models == []
    assert (
        ExternalAcpConfig(agent_id="antigravity", auth_method="oauth-personal").auth_method
        == "oauth-personal"
    )


async def test_discovery_handles_notifications_and_rejects_a_missing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingSession(AntigravityAgent):
        def on_message(self, message: dict[str, object]) -> None:
            super().on_message(message)
            if message.get("method") == "session/new":
                self.out[-1]["result"].pop("sessionId")
                self.out.insert(
                    len(self.out) - 1,
                    self._update(
                        {
                            "sessionUpdate": "tool_call",
                            "toolCallId": "catalog",
                            "kind": "read",
                            "title": "Read model metadata",
                            "status": "pending",
                        }
                    ),
                )

    computer = AntigravityComputer(MissingSession())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("antigravity")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert "discovery failed" in result
    assert computer.ops[-1] == "agent.close"


@pytest.mark.parametrize("mode", ["read_only", "workspace_write"])
async def test_narrower_chat_modes_cannot_start_a_native_agent(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from uuid import uuid4

    from pydantic_ai.workspaces import Workspace, WrapperWorkspace

    from app.schemas.local_target import LocalTarget

    computer = AntigravityComputer(AntigravityAgent())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    workspace = WrapperWorkspace(
        Workspace(
            workspace_module.DeviceWorkspace(uuid4(), uuid4(), LocalTarget(folder="/w", mode=mode))
        )
    )
    tools = ExternalAcp("antigravity").get_toolset().tools
    ctx = _ctx(workspace, [])
    assert "full-access" in await tools["inspect_acp_agent"].function(ctx)
    assert "full-access" in await tools["run_acp_agent"].function(ctx, "Do work")
    assert computer.ops == []


async def test_discovery_reports_a_failed_native_launch_without_claiming_a_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.device_hub.exceptions import DeviceCallFailed

    async def refused(*args: object, **kwargs: object) -> dict[str, object]:
        raise DeviceCallFailed(message="Registration unavailable", details={})

    monkeypatch.setattr(workspace_module._hub, "call", refused)
    result = (
        await ExternalAcp("antigravity")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert "discovery failed" in result
    assert "models" not in result


@pytest.mark.parametrize("methods", [None, [], [None], [{"id": "gemini-api-key"}]])
async def test_an_explicit_personal_login_cannot_use_an_unadvertised_method(
    monkeypatch: pytest.MonkeyPatch, methods: object
) -> None:
    class OtherAuthentication(ScriptedAgent):
        def on_message(self, message: dict[str, object]) -> None:
            super().on_message(message)
            if message.get("method") == "initialize":
                self.out[-1]["result"]["authMethods"] = methods

    computer = Computer(OtherAuthentication())
    monkeypatch.setattr(workspace_module._hub, "call", computer.call)
    result = (
        await ExternalAcp("agent", auth_method="oauth-personal")
        .get_toolset()
        .tools["inspect_acp_agent"]
        .function(_ctx(_local_workspace(), []))
    )
    assert "does not advertise" in result
    assert not any(message.get("method") == "authenticate" for message in computer.agent.seen)
    assert computer.ops[-1] == "agent.close"


async def test_legacy_builtin_initialization_keeps_its_existing_contract() -> None:
    from tests.test_coding_agent_acp import _run

    class Legacy(ScriptedAgent):
        def on_message(self, message: dict[str, object]) -> None:
            super().on_message(message)
            if message.get("method") == "initialize":
                self.out[-1]["result"] = None

    report, _, pipe = await _run(Legacy())
    assert report.outcome == "completed" and pipe.closed
