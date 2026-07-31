"""Tests for what each capability's tools actually do.

The registry tests cover assembly; these cover behaviour. Both matter, and they
fail for different reasons: a broken registry means an agent cannot be built, a
broken tool means it is built and then answers wrongly.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.charts import ChartsToolset
from app.agents.capabilities.charts._spec import ChartSeries, parse_chart_spec
from app.agents.capabilities.charts._toolset import _infer_series
from app.agents.capabilities.code_execution import CodeExecution
from app.agents.capabilities.code_execution._sandbox import _clip, _format_result, run_python
from app.agents.capabilities.knowledge._search import _format_results
from app.agents.capabilities.knowledge._toolset import build_knowledge_toolset
from app.agents.capabilities.web_research._search import parse_web_search
from app.agents.deps import AgentDeps


def _ctx(deps: AgentDeps) -> MagicMock:
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


class TestKnowledgeTool:
    @pytest.mark.anyio
    async def test_searches_only_the_bound_collections(self):
        """The model chooses what to search; the server chooses where."""
        toolset = build_knowledge_toolset(default_top_k=5)
        search = toolset.tools["search_documents"].function

        with patch(
            "app.agents.capabilities.knowledge._toolset.search_knowledge_base",
            new=AsyncMock(return_value="results"),
        ) as backend:
            result = await search(
                _ctx(AgentDeps(kb_collection_names=["kb_a", "kb_b"])), query="refunds"
            )

        assert result == "results"
        assert backend.call_args.kwargs["kb_collection_names"] == ["kb_a", "kb_b"]

    @pytest.mark.anyio
    async def test_uses_the_agent_default_when_the_model_omits_top_k(self):
        toolset = build_knowledge_toolset(default_top_k=9)
        search = toolset.tools["search_documents"].function

        with patch(
            "app.agents.capabilities.knowledge._toolset.search_knowledge_base",
            new=AsyncMock(return_value=""),
        ) as backend:
            await search(_ctx(AgentDeps()), query="x")

        assert backend.call_args.kwargs["top_k"] == 9

    @pytest.mark.anyio
    async def test_an_explicit_top_k_wins(self):
        toolset = build_knowledge_toolset(default_top_k=9)
        search = toolset.tools["search_documents"].function

        with patch(
            "app.agents.capabilities.knowledge._toolset.search_knowledge_base",
            new=AsyncMock(return_value=""),
        ) as backend:
            await search(_ctx(AgentDeps()), query="x", top_k=2)

        assert backend.call_args.kwargs["top_k"] == 2

    @pytest.mark.anyio
    async def test_a_backend_failure_asks_the_model_to_retry(self):
        """A transient vector-store error should not end the conversation."""
        from pydantic_ai import ModelRetry

        toolset = build_knowledge_toolset(default_top_k=5)
        search = toolset.tools["search_documents"].function

        with (
            patch(
                "app.agents.capabilities.knowledge._toolset.search_knowledge_base",
                new=AsyncMock(side_effect=RuntimeError("vector store down")),
            ),
            pytest.raises(ModelRetry),
        ):
            await search(_ctx(AgentDeps()), query="x")


class TestKnowledgeFormatting:
    def test_no_results_says_so_rather_than_returning_nothing(self):
        """An empty string reads to the model as a broken tool."""
        assert "No relevant" in _format_results([])

    def test_results_carry_their_source(self):
        result = MagicMock(score=0.9, content="Refunds within 30 days.")
        result.metadata = {"filename": "policy.pdf", "page_num": 3}
        formatted = _format_results([result])
        assert "policy.pdf" in formatted
        assert "page 3" in formatted
        assert "Refunds within 30 days." in formatted

    def test_the_model_is_told_to_cite_inline(self):
        """Without this instruction models append a bibliography nobody reads."""
        result = MagicMock(score=0.9, content="text")
        result.metadata = {"filename": "a.pdf"}
        assert "cite inline" in _format_results([result])


class TestCodeExecutionTool:
    @pytest.mark.anyio
    async def test_runs_a_program_and_returns_its_output(self):
        toolset = CodeExecution().get_toolset()
        run = toolset.tools["run_python"].function

        with patch(
            "app.agents.capabilities.code_execution._toolset.run_python",
            new=AsyncMock(return_value="42"),
        ):
            assert await run("print(6*7)") == "42"

    @pytest.mark.anyio
    async def test_the_bindings_limits_reach_the_sandbox(self):
        """The config is only real if the sandbox call carries it - a limit
        raised in the Builder that never reaches Monty bounds nothing."""
        toolset = CodeExecution(timeout_secs=30.0, max_memory_mb=512).get_toolset()
        run = toolset.tools["run_python"].function
        sandbox = AsyncMock(return_value="ok")

        with patch("app.agents.capabilities.code_execution._toolset.run_python", new=sandbox):
            await run("6*7")

        assert sandbox.call_args.kwargs == {"timeout_secs": 30.0, "max_memory_mb": 512}

    def test_long_output_is_clipped_rather_than_flooding_the_context(self):
        clipped = _clip("x" * 100_000)
        assert len(clipped) < 100_000
        assert "truncated" in clipped.lower() or clipped.endswith("...")

    def test_short_output_is_untouched(self):
        assert _clip("hello") == "hello"

    def test_stdout_and_the_final_value_are_both_reported(self):
        formatted = _format_result("printed line", 42)
        assert "printed line" in formatted
        assert "42" in formatted

    def test_no_output_is_stated_explicitly(self):
        """Silence reads to the model as a failure; say the program produced nothing."""
        formatted = _format_result("", None)
        assert formatted.strip() != ""

    @pytest.mark.anyio
    async def test_a_sandbox_error_is_returned_not_raised(self):
        """The model can fix its own syntax error if it is told what went wrong."""
        with patch(
            "app.agents.capabilities.code_execution._sandbox.AsyncMonty",
            side_effect=RuntimeError("sandbox unavailable"),
        ):
            result = await run_python("this is not python")
        assert "Execution failed" in result
        assert "sandbox unavailable" in result


class TestChartTool:
    def test_creates_a_parsable_specification(self):
        spec = ChartsToolset().create_chart(
            chart_type="bar",
            title="Revenue",
            data=[{"x": "Jan", "y": 10}, {"x": "Feb", "y": 20}],
        )
        assert json.loads(spec)["kind"] == "chart"
        assert parse_chart_spec(spec) is not None

    def test_series_are_inferred_from_the_data(self):
        series = _infer_series([{"x": "Jan", "revenue": 1, "cost": 2}], "x")
        assert {s.key for s in series} == {"revenue", "cost"}

    def test_the_x_axis_field_is_not_treated_as_a_series(self):
        series = _infer_series([{"x": "Jan", "revenue": 1}], "x")
        assert all(s.key != "x" for s in series)

    def test_explicit_series_are_respected(self):
        spec = ChartsToolset().create_chart(
            chart_type="line",
            title="Revenue",
            data=[{"x": "Jan", "revenue": 1}],
            series=[ChartSeries(key="revenue", label="Revenue")],
        )
        parsed = parse_chart_spec(spec)
        assert parsed is not None
        assert parsed.series[0].key == "revenue"

    def test_parsing_junk_returns_nothing_rather_than_raising(self):
        """The channel renderer inspects every tool result; a stray string is normal."""
        assert parse_chart_spec("not a chart") is None

    def test_a_series_carries_a_label(self):
        assert ChartSeries(key="revenue", label="Revenue").label == "Revenue"


class TestWebSearchParsing:
    def test_parsing_junk_returns_nothing(self):
        assert parse_web_search("not results") is None
