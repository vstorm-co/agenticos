"""Tests for the capability registry - the code/configuration boundary.

What is guarded: configuration may reach only what code registered, a capability
that contributes nothing is not attached, and a spec asking for something
ungranted fails while a person is looking at a form rather than mid-run.
"""

import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai._run_context import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities import (
    REGISTRY,
    CapabilityBinding,
    CapabilityBuildContext,
    CapabilityToolInfo,
    ToolOverride,
    all_capabilities,
    build,
    get,
    load_builtins,
    register,
)
from app.agents.capabilities.channel_tools import CHANNEL_DIRECTORY_RESOURCE
from app.agents.capabilities.charts import Charts
from app.agents.capabilities.clock import Clock
from app.agents.capabilities.code_execution import CodeExecution, CodeExecutionConfig
from app.agents.capabilities.knowledge import Knowledge, KnowledgeConfig
from app.agents.capabilities.skills import SAFE_SKILL_TOOLS, Skills
from app.agents.capabilities.web_research import WebResearch
from app.agents.subagent_runtime import (
    SUBAGENT_RUNTIME_RESOURCE,
    DynamicSpecialists,
    ResolvedSubagent,
    SubagentRuntime,
)
from app.core.exceptions import BadRequestError


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


def _run_context() -> RunContext[None]:
    """The least a wrapped toolset needs before it will list its tools."""
    return RunContext(deps=None, model=TestModel(), usage=RunUsage())


