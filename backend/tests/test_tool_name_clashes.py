"""Two of an agent's tools under one name (#2890).

Pydantic AI answers a duplicate tool name by raising `UserError` while it lists
the run's tools, which aborts the turn. A connection's prefix keeps one MCP
server's tools apart from another's, but not from a capability's or the
platform's own: a connection `request` whose server offers `capability` presents
`request_capability`, which nearly every agent has. Publish refuses that (see
`test_agent_registry.py`); these hold the run's half, and the names both read.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities import FRAMEWORK_TOOL_NAMES
from app.agents.computer_on_use import RequestComputerOnUse
from app.agents.connect_on_use import ConnectionRequest, ConnectOnUse, PendingService
from app.agents.factory import build_agent
from app.agents.hand_off import CallWorker
from app.agents.mcp import TOOL_NAME_LIMIT, LeftOutOnClash, McpServerSpec, _make_toolset
from app.agents.setup_briefing import SetupBriefing
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.agents.tool_names import PLATFORM_TOOL_NAMES, taken_tool_names
from app.services.mcp_connection import presented_tool_names
from tests.test_agent_spec_and_factory import _model_spec
from tests.test_mcp_connections import _connection

pytestmark = pytest.mark.anyio


def capability() -> str:
    """A server's tool called `capability`."""
    return "x"


def get_objects() -> str:
    """List objects."""
    return "objects"


async def _run(*, toolsets: list, capabilities: list | None = None) -> tuple[list[str], str]:
    """The tool names and instructions a model is handed on a turn's first request."""
    seen: dict = {}

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.setdefault("tools", sorted(tool.name for tool in info.function_tools))
        seen.setdefault("instructions", info.instructions or "")
        return ModelResponse(parts=[TextPart("ok")])

    await Agent(FunctionModel(answer), toolsets=toolsets, capabilities=capabilities or []).run(
        "List the devices."
    )
    return seen["tools"], seen["instructions"]


def _listing(*names: str) -> MagicMock:
    """A toolset listing `names`, as the wrappers under the guard hand them up."""
    inner = MagicMock()
    inner.get_tools = AsyncMock(return_value={name: f"<{name}>" for name in names})
    return inner


class TestTheNamesARunHolds:
    def test_a_capability_s_tools_are_held_under_the_names_its_binding_gives_them(self):
        spec = AgentSpec(
            name="Support",
            capabilities=[
                CapabilityBindingSpec(
                    id="charts", tool_overrides={"create_chart": {"name": "draw_chart"}}
                ),
                CapabilityBindingSpec(id="web_fetch", enabled=False),
            ],
        )

        taken = taken_tool_names(spec)

        assert taken["draw_chart"] == "the charts capability"
        assert "create_chart" not in taken
        assert "web_fetch" not in taken

    def test_the_platform_s_own_tools_are_held_on_every_agent(self):
        """Publish cannot know the surface, and a name free in the console but taken
        in Slack would be an agent that works in one of them."""
        taken = taken_tool_names(AgentSpec(name="Support"))

        assert FRAMEWORK_TOOL_NAMES | {"request_capability"} <= PLATFORM_TOOL_NAMES
        assert {name for name, holder in taken.items() if holder == "this platform"} == (
            PLATFORM_TOOL_NAMES
        )

    def test_the_channel_tools_are_held_although_no_published_spec_binds_them(self):
        """A channel adds them per run, after publish, so publish holds them as it
        holds the platform's own."""
        taken = taken_tool_names(AgentSpec(name="Support"))

        assert taken["get_channel_info"] == "the channel_tools capability"
        assert taken["send_channel_file"] == "the channel_tools capability"

    def test_a_capability_the_registry_does_not_hold_is_left_out(self):
        """Publish refuses it on its own; it must not take the name check down with it."""
        spec = AgentSpec(name="Support", capabilities=[CapabilityBindingSpec(id="no-such")])

        assert taken_tool_names(spec) == taken_tool_names(AgentSpec(name="Support"))


