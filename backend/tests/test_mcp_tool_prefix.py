"""A connection that skips its tool prefix (#2881): the server's own names, kept apart.

Every MCP tool reaches the model as the connection's prefix and the server's name
joined, so NetBox's `netbox_get_objects` arrived as `netbox_netbox_get_objects` -
longer, harder to predict, and in one agent's case guessed at wrongly. Skipping
the prefix hands the model the server's own names, and gives up the one thing the
prefix guaranteed: that no other tool of the agent has the same name. These tests
hold the rest of that bargain. A server that skips its prefix yields to every
other tool, refused at publish (see `test_agent_registry.py`) and left out of a
turn rather than taking it down.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities import FRAMEWORK_TOOL_NAMES
from app.agents.mcp import (
    AnsweredRecently,
    McpServerSpec,
    OwnToolNames,
    ToolOrigins,
    _answer_key,
    _make_toolset,
    _note_answer,
    name_holder,
    probe_toolsets,
    unreachable_briefing,
)
from app.agents.spec import AgentSpec, CapabilityBindingSpec, OrgMcpServerRef
from app.agents.tool_names import PLATFORM_TOOL_NAMES, taken_tool_names
from app.core.permissions import AuthContext, OrgRoleName
from app.repositories.conversation import ToolCallSeen
from app.schemas.mcp_connection import McpConnectionRead, McpConnectionUpdate
from app.schemas.mention import Mentionable
from app.services import mcp_connection as mcp_connection_service
from app.services.agent_runner import _with_account_notes
from app.services.mcp_connection import (
    AccountNote,
    McpConnectionService,
    UnavailableUnreachableServer,
    unprefixed_tool_names,
)
from app.services.mentions import _note, _tools_named
from tests.test_mcp_connections import _connection

pytestmark = pytest.mark.anyio


def netbox_get_objects() -> str:
    """List NetBox objects."""
    return "objects"


def read_file(path: str) -> str:
    """Read a file."""
    return path


async def _run(toolsets: list) -> tuple[list[str], str | None]:
    """The tool names and instructions a model is handed on a turn's first request."""
    seen: dict = {}

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.setdefault("tools", sorted(tool.name for tool in info.function_tools))
        seen.setdefault("instructions", info.instructions)
        return ModelResponse(parts=[TextPart("ok")])

    await Agent(FunctionModel(answer), toolsets=toolsets).run("List the devices.")
    return seen["tools"], seen["instructions"]


def _listing(*names: str) -> MagicMock:
    """A toolset listing `names`, as the wrappers under `OwnToolNames` hand them up."""
    inner = MagicMock()
    inner.get_tools = AsyncMock(return_value={name: f"<{name}>" for name in names})
    return inner


class TestTheNamesTheModelSees:
    async def test_a_connection_that_skips_its_prefix_presents_the_server_s_own_names(
        self, monkeypatch
    ):
        """The issue in one assertion: `netbox_get_objects`, not `netbox_netbox_get_objects`."""
        monkeypatch.setattr(
            "app.agents.mcp.MCPToolset", lambda *_a, **_k: FunctionToolset([netbox_get_objects])
        )

        prefixed, _ = await _run(
            [_make_toolset(McpServerSpec(name="netbox", url="https://nb.example/mcp"))]
        )
        own, _ = await _run(
            [
                _make_toolset(
                    McpServerSpec(
                        name="netbox", url="https://nb.example/mcp", skip_tool_prefix=True
                    )
                )
            ]
        )

        assert prefixed == ["netbox_netbox_get_objects"]
        assert own == ["netbox_get_objects"]

    def test_the_connection_keeps_its_prefix_as_the_server_s_namespace(self):
        """Tool search keeps a server visible by `mcp-<prefix>`, and the run's records
        name the connection by it: neither changes when the tool names do."""
        ids: list[str | None] = []
        _make_toolset(
            McpServerSpec(name="netbox", url="https://nb.example/mcp", skip_tool_prefix=True)
        ).apply(lambda toolset: ids.append(toolset.id))

        assert "mcp-netbox" in ids


