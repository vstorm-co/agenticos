"""`harness_start`, `harness_prompt`, `harness_stop` and `harness_sessions`.

One idea, four tools: a CLI session - Claude Code, Codex, OpenCode, Gemini CLI
or Pi in the agent's sandbox - that the agent drives across turns as its working
backend, instead of firing one-off tasks at it. The session is the CLI's own: its
id is kept beside the work, so a follow-up prompt continues the same conversation,
with the same files and context the earlier prompts left.

What the model must not choose is closed over: which harness, what it may do,
its model and its key. It chooses the session and what to say to it. Whether
a person says yes first is the binding's approval, like any other tool's.
"""

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from pydantic_ai.exceptions import UserError
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities._failures import steer
from app.agents.capabilities.budget import assert_ambient_budget, record_ambient_usage
from app.agents.capabilities.coding_agent._harness import (
    CLAUDE_TOKEN_PREFIX,
    LABELS,
    Access,
    Harness,
    Usage,
    claude_report,
    codex_report,
    gemini_report,
    invocation,
    live_items,
    opencode_report,
    pi_report,
)
from app.agents.capabilities.coding_agent._narration import Narration
from app.agents.capabilities.coding_agent._task import (
    MAIN_SESSION,
    SANDBOX_FAILURES,
    Outcome,
    clean_up,
    outline,
    run_detached,
)
from app.agents.capabilities.harness._report import HarnessReport, from_coding
from app.agents.capabilities.harness._sessions import (
    forget_session,
    list_sessions,
    remember_session,
    remembered_session,
    task_files,
    valid_session_name,
)

logger = logging.getLogger(__name__)

MISSING_COMMAND = 127
"""A shell's exit code for a program that is not installed."""


