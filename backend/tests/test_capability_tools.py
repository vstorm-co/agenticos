"""Tests for what each capability's tools actually do.

The registry tests cover assembly; these cover behaviour. Both matter, and they
fail for different reasons: a broken registry means an agent cannot be built, a
broken tool means it is built and then answers wrongly.
"""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai_backends import StateBackend

from app.agents.capabilities.charts import ChartsToolset
from app.agents.capabilities.charts._spec import ChartSeries, parse_chart_spec
from app.agents.capabilities.charts._toolset import _infer_series
from app.agents.capabilities.code_execution import CodeExecution
from app.agents.capabilities.code_execution._sandbox import _clip, _format_result, run_python
from app.agents.capabilities.knowledge._search import _format_results
from app.agents.capabilities.knowledge._toolset import build_knowledge_toolset
from app.agents.capabilities.sandbox._capability import build_workspace
from app.agents.capabilities.sandbox._permissions import GuardedBackend, workspace_ruleset
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


class TestTheWorkspaceRefusesAnOffLimitsPath:
    """The ruleset only means something if something evaluates it.

    It used to mean nothing. `ConsoleCapability(permissions=...)` reads each
    operation's *default action* and never its per-path `rules`, so twenty deny
    patterns per operation sat there while an agent read `/etc/passwd` and
    `**/.env` as freely as its own scratch files. These assert the consequence
    rather than the shape of the ruleset - a test that checked the rules were
    present passed throughout.
    """

    pytestmark = pytest.mark.anyio

    @staticmethod
    def _guarded() -> GuardedBackend:
        backend = StateBackend()
        backend.write("/notes.txt", "ordinary work")
        backend.write("/.env", "OPENAI_API_KEY=sk-live-secret")
        backend.write("/sub/.env", "NESTED=sk-live-secret")
        backend.write("/credentials.txt", "PASSWORD=hunter2")
        backend.write("/etc/passwd", "root:x:0:0")
        return GuardedBackend(backend, workspace_ruleset())

    @pytest.mark.parametrize("path", ["/.env", "/sub/.env", "/credentials.txt", "/etc/passwd"])
    async def test_reading_a_credential_or_the_system_is_refused(self, path: str):
        with pytest.raises(PermissionError):
            await self._guarded().read(path)

    @pytest.mark.parametrize("path", ["/.env", "/sub/.env", "/credentials.txt", "/etc/passwd"])
    async def test_reading_one_as_bytes_is_refused_too(self, path: str):
        """`read_file` on an image goes through `read_bytes`, so a guard on
        `read` alone would leave the same file readable by asking differently."""
        with pytest.raises(PermissionError):
            await self._guarded().read_bytes(path)

    async def test_the_workspaces_own_files_still_read(self):
        assert "ordinary work" in await self._guarded().read("/notes.txt")

    async def test_the_workspaces_own_files_still_read_as_bytes(self):
        """The path `read_file` takes for an image, so it needs its own case -
        a guard that only let text through would stop an agent seeing a chart."""
        assert await self._guarded().read_bytes("/notes.txt") == b"ordinary work"

    async def test_writing_over_a_credential_is_refused_as_a_value(self):
        """An error result, not a raise: it is what the model reads and acts on,
        and the protocol has a place for it."""
        result = await self._guarded().write("/sub/.env", "x")
        assert result.error is not None
        assert "Permission denied" in result.error

    async def test_an_ordinary_write_still_lands(self):
        assert (await self._guarded().write("/report.csv", "a,b")).error is None

    async def test_editing_a_credential_is_refused_as_a_value(self):
        result = await self._guarded().edit("/.env", "sk-live-secret", "x")
        assert result.error is not None

    async def test_an_ordinary_edit_still_applies(self):
        assert (await self._guarded().edit("/notes.txt", "ordinary", "usual")).error is None

    async def test_grep_does_not_return_a_line_from_a_file_it_may_not_read(self):
        """The one that matters most, and the one a guard on `read` misses.

        `GrepMatch` carries the matching *line*, so an unfiltered grep hands over
        the contents of exactly the files the ruleset exists to protect - by a
        different tool, with no refusal anywhere.
        """
        backend = StateBackend()
        backend.write("/credentials.txt", "PASSWORD=hunter2")
        backend.write("/notes.txt", "PASSWORD is stored elsewhere")
        guarded = GuardedBackend(backend, workspace_ruleset())

        found = await guarded.grep_raw("PASSWORD")

        assert [match["path"] for match in found] == ["/notes.txt"]

    async def test_a_grep_that_answers_with_a_string_is_passed_through(self):
        """ "No matches" and a backend error are strings, not result sets."""

        class _Backend:
            def grep_raw(self, *_args: object, **_kwargs: object) -> str:
                return "No matches for 'x'"

        guarded = GuardedBackend(cast("Any", _Backend()), workspace_ruleset())
        assert await guarded.grep_raw("x") == "No matches for 'x'"

    async def test_names_are_not_secret_so_discovery_delegates(self):
        """`exists`, `ls` and `glob` answer about names rather than contents.

        Deliberate, and worth a test so a later reader does not "fix" it: `ls
        /etc` saying what is there while every read of it refuses is the stated
        boundary, not an oversight.
        """
        guarded = self._guarded()
        assert await guarded.exists("/etc/passwd") is True
        assert [entry["path"] for entry in await guarded.glob_info("**/.env")]
        assert await guarded.ls_info("/")

    async def test_anything_the_protocol_does_not_name_passes_through(self):
        """A container-backed workspace has `execute` and `stop`, and a stored one
        has `files` that the flush reads. An explicit method list would have
        dropped all three."""

        class _Backend:
            files = {"/a.txt": {}}

            def execute(self, command: str, timeout: int | None = None) -> str:
                return f"ran {command}"

        guarded = GuardedBackend(cast("Any", _Backend()), workspace_ruleset())
        assert await guarded.execute("ls") == "ran ls"
        assert guarded.files == {"/a.txt": {}}

    def test_it_says_what_it_wraps(self):
        assert "GuardedBackend" in repr(self._guarded())

    async def test_the_capability_is_built_with_the_guard_in_place(self):
        """The assertion that would have caught the original defect: not that the
        ruleset exists, but that the toolset the model is handed refuses."""
        backend = StateBackend()
        backend.write("/etc/passwd", "root:x:0:0")

        capability = build_workspace(backend=backend, include_execute=False)

        with pytest.raises(PermissionError):
            await capability.backend.read("/etc/passwd")
