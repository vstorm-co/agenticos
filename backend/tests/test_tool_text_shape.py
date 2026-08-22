"""One shape for what every tool tells the model, whoever wrote the tool.

A tool implemented here reaches the model through its docstring, and pydantic-ai
wraps a `Returns:` section in `<summary>` and `<returns>` on the way. A tool that
comes from a library is registered with an explicit `description=`, which takes
that path away - so its text goes through `ToolText`, which renders what the
framework would have rendered.

These tests are what stops the two drifting: one pins `ToolText` against a tool
the framework builds itself, and the rest assert that every tool this deployment
offers says what it returns, whichever of the two routes it took.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage

from app.agents.capabilities import load_builtins
from app.agents.capabilities._registry import CapabilityBinding, build
from app.agents.capabilities._tool_text import ToolText

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _builtins_loaded() -> None:
    load_builtins()


def _ctx() -> RunContext[None]:
    return RunContext(deps=None, model=TestModel(), usage=RunUsage())


async def _described(capability_id: str, config: dict[str, object] | None = None) -> dict[str, str]:
    """Every tool one capability offers, and the text the model reads for it."""
    built = build([CapabilityBinding(capability_id=capability_id, config=config or {})])
    toolset = built[0].get_toolset()
    assert toolset is not None
    tools = await toolset.get_tools(_ctx())
    return {name: tool.tool_def.description or "" for name, tool in tools.items()}


class TestTheShapeIsTheFrameworksOwn:
    def test_tool_text_matches_a_tool_pydantic_ai_renders_itself(self) -> None:
        """Pinned against the framework, not a literal: it moves, this fails."""
        native: FunctionToolset[None] = FunctionToolset()

        @native.tool_plain
        def demo() -> str:
            """Do a thing.

            A second paragraph of usage.

            Returns:
                One line per entry.
            """
            return ""  # pragma: no cover - never called, only described

        rendered = ToolText(
            summary="Do a thing.",
            usage="A second paragraph of usage.",
            returns="One line per entry.",
        ).render()

        assert rendered == native.tools["demo"].tool_def.description

    def test_a_text_with_nothing_to_report_is_left_as_prose(self) -> None:
        """No `Returns:` section, no tags - which is what the framework does."""
        assert ToolText(summary="Do a thing.", usage="Carefully.").render() == (
            "Do a thing.\n\nCarefully."
        )

    def test_the_dynamic_half_lands_inside_the_summary(self) -> None:
        """Appended past the closing tag, the tags bracket half the text."""
        rendered = ToolText(summary="Do a thing.", returns="A line.").render("Models: gpt-5.4")

        assert "Models: gpt-5.4</summary>" in rendered


class TestEveryToolSaysWhatItReturns:
    """Whoever wrote the tool, the model is told what comes back."""

    @pytest.mark.parametrize(
        ("capability_id", "config"),
        [
            ("charts", None),
            ("sandbox", None),
            ("code_execution", None),
            ("web_research", None),
            ("web_fetch", None),
            ("planning", {"enable_subtasks": True}),
            ("tool_output_limits", None),
            ("browser_use", None),
        ],
    )
    async def test_the_capabilitys_tools_carry_a_return_shape(
        self, capability_id: str, config: dict[str, object] | None
    ) -> None:
        described = await _described(capability_id, config)

        assert described
        assert all("<returns>" in text for text in described.values()), capability_id

    async def test_the_context_tools_carry_one(self) -> None:
        from app.agents.capabilities.context._toolset import ContextItem, ContextToolset

        toolset = ContextToolset(
            [
                ContextItem(
                    name="glossary", description="terms", content="c", mode="link", format="md"
                )
            ]
        )

        assert all(
            "<returns>" in (tool.tool_def.description or "") for tool in toolset.tools.values()
        )

    async def test_the_knowledge_tool_carries_one(self) -> None:
        from app.agents.capabilities.knowledge._toolset import build_knowledge_toolset

        toolset = build_knowledge_toolset(default_top_k=5)

        assert all(
            "<returns>" in (tool.tool_def.description or "") for tool in toolset.tools.values()
        )

    async def test_the_channel_tools_carry_one(self) -> None:
        from app.agents.capabilities.channel_tools._toolset import build_channel_toolset

        toolset = build_channel_toolset(
            directory=MagicMock(),
            default_limit=20,
            tools=(
                "get_channel_info",
                "list_channel_members",
                "search_channels",
                "read_channel_history",
            ),
        )

        assert all(
            "<returns>" in (tool.tool_def.description or "") for tool in toolset.tools.values()
        )

    async def test_a_toolset_it_cannot_rewrite_is_refused_rather_than_left_alone(self) -> None:
        """Left alone, the model reads one text and the Builder shows another."""
        from dataclasses import dataclass
        from typing import Any

        from pydantic_ai.capabilities import AbstractCapability

        from app.agents.capabilities.tool_output_limits._capability import (
            MeteredToolOutputLimits,
        )

        @dataclass
        class _PerRun(AbstractCapability[Any]):
            def get_toolset(self) -> Any:
                return lambda ctx: FunctionToolset()

        wrapped = MeteredToolOutputLimits(wrapped=_PerRun(id="per_run"))

        with pytest.raises(TypeError, match="read_tool_result"):
            wrapped.get_toolset()

    async def test_tool_search_carries_one(self) -> None:
        """The tool a model reaches for when it is already lost."""
        from app.agents.capabilities.tool_search._capability import SEARCH_TEXT, build_tool_search

        capability = build_tool_search("auto", max_results=10)

        assert capability.tool_description == SEARCH_TEXT.render()
        assert "<returns>" in SEARCH_TEXT.render()


class TestTheBuilderReadsWhatTheModelReads:
    """A contract is the whole text; the catalog entry is its first sentence."""

    def test_every_capability_that_builds_reports_its_tools(self) -> None:
        """An unreadable toolset shows the catalog one-liner and logs, silently."""
        from app.services.capability_contracts import tool_contracts

        contracts = tool_contracts()

        for capability_id in ("context", "tool_output_limits", "planning", "sandbox", "charts"):
            assert contracts.get(capability_id), capability_id

    def test_the_contract_opens_with_the_sentence_the_catalog_shows(self) -> None:
        """Two copies drift; the Builder must not paraphrase what the model reads."""
        from app.agents.capabilities._registry import all_capabilities
        from app.services.capability_contracts import tool_contracts

        contracts = tool_contracts()

        for definition in all_capabilities():
            for tool in definition.tools:
                contract = contracts.get(definition.id, {}).get(tool.id)
                if contract is None:
                    continue
                assert contract.description.startswith(
                    f"<summary>{tool.description}"
                ) or contract.description.startswith(tool.description), f"{definition.id}.{tool.id}"
