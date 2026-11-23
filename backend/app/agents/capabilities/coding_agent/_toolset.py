"""`run_coding_agent`, and the text the model reads about it.

One tool, because there is one thing to do: hand a task to Claude Code or Codex
and let it work. What it may do there - read and answer, or change files and run
commands - is the binding's `access`, decided by whoever built the agent rather
than chosen by the model call by call, and whether a person says yes first is
the binding's approval, like any other tool's.

A conversation's tasks continue a harness session by name: the session id is kept
beside the work, so the second task in a chat knows what the first read without
the model carrying ids around. Several named sessions run side by side - two
projects, or both harnesses on the person's computer - and `fresh_session` starts
one over.
"""

import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from dataclasses import replace
from typing import Any, Literal
from uuid import UUID

import anyio
from pydantic import ValidationError
from pydantic_ai.exceptions import UserError
from pydantic_ai.providers.openai_codex import OpenAICodexCredentials
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RequestUsage
from pydantic_ai.workspaces import Workspace, WorkspaceError, WorkspaceUnavailableError
from sqlalchemy.exc import SQLAlchemyError

from app.agents.audience import RunAudience
from app.agents.capabilities._failures import steer
from app.agents.capabilities.budget import assert_ambient_budget, record_ambient_usage
from app.agents.capabilities.coding_agent import _changes
from app.agents.capabilities.coding_agent._acp import (
    AcpError,
    CredentialProbe,
    DevicePipe,
    private_state_scope,
    run_task,
)
from app.agents.capabilities.coding_agent._harness import (
    CLAUDE_TOKEN_PREFIX,
    LABELS,
    Access,
    AcpHarness,
    CodingReport,
    Harness,
    LiveItem,
    Said,
    StepEnded,
    StepStarted,
    Usage,
    claude_report,
    codex_auth_file,
    codex_report,
    invocation,
    live_items,
    rotated_sign_in,
)
from app.agents.capabilities.coding_agent._narration import Narration
from app.agents.capabilities.coding_agent._personal import (
    CodexSignIn,
    PersonalCodingExecutor,
    SignIn,
)
from app.agents.capabilities.coding_agent._redaction import (
    redact_changes,
    redact_report,
    redact_text,
)
from app.agents.capabilities.coding_agent._task import (
    MAIN_SESSION,
    SANDBOX_FAILURES,
    SESSION_NAME,
    Outcome,
    clean_up,
    outline,
    remember_session,
    remembered_session,
    run_detached,
    task_files,
)
from app.agents.capabilities.sandbox._project import ProjectWorkspacePort
from app.agents.capabilities.sandbox._recording import RecordingWorkspace
from app.agents.deps import AgentDeps
from app.agents.model_context import check_model_context
from app.agents.pi_keys import NativeRuntimeKey
from app.agents.runtime_questions import RuntimeQuestionRequest, RuntimeQuestionResponse
from app.core.exceptions import AppException, BadRequestError
from app.db.session import get_db_context
from app.services.coding_task_changes import CodingTaskChangeService
from app.services.device_hub import (
    DeviceCallFailed,
    DeviceCallTimedOut,
    DeviceUnavailable,
    DeviceWorkspace,
)

logger = logging.getLogger(__name__)

RUN_DESCRIPTION = (
    "Hand a software task to the coding agent, which works on it in the sandbox until done."
)

