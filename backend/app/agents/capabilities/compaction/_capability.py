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

from pydantic import BaseModel, Field, field_validator
from pydantic_ai.capabilities import AbstractCapability, WrapperCapability
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import AgentDepsT, RunContext
from pydantic_ai.usage import RequestUsage, RunUsage
from pydantic_ai_harness.compaction import (
    DEFAULT_CONTEXT_WINDOW,
    ClearToolResults,
    SlidingWindowCompaction,
    SummarizingCompaction,
    TieredCompaction,
    estimate_token_count,
)

from app.agents.capabilities.budget import record_ambient_usage
from app.agents.compaction_events import CompactionEvent

logger = logging.getLogger(__name__)

CONTEXT_GAUGE_RESOURCE = "context_gauge"
"""Where the factory puts the run's own gauge, for the trigger to read.

A resource rather than a config field, for the reason the window is one: it is
not a decision an author makes. The gauge measures what every request carries
before a single message, and the trigger has to allow for it - see
:func:`_allow_for_overhead`.
"""

MODEL_CONTEXT_WINDOW_RESOURCE = "model_context_window"
"""Where the factory puts the window the run's model profile recorded.

A resource rather than a config field, because it is not a decision an author
makes - it is what the provider's own listing said when somebody added the
model. `CompactionConfig.context_window` still beats it, for the deployment that
knows better than both the provider and us.
"""

