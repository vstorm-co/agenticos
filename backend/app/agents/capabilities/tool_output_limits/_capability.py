"""Reducing an oversized tool return before it costs the run for the rest of it.

A tool can hand back a payload large enough to dominate the model's window - a
grep over a big repository, a verbose API response, a directory listing that runs
to tens of thousands of characters. That return persists in history as a
`ToolReturnPart`, so it is re-sent on *every* later request of the run, paying its
token cost again each time. The repo's existing answer is to truncate at the
source (`code_execution` clips at 8,000 chars); the right default, the wrong
ceiling, because the part that mattered is silently gone from the model's view.

The reduction itself is `pydantic-ai-harness`'s `ToolOutputLimits`, the same
bargain `compaction` strikes with the harness: the library owns the mechanism,
this module owns the two things a platform has to add.

**A store the tenant owns.** The harness default keeps spilled payloads on shared
disk, forever - a cross-tenant leak that outlives the run. Here a spill goes to
the agent's own backend when it has one, and to an ephemeral in-memory backend
when it does not; see :mod:`._store` and :func:`_build_store`.

**A budget that can see a summary.** The `summarize` action writes through an
`Agent` the harness builds itself, so that request never passes `BudgetGuard` -
the same #16 hole `compaction` closes. Its tokens land in `ctx.usage` and nowhere
else, so :class:`MeteredToolOutputLimits` books the delta against the run's ledger.

One knob the harness offers is deliberately not exposed: the `bands` list. The
Builder renders a form from the config's JSON schema and cannot draw a nested list
of `(threshold, action)` pairs, so - as `compaction` chooses a strategy rather than
composing tiers - an author picks one `action` and one `threshold`, and the module
assembles the single band with the fallbacks the harness README recommends
(`spill -> truncate`, `summarize -> spill -> truncate`), so a reduction that cannot
run degrades to a cheaper one rather than to a silent drop.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_ai.capabilities import WrapperCapability
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import AgentDepsT, RunContext, ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, AgentToolset
from pydantic_ai_backends import StateBackend
from pydantic_ai_harness.tool_output_limits import (
    READ_TOOL_NAME,
    Action,
    Band,
    Spill,
    Summarize,
    ToolOutputLimits,
    Truncate,
    TruncationStrategy,
)

from app.agents.capabilities._tool_text import ToolText
from app.agents.capabilities.budget import record_ambient_usage, usage_counts, usage_delta
from app.agents.capabilities.tool_output_limits._store import BackendOverflowStore

DEFAULT_THRESHOLD = 10_000
"""Size at or above which a return is reduced - characters, or estimated tokens
when `over_tokens` is set. Matches the harness's own default."""

DEFAULT_MAX_CHARS = 4_000
"""Characters kept when a return is truncated, or when a spill falls back to one."""

DEFAULT_SUMMARY_PROMPT: str = ToolOutputLimits().summary_prompt
"""The prompt a `summarize` reduction is written with, unless a binding replaces it.

Read off the library rather than copied, so the two cannot drift - a copy here
would be offered to authors long after the upstream one changed, and the gap
between the prompt they edit and the prompt that runs would be invisible. Building
a throwaway `ToolOutputLimits` is cheap: its default store touches no disk until a
payload is written."""

ActionName = Literal["spill", "truncate", "summarize"]
"""Which reduction a binding picked.

Stored in published specs and exported into a client's git repository, so these
three strings are as permanent as the capability id. An action that stops making
sense is deprecated in the documentation; the value keeps resolving.
"""

StrategyName = Literal["head", "tail", "head_tail"]
"""Which end(s) of an oversized text a `truncate` keeps."""


