"""Code mode: call many tools from one sandboxed script (#2107).

An agent that has to call a tool ten times and then work with the results needs
a model turn for each dependent batch, and every turn re-sends the whole context.
With code mode on, `pydantic-ai-harness`'s `CodeMode` folds the agent's tools into
one `run_code` tool: the model writes a short Python script - loops, conditions,
`asyncio.gather` - that runs in the Monty sandbox, and every tool it calls is
dispatched through Pydantic AI to the real tool.

**Every governed path still applies**, because a call from a script goes through
the same tool hooks a direct call does: the guardrails, the budget, and the
permission checks inside each tool. A tool that can *park* the run is the one a
script cannot call - a script has no way to stop mid-line and resume tomorrow - so
none is folded in: one that needs approval, a question to the person
(`ask_user`), and a delegation (`subagents`), whose delegate may itself park.
Each stays a tool the model calls directly, and the run stops for the person
exactly as it does without code mode. With a session that asks before every tool,
nothing is folded and code mode is not added at all.

**What it did is written down.** :class:`CodeCalls` keeps each script and every
call it made on the run's manifest, so a reviewer sees what the agent actually did
rather than one opaque `run_code` step.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition
from pydantic_ai_harness import CodeMode

from app.agents.deps import AgentDeps
from app.agents.manifest import RECORDED_SCRIPTS, RunRecorder
from app.agents.mcp import NEEDS_APPROVAL

CODE_TOOL = "run_code"
"""The one tool code mode offers the model, as `CodeMode` names it."""

PARKING_CAPABILITIES = frozenset({"ask_user", "subagents"})
"""Capabilities whose tools can end the run waiting on a person, so stay out of scripts."""

ARGS_PREVIEW_CHARS = 200
"""How much of a nested call's arguments the manifest keeps."""

CODE_CHARS = 20_000
"""How much of one script the manifest keeps."""

RECORDED_CALLS = 100
"""How many of one script's calls the manifest lists; the rest are counted."""

CONCURRENT_CALLS = 4
"""How many of one script's tool calls run at once.

`max_tool_calls` bounds how many a script makes, not how many run together: an
`asyncio.gather` over hundreds of `run_python` calls would otherwise open as many
sandboxes at once, each with its own memory and time allowance. The rest wait.
"""


@dataclass
class _Running:
    """A `run_code` script while it runs: its manifest entry and its call gate."""

    record: dict[str, Any]
    gate: asyncio.Semaphore


_script: ContextVar[_Running | None] = ContextVar("code_mode_script", default=None)
"""The script a tool call is being made from, if it is being made from one."""


def code_mode(
    *, approval_required: frozenset[str], asking: frozenset[str], max_tool_calls: int
) -> CodeMode[AgentDeps]:
    """`CodeMode` over every tool but those a person has to answer before they run."""

    def foldable(_ctx: RunContext[AgentDeps], tool: ToolDefinition) -> bool:
        if tool.name in approval_required or tool.name in asking:
            return False
        if tool.capability_id in PARKING_CAPABILITIES:
            return False
        return (tool.metadata or {}).get(NEEDS_APPROVAL) is not True

    return CodeMode(tools=foldable, max_tool_calls=max_tool_calls)


@dataclass
class CodeCalls(AbstractCapability[AgentDeps]):
    """Keeps each `run_code` script, and every call it made, on the run's manifest."""

    recorder: RunRecorder

    async def wrap_tool_execute(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        handler: Callable[[dict[str, Any]], Awaitable[Any]],
    ) -> Any:
        if tool_def.name == CODE_TOOL:
            script: dict[str, Any] = {
                "tool_call_id": call.tool_call_id,
                "code": str(args.get("code", ""))[:CODE_CHARS],
                "calls": [],
                "omitted_calls": 0,
            }
            if len(self.recorder.code_runs) < RECORDED_SCRIPTS:
                self.recorder.code_runs.append(script)
            token = _script.set(_Running(script, asyncio.Semaphore(CONCURRENT_CALLS)))
            try:
                return await handler(args)
            finally:
                _script.reset(token)
        running = _script.get()
        if running is None:
            return await handler(args)
        script = running.record
        made: dict[str, Any] = {"tool": tool_def.name, "args": _preview(args), "status": "failed"}
        if len(script["calls"]) < RECORDED_CALLS:
            script["calls"].append(made)
        else:
            script["omitted_calls"] += 1
        async with running.gate:
            result = await handler(args)
        made["status"] = "returned"
        return result


def _preview(args: dict[str, Any]) -> str:
    text = json.dumps(args, default=str, ensure_ascii=False)
    return text if len(text) <= ARGS_PREVIEW_CHARS else f"{text[:ARGS_PREVIEW_CHARS]}…"
