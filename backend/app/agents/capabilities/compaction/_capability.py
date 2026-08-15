"""Keeping a run's history inside the model's context window.

The strategies themselves come from `pydantic-ai-harness`; what this module adds
is the two things a platform has to add to them.

**A budget that can see the summary.** `SummarizingCompaction` writes its summary
through an `Agent` it constructs itself, so that request never passes
`BudgetGuard.wrap_model_request` - the guard is a capability on *our* agent, not
on the one the strategy builds. The tokens land in `ctx.usage` and would land
nowhere else, which is #16 wearing a different hat: a run under-reports its cost
and no cap can stop a compaction loop. :class:`MeteredCompaction` books the
difference against the run's ledger.

**A scope somebody can reason about.** This reaches the messages of *one run*.
Between turns the history is rebuilt from the transcript by
`app.services.agent.build_message_history`, which reconstructs a conversation as
text and drops tool calls, tool returns and thinking - so no edit made here
survives a turn boundary. That is not a defect in the capability: the history
worth compacting is the hundred-step tool loop `DEFAULT_MAX_STEPS` allows, where
one sandbox listing or one knowledge search can be tens of thousands of tokens.
It does mean a summarizing pass is paid for once per run rather than amortised
across a conversation, which is why the cheap tiers come first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import AbstractCapability, WrapperCapability
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import AgentDepsT, RunContext
from pydantic_ai.usage import RequestUsage, RunUsage
from pydantic_ai_harness.compaction import (
    DEFAULT_CONTEXT_WINDOW,
    ClearToolResults,
    SlidingWindowCompaction,
    SummarizingCompaction,
    TieredCompaction,
)

from app.agents.capabilities.budget import record_ambient_usage

logger = logging.getLogger(__name__)

MODEL_CONTEXT_WINDOW_RESOURCE = "model_context_window"
"""Where the factory puts the window the run's model profile recorded.

A resource rather than a config field, because it is not a decision an author
makes - it is what the provider's own listing said when somebody added the
model. `CompactionConfig.context_window` still beats it, for the deployment that
knows better than both the provider and us.
"""

StrategyName = Literal["summarize", "tiered", "clear_tool_results", "sliding_window"]
"""Which strategy a binding picked.