LOCAL_DOC = """Hand a software task to the coding agent, which works on it on the person's computer until done.

        The coding agent (Claude Code or Codex) is a separate agent with its own tools: it
        reads the code, searches it and - when this agent may change code - edits files and
        runs commands such as tests, then answers. The person watches it work. Hand it whole
        tasks rather than single steps, and say what done looks like.

        Args:
            task: The task in full: the goal, the files or area it concerns, constraints, and
                how to check the result. Later tasks in this conversation resume this
                agent's session for the same folder and access policy.
            session: A lower-case session name, 1-40 letters, digits, hyphens or
                underscores, starting with a letter or digit. Use distinct names
                for independent parallel tasks; the same name resumes earlier work.
            fresh_session: Start this named session over instead of resuming it.
            harness: `claude_code` or `codex`; empty uses the configured harness.
                The selected harness must be installed and signed in on this computer.
            folder: Relative or absolute folder inside the chat's approved folder.
                Empty or `.` uses the chat's folder. This never grants new access.

        Returns:
            JSON with `outcome` (`completed`, `failed` or `timed_out`), `answer` - what it
            found or did, in the coding agent's words - `files_changed` and `steps`, what it
            read and ran. Answer the person from `answer`.
        """

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
never list it. Removed again, home and all, by `READ_AUTH` once the task is over -
with the sessions too (`DISCARD_ENV`) for a run in no conversation, which nothing
will ever resume.
"""
DISCARD_ENV = "AGENTICOS_CODEX_DISCARD"
READ_AUTH = (
    f'cat "${HOME_ENV}/auth.json" 2>/dev/null; auth_read_status=$?; rm -rf "${HOME_ENV}"'
    f' ${{{DISCARD_ENV}:+"${DISCARD_ENV}"}} || exit $?; exit "$auth_read_status"'
)

CODEX_HOMES = "/tmp/agenticos-codex"  # noqa: S108
"""Where each conversation's Codex sessions, and each task's home, are made - outside any workspace."""


RunsOn = Literal["sandbox", "personal_sandbox", "this_computer"]
"""Where a task runs: the agent's sandbox, or the folder the person chose on their computer."""

_LOCAL_FAILURES = (WorkspaceError, DeviceCallFailed, DeviceUnavailable, DeviceCallTimedOut, OSError)
"""What reaching the person's computer raises; each says why in words."""