class TestSelfLoading:
    """The registry must not depend on the caller having warmed it up.

    It used to: `load_builtins()` ran in the FastAPI lifespan and nowhere
    else, so the CLI, a worker or a script got an empty registry and every
    publish failed with "Unknown capability" - naming a capability that is in
    the repository, listed in the picker and documented. The gap only showed up
    when somebody actually ran `make platform-bootstrap`.
    """

    @staticmethod
    def _in_a_fresh_process(source: str) -> str:
        """Run a snippet in a new interpreter and return what it printed.

        A subprocess is the only honest way to test this. Clearing `REGISTRY`
        inside this one proves nothing: the capability modules are already
        imported, so re-importing them is a no-op and their decorators never run
        again. Only a process that has not imported them can show what a CLI
        invocation actually sees.
        """
        result = subprocess.run(
            [sys.executable, "-c", source],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path(__file__).resolve().parent.parent,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def test_a_lookup_in_a_fresh_process_finds_a_builtin(self):
        assert (
            self._in_a_fresh_process(
                "from app.agents.capabilities import get; print(get('clock').id)"
            )
            == "clock"
        )

    def test_listing_in_a_fresh_process_is_not_empty(self):
        """The Builder's picker is a listing, and an empty one is a broken page."""
        listed = self._in_a_fresh_process(
            "from app.agents.capabilities import all_capabilities\n"
            "print(','.join(sorted(d.id for d in all_capabilities())))"
        )

        assert {"clock", "knowledge"} <= set(listed.split(","))

    def test_loading_twice_does_not_raise_on_duplicate_ids(self):
        """`register` refuses a duplicate id, so a second load must be a no-op."""
        load_builtins()
        load_builtins()

        assert get("clock").id == "clock"


class TestToolDeclarations:
    """A tool's declared identity is what the approval gate keys on."""

    def test_a_tool_is_seen_under_the_name_it_was_declared_with(self):
        tool = CapabilityToolInfo(id="send_email", description="Sends mail.")

        assert (tool.id, tool.name) == ("send_email", "send_email")

    def test_a_renamed_tool_keeps_the_id_the_gate_matches_on(self):
        """The whole reason id and name are separate.

        `tool_approval` is keyed by id, so renaming what the model sees cannot
        quietly drop the gate an operator put on it.
        """
        tool = CapabilityToolInfo(
            id="search_documents", name="search_orders", description="Search."
        )

        assert (tool.id, tool.name) == ("search_documents", "search_orders")

    def test_a_declaration_that_is_not_a_mapping_is_left_to_pydantic(self):
        """The before-validator must not swallow a malformed declaration."""
        with pytest.raises(ValidationError):
            CapabilityToolInfo.model_validate(["send_email"])

    # Enough for *every* capability to build, which is load-bearing rather than
    # convenient - see `test_no_capability_escapes_the_drift_check`. The
    # assertions here are about names, not about search results.
    RESOURCES = {
        "kb_collection_names": ["kb_1"],
        # Any object at all: `channel_tools` builds when a run is in a channel
        # and contributes nothing when it is not, and this test is about the
        # names it offers rather than what a platform answers.
        CHANNEL_DIRECTORY_RESOURCE: SimpleNamespace(),
        "skills": [
            SimpleNamespace(
                name="refunds",
                description="How refunds work.",
                content="…",
                resources=[],
            )
        ],
        # A delegating agent at its widest: one resolved delegate *and* permission
        # to invent specialists, because `subagents` is the one capability whose
        # tool list is not fixed - `create_agent` and `delegate` are offered only
        # to an agent whose author asked for them. The widest configuration is the
        # one worth checking: an undeclared tool can only appear where the most
        # tools do.
        SUBAGENT_RUNTIME_RESOURCE: SubagentRuntime(
            subagents=(
                ResolvedSubagent(
                    name="researcher",
                    description="Researches a topic.",
                    # Never called: this test lists tools, and a delegate's agent
                    # is built on its first delegation.
                    build=lambda: PydanticAgent(TestModel()),
                ),
            ),
            record=None,
            depth_remaining=1,
            dynamic=DynamicSpecialists(
                # Never called either, for the same reason.
                build=lambda **_: PydanticAgent(TestModel()),
                allowed_models=("GPT-4.1 (prod)",),
            ),
        ),
    }
    """Everything every registered capability needs in order to build.

    Wide rather than minimal on purpose. There used to be a
    `CapabilityDef.drift_config` field naming a configuration nothing read, and
    then an `UNWIRED_TOOLS` table naming `create_agent` and `delegate` as declared
    and not implemented - both ways of saying "this capability is partly outside
    the check", and both removed by wiring the tools. What stands in their place is
    resources wide enough that no capability has an excuse for not building.
    """

    DECLARED_AND_NOT_OFFERED: dict[str, frozenset[str]] = {
        "subagents": frozenset({"answer_subagent"}),
    }
    """Tools a capability declares and deliberately offers no model.

    The one legitimate reason to declare a tool that never reaches a model: the
    library owning it adds it unconditionally, nothing in this deployment can put
    it in a state where it does anything, and dropping it from `tools=` would take
    it out of reach of the approval policy and of a binding's rename. `subagents`
    declares `answer_subagent` for exactly that reason -
    `app.agents.capabilities.subagents._capability.UNREACHABLE_TOOLS` has the whole
    of it, including why agenticos#184 would not empty this table on its own.

    Spelt out here rather than imported from the capability, and subtracted rather
    than skipped. An imported set would make the check below a tautology, and
    skipping the capability would put it back outside the drift test the way
    `drift_config` and `UNWIRED_TOOLS` did - an undeclared tool could then appear
    beside the exempt one and nothing would notice. Everything else about the
    capability is still compared in both directions, and
    `test_the_exemption_table_names_tools_that_are_still_declared` is what stops
    an entry outliving its reason.
    """

    def _expected(self, definition_id: str) -> frozenset[str]:
        """The tool ids this capability's model should be offered, exemptions applied."""
        return get(definition_id).tool_ids - self.DECLARED_AND_NOT_OFFERED.get(
            definition_id, frozenset()
        )

    CONFIGS: dict[str, dict[str, Any]] = {
        # The only capability whose *tools* are configuration rather than a fixed
        # list: a binding names which lookups it allows, so the widest
        # configuration is the one that allows all of them. Same reason the
        # subagents resource above is at its widest - an undeclared tool can only
        # appear where the most tools do.
        "channel_tools": {"tools": sorted(get("channel_tools").tool_ids)},
        # Builds `None` from an empty blob on purpose - enabling the capability
        # without turning on an edge attaches no guardrail. One edge on is what
        # makes it build here; it offers no tools either way.
        "guardrails": {"blocked_keywords_in": "secret"},
        # Its three subtask tools are offered only when this is set, so the widest
        # configuration is the one that switches them on. The default (a flat
        # checklist) offers the six core tools and would hide the other three from
        # the comparison rather than check them.
        "planning": {"enable_subtasks": True},
    }
    """Configurations a capability needs before it offers anything.

    Absent for almost everything: a capability builds from an empty blob and
    applies its own defaults, which is the configuration most agents run. An
    entry here says the defaults leave tools switched off, and names the widest
    setting instead - never a narrower one, which would hide a tool from the
    comparison below rather than check it.
    """

    def _built(self, definition_id: str) -> Any:
        definition = get(definition_id)
        blob = self.CONFIGS.get(definition_id, {})
        return definition.builder(
            CapabilityBuildContext(
                binding=CapabilityBinding(capability_id=definition_id, config=blob),
                config=definition.validate_config(blob),
                resources=self.RESOURCES,
            )
        )

    def test_no_capability_escapes_the_drift_check(self):
        """A capability that cannot be built here is a capability nothing checks.

        The two tests below compare what a capability declares against what it
        offers, and both used to answer `continue` for a builder that returned
        `None` - which is how `subagents` sat outside the check entirely while
        appearing to be covered by it. A capability could have added an
        undeclared, side-effecting tool and no shared test would have noticed.

        So the resources above exist to make every registered capability
        buildable, and this is the assertion that keeps them that way: a new
        capability needing a run-time resource fails *here*, naming itself,
        rather than quietly opting out.
        """
        unbuildable = [
            definition.id for definition in all_capabilities() if self._built(definition.id) is None
        ]

        assert unbuildable == [], (
            "add whatever these need to TestToolDeclarations.RESOURCES; a capability "
            "the drift check cannot build is a capability it does not check"
        )

    @staticmethod
    async def _offered(built: Any) -> frozenset[str]:
        """The tool names a built capability actually hands its model.

        Asked of the toolset rather than read off a `.tools` mapping: a wrapper -
        which is what a capability wrapping a library's toolset is, and what a
        renaming binding produces - resolves its tools per run context and has no
        such mapping at all.
        """
        toolset = built.get_toolset()
        if toolset is None:
            return frozenset()
        return frozenset(await toolset.get_tools(_run_context()))

    def test_the_exemption_table_names_tools_that_are_still_declared(self):
        """An exemption that outlived its tool would quietly widen the check.

        Both halves matter. An id no longer declared - renamed, or removed with the
        capability it belonged to - subtracts nothing and reads as if it did, so the
        next tool that *is* wrongly unoffered looks exempt. And a capability listed
        with an empty set is an entry that says "partly outside the check" while
        exempting nothing at all.

        The other direction needs no test: a tool that becomes genuinely offered
        while still named here fails the comparison below, because the offered set
        then holds something the expectation subtracted.
        """
        for capability_id, exempt in self.DECLARED_AND_NOT_OFFERED.items():
            assert exempt, capability_id
            assert exempt <= get(capability_id).tool_ids, capability_id

    @pytest.mark.anyio
    async def test_every_builtin_declares_the_tools_it_actually_offers(self):
        """Declaration feeds the Builder; the toolset is the truth.

        A declared tool that does not exist offers approval for nothing. The
        dangerous direction is the other one: a real tool nobody declared is a
        tool the Builder cannot gate, and a side-effecting one would run
        unattended with no way to say otherwise.
        """
        for definition in all_capabilities():
            built = self._built(definition.id)
            assert built is not None, definition.id

            assert await self._offered(built) == self._expected(definition.id), definition.id

    @pytest.mark.anyio
    async def test_renaming_every_tool_cannot_hide_an_undeclared_one(self):
        """The same check, through a binding that renames all of it.

        Renaming is the one thing that makes "declared" and "offered" legitimately
        different strings, so the check above could have been satisfied by
        loosening it - and a loosened version would stop catching the failure it
        exists for. Instead the expectation moves with the rename: every declared
        tool must arrive under its new name, and a tool nobody declared has no new
        name to arrive under, so it still shows up as a difference.

        A tool in `DECLARED_AND_NOT_OFFERED` must not arrive under either name. It
        is renamed here like every other - a binding may name a tool the model is
        not shown, and publishing accepts it - so this is also the check that the
        rename cannot smuggle it back in: the filter keys on the stable id, inside
        the wrapper that renames.
        """
        for definition in all_capabilities():
            overrides = {
                tool.id: ToolOverride(name=f"{tool.id}_as_this_agent_calls_it")
                for tool in definition.tools
            }
            built = build(
                [
                    CapabilityBinding(
                        capability_id=definition.id,
                        config=self.CONFIGS.get(definition.id, {}),
                        tool_overrides=overrides,
                    )
                ],
                resources=self.RESOURCES,
            )
            assert built, definition.id
            offered = await self._offered(built[0])

            expected = frozenset(
                tool.name
                for tool in definition.effective_tools(overrides)
                if tool.id in self._expected(definition.id)
            )
            assert offered == expected, definition.id


class TestEffectiveTools:
    """What the model will see, which is not always what the source says."""

    def test_without_an_override_the_declaration_stands(self):
        assert get("knowledge").effective_tools({}) == get("knowledge").tools

    def test_a_rename_keeps_the_id_and_the_declared_description(self):
        """Half an override is an override: the other half falls back to code."""
        (tool,) = get("knowledge").effective_tools(
            {"search_documents": ToolOverride(name="search_refund_policy")}
        )

        assert (tool.id, tool.name) == ("search_documents", "search_refund_policy")
        assert tool.description == get("knowledge").tools[0].description

    def test_a_reworded_description_keeps_the_declared_name(self):
        (tool,) = get("knowledge").effective_tools(
            {"search_documents": ToolOverride(description="Look up the refund policy.")}
        )

        assert (tool.name, tool.description) == (
            "search_documents",
            "Look up the refund policy.",
        )

    def test_an_override_for_a_tool_that_does_not_exist_changes_nothing(self):
        """It is refused at publish; here it must not corrupt the answer."""
        assert (
            get("knowledge").effective_tools({"search_docuemnts": ToolOverride(name="typo")})
            == get("knowledge").tools
        )


class TestRegistration:
    def test_builtin_capabilities_are_registered(self):
        assert {
            "knowledge",
            "web_research",
            "charts",
            "code_execution",
            "clock",
            "skills",
            "thinking",
            "tool_search",
        } <= set(REGISTRY)

    def test_catalog_is_ordered_for_a_stable_picker(self):
        entries = all_capabilities()
        assert entries == sorted(entries, key=lambda d: (d.category, d.name))

    def test_registering_a_duplicate_id_is_refused(self):
        """Import order must not decide what an agent can do."""
        with pytest.raises(RuntimeError, match="already registered"):

            @register(id="clock", name="Clashing", category="test", description="", tools=())
            def _clashing(ctx):
                return None

    def test_unknown_capability_names_what_is_available(self):
        with pytest.raises(BadRequestError) as exc:
            get("no_such_capability")
        assert exc.value.details is not None
        assert "available" in exc.value.details


class TestConfigValidation:
    def test_valid_config_is_parsed_into_its_schema(self):
        config = get("knowledge").validate_config({"default_top_k": 8})
        assert isinstance(config, KnowledgeConfig)
        assert config.default_top_k == 8

    def test_invalid_config_reports_field_errors(self):
        """The Builder needs field-level errors to point at the right input."""
        with pytest.raises(BadRequestError) as exc:
            get("knowledge").validate_config({"default_top_k": 999})
        assert exc.value.details is not None
        assert exc.value.details["errors"]

    def test_the_rejected_value_is_not_echoed_back(self):
        """`details` reaches the caller verbatim, so it carries the diagnosis
        rather than a copy of what was posted (agenticos#307)."""
        with pytest.raises(BadRequestError) as exc:
            get("knowledge").validate_config({"default_top_k": 999})
        assert exc.value.details is not None
        assert all("input" not in error for error in exc.value.details["errors"])

    def test_capabilities_without_a_schema_accept_nothing(self):
        assert get("charts").validate_config({}) is None

    def test_sandbox_limits_are_validated_where_the_form_is(self):
        """A limit outside the cap is refused at configuration time, not
        discovered as an unkillable program at run time."""
        config = get("code_execution").validate_config({"timeout_secs": 30, "max_memory_mb": 512})
        assert isinstance(config, CodeExecutionConfig)
        assert (config.timeout_secs, config.max_memory_mb) == (30, 512)

        with pytest.raises(BadRequestError):
            get("code_execution").validate_config({"timeout_secs": 0})
        with pytest.raises(BadRequestError):
            get("code_execution").validate_config({"max_memory_mb": 8})

    def test_config_schema_is_exposed_as_json_schema(self):
        """The configuration form is generated from this, never hand-written."""
        schema = get("knowledge").config_json_schema()
        assert schema is not None
        assert "default_top_k" in schema["properties"]

    def test_capabilities_without_a_schema_expose_none(self):
        assert get("charts").config_json_schema() is None


class TestBuilding:
    def test_disabled_bindings_are_skipped(self):
        assert build([CapabilityBinding(capability_id="clock", enabled=False)]) == []

    def test_builds_in_binding_order(self):
        built = build(
            [
                CapabilityBinding(capability_id="charts"),
                CapabilityBinding(capability_id="clock"),
            ]
        )
        assert [type(c) for c in built] == [Charts, Clock]

    def test_knowledge_is_not_attached_without_collections(self):
        """A search tool that always returns empty is worse than none - the model keeps trying."""
        built = build(
            [CapabilityBinding(capability_id="knowledge")],
            granted_scopes=frozenset({"knowledge:read"}),
        )
        assert built == []

    def test_knowledge_is_attached_when_collections_are_bound(self):
        built = build(
            [CapabilityBinding(capability_id="knowledge")],
            granted_scopes=frozenset({"knowledge:read"}),
            resources={"kb_collection_names": ["kb_1"]},
        )
        assert isinstance(built[0], Knowledge)

    def test_config_reaches_the_capability(self):
        built = build(
            [CapabilityBinding(capability_id="knowledge", config={"default_top_k": 9})],
            resources={"kb_collection_names": ["kb_1"]},
        )
        capability = built[0]
        assert isinstance(capability, Knowledge)
        assert capability.default_top_k == 9
        assert list(capability.get_toolset().tools) == ["search_documents"]

    def test_sandbox_limits_reach_the_capability_and_default_when_absent(self):
        """Both halves of the config contract: a stated limit is carried, and a
        binding that says nothing gets the defaults rather than a crash."""
        configured, bare = build(
            [
                CapabilityBinding(
                    capability_id="code_execution",
                    config={"timeout_secs": 30, "max_memory_mb": 512},
                ),
                CapabilityBinding(capability_id="code_execution"),
            ],
            granted_scopes=frozenset({"code:execute"}),
        )
        assert isinstance(configured, CodeExecution)
        assert (configured.timeout_secs, configured.max_memory_mb) == (30, 512)
        assert isinstance(bare, CodeExecution)
        assert (bare.timeout_secs, bare.max_memory_mb) == (
            CodeExecutionConfig().timeout_secs,
            CodeExecutionConfig().max_memory_mb,
        )

    def test_a_binding_that_overrides_nothing_is_left_unwrapped(self):
        """An override wrapper around a capability that changes nothing is noise.

        `BuiltAgent.capabilities` is introspected by surfaces that want to say
        what an agent can do; making them see through a transparent wrapper is a
        cost paid by every agent to serve the few that rename anything.
        """
        built = build(
            [
                CapabilityBinding(
                    capability_id="knowledge",
                    tool_overrides={"search_documents": ToolOverride()},
                )
            ],
            resources={"kb_collection_names": ["kb_1"]},
        )

        assert isinstance(built[0], Knowledge)

    def test_missing_scope_is_refused_at_build_time(self):
        with pytest.raises(BadRequestError) as exc:
            build(
                [CapabilityBinding(capability_id="code_execution")],
                granted_scopes=frozenset(),
            )
        assert exc.value.details is not None
        assert exc.value.details["missing_scopes"] == ["code:execute"]

    def test_granted_scope_allows_the_capability(self):
        built = build(
            [CapabilityBinding(capability_id="code_execution")],
            granted_scopes=frozenset({"code:execute"}),
        )
        assert isinstance(built[0], CodeExecution)

    def test_scope_check_is_skipped_only_when_explicitly_disabled(self):
        """None means "internal run"; it must not become the accidental default."""
        assert build([CapabilityBinding(capability_id="code_execution")])


class TestToolsets:
    def test_the_clock_exposes_no_tools(self):
        """It contributes instructions instead; see tests/test_clock.py."""
        assert Clock().get_toolset() is None

    def test_charts_exposes_create_chart(self):
        assert list(Charts().get_toolset().tools) == ["create_chart"]

    def test_code_execution_exposes_run_python(self):
        assert list(CodeExecution().get_toolset().tools) == ["run_python"]

    def test_web_research_exposes_web_search(self):
        assert list(WebResearch().get_toolset().tools) == ["web_search"]

    def test_knowledge_default_tool_name(self):
        assert list(Knowledge().get_toolset().tools) == ["search_documents"]

    def test_toolsets_are_built_once_per_instance(self):
        capability = Clock()
        assert capability.get_toolset() is capability.get_toolset()

    def test_skills_exclude_script_execution(self):
        """Without a sandbox, run_skill_script is remote code execution."""

        class _Skill:
            name = "refunds"
            description = "How refunds work."
            content = "# Refunds"
            resources: list[object] = []

        toolset = Skills(skills=[_Skill()]).get_toolset()
        assert toolset is not None
        assert set(toolset.tools) == set(SAFE_SKILL_TOOLS)


CATALOG_PATH = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "tool-catalog.ts"


def _frontend_tool_ids() -> frozenset[str]:
    """The ids the web chat has a row for, read out of `TOOL_CATALOG`.

    Parsed rather than generated. A generated file is a file somebody regenerates,
    and the failure this guards against is exactly the one where nobody did - so the
    check reads what a reviewer reads, and the only thing it depends on is that
    prettier keeps the object's own keys at two spaces of indentation.
    """
    source = CATALOG_PATH.read_text(encoding="utf-8")
    start = source.index("export const TOOL_CATALOG")
    body = source[source.index("{", start) : source.index("\n};", start)]
    return frozenset(re.findall(r"^  ([a-z][a-z0-9_]*): \{", body, flags=re.MULTILINE))


class TestFrontendToolCatalog:
    """The web chat's tool table holds exactly the tools capabilities register.

    The registry is the source of truth on both sides of the wire, and until #144
    nothing said so. `web_search` and `create_chart` were renamed in the backend
    (b56ba1f), three frontend files went on matching the names they had before, and
    both calls rendered as pretty-printed JSON for five weeks - beside the renderers
    written for them, with a green frontend suite, because those tests constructed
    tool calls under the old names too.

    So this is the drift check across the boundary, and it is the *backend's* because
    the registry is. Both directions matter and they fail for different reasons: a
    missing row is a call whose result a person never sees, and a surplus row is a
    renderer nothing will ever reach - which is the half that hid the bug, since a
    frontend test can assert happily on a name no backend has emitted since July.

    A name arriving from somewhere other than the registry - an MCP tool, or one a
    binding renamed - is not in scope for either direction: it has no row, falls back
    to the generic renderer, and that is the honest answer for it.
    """

    def test_the_frontend_catalog_matches_the_registry_exactly(self):
        registered = frozenset(
            tool.id for definition in all_capabilities() for tool in definition.tools
        )
        listed = _frontend_tool_ids()

        assert sorted(registered - listed) == [], (
            f"add a row to {CATALOG_PATH.name} for each of these - an icon, what the "
            "step says while it runs, and which renderer opens under it"
        )
        assert sorted(listed - registered) == [], (
            f"{CATALOG_PATH.name} has a row for a tool no capability registers; "
            "nothing will ever render it"
        )
