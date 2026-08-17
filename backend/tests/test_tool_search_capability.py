"""Tests for the tool-search capability.

What is worth pinning: the chosen strategy reaches the library unchanged, `auto`
becomes the library's `None` rather than a string it does not know, the capability
declares no tool for the model to be shown or asked to approve, and - the reason
the capability exists at all - it is what makes the factory hide the MCP toolsets
behind search. An agent that does not bind it pays nothing.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from pydantic_ai.capabilities import ToolSearch

from app.agents.capabilities import build, get
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext
from app.agents.capabilities.tool_search import ToolSearchConfig, build_tool_search


def _built(config: dict | None = None) -> ToolSearch[object]:
    (capability,) = build([CapabilityBinding(capability_id="tool_search", config=config or {})])
    assert isinstance(capability, ToolSearch)
    return capability


class TestStrategy:
    def test_auto_is_the_librarys_none_not_a_string_it_rejects(self):
        """`auto` is our word for "let Pydantic AI pick"; the library spells it `None`."""
        assert build_tool_search("auto", 10).strategy is None

    @pytest.mark.parametrize("named", ["keywords", "bm25", "regex"])
    def test_a_named_strategy_reaches_the_library_unchanged(self, named: str):
        assert build_tool_search(named, 10).strategy == named  # type: ignore[arg-type]

    def test_the_result_cap_is_carried_through(self):
        assert build_tool_search("keywords", 3).max_results == 3

    def test_the_default_binding_is_auto(self):
        built = _built()
        assert built.strategy is None
        assert built.max_results == 10


class TestConfig:
    def test_max_results_is_bounded(self):
        """A local search that returns nothing, or the whole toolset, is not a search."""
        with pytest.raises(ValidationError):
            ToolSearchConfig(max_results=0)
        with pytest.raises(ValidationError):
            ToolSearchConfig(max_results=51)

    def test_an_unknown_strategy_is_refused(self):
        with pytest.raises(ValidationError):
            ToolSearchConfig(strategy="fuzzy")  # type: ignore[arg-type]

    def test_a_binding_with_no_config_uses_the_defaults(self):
        """The builder is reached with `config=None` on an internal path; it must
        not fall over, because the drift test builds every capability that way."""
        definition = get("tool_search")
        capability = definition.builder(
            CapabilityBuildContext(
                binding=CapabilityBinding(capability_id="tool_search"), config=None
            )
        )
        assert isinstance(capability, ToolSearch)
        assert capability.strategy is None


class TestContributesNoTool:
    def test_it_declares_no_tool_to_gate_or_rename(self):
        assert get("tool_search").tool_ids == frozenset()

    def test_in_isolation_it_resolves_to_no_toolset(self):
        """`search_tools` appears only once it wraps a toolset with deferred tools,
        which the factory arranges - so on its own it offers the model nothing."""
        assert _built().get_toolset() is None
