"""Tests for the context capability - how bound files reach the model.

The things worth guarding: an injected file is framed as reference material
rather than commands, a linked file is read on demand and an unknown name is a
retry not a crash, and a binding with nothing usable contributes nothing at all
(the issue's own done-when).
"""

from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

from app.agents.capabilities import build
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext
from app.agents.capabilities.context import CONTEXT_FILES_RESOURCE, Context, ContextConfig, _build
from app.agents.capabilities.context._capability import _PREAMBLE
from app.agents.capabilities.context._toolset import ContextItem, ContextToolset


def _item(name="glossary", *, mode="inject", content="SLA: service level agreement.", desc="terms"):
    return ContextItem(name=name, description=desc, content=content, mode=mode, format="md")


def _file(name="glossary", *, mode="inject", content="body", desc="terms"):
    return SimpleNamespace(name=name, description=desc, content=content, mode=mode, format="md")


def _ctx(files, *, expose_read_tool=True):
    return CapabilityBuildContext(
        binding=CapabilityBinding(capability_id="context"),
        config=ContextConfig(expose_read_tool=expose_read_tool),
        resources={CONTEXT_FILES_RESOURCE: files},
    )


class TestInstructions:
    def test_an_injected_file_is_framed_as_reference_material(self):
        cap = Context(items=(_item(content="SLA means service level agreement."),))
        instructions = cap.get_instructions()
        assert instructions is not None
        assert _PREAMBLE in instructions
        assert '<context-file name="glossary" format="md">' in instructions
        assert "SLA means service level agreement." in instructions

    def test_a_linked_file_is_not_injected(self):
        cap = Context(items=(_item(mode="link"),))
        assert cap.get_instructions() is None

    def test_only_injected_files_appear_in_the_instructions(self):
        cap = Context(
            items=(
                _item("in", mode="inject", content="injected body"),
                _item("out", mode="link", content="linked body"),
            )
        )
        instructions = cap.get_instructions()
        assert instructions is not None
        assert "injected body" in instructions
        assert "linked body" not in instructions


class TestToolset:
    def test_no_linked_files_means_no_toolset(self):
        assert Context(items=(_item(mode="inject"),)).get_toolset() is None

    def test_a_linked_file_exposes_both_tools(self):
        toolset = Context(items=(_item(mode="link"),)).get_toolset()
        assert isinstance(toolset, ContextToolset)

    def test_the_read_tool_can_be_turned_off(self):
        cap = Context(items=(_item(mode="link"),), expose_read_tool=False)
        assert cap.get_toolset() is None

    def test_the_toolset_is_built_once(self):
        cap = Context(items=(_item(mode="link"),))
        assert cap.get_toolset() is cap.get_toolset()

    def test_list_context_names_files_without_their_bodies(self):
        toolset = ContextToolset(
            [_item("glossary", mode="link", content="secret body", desc="terms")]
        )
        listed = toolset.list_context()
        assert "glossary: terms" in listed
        assert "secret body" not in listed

    def test_list_context_falls_back_to_the_name_without_a_description(self):
        toolset = ContextToolset([_item("runbook", mode="link", desc=None)])
        assert toolset.list_context() == "- runbook"

    def test_read_context_returns_the_body(self):
        toolset = ContextToolset([_item("glossary", mode="link", content="the body")])
        assert toolset.read_context("glossary") == "the body"

    def test_reading_an_unknown_file_is_a_retry_naming_what_exists(self):
        toolset = ContextToolset([_item("glossary", mode="link")])
        with pytest.raises(ModelRetry, match="glossary"):
            toolset.read_context("missing")

    def test_reading_when_nothing_is_linked_reports_none_available(self):
        toolset = ContextToolset([])
        with pytest.raises(ModelRetry, match="none"):
            toolset.read_context("anything")


class TestBuilder:
    def test_no_files_contributes_nothing(self):
        assert _build(_ctx([])) is None

    def test_a_binding_with_only_read_tool_off_and_links_contributes_nothing(self):
        assert _build(_ctx([_file(mode="link")], expose_read_tool=False)) is None

    def test_an_injected_file_builds_the_capability(self):
        cap = _build(_ctx([_file(mode="inject")]))
        assert isinstance(cap, Context)
        assert cap.get_instructions() is not None

    def test_a_linked_file_builds_the_capability(self):
        cap = _build(_ctx([_file(mode="link")]))
        assert isinstance(cap, Context)
        assert cap.get_toolset() is not None

    def test_the_builder_falls_back_to_default_config(self):
        ctx = CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="context"),
            config=None,
            resources={CONTEXT_FILES_RESOURCE: [_file(mode="link")]},
        )
        assert isinstance(_build(ctx), Context)

    def test_it_is_registered_and_offers_its_tools_through_the_registry(self):
        (capability,) = build(
            [CapabilityBinding(capability_id="context")],
            resources={CONTEXT_FILES_RESOURCE: [_file(mode="link")]},
        )
        assert capability.id == "context"