class TestWhoHoldsAName:
    def test_a_name_another_tool_has_is_its(self):
        assert (
            name_holder("read_file", taken={"read_file": "the sandbox capability"}, prefixes={})
            == "the sandbox capability"
        )

    def test_a_name_under_another_binding_s_prefix_is_that_binding_s(self):
        """Whether or not that server lists the tool today: what a server lists
        changes with nobody publishing."""
        assert (
            name_holder("github_search", taken={}, prefixes={"github": "the connection 'github'"})
            == "the connection 'github'"
        )

    def test_a_prefix_owns_only_what_follows_its_separator(self):
        assert name_holder("githubx_search", taken={}, prefixes={"github": "x"}) is None
        assert name_holder("netbox_get_objects", taken={"read_file": "x"}, prefixes={}) is None


class TestAServerThatYields:
    async def test_free_names_keep_every_tool_and_the_server_s_own_instructions(self):
        own = OwnToolNames(
            FunctionToolset([netbox_get_objects], instructions="Use get_objects first."),
            server="netbox",
            binding="the connection 'netbox'",
            taken={"read_file": "the sandbox capability"},
            prefixes={"github": "the connection 'github'"},
        )

        tools, instructions = await _run([own])

        assert tools == ["netbox_get_objects"]
        assert instructions == "Use get_objects first."

    async def test_a_taken_name_leaves_the_whole_server_out_and_says_why(self):
        """The binding yields, not just the tool: a server missing one tool the model
        is not told about reads as one that has nothing to say about it."""
        own = OwnToolNames(
            _listing("netbox_get_objects", "read_file"),
            server="fs",
            binding="the connection 'fs'",
            taken={"read_file": "the sandbox capability"},
        )

        assert await own.get_tools(MagicMock()) == {}
        briefing = await own.get_instructions(MagicMock())
        assert isinstance(briefing, str)
        assert briefing.startswith("The fs server (the connection 'fs') is not available")
        assert "its tool `read_file` would take a name that belongs to the sandbox capability" in (
            briefing
        )
        assert "turning the connection's tool prefix back on or narrowing its tools" in briefing

    async def test_a_name_under_another_binding_s_prefix_leaves_it_out(self):
        own = OwnToolNames(
            _listing("github_search"),
            server="gh-mirror",
            binding="the connection 'gh-mirror'",
            prefixes={"github": "the connection 'github'"},
        )

        assert await own.get_tools(MagicMock()) == {}
        assert own.clash == ("github_search", "the connection 'github'")

    async def test_of_two_servers_presenting_one_name_the_earlier_keeps_it(self):
        first = OwnToolNames(_listing("search"), server="kb", binding="the connection 'kb'")
        second = OwnToolNames(
            _listing("search", "fetch"),
            server="wiki",
            binding="the connection 'wiki'",
            before=(first,),
        )

        assert await second.get_tools(MagicMock()) == {}
        assert second.clash == ("search", "the connection 'kb'")
        assert await first.get_tools(MagicMock()) == {"search": "<search>"}

    async def test_an_earlier_server_that_yielded_holds_nothing(self):
        first = OwnToolNames(
            _listing("search", "read_file"),
            server="kb",
            binding="the connection 'kb'",
            taken={"read_file": "the sandbox capability"},
        )
        second = OwnToolNames(
            _listing("search"), server="wiki", binding="the connection 'wiki'", before=(first,)
        )

        assert await second.get_tools(MagicMock()) == {"search": "<search>"}

    async def test_it_is_decided_again_on_every_step(self):
        """A server that dropped the clashing tool comes back, and stops briefing."""
        inner = _listing("read_file")
        own = OwnToolNames(
            inner, server="fs", binding="b", taken={"read_file": "the sandbox capability"}
        )
        assert await own.get_tools(MagicMock()) == {}

        inner.get_tools.return_value = {"list_dir": "<list_dir>"}

        assert await own.get_tools(MagicMock()) == {"list_dir": "<list_dir>"}
        assert own.clash is None

    async def test_the_turn_goes_on_without_the_server_rather_than_aborting(self):
        """Pydantic AI answers two tools of one name by raising, which ends the turn.

        Run through a real agent: the capability keeps `read_file`, the server is
        left out, and the same request's instructions say why - pydantic-ai lists
        a step's tools before it reads its instructions."""
        own = OwnToolNames(
            FunctionToolset([read_file, netbox_get_objects]),
            server="fs",
            binding="the connection 'fs'",
            taken={"read_file": "the sandbox capability"},
        )

        tools, instructions = await _run([FunctionToolset([read_file]), own])

        assert tools == ["read_file"]
        assert instructions is not None
        assert "The fs server (the connection 'fs') is not available this turn" in instructions


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

    def test_a_capability_the_registry_does_not_hold_is_left_out(self):
        """Publish refuses it on its own; it must not take the MCP check down with it."""
        spec = AgentSpec(name="Support", capabilities=[CapabilityBindingSpec(id="no-such")])

        assert set(taken_tool_names(spec)) == PLATFORM_TOOL_NAMES


