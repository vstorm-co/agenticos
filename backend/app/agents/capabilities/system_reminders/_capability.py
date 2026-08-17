"""Re-injecting steering guidance mid-run, without busting the cache.

The strategy comes from `pydantic-ai-harness`; what this module adds is the two
things a platform has to add to it.

**A cadence that outlives a run.** The harness keeps its request counter and
fire counts in memory and resets them for each run, keyed by `id(reminder)` -
neither of which survives a process or a database. On this platform a run is one
turn, and a conversation is rebuilt from the transcript each turn, so an
in-memory counter would reset to zero every turn and a reminder set to fire
"every ten requests" would never fire in a chat of ten one-request turns. So the
counter and the per-reminder fire counts live in a :class:`ReminderState` seeded
from the conversation and written back after the turn, keyed by a stable string
rather than an object id.

**A budget that can see an LLM reminder.** :class:`_LlmReminder` writes its text
through an `Agent` it constructs itself, so that request never passes
`BudgetGuard.wrap_model_request` - the guard is a capability on *our* agent, not
on the one the reminder builds. The tokens land in `ctx.usage` and would land
nowhere else, which is #16 in a different hat. It books the difference against the
run's ledger through :func:`record_ambient_usage`, and it inherits the run's own
model rather than a name from config: the run's model is the one whose credential
was resolved from the vault, and a model named as a string would be looked up
against process environment variables, which on this platform is either nothing or
somebody else's key.

The injection itself is the harness's and its cache-safety is the whole point. A
fired reminder is appended to the *tail* of the request as an ephemeral
`UserPromptPart` behind a `CachePoint`, inside `wrap_model_request` - which runs
after core has persisted the durable history. So the reminder reaches the model
but never enters `message_history`: no stale reminders pile up, and the cached
prefix (tools, system, the real conversation) stays byte-identical turn over turn
while only the small reminder falls outside the cache.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    CachePoint,
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    RetryPromptPart,
    TextContent,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.tools import AgentDepsT, RunContext
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.system_reminders import GoalReanchor

from app.agents.capabilities.budget import record_ambient_usage, usage_counts, usage_delta

if TYPE_CHECKING:
    from pydantic_ai.capabilities.abstract import WrapModelRequestHandler
    from pydantic_ai.models import ModelRequestContext

logger = logging.getLogger(__name__)

REMINDER_STATE_RESOURCE = "reminder_state"
"""Where the factory puts the run's :class:`ReminderState`, for the capability to
mutate and the runner to persist.

A resource rather than a config field, for the reason the context gauge is one: it
is not a decision an author makes. It is seeded from the conversation before the
run and read back after it, so the cadence is the conversation's and not one run's.
"""


@dataclass
class ReminderState:
    """How far a conversation's reminder cadence has advanced.

    Mutated during a run and read back after it, the way :class:`ContextGauge` is:
    the capability increments it in `wrap_model_request`, and the runner persists
    :meth:`snapshot` onto the conversation once the turn is over. Seeded from that
    stored value at the next turn's build, so leaving and reloading a conversation
    resumes the cadence rather than restarting it.

    `fire_counts` is keyed by a stable string - a static reminder's position, or
    the name of the goal-reanchor or LLM reminder - never by `id(reminder)` the
    way the harness keys it, because an object id means nothing after the process
    that made it has gone.
    """

    request_count: int = 0
    """Real model requests this conversation has made through a reminder capability."""

    fire_counts: dict[str, int] = field(default_factory=dict[str, int])
    """How many times each reminder has fired, keyed by its stable id."""

    def snapshot(self) -> dict[str, Any]:
        """The JSON the runner writes onto the conversation."""
        return {"request_count": self.request_count, "fire_counts": dict(self.fire_counts)}

    @classmethod
    def seed(cls, raw: dict[str, Any] | None) -> ReminderState:
        """A state seeded from what a conversation stored, tolerant of nothing.

        The column is null until a reminder has fired once, and a value written by
        an older shape of this code is read defensively rather than trusted: a
        count that is not an integer, or fire counts that are not a string-to-int
        map, is dropped back to the default rather than raising mid-build.
        """
        if not isinstance(raw, dict):
            return cls()
        count = raw.get("request_count")
        raw_fires = raw.get("fire_counts")
        fire_counts = (
            {str(key): value for key, value in raw_fires.items() if isinstance(value, int)}
            if isinstance(raw_fires, dict)
            else {}
        )
        return cls(
            request_count=count if isinstance(count, int) and count >= 0 else 0,
            fire_counts=fire_counts,
        )


ReminderProducer = Callable[[RunContext[AgentDepsT]], Awaitable[str | None]]
"""Produces one reminder's text for this request, or `None` to stay silent."""


