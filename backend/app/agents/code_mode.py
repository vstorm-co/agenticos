"""Code mode: call many tools from one sandboxed script (#2107).

An agent that has to call a tool ten times and then work with the results needs
a model turn for each dependent batch, and every turn re-sends the whole context.
With code mode on, `pydantic-ai-harness`'s `CodeMode` folds the agent's tools into
one `run_code` tool: the model writes a short Python script - loops, conditions,
`asyncio.gather` - that runs in the Monty sandbox, and every tool it calls is
dispatched through Pydantic AI to the real tool.

**Every governed path still applies**, because a call from a script goes through
the same tool hooks a direct call does: the guardrails, the budget, and the
permission checks inside each tool. Approval is the one a script cannot wait for -
the run parks on it, and a script has no way to park mid-line - so a tool that
needs approval is never folded in. It stays a tool the model calls directly, and
the run stops for the person exactly as it does without code mode. With a session
that asks before every tool, nothing is folded and code mode is not added at all.

**What it did is written down.** :class:`CodeCalls` keeps each script and every
call it made on the run's manifest, so a reviewer sees what the agent actually did
rather than one opaque `run_code` step.
"""

from __future__ import annotations

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
from app.agents.manifest import RunRecorder
from app.agents.mcp import NEEDS_APPROVAL

CODE_TOOL = "run_code"
"""The one tool code mode offers the model, as `CodeMode` names it."""

ARGS_PREVIEW_CHARS = 500
"""How much of a nested call's arguments the manifest keeps."""

_script: ContextVar[dict[str, Any] | None] = ContextVar("code_mode_script", default=None)
"""The script a tool call is being made from, if it is being made from one."""


def code_mode(
    *, approval_required: frozenset[str], asking: frozenset[str], max_tool_calls: int
) -> CodeMode[AgentDeps]:
    """`CodeMode` over every tool but those a person has to answer before they run."""

    def foldable(_ctx: RunContext[AgentDeps], tool: ToolDefinition) -> bool:
        if tool.name in approval_required or tool.name in asking:
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
                "code": str(args.get("code", "")),
                "calls": [],
            }
            self.recorder.code_runs.append(script)
            token = _script.set(script)
            try:
                return await handler(args)
            finally:
                _script.reset(token)
        script = _script.get()
        if script is None:
            return await handler(args)
        made: dict[str, Any] = {"tool": tool_def.name, "args": _preview(args), "status": "failed"}
        script["calls"].append(made)
        result = await handler(args)
        made["status"] = "returned"
        return result


def _preview(args: dict[str, Any]) -> str:
    text = json.dumps(args, default=str, ensure_ascii=False)
    return text if len(text) <= ARGS_PREVIEW_CHARS else f"{text[:ARGS_PREVIEW_CHARS]}…"