def build_harness_toolset(
    *,
    harness: Harness,
    access: Access,
    model: str | None,
    base_url: str | None,
    api_key: str | None,
    timeout_seconds: int,
    model_vendor: str | None = None,
) -> FunctionToolset[Any]:
    """The tools, bound to one harness, its access, its model and its key.

    Everything the model must not choose is closed over. It chooses the
    session and what to say to it.
    """
    label = LABELS[harness]
    # Prompts in one toolset run one at a time, so two prompts to the same
    # session cannot interleave their stored session ids.
    sandbox_tasks = anyio.Lock()

    def mismatch() -> str | None:
        """A credential this harness cannot sign in with, said before anything runs."""
        claude_token = api_key is not None and api_key.startswith(CLAUDE_TOKEN_PREFIX)
        if claude_token and harness != "claude_code":
            return "A Claude subscription token works only for Claude Code. Say so."
        if claude_token and base_url:
            return (
                "A Claude subscription token signs in to Anthropic itself, not to a "
                "gateway. Say that the endpoint needs clearing."
            )
        return None

    async def harness_start(ctx: RunContext[Any], prompt: str, session: str = MAIN_SESSION) -> str:
        """Open a named harness session with a first prompt, and keep it open.

        The harness is a separate agent with its own tools: it reads the code, searches it and - when this agent may change
        code - edits files and runs commands such as tests, then answers. The
        person watches it work. Open one session per line of work and keep
        prompting it, rather than starting over for every question: the
        session remembers what its earlier prompts read and changed.

        Args:
            prompt: What the session should do first, in full: the goal, the
                files or area it concerns, constraints, and how to check the
                result. The harness sees nothing of this conversation but this
                text.
            session: Which session to open, by a short lower-case name such as
                `main`, `api` or `review`. If a session by this name is already
                open, this starts it over.

        Returns:
            JSON with `session`, `outcome` (`completed`, `failed` or
            `timed_out`), `answer` - what it found or did, in the harness's
            words - `files_changed` and `steps`, what it read and ran. Answer
            the person from `answer`, and keep prompting this session for
            follow-ups.
        """
        return await _prompt(ctx, session, prompt, fresh=True)

    async def harness_prompt(ctx: RunContext[Any], prompt: str, session: str = MAIN_SESSION) -> str:
        """Send a follow-up prompt to a named harness session.

        The session continues where its earlier prompts left off: the same
        files, the same context, the same harness. Use this for the next step
        of work already under way, not for something unrelated - that gets its
        own session.

        Args:
            prompt: The next thing to say to the session: a follow-up question,
                a correction, or the next step of the work.
            session: Which session to prompt, by the name it was opened with.

        Returns:
            JSON with `session`, `outcome`, `answer`, `files_changed` and
            `steps`, as `harness_start` returns. Answer the person from
            `answer`.
        """
        if not valid_session_name(session):
            return steer(
                ctx,
                "Name the session in lower case letters, digits, `-` or `_`, up to 40 "
                "characters, such as `main` or `api`.",
            )
        if await remembered_session(ctx, harness, session) is None:
            return steer(
                ctx,
                f"No harness session named `{session}` is open in this conversation "
                "yet. Open it with harness_start first.",
            )
        return await _prompt(ctx, session, prompt, fresh=False)

    async def harness_stop(ctx: RunContext[Any], session: str = MAIN_SESSION) -> str:
        """Close a named harness session.

        Forgets the session, so a later prompt by this name opens a new one
        instead of continuing it. The harness's own process already exited
        after its last prompt; nothing is left running to stop, and closing a
        session changes no files it worked on.

        Args:
            session: Which session to close, by the name it was opened with.

        Returns:
            JSON with `session` and `stopped` - whether a session by that
            name was open to close.
        """
        if not valid_session_name(session):
            return steer(
                ctx,
                "Name the session in lower case letters, digits, `-` or `_`, up to 40 "
                "characters, such as `main` or `api`.",
            )
        # Under the same lock as a prompt: a stop during an in-flight prompt waits for
        # it, so remember_session cannot re-add the session after it is forgotten.
        async with sandbox_tasks:
            stopped = await forget_session(ctx, session)
        return json.dumps({"session": session, "stopped": stopped is not None, "harness": stopped})

    async def harness_sessions(ctx: RunContext[Any]) -> str:
        """List the harness sessions this conversation has open.

        Use this when the conversation has gone on and it is no longer clear
        which sessions exist, before prompting one by name or opening another.

        Returns:
            JSON with `sessions`, each a `session` name and the `harness`
            backing it. A session stays listed until it is closed.
        """
        sessions = await list_sessions(ctx)
        return json.dumps(
            {"sessions": [{"session": found.name, "harness": found.harness} for found in sessions]}
        )

    async def _prompt(ctx: RunContext[Any], session: str, prompt: str, *, fresh: bool) -> str:
        if not valid_session_name(session):
            return steer(
                ctx,
                "Name the session in lower case letters, digits, `-` or `_`, up to 40 "
                "characters, such as `main` or `api`.",
            )
        if api_key is None:
            # Unreachable once published - the key is required at publish and at
            # build. A retry rather than a crash for a preview built without one.
            return steer(ctx, f"{label} has no API key configured.")
        refused = mismatch()
        if refused is not None:
            return refused
        if not prompt.strip():
            return steer(ctx, "Say what the harness should do in `prompt`.")
        if not ctx.workspace.attached:
            return (
                f"{label} needs a sandbox with a shell, and this agent has none. "
                "Say so rather than trying again."
            )
        await assert_ambient_budget()
        narration = Narration.for_call(ctx.deps, ctx.tool_call_id or uuid.uuid4().hex, harness)
        await narration.started(prompt)
        try:
            async with sandbox_tasks:
                report = await _run(ctx, session, prompt, fresh, narration)
        except BaseException:
            # Stopped, or a bug: either way the panel must not keep spinning, and
            # a cancellation would otherwise cancel the frame that closes it.
            with anyio.CancelScope(shield=True):
                await narration.finished("cancelled")
            raise
        if isinstance(report, str):
            await narration.finished("failed", error=report)
            return report
        await narration.finished(
            "completed" if report.outcome == "completed" else "failed",
            error=None if report.outcome == "completed" else report.answer[:500],
        )
        # `kind` is a default, and dropping defaults dropped it - and it is the
        # one field the console tells a report from a sentence by.
        return json.dumps(
            {
                "session": session,
                "kind": report.kind,
                **report.model_dump(mode="json", exclude_defaults=True),
            }
        )

    async def _run(
        ctx: RunContext[Any],
        session: str,
        prompt: str,
        fresh: bool,
        narration: Narration,
    ) -> HarnessReport | str:
        """One prompt in this conversation's session, or a new one when that is gone."""
        session_id = None if fresh else await remembered_session(ctx, harness, session)
        report = await _attempt(ctx, prompt, session_id, narration)
        if (
            isinstance(report, HarnessReport)
            and session_id
            and report.outcome == "failed"
            and not report.steps
        ):
            # A session the sandbox no longer holds - a fresh container, a session
            # the harness pruned - fails before any step. Once, from nothing.
            report = await _attempt(ctx, prompt, None, narration)
        if isinstance(report, HarnessReport) and report.session_id:
            await remember_session(ctx, harness, report.session_id, session)
        return report

    async def _attempt(
        ctx: RunContext[Any],
        prompt: str,
        session_id: str | None,
        narration: Narration,
    ) -> HarnessReport | str:
        try:
            command = invocation(
                harness,
                access,
                prompt,
                api_key=api_key,
                model=model,
                model_vendor=model_vendor,
                session_id=session_id,
                base_url=base_url,
            )
        except UserError as failed:
            return str(failed)
        files = task_files(uuid.uuid4().hex)

        seen: list[dict[str, Any]] = []

        async def shown(events: list[dict[str, Any]]) -> None:
            # Kept only for what a stopped prompt spent, which an outline still says:
            # whole, they were a second copy of an hour of output.
            seen.extend(outline(event) for event in events)
            for event in events:
                await narration.shown(live_items(harness, event))

        try:
            outcome = await run_detached(
                ctx, command, files, timeout_seconds=timeout_seconds, on_events=shown
            )
        except SANDBOX_FAILURES as failed:
            logger.warning("%s could not run in this sandbox: %s", label, failed)
            if seen:
                # The sandbox went mid-prompt, after the harness had started work:
                # what it spent is spent, as for a prompt that was stopped.
                _book(_spent(seen))
            return f"{label} could not run in this sandbox ({type(failed).__name__})."
        except BaseException:
            # Stopped mid-prompt: the harness has already spent what it spent, and
            # a budget that only heard about finished prompts could be walked past
            # by stopping each one late.
            _book(_spent(seen))
            raise
        finally:
            try:
                await clean_up(ctx, files)
            except SANDBOX_FAILURES:
                logger.debug("A harness prompt's files in %s were already gone", files.events)
        return _reported(outcome)

    def _spent(events: list[dict[str, Any]]) -> Usage:
        if harness == "claude_code":
            return claude_report(events, access=access, base_url=base_url)[1]
        if harness == "codex":
            return codex_report(events, access=access, model=model)[1]
        if harness == "opencode":
            return opencode_report(events, access=access, model=model)[1]
        if harness == "gemini":
            return gemini_report(events, access=access, model=model)[1]
        return pi_report(events, access=access, model=model)[1]

    def _reported(outcome: Outcome) -> HarnessReport | str:
        if outcome.exit_code == MISSING_COMMAND and not outcome.events:
            if harness in ("claude_code", "codex"):
                return (
                    f"{label} is not installed in this sandbox's runtime. The `workbench` "
                    "runtime has it; say that the agent's sandbox needs it."
                )
            # Whether the `workbench` runtime ships the newer CLIs is not
            # established; say only that the sandbox needs it.
            return (
                f"{label} is not installed in this sandbox's runtime. Say that "
                "the agent's sandbox needs it installed."
            )
        if harness == "claude_code":
            report, usage = claude_report(outcome.events, access=access, base_url=base_url)
        elif harness == "codex":
            report, usage = codex_report(outcome.events, access=access, model=model)
        elif harness == "opencode":
            report, usage = opencode_report(outcome.events, access=access, model=model)
        elif harness == "gemini":
            report, usage = gemini_report(outcome.events, access=access, model=model)
        else:
            report, usage = pi_report(outcome.events, access=access, model=model)
        _book(usage)
        converted = from_coding(report)
        if outcome.timed_out:
            return converted.model_copy(
                update={
                    "outcome": "timed_out",
                    "answer": f"{label} was stopped after {timeout_seconds // 60} minutes. "
                    "Send a narrower prompt, or split it.",
                }
            )
        if converted.outcome == "failed" and not outcome.events and outcome.stderr.strip():
            # Nothing parsed and something printed: a refused key, a bad flag. The
            # last lines say which, and are the harness's own words.
            return converted.model_copy(update={"answer": outcome.stderr.strip()[-2000:]})
        return converted

    tools: list[Callable[..., Awaitable[str]]] = [
        harness_start,
        harness_prompt,
        harness_stop,
        harness_sessions,
    ]
    return FunctionToolset(tools)


UNREPORTED = "harness:unreported"
"""What a prompt is booked as when the harness ended before saying what it spent."""


def _book(usage: Usage) -> None:
    """Put each model the session ran on the run's ledger, priced by its tokens.

    A prompt that failed, timed out or was stopped before the harness reported
    its usage may still have spent tokens: it is booked as one unpriced call, so
    the run's cost says it is a floor rather than reading as complete.
    """
    if not usage.by_model:
        record_ambient_usage(UNREPORTED, RequestUsage(), provider=usage.provider)
    for model_name, spent in usage.by_model.items():
        record_ambient_usage(model_name, spent, provider=usage.provider)