@dataclass(frozen=True)
class CompiledReminder:
    """One reminder as the capability fires it: a cadence, a budget, a producer.

    The three config shapes - a static line, a goal reanchor, an LLM-written line -
    differ only in how they produce text, so they compile to this one object and
    the firing logic is written once. `key` is what the state counts fires under,
    and is stable across turns: a static reminder's position in the list, or the
    literal name of the goal-reanchor or LLM reminder.
    """

    key: str
    interval: int
    first_after: int | None
    max_fires: int | None
    tag: str | None
    produce: ReminderProducer[Any]


@dataclass
class SystemReminders(AbstractCapability[AgentDepsT]):
    """Inject periodic reminders to counter instruction fade in long sessions.

    See the module docstring for why the cadence is durable and why an LLM
    reminder inherits the run's model. This class owns the firing: on each real
    model request it advances the conversation's counter, selects the reminders
    whose cadence and `max_fires` allow firing, renders their text, and appends it
    to the request tail behind a `CachePoint`.
    """

    reminders: Sequence[CompiledReminder]
    state: ReminderState
    cache_ttl: Literal["5m", "1h"] = "5m"

    async def wrap_model_request(
        self,
        ctx: RunContext[AgentDepsT],
        *,
        request_context: ModelRequestContext,
        handler: WrapModelRequestHandler,
    ) -> ModelResponse:
        """Append fired reminders to the request tail, then call the model.

        Runs after core persists the durable history; the per-request message list
        mutated here is never written back, so the reminder and its `CachePoint`
        reach the model but never enter the conversation's history.
        """
        messages = request_context.messages
        # A provider-resume turn hands back a message list whose tail is a
        # suspended `ModelResponse`, echoed to the provider verbatim to continue
        # the turn - injecting into it would corrupt the continuation. So only a
        # real `ModelRequest` tail carries a reminder, and only such a turn spends
        # a cadence slot.
        if messages and isinstance(last := messages[-1], ModelRequest):
            self.state.request_count += 1
            texts = await self._fire(ctx)
            if texts:
                content: list[CachePoint | str] = []
                # A leading `CachePoint` is only valid when the request already
                # carries a user-content block for it to attach to; Anthropic and
                # Bedrock raise otherwise.
                if _has_user_content(last.parts):
                    content.append(CachePoint(ttl=self.cache_ttl))
                content.append("\n\n".join(texts))
                messages[-1] = replace(last, parts=[*last.parts, UserPromptPart(content=content)])
        return await handler(request_context)

    async def _fire(self, ctx: RunContext[AgentDepsT]) -> list[str]:
        """The reminder texts to inject this request, committing their fire counts.

        Fire state is committed only once a reminder actually produces text and is
        appended: a producer that returns `None` - an LLM reminder that decided to
        stay quiet, a goal reanchor with no goal yet - has not fired and does not
        spend its `max_fires` budget.
        """
        texts: list[str] = []
        for reminder in self.reminders:
            if not _should_fire(reminder, self.state.request_count):
                continue
            if (
                reminder.max_fires is not None
                and self.state.fire_counts.get(reminder.key, 0) >= reminder.max_fires
            ):
                continue
            text = await reminder.produce(ctx)
            if text is None:
                continue
            texts.append(_wrap(text, reminder.tag))
            self.state.fire_counts[reminder.key] = self.state.fire_counts.get(reminder.key, 0) + 1
        return texts


def static_producer(content: str) -> ReminderProducer[Any]:
    """A producer that returns a fixed line, ignoring the run context."""

    async def produce(_ctx: RunContext[Any]) -> str | None:
        return content

    return produce


def goal_reanchor_producer(fallback: str) -> ReminderProducer[Any]:
    """A producer that re-states the run's first user request as the anchor.

    The harness `GoalReanchor` reads the first user message off `ctx.messages` and
    asks the model to check its next action advances it - no model call and no
    dependencies. Reused rather than reimplemented: it is public and stateless, so
    the only thing to add is the async wrapper the producer protocol wants.
    """
    reanchor = GoalReanchor[Any](fallback=fallback)

    async def produce(ctx: RunContext[Any]) -> str | None:
        return reanchor(ctx)

    return produce