def _org(**overrides):
    return _connection(scope="org", user_id=None, organization_id=uuid4(), **overrides)


def _probe_answering(monkeypatch, *, down: tuple[str, ...] = ()):
    """Every server answers its probe, each standing in as its own name, except `down`."""

    async def fake_probe(specs):
        return [(spec, None if spec.url in down else spec.name) for spec in specs]

    monkeypatch.setattr(mcp_connection_service, "probe_toolsets", fake_probe)
    monkeypatch.setattr(
        mcp_connection_service, "spawn_after_commit", lambda db, coro, *, name: coro.close()
    )


def _found(monkeypatch, *connections):
    monkeypatch.setattr(
        mcp_connection_service.mcp_connection_repo,
        "get_org_scoped_by_ids",
        AsyncMock(return_value={connection.id: connection for connection in connections}),
    )


def _own(resolved) -> list[OwnToolNames]:
    return [
        toolset.wrapped
        for toolset in resolved.toolsets
        if isinstance(toolset, ToolOrigins) and isinstance(toolset.wrapped, OwnToolNames)
    ]


class TestTheRunResolves:
    async def test_a_skipping_connection_keeps_off_the_names_the_run_holds(self, monkeypatch):
        github = _org(name="github", url="https://gh.example/mcp")
        netbox = _org(name="netbox", url="https://nb.example/mcp", skip_tool_prefix=True)
        _found(monkeypatch, github, netbox)
        _probe_answering(monkeypatch)

        resolved = await mcp_connection_service.build_toolsets_for_agent(
            AsyncMock(),
            organization_id=uuid4(),
            refs=[
                OrgMcpServerRef(connection_id=github.id),
                OrgMcpServerRef(connection_id=netbox.id),
            ],
            taken_names={"read_file": "the sandbox capability"},
        )

        (own,) = _own(resolved)
        assert (own.wrapped, own.server, own.binding) == (
            "netbox",
            "netbox",
            "the connection 'netbox'",
        )
        assert own.taken == {"read_file": "the sandbox capability"}
        # Only the prefixes tools really carry: `netbox` presents its tools under none.
        assert own.prefixes == {"github": "the connection 'github'"}
        assert own.before == ()
        # The prefixed server is attached as it always was.
        assert resolved.toolsets[0].wrapped == "github"

    async def test_two_skipping_connections_are_decided_in_binding_order(self, monkeypatch):
        kb = _org(name="kb", url="https://kb.example/mcp", skip_tool_prefix=True)
        wiki = _org(name="wiki", url="https://wiki.example/mcp", skip_tool_prefix=True)
        _found(monkeypatch, kb, wiki)
        _probe_answering(monkeypatch)

        resolved = await mcp_connection_service.build_toolsets_for_agent(
            AsyncMock(),
            organization_id=uuid4(),
            refs=[OrgMcpServerRef(connection_id=kb.id), OrgMcpServerRef(connection_id=wiki.id)],
        )

        first, second = _own(resolved)
        assert second.before == (first,)
        assert first.taken == {}

    @pytest.mark.parametrize("production_skips", [True, False])
    async def test_a_test_connection_presents_its_production_connection_s_names(
        self, monkeypatch, production_skips
    ):
        """An eval's trajectory is compared across environments by the tool names it called."""
        production = _org(
            name="netbox", url="https://nb.example/mcp", skip_tool_prefix=production_skips
        )
        sandbox = _org(
            name="netbox-lab", url="https://lab.example/mcp", skip_tool_prefix=not production_skips
        )
        _found(monkeypatch, production, sandbox)
        seen: list[McpServerSpec] = []

        async def fake_probe(specs):
            seen.extend(specs)
            return [(spec, spec.name) for spec in specs]

        monkeypatch.setattr(mcp_connection_service, "probe_toolsets", fake_probe)

        await mcp_connection_service.build_toolsets_for_agent(
            AsyncMock(),
            organization_id=uuid4(),
            refs=[OrgMcpServerRef(connection_id=production.id)],
            test_connections={production.id: sandbox.id},
        )

        assert [(spec.name, spec.skip_tool_prefix) for spec in seen] == [
            ("netbox", production_skips)
        ]

    async def test_a_skipping_server_that_did_not_answer_is_briefed_without_a_prefix(
        self, monkeypatch
    ):
        netbox = _org(name="netbox", url="https://nb.example/mcp", skip_tool_prefix=True)
        _found(monkeypatch, netbox)
        _probe_answering(monkeypatch, down=(netbox.url,))

        resolved = await mcp_connection_service.build_toolsets_for_agent(
            AsyncMock(), organization_id=uuid4(), refs=[OrgMcpServerRef(connection_id=netbox.id)]
        )

        assert resolved.unavailable == [
            UnavailableUnreachableServer(
                server="netbox", binding="the connection 'netbox'", prefixed=False
            )
        ]

    async def test_a_dead_server_is_not_told_its_prefix_is_held_by_one_that_skips_it(
        self, monkeypatch
    ):
        """`notion` and `notion-` are one prefix, and the first holds it - but its
        tools carry none, so there are no `notion_*` tools to say are its."""
        notion = _org(name="notion", url="https://live.example/mcp", skip_tool_prefix=True)
        dead = _org(name="notion-", url="https://dead.example/mcp")
        _found(monkeypatch, notion, dead)
        _probe_answering(monkeypatch, down=(dead.url,))

        resolved = await mcp_connection_service.build_toolsets_for_agent(
            AsyncMock(),
            organization_id=uuid4(),
            refs=[OrgMcpServerRef(connection_id=notion.id), OrgMcpServerRef(connection_id=dead.id)],
        )

        assert resolved.unavailable == [
            UnavailableUnreachableServer(server="notion-", binding="the connection 'notion-'")
        ]

    async def test_a_skipping_connection_bound_twice_and_answering_once_is_not_missing(
        self, monkeypatch
    ):
        netbox = _org(name="netbox", url="https://nb.example/mcp", skip_tool_prefix=True)
        _found(monkeypatch, netbox)

        async def fake_probe(specs):
            return [(spec, None if at == 0 else spec.name) for at, spec in enumerate(specs)]

        monkeypatch.setattr(mcp_connection_service, "probe_toolsets", fake_probe)
        monkeypatch.setattr(
            mcp_connection_service, "spawn_after_commit", lambda db, coro, *, name: coro.close()
        )

        resolved = await mcp_connection_service.build_toolsets_for_agent(
            AsyncMock(),
            organization_id=uuid4(),
            refs=[OrgMcpServerRef(connection_id=netbox.id)] * 2,
        )

        assert resolved.unavailable == []

    async def test_an_account_that_skips_its_prefix_is_noted_by_the_tools_with_none(
        self, monkeypatch
    ):
        work = _org(
            name="outlook", url="https://a.example/mcp", catalog_key="outlook", label="Work"
        )
        work.skip_tool_prefix = True
        info = _org(
            name="outlook-info", url="https://b.example/mcp", catalog_key="outlook", label="info@"
        )
        _found(monkeypatch, work, info)
        _probe_answering(monkeypatch)

        resolved = await mcp_connection_service.build_toolsets_for_agent(
            AsyncMock(),
            organization_id=uuid4(),
            refs=[OrgMcpServerRef(connection_id=work.id), OrgMcpServerRef(connection_id=info.id)],
        )

        assert resolved.accounts == [
            AccountNote("outlook", None, "Work", "organization"),
            AccountNote("outlook", "outlook_info", "info@", "organization"),
        ]