class ToolOutputLimitsConfig(BaseModel):
    """How an agent should reduce a tool return too large for its window.

    Flat scalars and two enums, deliberately: the Builder generates this form from
    the JSON schema and renders string, number, boolean and enum fields, so the
    band the harness composes from a nested list is expressed here as one `action`
    at one `threshold` instead.
    """

    action: ActionName = Field(
        default="spill",
        description="What to do with a return once it is over the threshold",
        # What the Builder puts in the picker; spec values cannot say what they do.
        json_schema_extra={
            "x-enum-labels": {
                "spill": "Keep it in full on the backend; the model reads slices on demand",
                "truncate": "Clamp it to a character budget - cheap, lossy, no read-back",
                "summarize": "Replace it with an LLM summary - the expensive option",
            }
        },
    )
    threshold: int = Field(
        default=DEFAULT_THRESHOLD,
        ge=500,
        description=(
            "Size at or above which a return is reduced. Characters by default; "
            "estimated tokens when 'over tokens' is set"
        ),
    )
    over_tokens: bool = Field(
        default=False,
        description="Measure the threshold in estimated tokens rather than characters",
    )
    max_chars: int = Field(
        default=DEFAULT_MAX_CHARS,
        ge=200,
        description=(
            "Characters kept when a return is truncated, or when a spill or summary "
            "falls back to truncation"
        ),
    )
    truncation_strategy: StrategyName = Field(
        default="head_tail",
        description="Which end(s) of an oversized text to keep when truncating",
        json_schema_extra={
            "x-enum-labels": {
                "head": "Keep the start - good for headers and schemas",
                "tail": "Keep the end - good for logs, where errors land last",
                "head_tail": "Keep the start and end, eliding the middle",
            }
        },
    )
    strip_ansi: bool = Field(
        default=False,
        description="Strip terminal colour codes from text returns before measuring and reducing",
    )
    summary_prompt: str = Field(
        default=DEFAULT_SUMMARY_PROMPT,
        min_length=1,
        max_length=8_000,
        description=(
            "What the summarising model is told, for the 'summarize' action. Must "
            "contain {output}, where the tool's full output is inserted; {tool_name} "
            "is available too, for the name of the tool that produced it"
        ),
        json_schema_extra={"x-multiline": True},
    )

    @field_validator("summary_prompt")
    @classmethod
    def _must_carry_the_output(cls, prompt: str) -> str:
        """A summary prompt missing `{output}` summarises nothing; a stray field crashes it.

        Refused here rather than mid-run, which is where it would otherwise
        surface: the harness formats this string only when a `summarize` fires,
        on the long returns an agent actually spills, so the mistake would be a
        turn that summarised an empty string - or raised `KeyError` on an unknown
        placeholder - after the run was already underway.

        Only `{output}` is required. The harness always passes `tool_name=` too,
        so a prompt that never names the tool formats fine and is a legitimate
        choice; requiring it would refuse a valid prompt for no mechanism's sake.
        """
        if "{output}" not in prompt:
            raise ValueError("The summary prompt must contain {output}")
        try:
            prompt.format(tool_name="", output="")
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(
                "The summary prompt has a placeholder other than {tool_name} and {output}"
            ) from exc
        return prompt


def _action(config: ToolOutputLimitsConfig) -> Action:
    """The single band action this configuration asks for, with harness fallbacks.

    `spill` degrades to a truncation when the backend cannot keep the payload, and
    `summarize` degrades through a spill to a truncation when the model call or the
    store fails - so a reduction that cannot run becomes a cheaper one, never a
    silent drop. `summarize` inherits the run's model (`model=None`), which is the
    only one whose credential was resolved from the vault.
    """
    truncate = Truncate(
        strategy=TruncationStrategy(config.truncation_strategy), max_chars=config.max_chars
    )
    if config.action == "truncate":
        return truncate
    spill = Spill(then=truncate)
    if config.action == "spill":
        return spill
    return Summarize(then=spill)


def _build_store(backend: Any, spill_log: list[str] | None = None) -> BackendOverflowStore:
    """Where spills go: the run's own backend, or an ephemeral one built for it.

    An agent that binds `sandbox` has a backend the runner opened and keyed to the
    organization; a spill lives and dies with that workspace, which on the default
    `run` scope is exactly the run. On a longer-scoped workspace (`conversation`,
    `user`, `agent`) a spill must not outlive the run either, and each backend
    shape has its own mechanism: a `state` workspace has the reserved prefix
    stripped at flush, so spills never enter the persisted document, and a
    *container* workspace has this run's handles - recorded in `spill_log` -
    deleted off its filesystem when the workspace closes (#803).

    An agent with no backend gets a fresh in-memory `StateBackend` here, so the
    store is per-run and process-local rather than on shared disk. The fallback is
    uncapped: the store itself grows with each spill, but nothing is persisted and
    the run bounds how much it can accumulate before it is discarded whole. No
    handles are recorded for it - there is nothing to delete from a backend that
    dies with the run.
    """
    if backend is None:
        return BackendOverflowStore(StateBackend())
    return BackendOverflowStore(backend, spill_log=spill_log)