def build_coding_toolset(
    *,
    harness: Harness,
    access: Access,
    model: str | None,
    base_url: str | None,
    api_key: str | None,
    timeout_seconds: int,
    effort: str | None = None,
    sign_in: SignIn | None = None,
    shared_sandbox: bool = False,
    runs_on: RunsOn = "sandbox",
    personal_executor: PersonalCodingExecutor | None = None,
    personal_isolated: bool = False,
    capture_changes: bool = True,
) -> FunctionToolset[Any]:
    """The tool, bound to one harness, its access, its model and its key.

    Everything the model must not choose is closed over. It chooses the task and
    whether to start the session over.
    """
    label = LABELS[harness]
    # The tool's own `harness` argument shadows this one inside it.
    configured = harness
    # Snapshot diffs cover the entire sandbox. Keep this toolset's tasks sequential
    # there, including reads that may execute commands; local ACP sessions have
    # no shared snapshot and remain parallel.
    sandbox_tasks = anyio.Lock()

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

    async def run_coding_agent(
        ctx: RunContext[Any],
        task: str,
        session: str = MAIN_SESSION,
        fresh_session: bool = False,
        harness: Literal["claude_code", "codex"] | None = None,
        folder: str | None = None,
    ) -> str:
        """Hand a software task to the coding agent, which works on it in the sandbox until done.

        The coding agent (Claude Code or Codex) is a separate agent with its own
        tools: it reads the code, searches it and - when this agent may change
        code - edits files and runs commands such as tests, then answers. The
        person watches it work. Hand it whole tasks rather than single steps,
        and say what done looks like.

        Args:
            task: The task in full: the goal, the files or area it concerns,
                constraints, and how to check the result. The coding agent sees
                this task and the allowed source files. Include the decisions and
                context it needs; named personal cloud sessions retain earlier work.
            session: Which session to work in, by a short lower-case name such as
                `main`, `api` or `review`. The same name continues that session's
                earlier work; a new name opens another. Local sessions run side by side; sandbox tasks queue to keep
                their workspace snapshots separate. Named personal cloud sessions retain
                separate files and histories, and may run in parallel on different accounts.
                Tasks using the same personal account wait in a bounded queue.
                Use distinct names for independent work.
            fresh_session: Start this session over instead of continuing it. Leave
                it off unless its earlier work is unrelated or it went wrong.
                Personal cloud keeps the named session's files when its history resets.
            harness: `claude_code` or `codex`, to choose the coding agent for this
                task in personal cloud mode or on this computer. Each uses the person's
                own account for that harness. Empty uses the configured default.
                Organization-sandbox mode uses only the configured harness.
            folder: A folder inside the chat's folder for this session to work in,
                relative or absolute - one project of several. Only on the
                person's computer. Empty uses the chat's folder.

        Returns:
            JSON with `outcome` (`completed`, `failed` or `timed_out`), `answer` -
            what it found or did, in the coding agent's words - `files_changed`
            and `steps`, what it read and ran. Answer the person from `answer`.
        """
        if not SESSION_NAME.fullmatch(session):
            return steer(
                ctx,
                "Name the session in lower case letters, digits, `-` or `_`, up to 40 "
                "characters, such as `main` or `api`.",
            )
        chosen = harness or configured
        if runs_on != "this_computer":
            if runs_on == "sandbox" and chosen != configured:
                return steer(
                    ctx,
                    f"This agent's sandbox is configured for {label} only. To choose either "
                    "harness per task, use personal cloud coding or this computer. "
                    "Leave `harness` empty here.",
                )
            if folder is not None:
                return steer(
                    ctx,
                    "`folder` chooses a project on the person's computer; this agent works in "
                    "its sandbox. Leave it empty and name the folder in the task.",
                )
        if runs_on == "personal_sandbox":
            if (
                shared_sandbox
                or isinstance(ctx.workspace.backend, ProjectWorkspacePort)
                or _in_room(ctx.deps)
            ):
                return (
                    "Personal coding accounts cannot run on sources from a shared workspace, "
                    "project or group chat. Copying those files into a private container does "
                    "not make their code trusted. Use a private unshared conversation workspace "
                    "for personal-account work, or the organization's configured coding mode."
                )
            if chosen == "codex" and access == "read_only":
                return steer(
                    ctx,
                    "Codex cannot run read-only inside a container. Use Claude Code for this "
                    "read-only task, or ask the agent's author to change its access policy.",
                )
            if personal_executor is None:
                return steer(
                    ctx,
                    "Personal coding accounts require a task you start in authenticated chat, with a server sandbox. Scheduled jobs and channel publishers cannot borrow your account.",
                )
            if not task.strip():
                return steer(ctx, "Describe the coding task first.")
            await check_model_context()
            await assert_ambient_budget()
            try:
                async with personal_executor.session(
                    ctx, harness=chosen, timeout_seconds=timeout_seconds, session=session
                ) as personal:
                    isolated = build_coding_toolset(
                        harness=chosen,
                        access=access,
                        model=model if chosen == configured else None,
                        base_url=None,
                        api_key=personal.api_key.get_secret_value() if personal.api_key else None,
                        timeout_seconds=timeout_seconds,
                        effort=effort if chosen == configured else None,
                        sign_in=personal.sign_in,
                        shared_sandbox=False,
                        personal_isolated=True,
                        capture_changes=False,
                    )
                    private_ctx = replace(
                        ctx,
                        workspace=personal.workspace,
                        deps=replace(ctx.deps, subagent_events=None),
                    )
                    baseline = (
                        await _changes.begin(private_ctx)
                        if access == "edit" and _keeps_changes(ctx.deps)
                        else None
                    )
                    try:
                        result: object = await isolated.tools["run_coding_agent"].function(
                            private_ctx, task, session=session, fresh_session=fresh_session
                        )
                        if not isinstance(result, str):
                            raise TypeError("The coding tool returned a non-text result")
                        redactions = tuple(
                            secret.get_secret_value() for secret in personal.redactions
                        )
                        if personal.sign_in is not None:
                            refreshed = await personal.sign_in(ctx.deps.organization_id).load()
                            redactions += (refreshed.access_token, refreshed.refresh_token)
                        try:
                            report = redact_report(
                                CodingReport.model_validate_json(result), redactions
                            )
                        except ValidationError:
                            if baseline is not None:
                                await _changes.discard(private_ctx, baseline.store)
                            return redact_text(result, redactions)
                        if baseline is not None:
                            report = await _with_changes(
                                private_ctx, report, baseline, redact_values=redactions
                            )
                        return report.model_copy(
                            update={
                                "account_label": personal.label,
                                "execution": "isolated_task",
                                "base_revision": personal.base_revision,
                                "result_archive": personal.result_archive,
                                "session_name": session,
                                "session_resumed": (
                                    report.session_resumed
                                    if report.session_resumed is not None
                                    else personal.resumed and not fresh_session
                                ),
                            }
                        ).model_dump_json(exclude_defaults=True)
                    finally:
                        if baseline is not None:
                            with anyio.CancelScope(shield=True):
                                await _changes.discard(private_ctx, baseline.store)
            except AppException as error:
                return steer(ctx, error.message)
        if runs_on == "this_computer":
            return await run_local_task(
                ctx,
                task,
                session,
                fresh_session,
                harness or configured,
                folder,
                access=access,
                timeout_seconds=timeout_seconds,
                model=model if harness is None or harness == configured else None,
                effort=effort if harness is None or harness == configured else None,
            )
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
        await check_model_context()
        await assert_ambient_budget()
        narration = Narration.for_call(ctx.deps, ctx.tool_call_id or uuid.uuid4().hex, configured)
        await narration.started(task)
        try:
            async with sandbox_tasks:
                report = await signed_in(ctx, task, session, fresh_session, narration)
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
        ctx: RunContext[Any],
        task: str,
        session: str,
        fresh_session: bool,
        narration: Narration,
    ) -> CodingReport | str:
        """The task, with Codex's ChatGPT sign-in put in place first when it uses one."""
        if sign_in is None:
            return await continued(ctx, task, session, fresh_session, narration, home=None)
        organization_id = getattr(ctx.deps, "organization_id", None)
        if not isinstance(organization_id, UUID):
            return f"{label} on a ChatGPT sign-in runs only inside an organization."
        # In a container other people's runs work in, their tasks run as the
        # same user and can read the tokens wherever they are written; a person's
        # subscription is theirs alone, so it runs only where nobody else does.
        # A group chat is shared the same way whatever the sandbox's scope says:
        # everybody in the room runs in its conversation's container.
        if (
            shared_sandbox
            or isinstance(ctx.workspace.backend, ProjectWorkspacePort)
            or (_in_room(ctx.deps) and not personal_isolated)
        ):
            return (
                f"{label} runs on a ChatGPT sign-in only in a sandbox nobody else's tasks "
                "share, and this one is shared - a project's, a group chat's, or the whole "
                "agent's. Say that the agent needs an OpenAI API key for Codex here."
            )
        source = sign_in(organization_id)
        # The tokens are written where Codex reads them, and anything Codex runs
        # can read them there too: a task - or a repository's text it obeys - can
        # print them. So only for somebody who may see the sign-in in the vault
        # themselves; running the agent must not be a way to somebody else's.
        person = _person(ctx.deps)
        if personal_isolated and person is None and ctx.deps.user_id is not None:
            person = uuid.UUID(ctx.deps.user_id)
        if person is None or not await source.visible_to(person):
            return (
                f"{label} runs on a ChatGPT sign-in only for somebody who may see that "
                "sign-in in the vault. Say that they need their own, or one shared with them."
            )
        conversation_id = getattr(ctx.deps, "conversation_id", None)
        conversation = f"{CODEX_HOMES}/{conversation_id or uuid.uuid4().hex}"
        home = f"{conversation}/{uuid.uuid4().hex}"
        # A run in no conversation leaves sessions nothing will resume.
        discard = {} if conversation_id else {DISCARD_ENV: conversation}
        try:
            written = await source.load()
        except BadRequestError as gone:
            return f"{gone.message}. Say that the sign-in needs choosing again."
        # The cleanup covers the write as well: a write that landed and then
        # failed on its way back would otherwise leave the tokens in the sandbox.
        try:
            try:
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
            except SANDBOX_FAILURES as failed:
                logger.warning("%s could not sign in in the workspace: %s", label, failed)
                return f"{label} could not run in this sandbox ({type(failed).__name__})."
            return await continued(ctx, task, session, fresh_session, narration, home=home)
        finally:
            # A personal task can rotate a single-use refresh token just before
            # Stop. Recover it and remove its auth file before cancellation wins.
            with anyio.CancelScope(shield=personal_isolated):
                await _keep_rotated(
                    ctx, source, written, env={HOME_ENV: home, **discard}, strict=personal_isolated
                )

    async def continued(
        ctx: RunContext[Any],
        task: str,
        session: str,
        fresh_session: bool,
        narration: Narration,
        *,
        home: str | None,
    ) -> CodingReport | str:
        workspace = ctx.workspace
        async with (
            workspace.task_snapshot()
            if isinstance(workspace, RecordingWorkspace)
            else nullcontext()
        ):
            return await captured_task(ctx, task, session, fresh_session, narration, home=home)

    async def captured_task(
        ctx: RunContext[Any],
        task: str,
        session: str,
        fresh_session: bool,
        narration: Narration,
        *,
        home: str | None,
    ) -> CodingReport | str:
        """The task in this conversation's session, or a new one when that is gone.

        Snapshotted before and diffed after when its changes are kept, so the
        report names what the task changed (#2480).
        """
        # A read-only task changes nothing to show; its snapshot would cost time for nothing.
        keeps = capture_changes and access == "edit" and _keeps_changes(ctx.deps)
        baseline = await _changes.begin(ctx) if keeps else None
        try:
            report = await resumed(ctx, task, session, fresh_session, narration, home=home)
        except BaseException:
            with anyio.CancelScope(shield=True):
                if baseline is not None:
                    await _changes.discard(ctx, baseline.store)
            raise
        if baseline is None:
            return (
                await _relative_report(ctx.workspace, report)
                if isinstance(report, CodingReport)
                else report
            )
        if isinstance(report, str):
            await _changes.discard(ctx, baseline.store)
            return report
        # A failed or timed-out task may have changed files too: its diff is kept as well.
        kept = await _with_changes(ctx, report, baseline)
        return kept if kept.changes_id is not None else await _relative_report(ctx.workspace, kept)

    async def resumed(
        ctx: RunContext[Any],
        task: str,
        session: str,
        fresh_session: bool,
        narration: Narration,
        *,
        home: str | None,
    ) -> CodingReport | str:
        session_id = None if fresh_session else await remembered_session(ctx, harness, session)
        report = await attempt(ctx, task, session_id, narration, home=home)
        continued_history = session_id is not None
        if (
            isinstance(report, CodingReport)
            and session_id
            and report.outcome == "failed"
            and not report.steps
        ):
            # A session the sandbox no longer holds - a fresh container, a session
            # the harness pruned - fails before any step. Once, from nothing.
            report = await attempt(ctx, task, None, narration, home=home)
            continued_history = False
        if personal_isolated and isinstance(report, CodingReport):
            report = report.model_copy(update={"session_resumed": continued_history})
        if isinstance(report, CodingReport) and report.session_id:
            await remember_session(ctx, harness, report.session_id, session)
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
        if personal_isolated:
            command = replace(command, supervised=True)
        if home is not None:
            # The sign-in is this task's, and the sessions it resumes the conversation's.
            command = replace(command, env={**command.env, HOME_ENV: home})
        files = task_files(uuid.uuid4().hex)

        seen: list[dict[str, Any]] = []

        async def shown(events: list[dict[str, Any]]) -> None:
            # Kept only for what a stopped task spent, which an outline still says:
            # whole, they were a second copy of an hour of output.
            seen.extend(outline(event) for event in events)
            for event in events:
                await narration.shown(live_items(harness, event))

        try:
            outcome = await run_detached(
                ctx, command, files, timeout_seconds=timeout_seconds, on_events=shown
            )
        except SANDBOX_FAILURES as failed:
            logger.warning("%s could not run in the workspace: %s", label, failed)
            if seen:
                # The sandbox went mid-task, after the harness had started work:
                # what it spent is spent, as for a task that was stopped.
                _book(spent(seen))
            return f"{label} could not run in this sandbox ({type(failed).__name__})."
        except BaseException:
            # Stopped mid-task: the harness has already spent what it spent, and
            # a budget that only heard about finished tasks could be walked past
            # by stopping each one late.
            _book(spent(seen))
            raise
        finally:
            try:
                await clean_up(ctx, files)
            except SANDBOX_FAILURES:
                logger.debug("A coding task's files in %s were already gone", files.events)
        return reported(outcome)

    def spent(events: list[dict[str, Any]]) -> Usage:
        if harness == "claude_code":
            return claude_report(events, access=access, base_url=base_url)[1]
        return codex_report(events, access=access, model=model)[1]

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

    if runs_on == "this_computer":
        # The sandbox contract promises that later tasks continue one session, which a
        # task on this computer does not (each is a new ACP session), so the model is
        # told what is true of this one.
        run_coding_agent.__doc__ = LOCAL_DOC
    tools: list[Callable[..., Awaitable[str]]] = [run_coding_agent]
    return FunctionToolset(tools)


