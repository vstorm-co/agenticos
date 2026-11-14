"""Code mode: call many tools from one sandboxed script (#2107).

An agent that has to call a tool ten times and then work with the results needs
a model turn for each dependent batch, and every turn re-sends the whole context.
With code mode on, `pydantic-ai-harness`'s `CodeMode` folds the agent's tools into
one `run_code` tool: the model writes a short Python script - loops, conditions,
`asyncio.gather` - that runs in the Monty sandbox, and every tool it calls is
dispatched through Pydantic AI to the real tool.

**Every governed path still applies**, because a call from a script goes through
the same tool hooks a direct call does: the guardrails, the budget, and the
permission checks inside each tool. An approval-controlled call parks the script:
the server saves the Monty interpreter and host-call state after draining already
started calls. A decision resumes that state on any worker, without another
model request or replaying completed effects. Rejection raises a controlled error
inside the script. Questions, delegations and visible UI tools stay native.
Sessions that ask before every tool and routine runs retain their existing
native-tool policy.

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

from pydantic import JsonValue, TypeAdapter
from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import ToolFailed
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition
from pydantic_ai_harness import CodeMode
from pydantic_monty import MontyRuntimeError, MontySyntaxError, MontyTypingError

from app.agents.code_checkpoint import CodeApprovalPause
from app.agents.code_diagnostics import name_error_issues, syntax_issues, typing_issues
from app.agents.deps import AgentDeps
from app.agents.durable_code import DurableCodeMode, checkpoint_key, code_owner
from app.agents.manifest import RECORDED_SCRIPTS, RunRecorder
from app.agents.tool_errors import (
    RUN_STOP_ERRORS,
    ControlledToolError,
    ToolArgumentIssue,
    ToolRunStopped,
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
    """Fold governed calls too; questions, delegations and visible UI remain native."""

    def foldable(_ctx: RunContext[AgentDeps], tool: ToolDefinition) -> bool:
        if tool.name in asking or tool.name in _ctx.deps.code_continuations.native_tools.get(
            code_owner(), frozenset()
        ):
            return False
        return tool.capability_id not in PARKING_CAPABILITIES | SHOWN_CAPABILITIES

    return DurableCodeMode(
        tools=foldable, max_tool_calls=max_tool_calls, required_tool_names=approval_required
    )


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
            kept = ctx.deps.code_continuations.checkpoints.get(checkpoint_key(call.tool_call_id))
            script: dict[str, Any] = (
                dict(kept.manifest)
                if kept is not None
                else {
                    "tool_call_id": call.tool_call_id,
                    "code": str(args.get("code", ""))[:CODE_CHARS],
                    "calls": [],
                    "omitted_calls": 0,
                }
            )
            if len(self.recorder.code_runs) < RECORDED_SCRIPTS:
                self.recorder.code_runs.append(script)
            token = _script.set(_Running(script, asyncio.Semaphore(CONCURRENT_CALLS)))
            try:
                with capture_tool_errors() as errors:
                    return await handler(args)
            except ToolRunStopped as stopped:
                raise stopped.error from None
            except RUN_STOP_ERRORS:
                raise
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
        made = next(
            (entry for entry in script["calls"] if entry.get("tool_call_id") == call.tool_call_id),
            None,
        )
        if made is None:
            made = {
                "tool_call_id": call.tool_call_id,
                "tool": tool_def.name,
                "args": _preview(args),
                "status": "failed",
            }
            if len(script["calls"]) < RECORDED_CALLS:
                script["calls"].append(made)
            else:
                script["omitted_calls"] += 1
        made["status"] = "failed"
        try:
            async with running.gate:
                result = await handler(args)
        except CodeApprovalPause:
            made["status"] = "awaiting_approval"
            raise
        made["status"] = "returned"
        return result


def current_code_record() -> dict[str, JsonValue]:
    running = _script.get()
    if running is None:
        return {}
    return TypeAdapter(dict[str, JsonValue]).validate_python(running.record)


def _preview(args: dict[str, Any]) -> str:
    text = json.dumps(args, default=str, ensure_ascii=False)
    return text if len(text) <= ARGS_PREVIEW_CHARS else f"{text[:ARGS_PREVIEW_CHARS]}…"


def _code_failure(
    exc: Exception, *, code: str, calls_started: bool, errors: list[ControlledToolError]
) -> str | None:
    """Summarize typed sandbox failures without returning its source or traceback.

    CodeMode wraps Monty's failure in ModelRetry and then ToolRetryError. The
    typed cause survives. For compiler failures, only the diagnostic code and
    source position are extracted from the rendered report.
    A snippet can call tools before its failing line; those effects cannot be
    inferred from the local exception and must be inspected before replaying it.

    Compiler diagnostics - a type-check rejection or a syntax error - carry their
    structural code and source position in `issues`, so the model sees which name
    is undefined or which line to fix rather than a generic `TypeError`. Runtime
    `NameError` keeps only a safe identifier read from the submitted source; a
    secret smuggled into an exception name or message is never echoed.
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
    if isinstance(cause, MontyTypingError):
        issues = typing_issues(cause.display(), code)
        return tool_error(
            tool=CODE_TOOL,
            code="invalid_arguments",
            execution="not_started",
            message=_validation_message(issues, exception_type),
            recovery="correct_arguments",
            issues=issues,
            error=exc,
        )
    if isinstance(cause, MontySyntaxError):
        issues = syntax_issues(cause)
        return tool_error(
            tool=CODE_TOOL,
            code="invalid_arguments",
            execution="not_started",
            message=_validation_message(issues, exception_type),
            recovery="correct_arguments",
            issues=issues,
            exception_type=exception_type,
            error=exc,
        )
    if isinstance(inner, NameError):
        issues = name_error_issues(inner, cause, code)
        if issues:
            return tool_error(
                tool=CODE_TOOL,
                code="invalid_arguments",
                execution="started",
                message=f"Code execution failed: {exception_type}. {' '.join(i.message for i in issues)}",
                recovery="correct_arguments",
                issues=issues,
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


def _validation_message(issues: list[ToolArgumentIssue], exception_type: str) -> str:
    """The concise correction prompt, from structured issues or a safe type name."""
    if issues:
        return " ".join(issue.message for issue in issues) + " Correct the `code` argument."
    return f"Code validation failed: {exception_type}. Correct the `code` argument."


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