class TestWhatTheModelIsTold:
    def test_a_dead_skipping_server_names_no_prefix_to_look_for(self):
        briefing = unreachable_briefing("netbox", binding="the connection 'netbox'", prefixed=False)

        assert "so none of its tools are attached" in briefing
        assert "netbox_*" not in briefing

    async def test_one_that_answered_recently_and_fails_on_connect_too(self, monkeypatch):
        spec = McpServerSpec(name="netbox", url="https://nb.example/mcp", skip_tool_prefix=True)
        _note_answer(_answer_key(spec))
        ((_, toolset),) = await probe_toolsets([spec])
        assert isinstance(toolset, AnsweredRecently)
        monkeypatch.setattr(
            toolset.wrapped, "__aenter__", AsyncMock(side_effect=ConnectionError("refused"))
        )

        await toolset.__aenter__()
        briefing = await toolset.get_instructions(MagicMock())

        assert isinstance(briefing, str)
        assert "so none of its tools are attached" in briefing

    def test_the_account_whose_tools_carry_no_prefix_is_named_by_that(self):
        spec = _with_account_notes(
            AgentSpec(name="Support", instructions="x"),
            [
                AccountNote("outlook", None, "Work", "organization"),
                AccountNote("outlook", "outlook_info", "info@", "organization"),
            ],
        )

        assert "its tools that carry no prefix act as the organization's account 'Work'" in (
            spec.instructions
        )
        assert "`outlook_info_` act as the organization's account 'info@'" in spec.instructions


