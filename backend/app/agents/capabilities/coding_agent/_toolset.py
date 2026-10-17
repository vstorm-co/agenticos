"""`plan_code_change` and `apply_code_change`, and the text the model reads about them.

Each call runs the chosen harness once, headless, in the run's sandbox, and waits
for it: the workspace runs a command to completion, so the harness's steps reach
the conversation when it finishes rather than as it goes. Its events are written
to a file beside the work and read back, because a session that reads a large
repository prints more than a command's output may carry.

The split into two tools is the approval model. Planning reads, so it runs
unattended; applying writes and runs commands, so it is side-effecting and the one
to put behind the platform's approval gate - one decision per change, with the
plan the person can read in the same conversation, rather than a prompt per file.
Applying can continue the planning session, so the harness keeps what it learned.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic_ai.exceptions import UserError
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.workspaces import WorkspaceError, WorkspaceTimeoutError

from app.agents.capabilities._failures import steer
from app.agents.capabilities.budget import assert_ambient_budget, record_ambient_usage
from app.agents.capabilities.coding_agent._harness import (
    LABELS,
    Harness,
    Mode,
    Usage,
    claude_report,
    codex_report,
    invocation,
    read_events,
)

logger = logging.getLogger(__name__)

LOG_DIR = ".agenticos"
"""Where a task's events are written while it runs, and removed from afterwards."""

MISSING_COMMAND = 127
"""A shell's exit code for a program that is not installed."""


def build_coding_toolset(
    *,
    harness: Harness,
    model: str | None,
    base_url: str | None,
    api_key: str | None,
    timeout_seconds: int,
) -> FunctionToolset[Any]:
    """The two tools, bound to one harness, its model and its key.

    Everything the model must not choose is closed over. It chooses the task and
    whether to continue a session.
    """
    label = LABELS[harness]

    async def run(ctx: RunContext[Any], mode: Mode, task: str, session_id: str | None) -> str:
        if api_key is None:
            # Unreachable once published - the key is required at publish and at
            # build. A retry rather than a crash for a preview built without one.
            return steer(ctx, f"{label} has no API key configured.")
        if not task.strip():
            return steer(ctx, "Describe the task in `task`: what to change or find, and where.")
        if not ctx.workspace.attached:
            return (
                f"{label} needs a sandbox with a shell, and this agent has none. "
                "Say so rather than trying again."
            )
        await assert_ambient_budget()
        command = invocation(
            harness,
            mode,
            task,
            api_key=api_key,
            model=model,
            session_id=session_id,
            base_url=base_url,
        )
        name = uuid.uuid4().hex
        log, errors = f"{LOG_DIR}/{name}.jsonl", f"{LOG_DIR}/{name}.err"
        timed_out = False
        try:
            await ctx.workspace.make_dir(LOG_DIR)
            # The redirections are the point; every word on the line is quoted.
            result = await ctx.workspace.run(  # noqa: S604
                command.shell_line(log, errors),
                shell=True,
                env=command.env,
                timeout=timeout_seconds,
            )
            exit_code: int | None = result.exit_code
        except WorkspaceTimeoutError:
            timed_out, exit_code = True, None
        # The sandboxd client raises its HTTP error unmapped when the service
        # refuses to open a session - a runtime still building answers 409 - so
        # that is a sandbox this task could not run in, like the two above.
        except (UserError, WorkspaceError, httpx.HTTPError) as failed:
            logger.warning("%s could not run in the workspace: %s", label, failed)
            return f"{label} could not run in this sandbox ({type(failed).__name__})."
        try:
            events = read_events(await _read(ctx, log))
            stderr = await _read(ctx, errors)
        finally:
            await _remove(ctx, log, errors)

        if exit_code == MISSING_COMMAND and not events:
            return (
                f"{label} is not installed in this sandbox's runtime. The `workbench` "
                "runtime has it; say that the agent's sandbox needs it."
            )
        if harness == "claude_code":
            report, usage = claude_report(events, mode=mode, base_url=base_url)
        else:
            report, usage = codex_report(events, mode=mode, model=model)
        _book(usage)
        if timed_out:
            report = report.model_copy(
                update={
                    "outcome": "timed_out",
                    "answer": f"{label} was stopped after {timeout_seconds // 60} minutes. "
                    "Continue the session with a narrower task, or split it.",
                }
            )
        elif report.outcome == "failed" and not events and stderr.strip():
            # Nothing parsed and something printed: a refused key, a bad flag. The
            # last lines say which, and are the harness's own words.
            report = report.model_copy(update={"answer": stderr.strip()[-2000:]})
        return report.model_dump_json(exclude_defaults=True)

    async def plan_code_change(
        ctx: RunContext[Any], task: str, session_id: str | None = None
    ) -> str:
        """Ask the coding agent to study the code and plan a change, without changing anything.

        Use this first for any change to code in the sandbox, and to answer
        questions about that code: the coding agent reads the files, may run
        read-only commands, and answers with what it found or the plan it would
        follow. Nothing is written. Show the person the plan before you apply it.

        Args:
            task: What to change or find out, in full: the goal, the files or
                area it concerns, and any constraint. The coding agent sees
                nothing of this conversation but this text.
            session_id: The `session_id` of an earlier call, to continue that
                session with what it already learned. Omit it to start fresh.

        Returns:
            JSON with `outcome` (`completed`, `failed` or `timed_out`), `answer` -
            the plan or the finding, in the coding agent's words - `session_id`
            to continue with, and `steps`, what it read and ran. The person sees
            the steps; answer from `answer`.
        """
        return await run(ctx, "plan", task, session_id)

    async def apply_code_change(
        ctx: RunContext[Any], task: str, session_id: str | None = None
    ) -> str:
        """Have the coding agent make a change in the sandbox: edit files and run commands.

        Use this once the person has agreed to a plan, passing the planning
        call's `session_id` so the change follows what was planned. The coding
        agent may edit any file in the sandbox and run any command there, such
        as tests.

        Args:
            task: What to do, in full - usually "apply the plan" plus anything
                the person added. The coding agent sees nothing of this
                conversation but this text and its own session.
            session_id: The `session_id` from `plan_code_change` or an earlier
                change, to continue that session. Omit it to start fresh.

        Returns:
            JSON with `outcome`, `answer` - what was done, in the coding agent's
            words - `files_changed`, `steps` and `session_id`. A `failed` or
            `timed_out` outcome may still have changed files; say which.
        """
        return await run(ctx, "apply", task, session_id)

    tools: list[Callable[..., Awaitable[str]]] = [plan_code_change, apply_code_change]
    return FunctionToolset(tools)


def _book(usage: Usage) -> None:
    """Put each model the session ran on the run's ledger, priced by its tokens."""
    for model_name, spent in usage.by_model.items():
        record_ambient_usage(model_name, spent, provider=usage.provider)


async def _read(ctx: RunContext[Any], path: str) -> str:
    try:
        return (await ctx.workspace.read_bytes(path)).decode("utf-8", errors="replace")
    except (FileNotFoundError, WorkspaceError):
        return ""


async def _remove(ctx: RunContext[Any], *paths: str) -> None:
    for path in paths:
        try:
            await ctx.workspace.remove(path)
        except (FileNotFoundError, WorkspaceError):
            logger.debug("A coding agent's log %s was already gone", path)
