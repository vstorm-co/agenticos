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

import ast
import asyncio
import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import ToolFailed
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition
from pydantic_ai_harness import CodeMode
from pydantic_monty import MontyRuntimeError, MontySyntaxError, MontyTypingError

from app.agents.deps import AgentDeps
from app.agents.manifest import RECORDED_SCRIPTS, RunRecorder
from app.agents.mcp import NEEDS_APPROVAL
from app.agents.tool_errors import (
    ControlledToolError,
    capture_tool_errors,
    nested_tool_error,
    tool_error,
)

CODE_TOOL = "run_code"
"""The one tool code mode offers the model, as `CodeMode` names it."""

PARKING_CAPABILITIES = frozenset({"ask_user", "subagents"})
"""Capabilities whose tools can end the run waiting on a person, so stay out of scripts."""

SHOWN_CAPABILITIES = frozenset({"drafts", "charts", "visuals"})
"""Capabilities whose call is what the person sees: run from a script it leaves no part for the console to draw."""

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
        if tool.capability_id in PARKING_CAPABILITIES | SHOWN_CAPABILITIES:
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
                with capture_tool_errors() as errors:
                    return await handler(args)
            except Exception as exc:
                failure = _code_failure(
                    exc,
                    code=str(args.get("code", "")),
                    calls_started=bool(script["calls"]),
                    errors=errors,
                )
                if failure is None:
                    raise
                raise ToolFailed(failure) from exc
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


def _code_failure(
    exc: Exception, *, code: str, calls_started: bool, errors: list[ControlledToolError]
) -> str | None:
    """Summarize typed sandbox failures without returning its source or traceback.

    CodeMode wraps Monty's failure in ModelRetry and then ToolRetryError. The
    typed cause survives, so the message never needs to parse a vendor's text.
    A snippet can call tools before its failing line; those effects cannot be
    inferred from the local exception and must be inspected before replaying it.
    """
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, MontyRuntimeError | MontySyntaxError | MontyTypingError):
            break
        cause = cause.__cause__
    if not isinstance(cause, MontyRuntimeError | MontySyntaxError | MontyTypingError):
        return None
    inner = cause.exception()
    nested = next((content for content in reversed(errors) if inner.args == (content,)), None)
    if nested is not None:
        return nested_tool_error(nested, tool=CODE_TOOL, calls_started=calls_started, error=exc)
    exception_type = type(inner).__name__
    if calls_started:
        return tool_error(
            tool=CODE_TOOL,
            code="execution_unknown",
            execution="unknown",
            message=(
                f"Code execution failed: {exception_type}. Tool calls started before the failure; "
                "inspect their execution status before retrying the script."
            ),
            recovery="inspect_execution_status",
            exception_type=exception_type,
            error=exc,
        )
    if not isinstance(cause, MontyRuntimeError):
        return tool_error(
            tool=CODE_TOOL,
            code="invalid_arguments",
            execution="not_started",
            message=f"Code validation failed: {exception_type}. Correct the `code` argument.",
            recovery="correct_arguments",
            exception_type=exception_type,
            error=exc,
        )
    denied = isinstance(inner, PermissionError)
    return tool_error(
        tool=CODE_TOOL,
        code="permission_denied" if denied else "invalid_arguments",
        execution="started",
        message=f"Code execution failed: {exception_type}{_code_operation(code, cause)}.",
        recovery="stop" if denied else "correct_arguments",
        exception_type=exception_type,
        error=exc,
    )


def _code_operation(code: str, error: MontyRuntimeError) -> str:
    """Name a known operation and only a literal path in the submitted code."""
    frames = error.traceback()
    if not frames:
        return ""
    frame = frames[-1]
    operations = {
        "iterdir": "listing",
        "listdir": "listing",
        "read_text": "reading",
        "read_bytes": "reading",
    }
    for node in ast.walk(ast.parse(code)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.lineno != frame.line or node.col_offset + 1 != frame.column:
            continue
        operation = operations.get(node.func.attr)
        if operation is None:
            return ""
        target = node.func.value
        arguments = target.args if isinstance(target, ast.Call) else node.args
        if (
            arguments
            and isinstance(arguments[0], ast.Constant)
            and isinstance(arguments[0].value, str)
        ):
            path = arguments[0].value
            if len(path) <= 200 and "\n" not in path and "\r" not in path and "://" not in path:
                return f" while {operation} {path!r}"
        return f" while {operation} a path in the submitted code"
    return ""