class TestTheNamesAConnectionShows:
    def test_both_allowlists_narrow_them_and_each_is_fitted(self):
        connection = _org(
            name="netbox",
            skip_tool_prefix=True,
            allowed_tools=["get_objects", "x" * 70],
            last_tools=[{"name": "get_objects"}, {"name": "x" * 70}, {"name": "delete"}],
        )

        everything = unprefixed_tool_names(connection, None)
        narrowed = unprefixed_tool_names(connection, ["get_objects"])

        assert everything is not None and len(everything) == 2
        assert everything[0] == "get_objects" and len(everything[1]) == 64
        assert narrowed == ["get_objects"]

    def test_a_connection_nothing_has_reached_has_no_names_to_show(self):
        assert unprefixed_tool_names(_org(skip_tool_prefix=True), None) is None

    def test_a_mention_names_the_tools_rather_than_a_prefix_they_lack(self):
        """Pointed at `netbox_*`, a model calls tools that do not exist - what the
        issue opened on."""
        skipping = _org(
            name="netbox",
            skip_tool_prefix=True,
            last_tools=[{"name": "netbox_get_objects"}, {"name": "netbox_get_changelogs"}],
        )
        ref = OrgMcpServerRef(connection_id=skipping.id)

        assert _tools_named(skipping, ref) == "netbox_get_objects, netbox_get_changelogs"
        assert _tools_named(_org(name="netbox-lab"), ref) == "netbox_lab_*"
        assert _tools_named(_org(name="nb", skip_tool_prefix=True), ref) is None

    def test_a_mention_with_no_names_to_give_points_at_the_server_alone(self):
        note = _note(
            [Mentionable(kind="mcp", id=str(uuid4()), name="NetBox")],
            {},
            hand_off="hand_off",
            search="search",
        )

        assert note is not None and 'MCP server "NetBox" - use its tools.' in note

    def test_only_an_organization_connection_can_skip_its_prefix(self):
        """A binding to each person's own account presents the catalog key, so an
        agent shows everyone the same names however each person set theirs up."""
        assert "skip_tool_prefix" not in McpConnectionUpdate.model_fields
        assert McpConnectionRead.from_model(_org(skip_tool_prefix=True)).skip_tool_prefix

    async def test_its_calls_are_listed_under_the_names_they_were_made_by(self, monkeypatch):
        """Stripping `netbox_` from `netbox_get_objects` would name a tool nobody called."""
        ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)
        service = McpConnectionService(db=AsyncMock())
        connection = _org(name="netbox", skip_tool_prefix=True)
        monkeypatch.setattr(service, "_get_org", AsyncMock(return_value=connection))
        call = ToolCallSeen(
            tool_name="netbox_get_objects",
            status="success",
            started_at=connection.created_at,
            duration_ms=12,
            agent_id=None,
            agent_name=None,
            run_id=None,
        )
        monkeypatch.setattr(
            mcp_connection_service.conversation_repo,
            "recent_tool_calls",
            AsyncMock(return_value=[call]),
        )

        (listed,) = await service.recent_calls(ctx, connection_id=connection.id)

        assert listed.tool == "netbox_get_objects"