async def run_local_task(
    ctx: RunContext[AgentDeps],
    task: str,
    session: str,
    fresh_session: bool,
    chosen: AcpHarness,
    folder: str | None,
    *,
    access: Access,
    timeout_seconds: int,
    model: str | None = None,
    effort: str | None = None,
    custom_agent_id: str | None = None,
    auth_method: str | None = None,
    credential_probe: CredentialProbe | None = None,
    pi_key: NativeRuntimeKey | None = None,
    platform_tools: bool = False,
) -> str:
    """The task on the person's computer, in the folder they chose, over ACP.

    The agent signs in with its own command on that computer, so there is no
    key here to check and nothing to put in a sandbox - which is also why
    either harness may be chosen per session here, and nowhere else.
    """
    name = LABELS[chosen]
    if not task.strip():
        return steer(ctx, "Describe the task in `task`: what to change or find, and where.")
    workspace = ctx.workspace.backend if ctx.workspace.attached else None
    if not isinstance(workspace, DeviceWorkspace):
        return (
            f"{name} is set to run on the person's computer, and this chat is not working "
            "on one. Say that Work on needs to be set to This computer."
        )
    if not workspace.local_coding_allowed:
        return "A native ACP agent requires this chat to use an approved full-access folder. Choose full access explicitly before starting it."
    try:
        chat_root = await workspace.working_dir()
        root = workspace.subfolder(folder) if folder else chat_root
    except WorkspaceUnavailableError as outside:
        return steer(ctx, f"{outside}. Choose a folder inside it, or leave `folder` empty.")
    await check_model_context()
    await assert_ambient_budget()
    narration = Narration.for_call(ctx.deps, ctx.tool_call_id or uuid.uuid4().hex, chosen)
    await narration.started(task)
    redactions = (pi_key.api_key.get_secret_value(),) if pi_key is not None else ()

    async def shown(items: list[LiveItem]) -> None:
        if not redactions:
            await narration.shown(items)
            return
        screened: list[LiveItem] = []
        for item in items:
            # Native text can split a key across arbitrary chunks; retain only the
            # complete redacted report rather than leaking a partial credential.
            if isinstance(item, StepStarted):
                screened.append(
                    replace(
                        item,
                        key=redact_text(item.key, redactions),
                        step=item.step.model_copy(
                            update={"title": redact_text(item.step.title, redactions)}
                        ),
                    )
                )
            elif isinstance(item, StepEnded):
                screened.append(replace(item, key=redact_text(item.key, redactions)))
        if screened:
            await narration.shown(screened)

    async def questions(request: RuntimeQuestionRequest) -> RuntimeQuestionResponse:
        if any(json.dumps(value)[1:-1] in request.model_dump_json() for value in redactions):
            raise AcpError(
                "The runtime put credential material in a human-input request. No question was shown."
            )
        callback = ctx.deps.runtime_questions
        return (
            await callback(request)
            if callback is not None
            else RuntimeQuestionResponse(cancelled=True)
        )

    native_tools = None
    if platform_tools:
        from app.agents.runtime_tools import RuntimeTools

        native_tools = RuntimeTools(ctx, secrets=redactions)

    identity = ctx.deps
    scope = (
        str(identity.organization_id),
        str(identity.user_id),
        str(identity.agent_id),
        str(identity.conversation_id),
        chosen,
        *(("platform-tools",) if platform_tools else ()),
        access,
        *(() if custom_agent_id is None else (custom_agent_id,)),
        *(() if auth_method is None else (auth_method,)),
        *(() if pi_key is None else (pi_key.provider, pi_key.revision)),
        # The unnamed session keeps the key every conversation used before names.
        *(() if session == MAIN_SESSION and workspace.is_root(root) else (session, root)),
    )
    resume_key = (
        hashlib.sha256(json.dumps(scope).encode()).hexdigest()
        if identity.conversation_id is not None
        else None
    )
    pipe = DevicePipe(
        workspace,
        chosen,
        state_scope=private_state_scope(ctx.deps),
        resume_key=resume_key,
        fresh_session=fresh_session,
        root=root if folder else None,
        custom_agent_id=custom_agent_id,
        runtime_model=model,
        pi_key=pi_key,
        pi_model=model if pi_key is not None else None,
        platform_tools=platform_tools,
    )
    try:
        await check_model_context()
        await pipe.open()
        try:
            with (
                ctx.deps.steering.listen(session)
                if ctx.deps.steering is not None
                else nullcontext(None) as steering
            ):
                if pipe.protocol == "pi_rpc":
                    from app.agents.capabilities.external_acp._pi import run_pi

                    report = await run_pi(
                        pipe,
                        task=task,
                        timeout_seconds=timeout_seconds,
                        shown=shown,
                        previous_session=pipe.session_id,
                        model=model,
                        effort=effort,
                        remember=pipe.remember,
                        runtime_questions=questions if redactions else ctx.deps.runtime_questions,
                        key_provider=pi_key.pi_provider if pi_key is not None else None,
                        platform_tools=native_tools,
                    )
                else:
                    report = await run_task(
                        pipe,
                        harness=chosen,
                        access=access,
                        root=root,
                        task=task,
                        timeout_seconds=timeout_seconds,
                        shown=shown,
                        # A model or reasoning level belongs to the configured harness.
                        model=model,
                        effort=effort,
                        previous_session=pipe.session_id,
                        auth_method=pipe.auth_method or auth_method,
                        model_prefix=pipe.model_prefix,
                        credential_probe=credential_probe,
                        configuration_policy=pipe.configuration_policy,
                        platform_tools=native_tools,
                        remember=pipe.remember,
                        steering=steering,
                        runtime_questions=questions if redactions else ctx.deps.runtime_questions,
                    )
        finally:
            # Failed and cancelled tasks may have spent subscription tokens too.
            _book(Usage())
    except AcpError as failed:
        error = redact_text(failed.message, redactions)
        await narration.finished("failed", error=error[:500])
        return f"{name} could not run on this computer: {error}"
    except _LOCAL_FAILURES as failed:
        error = redact_text(str(failed), redactions)
        await narration.finished("failed", error=error[:500])
        return f"{name} could not run on this computer: {error}"
    except BaseException:
        with anyio.CancelScope(shield=True):
            await narration.finished("cancelled")
        raise
    if pi_key is not None:
        report = redact_report(report, redactions)
        if report.answer:
            await narration.shown([Said(report.answer)])
    await narration.finished(
        "completed" if report.outcome == "completed" else "failed",
        error=None if report.outcome == "completed" else report.answer[:500],
    )
    report = _relative_files(report, chat_root).model_copy(
        update={
            "runtime_name": redact_text(pipe.runtime_name, redactions)
            if pipe.runtime_name
            else None
        }
    )
    return json.dumps(
        {"kind": report.kind, **report.model_dump(mode="json", exclude_defaults=True)}
    )