@dataclass
class _LlmReminder:
    """A producer whose text a model writes from a compact transcript.

    Constructed with the config it needs; the model is not among it, because the
    reminder inherits the run's own model at call time (`ctx.model`) - the one
    whose credential the vault resolved. Its spend is booked against the run's
    ledger through :func:`record_ambient_usage`, the way a compaction summary is,
    and it runs under the parent's usage limits minus one reserved request so it
    can never push the run past its own `request_limit`. On any error, or when the
    reserved budget is already spent, it falls back to the goal-reanchor line, so a
    failed generation never blocks the run.
    """

    instructions: str
    max_context_messages: int
    fallback: str
    _agent: Agent[None, str] | None = field(default=None, init=False, repr=False, compare=False)

    async def __call__(self, ctx: RunContext[Any]) -> str | None:
        try:
            text = (await self._generate(ctx)).strip()
        except Exception:
            # Never blocks the run: a provider error or an exhausted reserved
            # budget falls back to the zero-cost reanchor line.
            logger.warning("LLM reminder generation failed; using the goal reanchor", exc_info=True)
            return GoalReanchor[Any](fallback=self.fallback)(ctx)
        return text or None

    async def _generate(self, ctx: RunContext[Any]) -> str:
        """The model-written reminder, with its spend booked against the run.

        The metering is in a `finally` so a generation that raised after reaching
        the model still books what it spent - the run that failed is exactly the
        one whose cost is argued about later.
        """
        agent = self._agent
        if agent is None:
            model = ctx.model
            if not isinstance(model, Model):
                # A realtime model is not a request-response one, so it cannot run
                # the sub-agent. Raised, then caught above, so the run falls back
                # to the zero-cost reanchor rather than failing.
                raise TypeError(f"{type(model).__name__} cannot generate a reminder")
            agent = Agent[None, str](model, instructions=self.instructions, output_type=str)
            self._agent = agent
        before = usage_counts(ctx.usage)
        try:
            result = await agent.run(
                _compact_transcript(ctx.messages, self.max_context_messages),
                usage=ctx.usage,
                usage_limits=_reserved_limits(ctx.usage_limits),
            )
        finally:
            spent = usage_delta(before, ctx.usage)
            if spent is not None:
                record_ambient_usage(ctx.model.model_name or "unknown", spent)
        return result.output


def llm_reminder_producer(
    *, instructions: str, max_context_messages: int, fallback: str
) -> ReminderProducer[Any]:
    """A metered, model-inheriting LLM reminder as a producer."""
    return _LlmReminder(
        instructions=instructions, max_context_messages=max_context_messages, fallback=fallback
    )


def _reserved_limits(limits: UsageLimits | None) -> UsageLimits | None:
    """The run's limits with one request held back for the reminder's own call.

    `wrap_model_request` runs after the parent request already cleared its own
    limit check, so a nested run spending the last slot would let that approved
    request push the run one past `request_limit`. Holding the slot back makes the
    nested run raise first; the caller falls back to the reanchor, which costs no
    request, and the budget holds.
    """
    if limits is None or limits.request_limit is None:
        return limits
    return replace(limits, request_limit=max(0, limits.request_limit - 1))


def _should_fire(reminder: CompiledReminder, count: int) -> bool:
    """Whether this reminder's cadence fires on request number `count` (1-based)."""
    base = reminder.interval if reminder.first_after is None else reminder.first_after
    return count >= base and (count - base) % reminder.interval == 0


def _wrap(text: str, tag: str | None) -> str:
    """The text, wrapped in an XML tag when one is set.

    The default tag follows Claude Code's `system-reminder` convention, so the
    model reads the line as out-of-band steering rather than as something the user
    typed.
    """
    if tag is None:
        return text
    return f"<{tag}>\n{text}\n</{tag}>"


def _has_user_content(parts: Sequence[ModelRequestPart]) -> bool:
    """Whether these request parts carry a block a `CachePoint` can attach to.

    Anthropic and Bedrock reject a `CachePoint` that is the first content of a
    user message, so the tail reminder leads with one only when the request
    already contributes user-mappable content: a non-empty user prompt, a tool
    return, or a retry prompt. A system prompt maps to the system field, not user
    content, so it does not count.
    """
    for part in parts:
        if isinstance(part, ToolReturnPart | RetryPromptPart):
            return True
        if isinstance(part, UserPromptPart):
            content = part.content
            if isinstance(content, str):
                if content:
                    return True
            elif any(_is_user_content_item(item) for item in content):
                return True
    return False


def _is_user_content_item(item: object) -> bool:
    if isinstance(item, CachePoint):
        return False
    if isinstance(item, str):
        return bool(item)
    if isinstance(item, TextContent):
        return bool(item.content)
    return True


def _first_user_text(messages: Sequence[ModelMessage]) -> str | None:
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    text = _prompt_text(part.content)
                    if text:
                        return text
    return None


def _prompt_text(content: str | Sequence[object]) -> str:
    if isinstance(content, str):
        return content
    texts: list[str] = []
    for item in content:
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, TextContent):
            texts.append(item.content)
    return " ".join(texts)


def _compact_transcript(messages: Sequence[ModelMessage], max_messages: int) -> str:
    """The goal and the last few turns, as one string for the reminder model."""
    goal = _first_user_text(messages)
    recent = _recent_texts(messages, max_messages)
    sections: list[str] = []
    if goal is not None:
        sections.append(f"Original goal: {goal}")
    if recent:
        sections.append("Recent activity:\n" + "\n".join(recent))
    return "\n\n".join(sections) if sections else "No activity yet."


def _recent_texts(messages: Sequence[ModelMessage], max_messages: int) -> list[str]:
    fragments: list[str] = []
    for message in messages:
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                text = _prompt_text(part.content)
                if text:
                    fragments.append(f"user: {text}")
            elif isinstance(part, TextPart) and part.content:
                fragments.append(f"assistant: {part.content}")
    return fragments[-max_messages:]
