"""Malformed tool-call arguments repaired before validation, and counted (#2105).

A model sometimes sends a call whose JSON is broken - a trailing comma, single
quotes, an object cut short. Pydantic AI rejects it and the model retries, and
each retry is a paid request. Open-weight models served by Ollama or vLLM do it
far more often than frontier ones, and they are much of why a deployment is
self-hosted at all.

So every agent repairs a call's arguments with `json-repair` before they are
validated. Only the syntax: a missing field or a wrong type still fails
validation and retries as before, and a repaired call goes on through the same
approval gate and guardrails as any other, which see the repaired arguments.

The count is kept per run, so run history - and the per-model breakdown beside
it - shows which models needed it. The repair's span carries no arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_ai import RunContext
from pydantic_ai.capabilities import RawToolArgs
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition
from pydantic_ai_harness.repair_tool_arguments import RepairToolArguments

from app.agents.deps import AgentDeps


@dataclass
class RepairTally:
    """How many of one run's tool calls arrived malformed and were repaired."""

    count: int = 0


@dataclass
class CountedRepair(RepairToolArguments[AgentDeps]):
    """`RepairToolArguments`, counting each call it changed on the run's tally."""

    tally: RepairTally = field(default_factory=RepairTally)

    async def before_tool_validate(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: RawToolArgs,
    ) -> RawToolArgs:
        repaired = await super().before_tool_validate(ctx, call=call, tool_def=tool_def, args=args)
        if repaired != args:
            self.tally.count += 1
        return repaired
