"""Tests for what each capability's tools actually do.

The registry tests cover assembly; these cover behaviour. Both matter, and they
fail for different reasons: a broken registry means an agent cannot be built, a
broken tool means it is built and then answers wrongly.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend
from pydantic_ai_backends.permissions import PermissionChecker

from app.agents.capabilities.charts import ChartsToolset
from app.agents.capabilities.charts._spec import ChartSeries, parse_chart_spec
from app.agents.capabilities.charts._toolset import ChartSeriesInput
from app.agents.capabilities.code_execution import CodeExecution
from app.agents.capabilities.code_execution._sandbox import (
    RunOutcome,
    _clip,
    _format_result,
    run_python,
)
from app.agents.capabilities.knowledge._search import _format_results
from app.agents.capabilities.knowledge._toolset import build_knowledge_toolset
from app.agents.capabilities.sandbox._capability import build_workspace
from app.agents.capabilities.sandbox._permissions import workspace_ruleset
from app.agents.capabilities.web_research._search import parse_web_search
from app.agents.deps import AgentDeps


def _tool_ctx(deps: Any = None, *, retry: int = 0, max_retries: int = 1) -> RunContext[Any]:
    """A context with a retry left, which is what a real call starts with."""
    return RunContext(
        deps=deps, model=TestModel(), usage=RunUsage(), retry=retry, max_retries=max_retries
    )


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
        """Returned as text it reads as "nothing found", and the model invents."""
        toolset = build_knowledge_toolset(default_top_k=5)
        search = toolset.tools["search_documents"].function

        with (
            patch(
                "app.agents.capabilities.knowledge._toolset.search_knowledge_base",
                new=AsyncMock(side_effect=RuntimeError("vector store down")),
            ),
            pytest.raises(ModelRetry),
        ):
            await search(_tool_ctx(AgentDeps()), query="x")

    @pytest.mark.anyio
    async def test_the_last_attempt_says_so_rather_than_ending_the_run(self):
        """A `ModelRetry` past the budget takes the conversation with it."""
        toolset = build_knowledge_toolset(default_top_k=5)
        search = toolset.tools["search_documents"].function

        with patch(
            "app.agents.capabilities.knowledge._toolset.search_knowledge_base",
            new=AsyncMock(side_effect=RuntimeError("vector store down")),
        ):
            answered = await search(_tool_ctx(AgentDeps(), retry=1), query="x")

        assert "unavailable" in answered


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
            new=AsyncMock(return_value=RunOutcome("42")),
        ):
            assert await run(_tool_ctx(), code="print(6*7)") == "42"

    @pytest.mark.anyio
    async def test_a_program_that_raises_asks_the_model_to_fix_it(self):
        """The `code` argument is what the model wrote, so this is a bad call."""
        toolset = CodeExecution().get_toolset()
        run = toolset.tools["run_python"].function

        with (
            patch(
                "app.agents.capabilities.code_execution._toolset.run_python",
                new=AsyncMock(return_value=RunOutcome("Execution failed: NameError", fixable=True)),
            ),
            pytest.raises(ModelRetry, match="NameError"),
        ):
            await run(_tool_ctx(), code="nope")

    @pytest.mark.anyio
    async def test_a_sandbox_that_died_is_reported_rather_than_retried(self):
        """No rewrite of the program fixes the sandbox failing to start."""
        toolset = CodeExecution().get_toolset()
        run = toolset.tools["run_python"].function

        with patch(
            "app.agents.capabilities.code_execution._toolset.run_python",
            new=AsyncMock(return_value=RunOutcome("Execution failed: sandbox unavailable")),
        ):
            assert "sandbox unavailable" in await run(_tool_ctx(), code="6*7")

    @pytest.mark.anyio
    async def test_the_last_attempt_answers_rather_than_ending_the_run(self):
        toolset = CodeExecution().get_toolset()
        run = toolset.tools["run_python"].function

        with patch(
            "app.agents.capabilities.code_execution._toolset.run_python",
            new=AsyncMock(return_value=RunOutcome("Execution failed: NameError", fixable=True)),
        ):
            answered = await run(_tool_ctx(retry=1), code="nope")

        assert "NameError" in answered

    @pytest.mark.anyio
    async def test_the_bindings_limits_reach_the_sandbox(self):
        """The config is only real if the sandbox call carries it - a limit
        raised in the Builder that never reaches Monty bounds nothing."""
        toolset = CodeExecution(timeout_secs=30.0, max_memory_mb=512).get_toolset()
        run = toolset.tools["run_python"].function
        sandbox = AsyncMock(return_value=RunOutcome("ok"))

        with patch("app.agents.capabilities.code_execution._toolset.run_python", new=sandbox):
            await run(_tool_ctx(), code="6*7")

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
    async def test_the_sandbox_failing_to_start_is_not_the_programs_fault(self):
        """A retry prompt here would ask the model to rewrite working code."""
        with patch(
            "app.agents.capabilities.code_execution._sandbox.AsyncMonty",
            side_effect=RuntimeError("sandbox unavailable"),
        ):
            outcome = await run_python("this is not python")

        assert "sandbox unavailable" in outcome.text
        assert outcome.fixable is False

    @pytest.mark.anyio
    async def test_an_error_in_the_program_is_the_models_to_fix(self):
        outcome = await run_python("undefined_name")

        assert "NameError" in outcome.text
        assert outcome.fixable is True

    @pytest.mark.anyio
    async def test_a_program_that_runs_out_of_time_is_also_the_models_to_fix(self):
        """The limit reports as `TimeoutError`; cheaper code is the fix."""
        outcome = await run_python("while True: pass", timeout_secs=0.5)

        assert "TimeoutError" in outcome.text
        assert outcome.fixable is True


class TestChartTool:
    def test_creates_a_parsable_specification(self):
        spec = ChartsToolset().create_chart(
            _tool_ctx(),
            chart_type="bar",
            title="Revenue",
            x_values=["Jan", "Feb"],
            series=[ChartSeriesInput(key="y", values=[10, 20])],
        )
        assert json.loads(spec)["kind"] == "chart"
        assert parse_chart_spec(spec) is not None

    def test_the_x_axis_field_is_not_treated_as_a_series(self):
        """The axis is its own argument, so it cannot be mistaken for a series."""
        spec = parse_chart_spec(
            ChartsToolset().create_chart(
                _tool_ctx(),
                chart_type="line",
                title="Revenue",
                x_values=["Jan"],
                series=[ChartSeriesInput(key="revenue", values=[1])],
            )
        )
        assert spec is not None
        assert all(s.key != "x" for s in spec.series)

    def test_a_label_survives_onto_the_emitted_series(self):
        spec = parse_chart_spec(
            ChartsToolset().create_chart(
                _tool_ctx(),
                chart_type="line",
                title="Revenue",
                x_values=["Jan"],
                series=[ChartSeriesInput(key="revenue", values=[1], label="Revenue")],
            )
        )
        assert spec is not None
        assert (spec.series[0].key, spec.series[0].label) == ("revenue", "Revenue")

    def test_parsing_junk_returns_nothing_rather_than_raising(self):
        """The channel renderer inspects every tool result; a stray string is normal."""
        assert parse_chart_spec("not a chart") is None

    def test_a_series_carries_a_label(self):
        assert ChartSeries(key="revenue", label="Revenue").label == "Revenue"


class TestWebSearchParsing:
    def test_parsing_junk_returns_nothing(self):
        assert parse_web_search("not results") is None


class TestTheWorkspaceRefusesAnOffLimitsPath:
    """Our ruleset, applied to the toolset the model is actually handed.

    The mechanics of applying a ruleset are the library's now and tested there -
    `pydantic-ai-backend` 0.2.25 grew `GuardedBackend` after
    vstorm-co/pydantic-ai-backend#97, which is where a wrapper of ours used to
    live. What is still worth asserting here is the wiring and the *contents* of
    the ruleset this repository writes: that `build_workspace` passes it, that a
    credential and the system tree are in it, and that a chart an agent produced
    is not.

    Kept because that is exactly what a library upgrade could quietly take away.
    A test of the wrapper would now be a test of somebody else's code; this is a
    test that our agent cannot read `/etc/passwd`.
    """

    pytestmark = pytest.mark.anyio

    @staticmethod
    def _workspace() -> StateBackend:
        backend = StateBackend()
        backend.write("/notes.txt", "ordinary work")
        backend.write("/chart.png", "not really a png")
        backend.write("/.env", "OPENAI_API_KEY=sk-live-secret")
        backend.write("/sub/.env", "NESTED=sk-live-secret")
        backend.write("/credentials.txt", "PASSWORD=hunter2")
        backend.write("/etc/passwd", "root:x:0:0")
        return backend

    async def _call(self, name: str, **kwargs: Any) -> Any:
        capability = build_workspace(backend=self._workspace(), include_execute=False)
        result = capability._toolset.tools[name].function(MagicMock(), **kwargs)
        return await result if asyncio.iscoroutine(result) else result

    @pytest.mark.parametrize("path", ["/.env", "/sub/.env", "/credentials.txt", "/etc/passwd"])
    async def test_reading_a_credential_or_the_system_is_refused(self, path: str):
        """Through the registered tool, which is the only thing the model can
        reach - not through the ruleset object, which was correct all along and
        was never consulted."""
        assert "Permission denied" in await self._call("read_file", path=path)

    async def test_writing_over_a_credential_is_refused(self):
        assert "Permission denied" in await self._call("write_file", path="/sub/.env", content="x")

    async def test_the_agents_own_files_are_untouched(self):
        """The half that has to keep working: a ruleset that refused everything
        would pass every test above and make the capability useless."""
        assert "ordinary work" in await self._call("read_file", path="/notes.txt")
        assert "Wrote" in await self._call("write_file", path="/report.csv", content="a,b")

    async def test_a_search_does_not_return_a_line_from_a_credential(self):
        """`grep` carries the matching line, so an unfiltered one hands over the
        contents of exactly the files the ruleset protects."""
        answer = await self._call("grep", pattern="PASSWORD")

        assert "/credentials.txt" not in answer

    async def test_the_ruleset_covers_what_we_meant_it_to(self):
        """The contents rather than the mechanism. A library upgrade cannot change
        which patterns we chose, but a careless edit here could - and the
        consequence would be an agent reading a private key."""
        checker = PermissionChecker(workspace_ruleset())

        for path in ("/.env", "/deploy/id_rsa.pem", "/x/.ssh/config", "/etc/shadow", "/usr/bin/x"):
            assert checker.check_sync("read", path) == "deny", path
        for path in ("/notes.txt", "/uploads/report.csv", "/chart.png"):
            assert checker.check_sync("read", path) == "allow", path