async def _keep_rotated(
    ctx: RunContext[Any],
    source: CodexSignIn,
    written: OpenAICodexCredentials,
    *,
    env: dict[str, str],
    strict: bool = False,
) -> None:
    """Take the sign-in back out of the sandbox, keeping whatever Codex refreshed it to.

    A refresh token is single-use, so a pair Codex rotated during the task and
    left only in the sandbox would leave the vault holding a spent one - and the
    next task, or the next model request on the same sign-in, refused.
    """
    try:
        result = await ctx.workspace.run(  # noqa: S604
            READ_AUTH, shell=True, env=env, timeout=60
        )
    except SANDBOX_FAILURES as failed:
        if strict:
            raise
        logger.warning("Codex's sign-in could not be read back from the sandbox: %s", failed)
        return
    if strict and result.exit_code != 0:
        raise UserError("Codex could not remove its temporary sign-in from the private sandbox")
    rotated = rotated_sign_in(result.stdout, written, strict=strict)
    if rotated is not None:
        await source.swap(written, rotated)


def _keeps_changes(deps: object) -> bool:
    """Whether a task's change set is kept: in an organization's conversation, where a panel reads it."""
    return isinstance(getattr(deps, "organization_id", None), UUID) and isinstance(
        getattr(deps, "conversation_id", None), UUID
    )


