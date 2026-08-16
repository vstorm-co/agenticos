"""Tests for the tool-output-limits capability.

What is guarded: an oversized return is reduced once at production time and not
re-sent in full; a spill goes to the run's own backend and reads back by handle;
a spill the backend refuses degrades to a visible truncation rather than a silent
drop; a `summarize` call is booked against the run that paid for it; and an agent
that does not bind the capability gets nothing - no read-back tool, no reduction.
"""

from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_ai._run_context import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ToolCallPart, ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import AsyncBackendAdapter, StateBackend, WriteResult
from pydantic_ai_harness.tool_output_limits import Spill, Summarize, Truncate

from app.agents.capabilities import CapabilityBinding, build, get
from app.agents.capabilities._registry import CapabilityBuildContext
from app.agents.capabilities.budget import SpendLedger, metered_by
from app.agents.capabilities.sandbox import WORKSPACE_BACKEND_RESOURCE
from app.agents.capabilities.tool_output_limits import (
    DEFAULT_SUMMARY_PROMPT,
    BackendOverflowStore,
    MeteredToolOutputLimits,
    OverflowWriteError,
    ToolOutputLimitsConfig,
    build_limits,
)
from app.agents.capabilities.tool_output_limits._capability import _action, _build_store

pytestmark = pytest.mark.anyio

CAPABILITY_ID = "tool_output_limits"


def _run_context(usage: RunUsage | None = None) -> RunContext[None]:
    return RunContext(deps=None, model=TestModel(), usage=usage or RunUsage())


def _call(tool_call_id: str = "call-1", name: str = "grep") -> ToolCallPart:
    return ToolCallPart(tool_name=name, args={}, tool_call_id=tool_call_id)


def _tool_def(name: str = "grep") -> ToolDefinition:
    return ToolDefinition(name=name)


@dataclass
class _RefusingBackend:
    """A backend that refuses every write, standing in for a workspace at its cap."""

    async def write(self, path: str, content: str | bytes) -> WriteResult:
        return WriteResult(error="the workspace is full")

    async def exists(self, path: str) -> bool:  # pragma: no cover - never read from
        return False

    async def read_bytes(self, path: str) -> bytes:  # pragma: no cover - never read from
        return b""


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

    def test_a_summary_prompt_without_the_tool_name_placeholder_is_refused(self):
        with pytest.raises(ValidationError):
            ToolOutputLimitsConfig(summary_prompt="Summarise this: {output}")

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
        store = BackendOverflowStore(StateBackend())
        handle = await store.write("run-1/call-1.0", b"payload\nsecond line")
        assert await store.read(handle) == b"payload\nsecond line"

    async def test_an_async_backend_is_awaited(self):
        """`state` is synchronous; a container backend is not. One adapter, both."""
        store = BackendOverflowStore(AsyncBackendAdapter(StateBackend()))
        handle = await store.write("run-1/call-1.0", b"async payload")
        assert await store.read(handle) == b"async payload"

    async def test_a_refused_write_raises_so_spill_can_fall_back(self):
        store = BackendOverflowStore(_RefusingBackend())
        with pytest.raises(OverflowWriteError):
            await store.write("run-1/call-1.0", b"too big")

    async def test_an_unknown_handle_raises_rather_than_returning_empty(self):
        """The backend answers a missing path with empty bytes; the read-back tool
        needs a raised error to tell the model the handle is unknown."""
        store = BackendOverflowStore(StateBackend())
        with pytest.raises(FileNotFoundError):
            await store.read("tool_output/never-written")


class TestBuildStore:
    def test_no_backend_falls_back_to_an_in_memory_one(self):
        store = _build_store(None)
        assert isinstance(store.backend, StateBackend)

    def test_a_backend_is_used_as_given(self):
        backend = StateBackend()
        assert _build_store(backend).backend is backend


class TestReduction:
    async def test_a_small_return_passes_through_untouched(self):
        limits = build_limits(ToolOutputLimitsConfig(threshold=10_000), backend=StateBackend())
        out = await limits.after_tool_execute(
            _run_context(), call=_call(), tool_def=_tool_def(), args={}, result="small"
        )
        assert out == "small"

    async def test_an_oversized_return_is_spilled_and_reads_back_in_full(self):
        limits = build_limits(
            ToolOutputLimitsConfig(action="spill", threshold=500), backend=StateBackend()
        )
        payload = "x" * 5_000
        out = await limits.after_tool_execute(
            _run_context(), call=_call(), tool_def=_tool_def(), args={}, result=payload
        )
        assert isinstance(out, ToolReturn)
        assert "read_tool_result" in str(out.return_value)
        handle = out.metadata["overflow_handle"]
        assert (await limits.store.read(handle)).decode() == payload

    async def test_a_spill_the_backend_refuses_degrades_to_truncation(self):
        limits = build_limits(
            ToolOutputLimitsConfig(action="spill", threshold=500, max_chars=200),
            backend=_RefusingBackend(),
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
            backend=StateBackend(),
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

    def test_a_bound_backend_is_used_for_spills(self):
        backend = StateBackend()
        built = build(
            [CapabilityBinding(capability_id=CAPABILITY_ID)],
            resources={WORKSPACE_BACKEND_RESOURCE: backend},
        )
        limits = built[0].wrapped
        assert limits.store.backend is backend

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