def build_limits(
    config: ToolOutputLimitsConfig, *, backend: Any, spill_log: list[str] | None = None
) -> ToolOutputLimits[object]:
    """The harness capability this configuration asks for, spilling to `backend`."""
    return ToolOutputLimits(
        bands=[Band(over=config.threshold, action=_action(config))],
        over_tokens=config.over_tokens,
        store=_build_store(backend, spill_log),
        strip_ansi=config.strip_ansi,
        summary_prompt=config.summary_prompt,
    )


READ_TOOL_RESULT_TEXT = ToolText(
    summary="Read part of a tool result that was too large to return whole.",
    usage=(
        "The handle comes from a tool return that said it had been spilled. Read "
        "the part you need rather than the whole payload: narrow with `pattern` "
        "first, then page with `offset` and `limit`."
    ),
    returns=(
        "The matching lines, under a header saying which slice of how many they "
        "are, so a further call can pick up where this one stopped. A handle this "
        "run never spilled says so - that result is gone, not elsewhere, and no "
        "other handle will find it."
    ),
)


def _describe_read_tool_result(
    _ctx: RunContext[object], tool_defs: list[ToolDefinition]
) -> list[ToolDefinition]:
    """Give `read_tool_result` this repository's text, and leave anything else."""
    return [
        replace(tool_def, description=READ_TOOL_RESULT_TEXT.render())
        if tool_def.name == READ_TOOL_NAME
        else tool_def
        for tool_def in tool_defs
    ]


@dataclass
class MeteredToolOutputLimits(WrapperCapability[AgentDepsT]):
    """Books what a `summarize` reduction spent against the run that spent it.

    Wrapped around every configuration, not only `summarize`. An allowlist of
    "these can spend" is a list somebody has to remember to extend, and the entry
    they forget is a model call nobody is billed for - the same #16 shape the
    wrapper exists to close. `spill` and `truncate` call no model, so the delta is
    zero and nothing is booked; the cost of being uniform is reading four integers
    per tool return.

    The delta is measured on `ctx.usage`, which is what the harness's summary
    `Agent` was handed and therefore the only place its tokens appear, and booked
    through :func:`record_ambient_usage` rather than a ledger held here - the
    runner opens `metered_by` around the whole run, and a reduction inside a
    delegation must bill to its own row rather than to whichever ledger was
    captured when this was assembled.

    Booked in a `finally`: a summary that raised after its model call still spent
    the tokens, and a run that failed is exactly the one whose cost is argued about
    later. What this cannot do is *stop* the spend - `BudgetGuard` refuses on the
    request after it, the same as for compaction.
    """

    def get_toolset(self) -> AgentToolset[AgentDepsT] | None:
        """The wrapped toolset, with `read_tool_result` described properly.

        The library's own text is one sentence and says nothing about what comes
        back - and this is the tool a model reaches for holding a handle to a
        result it could not be given whole, which is the worst moment to leave it
        guessing whether an empty answer means "no matches" or "gone". Rewritten
        here rather than upstream because `pydantic-ai-harness` is Pydantic's
        package, not this organization's: a change to its default is a pull
        request to them, and this is a deployment's own wording either way.
        """
        toolset = super().get_toolset()
        if toolset is None:  # pragma: no cover - the library always builds one
            return None
        if not isinstance(toolset, AbstractToolset):
            # The same refusal `ToolOverrides` makes, for the same reason: a
            # toolset resolved per run has no tool list to rewrite here, and
            # returning it untouched would leave the model reading the library's
            # sentence while the Builder shows this one, with nothing saying so.
            raise TypeError(
                "Tool output limits resolved its toolset per run, "
                "so `read_tool_result` cannot be described here"
            )
        return toolset.prepared(_describe_read_tool_result)

    async def after_tool_execute(
        self,
        ctx: RunContext[AgentDepsT],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        result: Any,
    ) -> Any:
        before = usage_counts(ctx.usage)
        try:
            return await self.wrapped.after_tool_execute(
                ctx, call=call, tool_def=tool_def, args=args, result=result
            )
        finally:
            spent = usage_delta(before, ctx.usage)
            if spent is not None:
                record_ambient_usage(ctx.model.model_name or "unknown", spent)