Stored in published specs and exported into a client's git repository, so these
four strings are as permanent as the capability id. A strategy that stops making
sense is deprecated in the documentation; the value keeps resolving.
"""


class CompactionConfig(BaseModel):
    """How an agent should keep its history inside the window.

    Flat scalars and one enum, deliberately. The Builder generates this form from
    `config_json_schema` and renders string, number, boolean and enum fields - a
    nested list of tiers would arrive as a text box, so the tiers are chosen by
    `strategy` rather than composed by the author.

    There is no field naming a cheaper model to summarise with. The summary
    inherits the run's model because that is the one whose credential was
    resolved from the vault; a model named here as a string would be looked up
    against process environment variables, which on this platform is either
    nothing or somebody else's key.
    """

    strategy: StrategyName = Field(
        default="summarize",
        description="Which strategy to apply when the history approaches the window",
        # What the Builder puts in the picker. The values are spec format and
        # cannot say what they do; `clear_tool_results` in a dropdown is a
        # choice somebody makes by guessing, and the guess that costs money is
        # the one that picks `summarize`. See `x-enum-labels` in `schema-form`.
        json_schema_extra={
            "x-enum-labels": {
                "summarize": "Summarise older messages, keeping what they said",
                "tiered": "Clear old tool results first, summarise only if that was not enough",
                "clear_tool_results": "Clear old tool results - no model call",
                "sliding_window": "Drop the oldest messages - no model call",
            }
        },
    )
    max_fraction: float = Field(
        default=0.9,
        ge=0.05,
        le=0.95,
        description="Fraction of the model's context window at which compaction starts",
    )
    keep_messages: int = Field(
        default=20,
        ge=1,
        le=500,
        description="How many recent messages survive a summary or a sliding window",
    )
    keep_tool_pairs: int = Field(
        default=3,
        ge=0,
        le=50,
        description="How many recent tool calls keep their results when results are cleared",
    )
    context_window: int | None = Field(
        default=None,
        ge=1_000,
        description="Override the model's context window in tokens, when the registry is wrong",
    )
    fallback_context_window: int = Field(
        default=DEFAULT_CONTEXT_WINDOW,
        ge=1_000,
        description="Window to assume when the model's own cannot be resolved",
    )


def build_strategy(
    config: CompactionConfig, *, recorded_window: int | None = None
) -> AbstractCapability[Any]:
    """The harness strategy this configuration asks for.

    `summarize` is the default because it is the only one that keeps what the
    older turns *said*. The zero-LLM strategies are cheaper because they throw
    information away - a sliding window drops the oldest messages outright, and
    clearing a tool result blanks an answer the agent may still need - and an
    agent that silently forgets what it was told mid-run is a worse failure than
    a summary nobody asked for. `tiered` is the frugal choice, and one binding
    away.

    At 0.9 of the window rather than lower, for the same reason: compaction is
    the point at which a run starts losing detail, so it is worth deferring
    until the window is nearly full.

    Every strategy is handed `max_fraction` rather than an absolute token count,
    including the tiers inside `tiered` whose own triggers the orchestrator
    bypasses. An absolute number is correct only for the model it was measured
    against, and the same agent here runs on whatever profile its spec points at.

    `recorded_window` is what the model profile stored from its provider's own
    listing. It beats resolving the window from the pricing snapshot, which is
    wrong for Sonnet-class Anthropic models and answers nothing at all for a
    profile with fallbacks (#773). The author's own `context_window` beats both:
    the provider publishes the maximum a model *can* be made to accept, and a
    beta- or tier-gated deployment gets less.
    """
    # Spelt out at every call rather than splatted from a dict of the two: a
    # `**kwargs` splat is opaque to the type checker, and these constructors take
    # a `tokenizer` and a `receipts` flag that a mistyped key would land on.
    window = config.context_window or recorded_window
    fallback = config.fallback_context_window

    def clearing() -> ClearToolResults[Any]:
        return ClearToolResults(
            max_fraction=config.max_fraction,
            keep_pairs=config.keep_tool_pairs,
            context_window=window,
            fallback_context_window=fallback,
        )

    def summarizing() -> SummarizingCompaction[Any]:
        return SummarizingCompaction(
            max_fraction=config.max_fraction,
            keep_messages=config.keep_messages,
            context_window=window,
            fallback_context_window=fallback,
        )

    if config.strategy == "clear_tool_results":
        return clearing()
    if config.strategy == "sliding_window":
        return SlidingWindowCompaction(
            max_fraction=config.max_fraction,
            keep_messages=config.keep_messages,
            context_window=window,
            fallback_context_window=fallback,
        )
    if config.strategy == "summarize":
        return summarizing()
    return TieredCompaction(
        tiers=[clearing(), summarizing()],
        target_fraction=config.max_fraction,
        context_window=window,
        fallback_context_window=fallback,
    )


@dataclass
class ContextGauge:
    """How many tokens the last request of a run actually carried.

    **Measured, not estimated.** The obvious way to answer this is to count the
    message parts about to be sent, and the harness ships a capability that does
    - but a character heuristic cannot see the tool definitions, and those are
    billed on every request. On an agent with knowledge, a sandbox and delegation
    that is thousands of tokens of schema: a real conversation here measured
    1,688 by the estimate against 5,007 the provider charged for, on every turn.
    Three times short is not a rounding error at 90% of a window.

    So the number comes off the response. `RequestUsage.input_tokens` is exactly
    what the request occupied - instructions, tool schemas, every prior message,
    cached or not - as the provider counted it, and it costs nothing to read.

    The newest reading wins, which for a run is the last request it made: a tool
    loop grows the context with every step, so the last one is the peak and the
    one worth reporting. A `None` means the run reached no model at all.
    """

    latest: int | None = None


@dataclass
class ReportContextSize(AbstractCapability[AgentDepsT]):
    """Fills a :class:`ContextGauge` from what each response says it was sent.

    Attached to every agent, not only to one that compacts: the warning matters
    most to the agent that will *not*, because that is the one that reaches the
    ceiling and is refused by the provider mid-answer.

    It only observes. Nothing here edits history, and a response with no usage on
    it - a provider that reported none - leaves the previous reading standing
    rather than blanking it.
    """

    gauge: ContextGauge

    async def after_model_request(
        self,
        ctx: RunContext[AgentDepsT],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        if response.usage.input_tokens:
            self.gauge.latest = response.usage.input_tokens
        return response


def build_gauge(gauge: ContextGauge) -> ReportContextSize[Any]:
    """The capability that fills `gauge`, for the factory to attach."""
    return ReportContextSize(gauge=gauge)


@dataclass
class MeteredCompaction(WrapperCapability[AgentDepsT]):
    """Books what a compaction spent against the run that spent it.

    Wrapped around every strategy, including the two that provably never call a
    model. An allowlist of "these can spend" is a list somebody has to remember
    to add to, and the entry they forget is a model call nobody is billed for -
    the same shape of omission the wrapper exists to close. The cost of being
    uniform is reading four integers per request.

    The delta is measured on `ctx.usage`, which is what the strategy's own agent
    was handed and therefore the only place its tokens appear. It is booked
    through :func:`record_ambient_usage` rather than onto a ledger held here,
    because the runner opens `metered_by(built.ledger)` around the whole run and
    a delegation running inside that block must bill to its own row rather than
    to whichever ledger was captured when the agent was assembled.

    Booked in a `finally`: a strategy that raised after its summary call still
    spent the tokens, and a run that failed is exactly the run whose cost is
    argued about later.

    What this cannot do is *stop* the spend. `BudgetGuard` refuses in
    `wrap_model_request`, which runs after this hook, so a compaction that
    crosses a cap is recorded here and refused on the request after it.
    """

    async def before_model_request(
        self,
        ctx: RunContext[AgentDepsT],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        before = _counts(ctx.usage)
        try:
            return await self.wrapped.before_model_request(ctx, request_context)
        finally:
            spent = _spent(before, ctx.usage)
            if spent is not None:
                record_ambient_usage(_model_name(request_context), spent)


def _counts(usage: RunUsage) -> tuple[int, int, int, int]:
    """The four counters a price is computed from, read off the run's usage.

    A tuple rather than the object: `RunUsage` is accumulated in place, so
    keeping a reference to it and comparing later compares it with itself.
    """
    return (
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_tokens,
        usage.cache_write_tokens,
    )


def _spent(before: tuple[int, int, int, int], usage: RunUsage) -> RequestUsage | None:
    """What the strategy added, or `None` when it called no model.

    Cached tokens are carried as well as the plain ones because they are priced
    differently and `input_tokens` already includes them - dropping them here
    would bill a cache read at the full input rate, which is the defect
    `price_request` exists to avoid.
    """
    after = _counts(usage)
    if after == before:
        return None
    return RequestUsage(
        input_tokens=after[0] - before[0],
        output_tokens=after[1] - before[1],
        cache_read_tokens=after[2] - before[2],
        cache_write_tokens=after[3] - before[3],
    )


def _model_name(request_context: ModelRequestContext) -> str:
    """What to price the summary against.

    The model this request is going to, which is the one the strategy inherits
    when nothing named another. A `FallbackModel` answers with its composite
    `fallback:...` id, which `genai-prices` cannot resolve - so the entry is
    booked unpriced and the run is marked `cost_is_partial`, which is the honest
    outcome rather than a number attributed to whichever entry happened to be
    first.

    `model_name` is abstract on `AbstractModel`, so it is always there - but at
    least one implementation answers `''` for a response that never carried one,
    and an empty string prices against nothing while reading in a log as though
    the field were missing rather than blank.
    """
    return request_context.model.model_name or "unknown"
