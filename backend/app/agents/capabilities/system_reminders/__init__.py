"""System reminders capability - re-inject steering guidance mid-run."""

from typing import Literal

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.system_reminders._capability import (
    REMINDER_STATE_RESOURCE,
    CompiledReminder,
    ReminderState,
    SystemReminders,
    goal_reanchor_producer,
    llm_reminder_producer,
    static_producer,
)

__all__ = [
    "REMINDER_STATE_RESOURCE",
    "CompiledReminder",
    "GoalReanchorConfig",
    "LlmReminderConfig",
    "ReminderConfig",
    "ReminderState",
    "SystemReminders",
    "SystemRemindersConfig",
]

_DEFAULT_LLM_INSTRUCTIONS = (
    "You write a short stay-on-task reminder for an AI agent mid-run. Given the "
    "original goal and recent activity, produce at most two sentences that refocus "
    "the agent on the goal. Output only the reminder text."
)
_DEFAULT_FALLBACK = "Stay on task."


class _CadenceConfig(BaseModel):
    """The three cadence knobs every reminder shares.

    `interval` and `first_after` count *model requests across the whole
    conversation*, not turns and not runs - the counter is durable, so a reminder
    set to fire every ten requests keeps counting where the last turn left off.
    `max_fires` caps the total over the conversation's life.
    """

    interval: int = Field(
        default=1,
        ge=1,
        le=1000,
        description="Fire every N model requests. interval=3 fires on the 3rd, 6th, 9th, ...",
    )
    first_after: int | None = Field(
        default=None,
        ge=1,
        le=10_000,
        description=(
            "Model request number of the first fire. Left unset, the first fire is the "
            "first multiple of interval"
        ),
    )
    max_fires: int | None = Field(
        default=None,
        ge=1,
        le=10_000,
        description="Most times this reminder may fire in the conversation. Unset means no limit",
    )


class ReminderConfig(_CadenceConfig):
    """One fixed line, re-stated on a cadence."""

    content: str = Field(
        min_length=1,
        max_length=4_000,
        description="The reminder text the model reads mid-run",
        json_schema_extra={"x-multiline": True},
    )
    tag: str | None = Field(
        default="system-reminder",
        max_length=64,
        description=(
            "Wrap the line in this XML tag so the model reads it as out-of-band steering. "
            "Set empty to emit the raw text"
        ),
    )


class GoalReanchorConfig(_CadenceConfig):
    """Re-state the run's first user request as the anchor. No model call."""

    fallback: str = Field(
        default=_DEFAULT_FALLBACK,
        min_length=1,
        max_length=1_000,
        description="What to say before there is a user message to anchor to",
    )
    tag: str | None = Field(default="system-reminder", max_length=64, description="XML wrapper tag")


class LlmReminderConfig(_CadenceConfig):
    """A reminder a model writes each time, from a compact transcript.

    It inherits the run's own model - the one whose key the vault holds - and its
    spend is booked against the run's budget. It issues one extra model call each
    time it fires, so the default cadence is wider than the others; raise
    `interval` further if per-turn generation is too costly.
    """

    interval: int = Field(
        default=5,
        ge=1,
        le=1000,
        description="Fire every N model requests. Wider by default, because each fire costs a call",
    )
    max_context_messages: int = Field(
        default=10,
        ge=1,
        le=50,
        description="How many recent messages the reminder model is shown",
    )
    instructions: str = Field(
        default=_DEFAULT_LLM_INSTRUCTIONS,
        min_length=1,
        max_length=4_000,
        description="What the reminder model is told to write",
        json_schema_extra={"x-multiline": True},
    )
    fallback: str = Field(
        default=_DEFAULT_FALLBACK,
        min_length=1,
        max_length=1_000,
        description="What to say when generation fails or the budget is too tight",
    )
    tag: str | None = Field(default="system-reminder", max_length=64, description="XML wrapper tag")


class SystemRemindersConfig(BaseModel):
    """What to re-state, and how often, to keep a long run on task.

    At least one of the three must be set, or the capability contributes nothing
    and is dropped from the run - which is what a spec with an empty config means.
    """

    reminders: list[ReminderConfig] = Field(
        default_factory=list,
        max_length=20,
        description="Fixed lines re-stated on their own cadences",
    )
    goal_reanchor: GoalReanchorConfig | None = Field(
        default=None,
        description="Re-state the original request on a cadence, at no token cost",
    )
    llm_reminder: LlmReminderConfig | None = Field(
        default=None,
        description="A model-written reminder on a cadence. Costs one extra call each fire",
    )
    cache_ttl: Literal["5m", "1h"] = Field(
        default="5m",
        description="Cache lifetime of the breakpoint placed before the tail reminder",
    )


def _compile(config: SystemRemindersConfig) -> list[CompiledReminder]:
    """The config's reminders as the capability fires them.

    Static reminders are keyed by their position, the goal reanchor and the LLM
    reminder by their names - stable strings the durable fire counts are stored
    under, so the count survives a turn boundary.
    """
    reminders: list[CompiledReminder] = [
        CompiledReminder(
            key=str(index),
            interval=spec.interval,
            first_after=spec.first_after,
            max_fires=spec.max_fires,
            tag=spec.tag or None,
            produce=static_producer(spec.content),
        )
        for index, spec in enumerate(config.reminders)
    ]
    if config.goal_reanchor is not None:
        spec = config.goal_reanchor
        reminders.append(
            CompiledReminder(
                key="goal_reanchor",
                interval=spec.interval,
                first_after=spec.first_after,
                max_fires=spec.max_fires,
                tag=spec.tag or None,
                produce=goal_reanchor_producer(spec.fallback),
            )
        )
    if config.llm_reminder is not None:
        llm = config.llm_reminder
        reminders.append(
            CompiledReminder(
                key="llm",
                interval=llm.interval,
                first_after=llm.first_after,
                max_fires=llm.max_fires,
                tag=llm.tag or None,
                produce=llm_reminder_producer(
                    instructions=llm.instructions,
                    max_context_messages=llm.max_context_messages,
                    fallback=llm.fallback,
                ),
            )
        )
    return reminders


@register(
    id="system_reminders",
    name="System reminders",
    category="reasoning",
    description=(
        "Re-state guidance mid-run so a long session stops drifting from its instructions."
    ),
    # No tools by design: this appends steering text to a request, so there is
    # nothing here for a person to approve. See `system_reminders/_capability.py`.
    tools=(),
    config_schema=SystemRemindersConfig,
)
def _build(ctx: CapabilityBuildContext) -> SystemReminders[object] | None:
    """The configured reminders, or `None` when none were configured.

    Returning `None` is what makes "on but with nothing to say" impossible: a spec
    that binds the capability and sets no reminder contributes nothing to the run
    rather than attaching a capability that never fires.
    """
    config = (
        ctx.config if isinstance(ctx.config, SystemRemindersConfig) else SystemRemindersConfig()
    )
    reminders = _compile(config)
    if not reminders:
        return None
    seeded = ctx.resources.get(REMINDER_STATE_RESOURCE)
    state = seeded if isinstance(seeded, ReminderState) else ReminderState()
    return SystemReminders(reminders=reminders, state=state, cache_ttl=config.cache_ttl)