DEFAULT_SUMMARY_PROMPT: str = SummarizingCompaction(max_messages=1).summary_prompt
"""The prompt the summary is written with, unless a binding replaces it.

Read off an instance rather than out of the dataclass's field metadata, which
answers `Any | _MISSING_TYPE` and would need a cast to become a string again. The
throwaway `max_messages=1` is only there because the class refuses to exist
without a trigger; nothing runs it.

Read off the library rather than copied, so the two cannot drift: a copy here
would go on being offered to authors long after the upstream one had changed, and
the difference between the prompt they edit and the prompt that runs is invisible.

It is a *default* rather than a stored value, so a spec that never touched it
keeps tracking the library and only an edit freezes anything.
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
    summary_prompt: str = Field(
        default=DEFAULT_SUMMARY_PROMPT,
        min_length=1,
        max_length=8_000,
        description=(
            "What the summarising model is told. `{messages}` is where the conversation "
            "being replaced is inserted, and it is required - a prompt without it "
            "summarises nothing. Edit it to keep what your agent's work depends on: the "
            "default keeps intent, decisions and open threads, which is not the same as "
            "what a support transcript or a code review needs"
        ),
        # Rendered as the Markdown editor the agent's own instructions get, not
        # as a one-line box: this is paragraphs, and it is read as much as it is
        # written.
        json_schema_extra={"x-multiline": True},
    )
    context_window: int | None = Field(
        default=None,
        ge=1_000,
        description=(
            "Override the window this triggers against. Also what the chat's context "
            "gauge divides by, so the two describe one ceiling. Two reasons to set it: "
            "the resolved number is wrong, or you are allowing for the instructions and "
            "tool schemas the trigger does not count - subtract what the gauge reads on "
            "the first turn of an empty conversation"
        ),
    )
    fallback_context_window: int = Field(
        default=DEFAULT_CONTEXT_WINDOW,
        ge=1_000,
        description="Window to assume when the model's own cannot be resolved",
    )

    @field_validator("summary_prompt")
    @classmethod
    def _must_place_the_conversation(cls, prompt: str) -> str:
        """A prompt with no `{messages}` summarises nothing.

        Refused here rather than at run time, which is where it would otherwise
        surface: the strategy formats this string mid-turn, so the mistake would
        be a turn that quietly summarised an empty conversation and threw the real
        one away - and it would be the *long* turns, on the agents that compact.
        """
        if "{messages}" not in prompt:
            raise ValueError(
                "The summary prompt must contain {messages}, which is where the "
                "conversation being summarised is inserted"
            )
        return prompt


@dataclass
class NotifyingSummarizingCompaction(SummarizingCompaction[AgentDepsT]):
    """`SummarizingCompaction` that says it is working, because it takes a while.

    The one strategy worth narrating. The zero-LLM ones edit a list and return, so
    a frame for them would be a spinner that appears and vanishes within a frame;
    this makes a whole model request over a history that is by definition long,
    between two of the turn's own requests, where nothing else streams. The chat
    stopped dead for the length of it with nothing said.

    Hooked on `compact` rather than on `before_model_request`, which is the
    difference between "it is happening" and "it happened": the base class calls
    `compact` only once its trigger has fired, so a frame from here is never a
    false alarm on a request that compacted nothing. It also covers the
    summarising *tier* of `tiered` for free, because `TieredCompaction` drives its
    tiers through the same method.

    The finish frame is sent in a `finally`. A summary that raised would otherwise
    leave a surface spinning for ever, and the run carries on either way.
    """

    async def compact(
        self, messages: list[ModelMessage], ctx: RunContext[AgentDepsT]
    ) -> list[ModelMessage]:
        sink = getattr(ctx.deps, "on_compaction", None)
        if sink is None:
            return await super().compact(messages, ctx)

        before = len(messages)
        compacted: list[ModelMessage] | None = None
        await sink(CompactionEvent(kind="compaction_started", messages_before=before))
        try:
            compacted = await super().compact(messages, ctx)
            return compacted
        finally:
            await sink(
                CompactionEvent(
                    kind="compaction_finished",
                    messages_before=before,
                    # `None` where the summary raised: the history is whatever it
                    # was, and a number here would report a compaction that did
                    # not happen.
                    messages_after=None if compacted is None else len(compacted),
                )
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

    **The trigger does not count everything the provider bills.** It measures the
    message parts, and a request also carries the instructions and every tool
    schema - which on a real agent here was 3,882 tokens against 16 the estimator
    saw. So it fires late by the size of that overhead, which on a large MCP
    surface is tens of thousands of tokens and is late in the direction that
    reaches the ceiling. The harness documents the gap ("tool schemas are outside
    that count") and `context_window` is the lever: set it to the real window
    minus what the gauge reads on the first turn of an empty conversation.

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

    def summarizing() -> NotifyingSummarizingCompaction[Any]:
        return NotifyingSummarizingCompaction(
            max_fraction=config.max_fraction,
            keep_messages=config.keep_messages,
            summary_prompt=config.summary_prompt,
            context_window=window,
            fallback_context_window=fallback,
        )

    if config.strategy == "clear_tool_results":
        return _remembering(clearing())
    if config.strategy == "sliding_window":
        return _remembering(
            SlidingWindowCompaction(
                max_fraction=config.max_fraction,
                keep_messages=config.keep_messages,
                context_window=window,
                fallback_context_window=fallback,
            )
        )
    if config.strategy == "summarize":
        return _remembering(summarizing())
    return _remembering(
        TieredCompaction(
            tiers=[clearing(), summarizing()],
            target_fraction=config.max_fraction,
            context_window=window,
            fallback_context_window=fallback,
        )
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

    overhead: int | None = None
    """What every request carries before a single message: instructions and tool
    schemas.

    The difference between what the provider charged for a request and what the
    compaction estimator counts in the same messages - a real agent here: 3,865
    against 60. It is fixed for the run, it is billed every time, and no strategy
    can compact it away, which is exactly why the trigger has to allow for it
    rather than pretend the messages are the whole request.

    `None` until a response has been seen, because it cannot be measured before
    one."""


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
            # And what of it was there before any message: the same request, as
            # the compaction estimator counts it, subtracted from what the
            # provider charged. Instructions and tool schemas, which no strategy
            # can compact and which the trigger must therefore allow for.
            self.gauge.overhead = max(
                0, response.usage.input_tokens - estimate_token_count(request_context.messages)
            )
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

    gauge: ContextGauge | None = None
    """The run's reading, for the trigger correction below. `None` in a test that
    only cares about the metering, and the correction is then not applied."""

    _said_it_cannot: bool = False
    """Whether this run has already reported that its window has no room.

    A configuration, not an event: repeating it on every request of a hundred-step
    loop would bury the turn's own steps under the same sentence."""

    async def before_model_request(
        self,
        ctx: RunContext[AgentDepsT],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        await self._correct_the_trigger(ctx)
        before = _counts(ctx.usage)
        try:
            return await self.wrapped.before_model_request(ctx, request_context)
        finally:
            spent = _spent(before, ctx.usage)
            if spent is not None:
                record_ambient_usage(_model_name(request_context), spent)

    async def _correct_the_trigger(self, ctx: RunContext[AgentDepsT]) -> None:
        """Move the trigger for the overhead, or say why it cannot be moved.

        The refusal is the part worth having. A window whose fixed overhead
        already exceeds the trigger cannot be compacted under it, so the platform
        does nothing - and doing nothing looks exactly like a setting that is
        working. Said once per run, because it describes a configuration rather
        than an event, and on the channel the summary already narrates itself on.
        """
        window = _allow_for_overhead(self.wrapped, self.gauge)
        if window is None or self._said_it_cannot:
            return
        self._said_it_cannot = True
        sink = getattr(ctx.deps, "on_compaction", None)
        overhead = None if self.gauge is None else self.gauge.overhead
        logger.warning(
            "Compaction cannot help: %s tokens of instructions and tool schemas "
            "against a %s-token window",
            overhead,
            window,
        )
        if sink is not None:
            await sink(
                CompactionEvent(
                    kind="compaction_impossible",
                    overhead_tokens=overhead,
                    window_tokens=window,
                )
            )


def _allow_for_overhead(
    strategy: AbstractCapability[Any], gauge: ContextGauge | None
) -> int | None:
    """Move the trigger down by what the request carries before any message.

    The trigger measures the message parts; a request also carries the
    instructions and every tool schema, which the provider bills and no strategy
    can compact. On a real agent here that was 3,865 tokens against the 60 the
    estimator saw - so a gauge reading 77% of a window sat beside a trigger that
    had not noticed anything, which is the same ceiling described two ways.

    The correction is exact rather than approximate. The trigger fires on
    `estimate > f x W'`; what is wanted is `estimate + overhead > f x W`, and
    `W' = W - overhead / f` is the substitution that makes those the same
    statement.

    **Applied only while there is room left.** When the overhead alone exceeds the
    trigger, no summary can get under it - the schemas are not in the history -
    and a corrected window would ask for one on every request, for ever, paying
    each time. The window is then left as configured, which under-fires the way it
    did before, because under-firing is recoverable and an unbounded paid loop is
    not.

    Written onto the strategy rather than passed, because `context_window` is a
    field decided at construction and the overhead cannot be measured until a
    response exists. Each run builds its own strategy, so nothing is shared.

    Returns:
        The configured window, when there was no room in it and nothing was
        corrected - the caller says so, because silence here is a setting that
        looks like it is working. `None` when the correction applied, or when
        there is no reading to correct from yet.
    """
    overhead = None if gauge is None else gauge.overhead
    if not overhead:
        return None
    impossible: int | None = None
    for target in _corrigible(strategy):
        # `max_fraction` on a strategy, `target_fraction` on the orchestrator -
        # `build_strategy` sets one or the other on everything it returns, so an
        # object here without either is one nothing built and is worth the
        # `AttributeError` rather than a silent no-op.
        fraction = getattr(target, "max_fraction", None) or target.target_fraction
        configured = getattr(target, _CONFIGURED_WINDOW)
        corrected = configured - overhead / fraction
        if corrected > 0:
            target.context_window = int(corrected)
        else:
            impossible = configured
    return impossible


_CONFIGURED_WINDOW = "_agenticos_configured_window"
"""Where the author's own `context_window` is kept, so the correction is applied to
it rather than to its own previous answer.

Reading `context_window` back each request would subtract the overhead again from
an already-corrected number, walking the trigger down to nothing over a long tool
loop."""


def _corrigible(strategy: AbstractCapability[Any]) -> tuple[Any, ...]:
    """The strategy, and each tier when it escalates through others.

    A tier left on the uncorrected window measures a different ceiling than the
    orchestrator driving it, and the orchestrator's own target is what decides
    when to stop escalating - so both are moved or neither is.
    """
    return (*getattr(strategy, "tiers", ()), strategy)


def _remembering[S: AbstractCapability[Any]](strategy: S) -> S:
    """Stash the window the author configured, before anything corrects it."""
    for target in _corrigible(strategy):
        setattr(target, _CONFIGURED_WINDOW, target.context_window)
    return strategy


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