async def _relative_report(workspace: Workspace, report: CodingReport) -> CodingReport:
    """Keep harness-only paths inside the workspace, relative to its actual root."""
    if not report.files_changed:
        return report
    try:
        root = await workspace.working_dir()
    except SANDBOX_FAILURES as failed:
        # A lost workspace costs this optional list, not the completed task's answer.
        logger.warning(
            "A coding task's relative file list is unavailable: %s", type(failed).__name__
        )
        return report.model_copy(update={"files_changed": []})
    return _relative_files(report, root)


def _relative_files(report: CodingReport, root: str) -> CodingReport:
    root = root.rstrip("/")
    paths: list[str] = []
    for path in report.files_changed:
        if path.startswith(root + "/"):
            path = path[len(root) + 1 :]
        if path.startswith("/") or ".." in path.split("/"):
            continue
        paths.append(path.removeprefix("./"))
    return report.model_copy(update={"files_changed": list(dict.fromkeys(paths))})


async def _with_changes(
    ctx: RunContext[Any],
    report: CodingReport,
    baseline: _changes.Baseline,
    *,
    redact_values: tuple[str, ...] = (),
) -> CodingReport:
    """The report, naming the change set the task left - once it is recorded."""
    changes = await _changes.finish(ctx, baseline)
    if changes is None:
        return report
    changes = redact_changes(changes, redact_values)
    try:
        async with get_db_context() as db:
            try:
                # A savepoint, caught inside the session: `get_db_context` logs
                # an error that leaves it with its traceback, and an INSERT's
                # error text holds its parameters - the workspace's code (#2480).
                async with db.begin_nested():
                    kept = await CodingTaskChangeService(db).record(
                        changes,
                        organization_id=ctx.deps.organization_id,
                        conversation_id=ctx.deps.conversation_id,
                        tool_call_id=ctx.tool_call_id,
                        harness=report.harness,
                        workspace_ref=ctx.workspace.ref,
                        snapshot_isolated=isinstance(ctx.workspace, RecordingWorkspace)
                        and ctx.workspace.snapshot_isolated,
                    )
            except SQLAlchemyError as failed:
                return _unrecorded(ctx, report, failed)
    except SQLAlchemyError as failed:
        # The commit, or a connection lost on the way: no parameters in that
        # error, and the same answer - the diff is lost, the report is not.
        return _unrecorded(ctx, report, failed)
    return report.model_copy(
        update={"changes_id": str(kept.id), "files_changed": [file.path for file in changes.files]}
    )


