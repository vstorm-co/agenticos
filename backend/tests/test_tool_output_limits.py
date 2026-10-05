"""Tests for the tool-output-limits capability.

What is guarded: an oversized return is reduced once at production time and not
re-sent in full; a spill goes to the run's own workspace and reads back by handle;
a spill the workspace refuses degrades to a visible truncation rather than a silent
drop; a `summarize` call is booked against the run that paid for it; and an agent
that does not bind the capability gets nothing - no read-back tool, no reduction.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_ai._run_context import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ToolCallPart, ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RunUsage
from pydantic_ai.workspaces import Workspace, WrapperWorkspace
from pydantic_ai_harness.tool_output_limits import Spill, Summarize, Truncate

from app.agents.capabilities import CapabilityBinding, build, get
from app.agents.capabilities._registry import CapabilityBuildContext
from app.agents.capabilities.budget import (
    BudgetGuard,
    BudgetScope,
    SpendLedger,
    SpendLimit,
    guarded_by,
    metered_by,
)
from app.agents.capabilities.sandbox import WORKSPACE_RESOURCE
from app.agents.capabilities.tool_output_limits import (
    DEFAULT_SUMMARY_PROMPT,
    SPILL_LOG_RESOURCE,
    MeteredToolOutputLimits,
    OverflowWriteError,
    ToolOutputLimitsConfig,
    WorkspaceOverflowStore,
    build_limits,
)
from app.agents.capabilities.tool_output_limits._capability import (
    _action,
    _build_store,
    readable_return,
)
from tests.workspaces import document_workspace

pytestmark = pytest.mark.anyio

CAPABILITY_ID = "tool_output_limits"


def _run_context(usage: RunUsage | None = None) -> RunContext[None]:
    return RunContext(deps=None, model=TestModel(), usage=usage or RunUsage())


def _call(tool_call_id: str = "call-1", name: str = "grep") -> ToolCallPart:
    return ToolCallPart(tool_name=name, args={}, tool_call_id=tool_call_id)


def _tool_def(name: str = "grep") -> ToolDefinition:
    return ToolDefinition(name=name)


class _Refusing(WrapperWorkspace):
    """A workspace that refuses every write, standing in for one at its cap."""

    async def write_bytes(self, path: str, data: bytes) -> None:
        raise OSError(28, "the workspace is full")


def _refusing() -> Workspace:
    return _Refusing(document_workspace())


@dataclass
class _Spender(AbstractCapability[Any]):
    """A stand-in reduction that spends what a `summarize` call would spend.

    The real `Summarize` reaches a provider; the thing under test - that whatever
    lands in `ctx.usage` during the hook is booked - is asserted against a
    capability that adds to it directly.
    """

    input_tokens: int = 0
    output_tokens: int = 0

    async def after_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        result: Any,
    ) -> Any:
        ctx.usage.input_tokens += self.input_tokens
        ctx.usage.output_tokens += self.output_tokens
        return result


class TestConfig:
    def test_defaults_spill(self):
        config = ToolOutputLimitsConfig()
        assert (config.action, config.over_tokens) == ("spill", False)
        assert config.summary_prompt == DEFAULT_SUMMARY_PROMPT

    def test_a_summary_prompt_without_the_output_placeholder_is_refused(self):
        with pytest.raises(ValidationError):
            ToolOutputLimitsConfig(summary_prompt="Summarise {tool_name}, please.")

    def test_a_summary_prompt_without_the_tool_name_placeholder_is_kept(self):
        """Only `{output}` is required; the harness passes `tool_name=` regardless."""
        prompt = "Summarise this: {output}"
        assert ToolOutputLimitsConfig(summary_prompt=prompt).summary_prompt == prompt

    def test_a_summary_prompt_with_a_stray_placeholder_is_refused(self):
        """Caught at publish, not mid-run where the harness would raise `KeyError`."""
        with pytest.raises(ValidationError):
            ToolOutputLimitsConfig(summary_prompt="{tool_name} {output} {unexpected}")

    def test_a_valid_custom_prompt_is_kept(self):
        prompt = "Compress {tool_name}: {output}"
        assert ToolOutputLimitsConfig(summary_prompt=prompt).summary_prompt == prompt


class TestActionMapping:
    def test_truncate_maps_to_a_bare_truncation(self):
        action = _action(ToolOutputLimitsConfig(action="truncate", truncation_strategy="tail"))
        assert isinstance(action, Truncate)
        assert action.strategy.value == "tail"

    def test_spill_falls_back_to_truncation(self):
        action = _action(ToolOutputLimitsConfig(action="spill"))
        assert isinstance(action, Spill)
        assert isinstance(action.then, Truncate)

    def test_summarize_falls_back_through_spill_to_truncation(self):
        action = _action(ToolOutputLimitsConfig(action="summarize"))
        assert isinstance(action, Summarize)
        assert isinstance(action.then, Spill)
        assert isinstance(action.then.then, Truncate)


class TestStore:
    async def test_a_spill_reads_back_by_the_handle_it_returned(self):
        store = WorkspaceOverflowStore(document_workspace())
        handle = await store.write("run-1/call-1.0", b"payload\nsecond line")
        assert await store.read(handle) == b"payload\nsecond line"

    async def test_the_handle_is_the_path_the_workspace_resolved(self):
        """What a later read, and the prune at close, have to name exactly."""
        store = WorkspaceOverflowStore(document_workspace())
        assert await store.write("run-1/call-1.0", b"x") == "/tool_output/run-1/call-1.0"

    async def test_a_refused_write_raises_so_spill_can_fall_back(self):
        store = WorkspaceOverflowStore(_refusing())
        with pytest.raises(OverflowWriteError):
            await store.write("run-1/call-1.0", b"too big")

    async def test_an_unknown_handle_raises_rather_than_returning_empty(self):
        """The read-back tool needs a raised error to tell the model the handle is
        unknown, rather than empty bytes."""
        store = WorkspaceOverflowStore(document_workspace())
        with pytest.raises(FileNotFoundError):
            await store.read("tool_output/never-written")

    async def test_a_written_handle_is_recorded_in_the_run_spill_log(self):
        """What lands in the log is the handle as the workspace resolved it, so the
        prune at workspace close deletes the path that actually exists (#803)."""
        log: list[str] = []
        store = WorkspaceOverflowStore(document_workspace(), spill_log=log)
        first = await store.write("run-1/call-1.0", b"payload")
        second = await store.write("run-1/call-2.0", b"payload")
        assert log == [first, second]

    async def test_a_refused_write_records_nothing(self):
        log: list[str] = []
        store = WorkspaceOverflowStore(_refusing(), spill_log=log)
        with pytest.raises(OverflowWriteError):
            await store.write("run-1/call-1.0", b"too big")
        assert log == []


class TestBuildStore:
    async def test_no_workspace_falls_back_to_an_in_memory_one(self):
        store = _build_store(None)
        handle = await store.write("k", b"kept")
        assert await store.read(handle) == b"kept"

    def test_a_workspace_is_used_as_given(self):
        workspace = document_workspace()
        assert _build_store(workspace).workspace is workspace

    def test_the_in_memory_fallback_records_no_handles(self):
        """A document discarded with the run leaves nothing to delete, so tracking
        its spills would offer the prune paths that no longer exist."""
        assert _build_store(None, ["polluted"]).spill_log is None

    def test_a_bound_workspace_records_into_the_run_log(self):
        log: list[str] = []
        assert _build_store(document_workspace(), log).spill_log is log


class TestReduction:
    async def test_a_small_return_passes_through_untouched(self):
        limits = build_limits(
            ToolOutputLimitsConfig(threshold=10_000), workspace=document_workspace()
        )
        out = await limits.after_tool_execute(
            _run_context(), call=_call(), tool_def=_tool_def(), args={}, result="small"
        )
        assert out == "small"

    async def test_a_page_of_forty_thousand_characters_arrives_whole_by_default(self):
        """At the old 10,000 a fetched page arrived as a preview to page through,
        which read as the tool being broken; an ordinary page now passes as it is."""
        limits = build_limits(ToolOutputLimitsConfig(), workspace=document_workspace())
        page = "x" * 40_000
        out = await limits.after_tool_execute(
            _run_context(), call=_call(), tool_def=_tool_def(), args={}, result=page
        )
        assert out == page
        assert ToolOutputLimitsConfig().max_chars == 20_000

    async def test_a_full_fetch_arrives_whole_with_its_url_and_title(self):
        """`web_fetch` returns up to 50,000 characters of content by default, and
        the URL, title and truncation marker come on top of it."""
        limits = build_limits(ToolOutputLimitsConfig(), workspace=document_workspace())
        fetched = {
            "url": "https://example.com/" + "a" * 500,
            "title": "A long page",
            "content": "x" * 50_000 + "\n\n[Content truncated]",
        }
        out = await limits.after_tool_execute(
            _run_context(), call=_call(), tool_def=_tool_def(), args={}, result=fetched
        )
        assert out == fetched

    def test_a_threshold_in_tokens_defaults_to_the_same_size_in_tokens(self):
        config = ToolOutputLimitsConfig(over_tokens=True)
        assert config.threshold == 15_000
        assert config.max_chars == 20_000
        assert ToolOutputLimitsConfig(over_tokens=True, threshold=1_000).max_chars == 4_000

    async def test_a_lowered_threshold_still_shortens_what_crosses_it(self):
        """Truncating at 10,000 with the 20,000 default kept a 15,000-character
        return as it was; left unset, what is kept follows the threshold."""
        config = ToolOutputLimitsConfig(action="truncate", threshold=10_000)
        assert config.max_chars == 10_000
        limits = build_limits(config, workspace=document_workspace())
        out = await limits.after_tool_execute(
            _run_context(), call=_call(), tool_def=_tool_def(), args={}, result="z" * 15_000
        )
        assert len(str(out)) < 15_000

    def test_a_truncation_the_binding_names_is_kept(self):
        config = ToolOutputLimitsConfig(threshold=10_000, max_chars=15_000, over_tokens=True)
        assert (config.threshold, config.max_chars) == (10_000, 15_000)

    async def test_a_spilled_page_pages_by_line_not_as_one_json_line(self):
        """An MCP page arrives as `{"title": ..., "text": "..."}`. Spilled as
        compact JSON it was one line, and every `read_tool_result` answered "1
        matching line, output capped"; its text is now what is paged."""
        limits = build_limits(ToolOutputLimitsConfig(threshold=500), workspace=document_workspace())
        page = {
            "metadata": {"type": "block"},
            "title": "VstormPedia",
            "text": "\n".join(f"line {n}" for n in range(200)),
        }
        out = await limits.after_tool_execute(
            _run_context(), call=_call(), tool_def=_tool_def(), args={}, result=page
        )
        assert isinstance(out, ToolReturn)
        stored = (await limits.store.read(out.metadata["overflow_handle"])).decode()
        lines = stored.splitlines()
        assert lines[:4] == [
            'metadata: {"type":"block"}',
            'title: "VstormPedia"',
            "text:",
            "line 0",
        ]
        assert lines[-1] == "line 199"

    def test_a_return_with_no_text_to_page_is_indented_json(self):
        assert readable_return({"rows": [1, 2], "title": "t"}) == (
            '{\n  "rows": [\n    1,\n    2\n  ],\n  "title": "t"\n}'
        )
        assert readable_return([{"a": 1}]) == '[\n  {\n    "a": 1\n  }\n]'

    async def test_an_oversized_return_is_spilled_and_reads_back_in_full(self):
        limits = build_limits(
            ToolOutputLimitsConfig(action="spill", threshold=500), workspace=document_workspace()
        )
        payload = "x" * 5_000
        out = await limits.after_tool_execute(
            _run_context(), call=_call(), tool_def=_tool_def(), args={}, result=payload
        )
        assert isinstance(out, ToolReturn)
        assert "read_tool_result" in str(out.return_value)
        handle = out.metadata["overflow_handle"]
        assert (await limits.store.read(handle)).decode() == payload

    async def test_a_spill_the_workspace_refuses_degrades_to_truncation(self):
        limits = build_limits(
            ToolOutputLimitsConfig(action="spill", threshold=500, max_chars=200),
            workspace=_refusing(),
        )
        out = await limits.after_tool_execute(
            _run_context(), call=_call(), tool_def=_tool_def(), args={}, result="y" * 5_000
        )
        assert isinstance(out, str)
        assert "truncated" in out


class TestBuildLimits:
    def test_the_configuration_reaches_the_capability(self):
        limits = build_limits(
            ToolOutputLimitsConfig(threshold=42_000, over_tokens=True, strip_ansi=True),
            workspace=document_workspace(),
        )
        assert limits.over_tokens is True
        assert limits.strip_ansi is True
        assert limits.bands[0].over == 42_000


class TestMetering:
    async def test_a_summary_is_booked_against_the_run_that_paid_for_it(self):
        """The harness `Summarize` runs its own agent, which no BudgetGuard wraps."""
        ledger = SpendLedger()
        capability = MeteredToolOutputLimits(
            wrapped=_Spender(input_tokens=1_200, output_tokens=300)
        )

        with metered_by(ledger):
            await capability.after_tool_execute(
                _run_context(), call=_call(), tool_def=_tool_def(), args={}, result="ok"
            )

        assert len(ledger.entries) == 1
        assert (ledger.input_tokens, ledger.output_tokens) == (1_200, 300)

    async def test_a_real_summarize_books_its_model_call(self):
        """The end-to-end path, so the metering does not silently book zero.

        `_Spender` proves the wrapper books whatever lands in `ctx.usage`; this
        proves the harness `Summarize` is what lands it there - it runs its own
        `Agent` with `usage=ctx.usage`, and if that ever stopped, the wrapper would
        see no delta and this test would go red where the mocked one would not.
        """
        ledger = SpendLedger()
        capability = MeteredToolOutputLimits(
            wrapped=build_limits(
                ToolOutputLimitsConfig(action="summarize", threshold=500),
                workspace=document_workspace(),
            )
        )

        with metered_by(ledger):
            await capability.after_tool_execute(
                _run_context(), call=_call(), tool_def=_tool_def(), args={}, result="x" * 5_000
            )

        assert ledger.entries and ledger.input_tokens > 0

    async def test_a_zero_cost_reduction_books_nothing(self):
        """`spill` and `truncate` call no model and must stay free, though wrapped."""
        ledger = SpendLedger()
        capability = MeteredToolOutputLimits(wrapped=_Spender())

        with metered_by(ledger):
            result = await capability.after_tool_execute(
                _run_context(), call=_call(), tool_def=_tool_def(), args={}, result="ok"
            )

        assert ledger.entries == []
        assert result == "ok"

    async def test_at_a_cap_the_reduction_is_skipped_and_the_return_passes_through(self):
        """At a cap a `summarize` band's own request would spend past it, so the
        reduction is skipped and the return is left un-reduced (agenticos#1808)."""
        ledger = SpendLedger()
        capability = MeteredToolOutputLimits(wrapped=_Spender(input_tokens=1_200))
        ctx = _run_context()
        exhausted = BudgetGuard(
            limits=[SpendLimit(scope=BudgetScope.ORGANIZATION, limit_usd=Decimal(0))]
        )

        with metered_by(ledger), guarded_by(exhausted):
            result = await capability.after_tool_execute(
                ctx, call=_call(), tool_def=_tool_def(), args={}, result="x" * 5_000
            )

        assert result == "x" * 5_000
        assert ledger.entries == []
        assert ctx.usage.input_tokens == 0


class TestRegistration:
    def test_an_agent_that_does_not_bind_it_gets_no_read_back_tool(self):
        """The capability contributes nothing when a spec does not enable it."""
        assert build([]) == []

    async def test_binding_it_offers_the_read_back_tool(self):
        built = build([CapabilityBinding(capability_id=CAPABILITY_ID)])
        assert len(built) == 1
        toolset = built[0].get_toolset()
        assert toolset is not None
        assert "read_tool_result" in await toolset.get_tools(_run_context())

    def test_a_bound_workspace_is_used_for_spills(self):
        workspace = document_workspace()
        built = build(
            [CapabilityBinding(capability_id=CAPABILITY_ID)],
            resources={WORKSPACE_RESOURCE: workspace},
        )
        limits = built[0].wrapped
        assert limits.store.workspace is workspace

    async def test_a_spill_is_recorded_in_the_workspace_spill_log(self):
        """The runner's log resource reaches the store, so a spill on a shared
        workspace is deletable at close by the run that wrote it (#803)."""
        log: list[str] = []
        built = build(
            [CapabilityBinding(capability_id=CAPABILITY_ID, config={"threshold": 500})],
            resources={WORKSPACE_RESOURCE: document_workspace(), SPILL_LOG_RESOURCE: log},
        )
        out = await built[0].after_tool_execute(
            _run_context(), call=_call(), tool_def=_tool_def(), args={}, result="x" * 5_000
        )
        assert log == [out.metadata["overflow_handle"]]

    def test_the_builder_defaults_a_missing_config(self):
        """The defensive `isinstance` branch: a builder handed no config still builds."""
        definition = get(CAPABILITY_ID)
        capability = definition.builder(
            CapabilityBuildContext(
                binding=CapabilityBinding(capability_id=CAPABILITY_ID), config=None
            )
        )
        assert isinstance(capability, MeteredToolOutputLimits)
        assert capability.wrapped.bands[0].over == ToolOutputLimitsConfig().threshold
