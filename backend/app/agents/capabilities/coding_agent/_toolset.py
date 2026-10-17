"""`run_coding_agent`, and the text the model reads about it.

One tool, because there is one thing to do: hand a task to Claude Code or Codex
and let it work. What it may do there - read and answer, or change files and run
commands - is the binding's `access`, decided by whoever built the agent rather
than chosen by the model call by call, and whether a person says yes first is
the binding's approval, like any other tool's.

A conversation's tasks continue one harness session: the session id is kept in
the sandbox beside the work, so the second task in a chat knows what the first
read without the model carrying ids around. `fresh_session` starts over.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Protocol
from uuid import UUID

import anyio
import httpx
from pydantic_ai.exceptions import UserError
from pydantic_ai.providers.openai_codex import OpenAICodexCredentials
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.workspaces import WorkspaceError

from app.agents.capabilities._failures import steer
from app.agents.capabilities.budget import assert_ambient_budget, record_ambient_usage
from app.agents.capabilities.coding_agent._harness import (
    CLAUDE_TOKEN_PREFIX,
    LABELS,
    Access,
    CodingReport,
    Harness,
    Usage,
    claude_report,
    codex_auth_file,
    codex_report,
    invocation,
    live_items,
    rotated_sign_in,
)
from app.agents.capabilities.coding_agent._narration import Narration
from app.agents.capabilities.coding_agent._task import (
    Outcome,
    clean_up,
    remember_session,
    remembered_session,
    run_detached,
    task_files,
)
from app.core.exceptions import BadRequestError

logger = logging.getLogger(__name__)

RUN_DESCRIPTION = (
    "Hand a software task to the coding agent, which works on it in the sandbox until done."
)

MISSING_COMMAND = 127
"""A shell's exit code for a program that is not installed."""

AUTH_ENV = "AGENTICOS_CODEX_AUTH"
HOME_ENV = "CODEX_HOME"
SESSIONS_ENV = "AGENTICOS_CODEX_SESSIONS"
WRITE_AUTH = (
    f'umask 077 && mkdir -p "${HOME_ENV}" "${SESSIONS_ENV}"'
    f' && ln -sfn "${SESSIONS_ENV}" "${HOME_ENV}/sessions"'
    f' && printf "%s" "${AUTH_ENV}" > "${HOME_ENV}/auth.json"'
    f' && if [ -f "$HOME/.codex/config.toml" ]; then cp "$HOME/.codex/config.toml" "${HOME_ENV}/"; fi'
)
"""Codex's sign-in, written where the CLI reads it - outside the workspace.

Into a Codex home of this one task's own (`CODEX_HOME`), not the sandbox
user's one `~/.codex` and not one per conversation: a sandbox runs several
tasks at once - two turns of one shared project chat among them - and one
shared `auth.json` let a task overwrite another's sign-in and save its rotated
tokens into the wrong secret. The sessions Codex resumes are the
conversation's, so its `sessions` directory is linked in from one the
conversation keeps across tasks. The configuration the runtime ships is
copied in beside it.

Passed through the environment of this one command, never on a command line,
and kept out of the working directory so the file tools and the file browser
never list it. Removed again, home and all, by `READ_AUTH` once the task is over.
"""
READ_AUTH = f'cat "${HOME_ENV}/auth.json" 2>/dev/null; rm -rf "${HOME_ENV}"'

CODEX_HOMES = "/tmp/agenticos-codex"  # noqa: S108
"""Where each conversation's Codex sessions, and each task's home, are made - outside any workspace."""


class CodexSignIn(Protocol):
    """A ChatGPT sign-in Codex can run on, and who may hand it to Codex.

    The vault's in production (`VaultCodexCredentials`).
    """

    async def load(self) -> OpenAICodexCredentials: ...

    async def save(self, credentials: OpenAICodexCredentials) -> None: ...

    async def visible_to(self, user_id: UUID) -> bool: ...


SignIn = Callable[[UUID], CodexSignIn]

_SANDBOX_FAILURES = (UserError, WorkspaceError, httpx.HTTPError)
"""What the sandbox raises when it cannot run a command at all.

The sandboxd client raises its HTTP error unmapped when the service refuses to
open a session - a runtime still building answers 409 - so that is a sandbox the
task could not run in, like the other two.
"""


