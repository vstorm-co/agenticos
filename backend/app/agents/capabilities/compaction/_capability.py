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

What *does* cross the boundary is what each replayed answer cost, and it is what
makes any of this fire. The estimator anchors on the most recent response carrying
provider usage - that request's `input_tokens` counted the instructions, every
tool schema and every prior message - and estimates only what came after. Replayed
as bare text there is nothing to anchor on and it counts characters instead: a real
agent here measured 9 tokens where the provider had charged for 3,859, so a
window the gauge showed at 77% sat beside a trigger that had noticed nothing.
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
from pydantic_ai_harness.compaction import (
    DEFAULT_CONTEXT_WINDOW,
    ClearToolResults,
    SlidingWindowCompaction,
    SummarizingCompaction,
    TieredCompaction,
    estimate_token_count,
)

from app.agents.capabilities.budget import record_ambient_usage, usage_counts, usage_delta
from app.agents.compaction_events import CompactionEvent

logger = logging.getLogger(__name__)

CONTEXT_GAUGE_RESOURCE = "context_gauge"
"""Where the factory puts the run's own gauge, for the strip and the guard to read.

A resource rather than a config field, for the reason the window is one: it is
not a decision an author makes. The gauge measures what every request actually
carried, which is what the chat reports - and what it carried *before a single
message*, which is what says whether a window has room for a summary at all; see
:func:`MeteredCompaction._has_no_room`.
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
            "gauge divides by, so the two describe one ceiling. Set it when the "
            "resolved number is wrong for your deployment - a beta or a tier can be "
            "given less than the provider publishes - or to make an agent compact "
            "earlier than its model would require"
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

    gauge: ContextGauge | None = None
    """The run's reading, so a summary that ran can be *kept*.

    A dataclass field rather than a constructor argument to `compact`, because
    the surface needs the answer after the run has finished and nothing else
    carries it that far. `None` in a test that builds a strategy on its own."""

    async def compact(
        self, messages: list[ModelMessage], ctx: RunContext[AgentDepsT]
    ) -> list[ModelMessage]:
        before = len(messages)
        sink = getattr(ctx.deps, "on_compaction", None)
        compacted: list[ModelMessage] | None = None
        if sink is not None:
            await sink(CompactionEvent(kind="compaction_started", messages_before=before))
        try:
            compacted = await super().compact(messages, ctx)
            return compacted
        finally:
            if compacted is not None and self.gauge is not None:
                self.gauge.summarized = True
            if sink is not None:
                await sink(
                    CompactionEvent(
                        kind="compaction_finished",
                        messages_before=before,
                        # `None` where the summary raised: the history is whatever
                        # it was, and a number here would report a compaction that
                        # did not happen.
                        messages_after=None if compacted is None else len(compacted),
                    )
                )


def build_strategy(
    config: CompactionConfig,
    *,
    recorded_window: int | None = None,
    gauge: ContextGauge | None = None,
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

    **What the trigger measures is the provider's own number, where a history
    carries one.** The estimator anchors on the most recent response with usage on
    it - that request's `input_tokens` counted the instructions, every tool schema
    and every prior message - and estimates only what came after. So the overhead
    is inside the count rather than outside it, and no lever is needed to allow for
    it. What makes that true here is `app.services.agent.build_message_history`
    replaying each answer with what it cost; replayed as bare text there is nothing
    to anchor on, and a real agent here measured 9 tokens where the provider had
    charged for 3,859.

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
            gauge=gauge,
            max_fraction=config.max_fraction,
            keep_messages=config.keep_messages,
            summary_prompt=config.summary_prompt,
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

    summarized: bool = False
    """Whether a summary replaced part of this run's history.

    Read after the run, by the surface that persists the conversation: a summary
    is a model request paid for over a history that is by definition long, and
    rebuilding the thread from the transcript next turn throws it away and buys
    it again on a history one turn longer. Two consecutive turns of a real
    conversation here each bought one (#49).

    Only a *summary* sets it. Dropping the oldest messages and clearing tool
    results cost nothing to redo, and persisting them would make a loss permanent
    that is currently reconsidered against the window on every turn.
    """

    overhead: int | None = None
    """What every request carries before a single message: instructions and tool
    schemas.

    The difference between what the provider charged for a request and what the
    character heuristic counts in the same messages - a real agent here: 3,865
    against 60. It is fixed for the run, it is billed every time, and no strategy
    can compact it away, which is what makes it the one number that says whether a
    window has room for a summary at all.

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
        if await self._has_no_room(ctx):
            return request_context
        before = usage_counts(ctx.usage)
        try:
            return await self.wrapped.before_model_request(ctx, request_context)
        finally:
            spent = usage_delta(before, ctx.usage)
            if spent is not None:
                record_ambient_usage(_model_name(request_context), spent)

    async def _has_no_room(self, ctx: RunContext[AgentDepsT]) -> bool:
        """Whether this window is too small for a summary to ever get under it.

        The overhead - instructions and tool schemas - is billed on every request
        and is not in the history, so no strategy can compact it away. Once it is
        past the trigger on its own, every request is over the line, every request
        buys a summary, and not one of them can bring the next below it. That is an
        unbounded paid loop, so compaction is skipped outright.

        **Only where a summary is bought.** Dropping messages and clearing tool
        results call no model, so running them on a window they can never get under
        costs nothing and still keeps the request smaller than not running them -
        skipping those would trade a warning for an unbounded history.

        Said once per run, on the channel the summary already narrates itself on,
        because it describes a configuration rather than an event - and because
        silence here is indistinguishable from a setting that works, which is what
        it looked like for two rounds of testing.
        """
        if not isinstance(self.wrapped, SummarizingCompaction | TieredCompaction):
            return False
        thresholds = _trigger_tokens(self.wrapped)
        overhead = None if self.gauge is None else self.gauge.overhead
        if thresholds is None or not overhead:
            return False
        trigger, window = thresholds
        if overhead < trigger:
            return False
        if self._said_it_cannot:
            return True
        self._said_it_cannot = True
        logger.warning(
            "Compaction cannot help: %s tokens of instructions and tool schemas "
            "against a %s-token trigger in a %s-token window",
            overhead,
            trigger,
            window,
        )
        sink = getattr(ctx.deps, "on_compaction", None)
        if sink is not None:
            await sink(
                CompactionEvent(
                    kind="compaction_impossible",
                    overhead_tokens=overhead,
                    window_tokens=window,
                )
            )
        return True


def _trigger_tokens(strategy: AbstractCapability[Any]) -> tuple[int, int] | None:
    """The token count above which this strategy compacts, and the window it is of.

    Both, because the caller reports one and decides on the other: the window is
    what an author set and can raise, the trigger is the line their overhead is
    past.

    `max_fraction` on a strategy, `target_fraction` on the orchestrator -
    `build_strategy` sets one or the other on everything it returns, so an object
    here with neither is one nothing built and is worth the `AttributeError`
    rather than a silent no-op. The orchestrator's own target is what decides when
    its tiers stop escalating, so reading the top level answers for all of them.

    `None` when no window could be resolved at all, and there is then no line to be
    past.
    """
    window: int | None = getattr(strategy, "context_window", None)
    if not window:
        return None
    # One-argument `getattr` on purpose: a strategy with neither fraction is one
    # nothing here built, and the `AttributeError` says so rather than answering
    # that it never triggers.
    fraction: float = getattr(strategy, "max_fraction", None) or getattr(  # noqa: B009
        strategy, "target_fraction"
    )
    return int(window * fraction), window


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
