"""Tests for the capability registry — the code/configuration boundary.

What is guarded: configuration may reach only what code registered, a capability
that contributes nothing is not attached, and a spec asking for something
ungranted fails while a person is looking at a form rather than mid-run.
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
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
from app.agents.capabilities.charts import Charts
from app.agents.capabilities.clock import Clock
from app.agents.capabilities.code_execution import CodeExecution
from app.agents.capabilities.knowledge import Knowledge, KnowledgeConfig
from app.agents.capabilities.skills import SAFE_SKILL_TOOLS, Skills
from app.agents.capabilities.web_research import WebResearch
from app.core.exceptions import BadRequestError


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


def _run_context() -> RunContext[None]:
    """The least a wrapped toolset needs before it will list its tools."""
    return RunContext(deps=None, model=TestModel(), usage=RunUsage())


class TestSelfLoading:
    """The registry must not depend on the caller having warmed it up.

    It used to: ``load_builtins()`` ran in the FastAPI lifespan and nowhere
    else, so the CLI, a worker or a script got an empty registry and every
    publish failed with "Unknown capability" — naming a capability that is in
    the repository, listed in the picker and documented. The gap only showed up
    when somebody actually ran `make platform-bootstrap`.
    """

    @staticmethod
    def _in_a_fresh_process(source: str) -> str:
        """Run a snippet in a new interpreter and return what it printed.

        A subprocess is the only honest way to test this. Clearing ``REGISTRY``
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

    # Enough for every capability that only builds when it has something to work
    # with; the assertions here are about names, not about search results.
    RESOURCES = {
        "kb_collection_names": ["kb_1"],
        "skills": [
            SimpleNamespace(
                name="refunds",
                description="How refunds work.",
                content="…",
                resources=[],
            )
        ],
    }

    def test_every_builtin_declares_the_tools_it_actually_offers(self):
        """Declaration feeds the Builder; the toolset is the truth.

        A declared tool that does not exist offers approval for nothing. The
        dangerous direction is the other one: a real tool nobody declared is a
        tool the Builder cannot gate, and a side-effecting one would run
        unattended with no way to say otherwise.
        """
        for definition in all_capabilities():
            built = definition.builder(
                CapabilityBuildContext(
                    binding=CapabilityBinding(capability_id=definition.id),
                    config=None,
                    resources=self.RESOURCES,
                )
            )
            if built is None:
                continue
            toolset = built.get_toolset()
            offered = frozenset(toolset.tools) if toolset is not None else frozenset()

            assert offered == definition.tool_ids, definition.id

    @pytest.mark.anyio
    async def test_renaming_every_tool_cannot_hide_an_undeclared_one(self):
        """The same check, through a binding that renames all of it.

        Renaming is the one thing that makes "declared" and "offered" legitimately
        different strings, so the check above could have been satisfied by
        loosening it — and a loosened version would stop catching the failure it
        exists for. Instead the expectation moves with the rename: every declared
        tool must arrive under its new name, and a tool nobody declared has no new
        name to arrive under, so it still shows up as a difference.
        """
        for definition in all_capabilities():
            overrides = {
                tool.id: ToolOverride(name=f"{tool.id}_as_this_agent_calls_it")
                for tool in definition.tools
            }
            built = build(
                [CapabilityBinding(capability_id=definition.id, tool_overrides=overrides)],
                resources=self.RESOURCES,
            )
            if not built:
                continue
            toolset = built[0].get_toolset()
            offered = (
                frozenset(await toolset.get_tools(_run_context()))
                if toolset is not None
                else frozenset()
            )

            expected = frozenset(tool.name for tool in definition.effective_tools(overrides))
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

    def test_capabilities_without_a_schema_accept_nothing(self):
        assert get("code_execution").validate_config({}) is None

    def test_config_schema_is_exposed_as_json_schema(self):
        """The configuration form is generated from this, never hand-written."""
        schema = get("knowledge").config_json_schema()
        assert schema is not None
        assert "default_top_k" in schema["properties"]

    def test_capabilities_without_a_schema_expose_none(self):
        assert get("code_execution").config_json_schema() is None


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
        """A search tool that always returns empty is worse than none — the model keeps trying."""
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