def build_coding_toolset(
    *,
    harness: Harness,
    access: Access,
    model: str | None,
    base_url: str | None,
    api_key: str | None,
    timeout_seconds: int,
    sign_in: SignIn | None = None,
) -> FunctionToolset[Any]:
    """The tool, bound to one harness, its access, its model and its key.

    Everything the model must not choose is closed over. It chooses the task and
    whether to start the session over.
    """
    label = LABELS[harness]

    def mismatch() -> str | None:
        """A credential this harness cannot sign in with, said before anything runs."""
        claude_token = api_key is not None and api_key.startswith(CLAUDE_TOKEN_PREFIX)
        if sign_in is not None and harness != "codex":
            return "A ChatGPT sign-in works only for Codex. Say that the key needs changing."
        if claude_token and harness != "claude_code":
            return "A Claude subscription token works only for Claude Code. Say so."
        if claude_token and base_url:
            return (
                "A Claude subscription token signs in to Anthropic itself, not to a "
                "gateway. Say that the endpoint needs clearing."
            )
        return None

    async def run_coding_agent(ctx: RunContext[Any], task: str, fresh_session: bool = False) -> str:
        """Hand a software task to the coding agent, which works on it in the sandbox until done.

        The coding agent (Claude Code or Codex) is a separate agent with its own
        tools: it reads the code, searches it and - when this agent may change
        code - edits files and runs commands such as tests, then answers. The
        person watches it work. Hand it whole tasks rather than single steps,
        and say what done looks like.

        Args:
            task: The task in full: the goal, the files or area it concerns,
                constraints, and how to check the result. The coding agent sees
                nothing of this conversation but this text and its own earlier
                tasks here.
            fresh_session: Start a new session instead of continuing the one
                this conversation's earlier tasks used. Leave it off unless the
                earlier work is unrelated or the session went wrong.

        Returns:
            JSON with `outcome` (`completed`, `failed` or `timed_out`), `answer` -
            what it found or did, in the coding agent's words - `files_changed`
            and `steps`, what it read and ran. Answer the person from `answer`.
        """
        if api_key is None and sign_in is None:
            # Unreachable once published - the key is required at publish and at
            # build. A retry rather than a crash for a preview built without one.
            return steer(ctx, f"{label} has no API key configured.")
        refused = mismatch()
        if refused is not None:
            return refused
        if not task.strip():
            return steer(ctx, "Describe the task in `task`: what to change or find, and where.")
        if not ctx.workspace.attached:
            return (
                f"{label} needs a sandbox with a shell, and this agent has none. "
                "Say so rather than trying again."
            )
        await assert_ambient_budget()
        narration = Narration.for_call(ctx.deps, ctx.tool_call_id or uuid.uuid4().hex, harness)
        await narration.started(task)
        try:
            report = await signed_in(ctx, task, fresh_session, narration)
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
            {"kind": report.kind, **report.model_dump(mode="json", exclude_defaults=True)}
        )

    async def signed_in(
        ctx: RunContext[Any], task: str, fresh_session: bool, narration: Narration
    ) -> CodingReport | str:
        """The task, with Codex's ChatGPT sign-in put in place first when it uses one."""
        if sign_in is None:
            return await continued(ctx, task, fresh_session, narration, home=None)
        organization_id = getattr(ctx.deps, "organization_id", None)
        if not isinstance(organization_id, UUID):
            return f"{label} on a ChatGPT sign-in runs only inside an organization."
        source = sign_in(organization_id)
        # The tokens are written where Codex reads them, and anything Codex runs
        # can read them there too: a task - or a repository's text it obeys - can
        # print them. So only for somebody who may see the sign-in in the vault
        # themselves; running the agent must not be a way to somebody else's.
        person = _person(ctx.deps)
        if person is None or not await source.visible_to(person):
            return (
                f"{label} runs on a ChatGPT sign-in only for somebody who may see that "
                "sign-in in the vault. Say that they need their own, or one shared with them."
            )
        conversation = (
            f"{CODEX_HOMES}/{getattr(ctx.deps, 'conversation_id', None) or uuid.uuid4().hex}"
        )
        home = f"{conversation}/{uuid.uuid4().hex}"
        try:
            written = await source.load()
            await ctx.workspace.run(  # noqa: S604
                WRITE_AUTH,
                shell=True,
                env={
                    AUTH_ENV: codex_auth_file(written),
                    HOME_ENV: home,
                    SESSIONS_ENV: f"{conversation}/sessions",
                },
                timeout=60,
            )
        except BadRequestError as gone:
            return f"{gone.message}. Say that the sign-in needs choosing again."
        except _SANDBOX_FAILURES as failed:
            logger.warning("%s could not sign in in the workspace: %s", label, failed)
            return f"{label} could not run in this sandbox ({type(failed).__name__})."
        try:
            return await continued(ctx, task, fresh_session, narration, home=home)
        finally:
            await _keep_rotated(ctx, source, written, home=home)

    async def continued(
        ctx: RunContext[Any],
        task: str,
        fresh_session: bool,
        narration: Narration,
        *,
        home: str | None,
    ) -> CodingReport | str:
        """The task in this conversation's session, or a new one when that is gone."""
        session_id = None if fresh_session else await remembered_session(ctx, harness)
        report = await attempt(ctx, task, session_id, narration, home=home)
        if (
            isinstance(report, CodingReport)
            and session_id
            and report.outcome == "failed"
            and not report.steps
        ):
            # A session the sandbox no longer holds - a fresh container, a session
            # the harness pruned - fails before any step. Once, from nothing.
            report = await attempt(ctx, task, None, narration, home=home)
        if isinstance(report, CodingReport) and report.session_id:
            await remember_session(ctx, harness, report.session_id)
        return report

    async def attempt(
        ctx: RunContext[Any],
        task: str,
        session_id: str | None,
        narration: Narration,
        *,
        home: str | None,
    ) -> CodingReport | str:
        command = invocation(
            harness,
            access,
            task,
            api_key=api_key,
            model=model,
            session_id=session_id,
            base_url=base_url,
        )
        if home is not None:
            # The sign-in is this task's, and the sessions it resumes the conversation's.
            command = replace(command, env={**command.env, HOME_ENV: home})
        files = task_files(uuid.uuid4().hex)

        async def shown(events: list[dict[str, Any]]) -> None:
            for event in events:
                await narration.shown(live_items(harness, event))

        try:
            outcome = await run_detached(
                ctx, command, files, timeout_seconds=timeout_seconds, on_events=shown
            )
        except _SANDBOX_FAILURES as failed:
            logger.warning("%s could not run in the workspace: %s", label, failed)
            return f"{label} could not run in this sandbox ({type(failed).__name__})."
        finally:
            try:
                await clean_up(ctx, files)
            except _SANDBOX_FAILURES:
                logger.debug("A coding task's files in %s were already gone", files.events)
        return reported(outcome)

    def reported(outcome: Outcome) -> CodingReport | str:
        if outcome.exit_code == MISSING_COMMAND and not outcome.events:
            return (
                f"{label} is not installed in this sandbox's runtime. The `workbench` "
                "runtime has it; say that the agent's sandbox needs it."
            )
        if harness == "claude_code":
            report, usage = claude_report(outcome.events, access=access, base_url=base_url)
        else:
            report, usage = codex_report(outcome.events, access=access, model=model)
        _book(usage)
        if outcome.timed_out:
            return report.model_copy(
                update={
                    "outcome": "timed_out",
                    "answer": f"{label} was stopped after {timeout_seconds // 60} minutes. "
                    "Hand it a narrower task, or split this one.",
                }
            )
        if report.outcome == "failed" and not outcome.events and outcome.stderr.strip():
            # Nothing parsed and something printed: a refused key, a bad flag. The
            # last lines say which, and are the harness's own words.
            return report.model_copy(update={"answer": outcome.stderr.strip()[-2000:]})
        return report

    tools: list[Callable[..., Awaitable[str]]] = [run_coding_agent]
    return FunctionToolset(tools)