class TestThePlatformsOwnToolsAreAllListed:
    """`PLATFORM_TOOL_NAMES` is kept by hand, and this is what keeps it honest.

    A capability's tools are declared in the registry and read from there. The
    platform's own are not declared anywhere: each is added by its own module,
    on the surfaces that need it - the setup briefing, connecting an account,
    asking for the computer, a voice call's hand-off, tool search's own search.
    One missing from the list is a name an MCP server can take and abort the
    turn with (#2890). So an agent is built with every one of them switched on,
    and whatever the model is offered that no capability declares must be on
    the list. A surface that adds a tool of its own belongs in these builds too.
    """

    @staticmethod
    async def _offered(spec: AgentSpec, **extras: object) -> set[str]:
        """The tool names the model is offered on a turn's first request, output tools too."""
        built = build_agent(
            spec, _model_spec(), organization_id=uuid4(), agent_id=uuid4(), **extras
        )
        seen: list[set[str]] = []

        def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen.append({tool.name for tool in [*info.function_tools, *info.output_tools]})
            if info.output_tools:
                return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {})])
            return ModelResponse(parts=[TextPart("ok")])

        with built.agent.override(model=FunctionModel(answer)):
            await built.agent.run("hello", deps=built.deps)
        return seen[0]

    async def test_every_tool_the_platform_adds_beside_the_capabilities_is_listed(self):
        async def unused() -> str:
            return "unreachable"

        server = FunctionToolset([get_objects])
        surfaces = await self._offered(
            AgentSpec(name="Support"),
            extra_toolsets=[
                server,
                CallWorker(MagicMock(), workspace=None, capability_names=[]).toolset(),
            ],
            extra_capabilities=[
                ConnectOnUse(
                    services=[
                        PendingService(
                            request=ConnectionRequest(
                                catalog_key="notion", name="Notion", gap="not_connected"
                            ),
                            resolve=unused,
                        )
                    ],
                    request_connection=AsyncMock(return_value=False),
                ),
                RequestComputerOnUse(request_access=AsyncMock(return_value=False)),
            ],
        )
        # Tool search defers the server, so its own search is the one tool offered beside it.
        searching = AgentSpec(
            name="Support", capabilities=[{"id": "tool_search", "config": {"strategy": "keywords"}}]
        )
        search = await self._offered(searching, extra_toolsets=[server])
        # A structured answer is an output tool, offered beside every other.
        structured = await self._offered(
            AgentSpec(name="Support", output_schema={"type": "object", "properties": {}})
        )
        declared = {
            name
            for name, holder in taken_tool_names(searching).items()
            if holder != "this platform"
        }

        offered = (surfaces | search | structured) - declared - {"get_objects"}

        assert offered - PLATFORM_TOOL_NAMES == set()
        # Each build did switch its tools on, so an empty difference is not a vacuous one.
        assert offered == PLATFORM_TOOL_NAMES - FRAMEWORK_TOOL_NAMES


class TestTheNamesAConnectionPresents:
    def test_its_prefix_and_each_tool_joined_narrowed_by_both_allowlists_and_fitted(self):
        connection = _connection(
            name="netbox-lab",
            allowed_tools=["get_objects", "x" * 70],
            last_tools=[{"name": "get_objects"}, {"name": "x" * 70}, {"name": "delete"}],
        )

        everything = presented_tool_names(connection, None)
        narrowed = presented_tool_names(connection, ["get_objects"])

        assert everything[0] == ("get_objects", "netbox_lab_get_objects")
        assert everything[1][0] == "x" * 70 and len(everything[1][1]) == TOOL_NAME_LIMIT
        assert len(everything) == 2
        assert narrowed == [("get_objects", "netbox_lab_get_objects")]

    def test_a_connection_nothing_has_reached_presents_nothing_to_compare(self):
        assert presented_tool_names(_connection(), None) == []


class TestAServerLeftOutOnAClash:
    async def test_free_names_keep_every_tool_and_the_server_s_own_instructions(self):
        guarded = LeftOutOnClash(
            FunctionToolset([get_objects], instructions="Use get_objects first."),
            server="netbox",
            binding="the connection 'netbox'",
            taken={"request_capability": "this platform"},
        )

        tools, instructions = await _run(toolsets=[guarded])

        assert tools == ["get_objects"]
        assert instructions == "Use get_objects first."

    async def test_a_taken_name_leaves_the_whole_server_out_and_says_why(self):
        """The server, not the one tool: one tool quietly missing goes unnoticed,
        and the clash is a misconfiguration somebody should fix."""
        guarded = LeftOutOnClash(
            _listing("request_list", "request_capability"),
            server="request",
            binding="the connection 'request'",
            taken={"request_capability": "this platform"},
        )

        assert await guarded.get_tools(MagicMock()) == {}
        briefing = await guarded.get_instructions(MagicMock())
        assert isinstance(briefing, str)
        assert briefing.startswith(
            "The request server (the connection 'request') is not available this turn"
        )
        assert "its tool `request_capability` has the name of a tool this platform" in briefing
        assert "renaming the connection or narrowing its tools" in briefing

    async def test_it_is_decided_again_on_every_step(self):
        """A server that dropped the clashing tool comes back, and stops briefing."""
        inner = _listing("create_chart")
        guarded = LeftOutOnClash(
            inner, server="create", binding="b", taken={"create_chart": "the charts capability"}
        )
        assert await guarded.get_tools(MagicMock()) == {}

        inner.get_tools.return_value = {"create_dashboard": "<create_dashboard>"}

        assert await guarded.get_tools(MagicMock()) == {"create_dashboard": "<create_dashboard>"}
        assert guarded.clash is None

    async def test_the_turn_goes_on_without_the_server_rather_than_aborting(self, monkeypatch):
        """The reproduction in #2890, through a real agent: a connection `request`
        whose server offers `capability`, beside the setup briefing's own
        `request_capability`. Unguarded, the run raises `UserError`; guarded, the
        briefing keeps its tool and the same request is told the server is out."""
        monkeypatch.setattr(
            "app.agents.mcp.MCPToolset", lambda *_a, **_k: FunctionToolset([capability])
        )
        spec = AgentSpec(name="Support")
        briefing = SetupBriefing.for_spec(spec, agent_id=uuid4())
        server = LeftOutOnClash(
            _make_toolset(McpServerSpec(name="request", url="https://r.example/mcp")),
            server="request",
            binding="the connection 'request'",
            taken=taken_tool_names(spec),
        )

        tools, instructions = await _run(toolsets=[server], capabilities=[briefing])

        assert tools == ["request_capability"]
        assert "The request server (the connection 'request') is not available" in instructions