def _unrecorded(ctx: RunContext[Any], report: CodingReport, failed: Exception) -> CodingReport:
    """The report without a diff, when the diff could not be kept.

    The task's work is done and its report is the model's answer; a diff that
    could not be kept - a conversation deleted meanwhile, or the database itself
    failing - costs the panel its diff, not the run its result. Named by its
    class alone: an INSERT's error text carries the workspace's code.
    """
    logger.error(
        "A coding task's changes in conversation %s could not be recorded: %s",
        ctx.deps.conversation_id,
        type(failed).__name__,
    )
    return report


def _person(deps: object) -> UUID | None:
    """Who the run is for, when it is somebody signed in - the audience, not the account.

    `user_id` on the deps is who the run is billed to, which on a public page or
    for an API key is the publisher or the key's issuer standing in for somebody
    else. The audience names only a person who is actually asking.
    """
    audience = getattr(deps, "audience", None)
    return audience.user_id if isinstance(audience, RunAudience) else None


def _in_room(deps: object) -> bool:
    """Whether the run answers a group chat, where several people's turns share one sandbox."""
    audience = getattr(deps, "audience", None)
    return isinstance(audience, RunAudience) and audience.room_key is not None


UNREPORTED = "coding-agent:unreported"
"""What a task is booked as when the harness ended before saying what it spent."""


def _book(usage: Usage) -> None:
    """Put each model the session ran on the run's ledger, priced by its tokens.

    A task that failed, timed out or was stopped before the harness reported its
    usage may still have spent tokens: it is booked as one unpriced call, so the
    run's cost says it is a floor rather than reading as complete.
    """
    if not usage.by_model:
        record_ambient_usage(UNREPORTED, RequestUsage(), provider=usage.provider)
    for model_name, spent in usage.by_model.items():
        record_ambient_usage(model_name, spent, provider=usage.provider)