async def _keep_rotated(
    ctx: RunContext[Any], source: CodexSignIn, written: OpenAICodexCredentials, *, home: str
) -> None:
    """Take the sign-in back out of the sandbox, keeping whatever Codex refreshed it to.

    A refresh token is single-use, so a pair Codex rotated during the task and
    left only in the sandbox would leave the vault holding a spent one - and the
    next task, or the next model request on the same sign-in, refused.
    """
    try:
        result = await ctx.workspace.run(  # noqa: S604
            READ_AUTH, shell=True, env={HOME_ENV: home}, timeout=60
        )
    except _SANDBOX_FAILURES as failed:
        logger.warning("Codex's sign-in could not be read back from the sandbox: %s", failed)
        return
    rotated = rotated_sign_in(result.stdout, written)
    if rotated is not None:
        await source.save(rotated)


def _person(deps: object) -> UUID | None:
    """Who the run is for, when it is somebody signed in."""
    user_id = getattr(deps, "user_id", None)
    try:
        return UUID(str(user_id)) if user_id else None
    except ValueError:
        return None


def _book(usage: Usage) -> None:
    """Put each model the session ran on the run's ledger, priced by its tokens."""
    for model_name, spent in usage.by_model.items():
        record_ambient_usage(model_name, spent, provider=usage.provider)
