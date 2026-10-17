"""Claude Code and Codex, each as one command and one stream of events to read.

Both harnesses run headless in the agent's sandbox and print one JSON object per
line: Claude Code with `--output-format stream-json`, Codex with `exec --json`.
This module is the whole of what differs between them - the command line, the
environment that carries the credential, and how their events become one
:class:`CodingReport`. Nothing here touches a workspace or a ledger, so all of it
is tested on recorded event streams.

The two modes are the platform's, not the harnesses': `plan` reads and may run a
read-only command, `apply` changes files and runs anything. Claude Code has a
permission mode for each. Codex's own sandbox is read-only for `plan`; for `apply`
it is bypassed, because the sandbox container is already the boundary and the
platform's approval gate is what a person says yes on.
"""

from __future__ import annotations

import base64
import json
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai.exceptions import UserError
from pydantic_ai.providers.openai_codex import OpenAICodexCredentials
from pydantic_ai.usage import RequestUsage

Harness = Literal["claude_code", "codex"]
Mode = Literal["plan", "apply"]
StepKind = Literal["read", "search", "edit", "command", "web", "other"]

MAX_STEPS = 200
"""Steps kept in a report. A long session is summarised by its last ones."""

MAX_TITLE_CHARS = 300
MAX_ANSWER_CHARS = 30_000
"""How much of the harness's final answer reaches the model that asked."""

LABELS: dict[Harness, str] = {"claude_code": "Claude Code", "codex": "Codex"}

CLAUDE_TOKEN_PREFIX = "sk-ant-oat"
"""What a Claude subscription token from `claude setup-token` starts with.

Anthropic's own prefix, which is how Claude Code itself tells an OAuth token
from an API key (`sk-ant-api`): the two go in different variables.
"""

_OPENAI_AUTH_CLAIM = "https://api.openai.com/auth"
_OPENAI_PROFILE_CLAIM = "https://api.openai.com/profile"

_CLAUDE_KINDS: dict[str, StepKind] = {
    "Read": "read",
    "NotebookRead": "read",
    "LS": "read",
    "Glob": "search",
    "Grep": "search",
    "Edit": "edit",
    "MultiEdit": "edit",
    "Write": "edit",
    "NotebookEdit": "edit",
    "Bash": "command",
    "WebFetch": "web",
    "WebSearch": "web",
}

_CLAUDE_QUIET = frozenset({"TodoWrite", "ExitPlanMode"})
"""Bookkeeping calls, not steps a person would recognise as work."""


class CodingStep(BaseModel):
    """One thing the harness did: a file read or changed, a command, a search."""

    kind: StepKind
    title: str
    failed: bool = False


class CodingReport(BaseModel):
    """What one task came to, as the model reads it and the console draws it."""

    kind: Literal["coding_agent"] = "coding_agent"
    harness: Harness
    mode: Mode
    outcome: Literal["completed", "failed", "timed_out"]
    answer: str
    session_id: str | None = None
    steps: list[CodingStep] = []
    files_changed: list[str] = []
    refused: list[str] = []
    """Tools the harness wanted and was not allowed in this mode."""


@dataclass(frozen=True)
class Invocation:
    """The command line and the environment one task runs with."""

    argv: list[str]
    env: dict[str, str] = field(repr=False)

    def shell_line(self, log: str, errors: str) -> str:
        """The command with its events and its errors each written to a file.

        To files rather than captured: a session that reads a large repository
        prints more than a command's output may carry back.
        """
        return f"{shlex.join(self.argv)} > {shlex.quote(log)} 2> {shlex.quote(errors)}"


@dataclass
class Usage:
    """What the session spent, per model, for the run's ledger."""

    by_model: dict[str, RequestUsage] = field(default_factory=dict)
    provider: str | None = None


def invocation(
    harness: Harness,
    mode: Mode,
    task: str,
    *,
    api_key: str | None,
    model: str | None,
    session_id: str | None,
    base_url: str | None,
) -> Invocation:
    """How to run `task` in `mode` on `harness`, continuing `session_id` when given.

    `api_key` is None only for Codex on a ChatGPT sign-in, whose tokens are in its
    `auth.json` rather than the environment.
    """
    if harness == "claude_code":
        argv = ["claude", "-p", task, "--output-format", "stream-json", "--verbose"]
        argv += (
            ["--permission-mode", "plan"] if mode == "plan" else ["--dangerously-skip-permissions"]
        )
        if model:
            argv += ["--model", model]
        if session_id:
            argv += ["--resume", session_id]
        env = {
            # Claude Code refuses to skip its prompts as root outside a sandbox;
            # this is one, and the platform's approval gate already asked.
            "IS_SANDBOX": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
        if api_key is None:
            raise UserError("Claude Code needs an API key or a subscription token.")
        if api_key.startswith(CLAUDE_TOKEN_PREFIX):
            env["CLAUDE_CODE_OAUTH_TOKEN"] = api_key
        elif base_url:
            # A gateway takes a bearer token where Anthropic takes `x-api-key`,
            # and an empty key keeps Claude Code from sending one at all.
            env |= {
                "ANTHROPIC_BASE_URL": base_url,
                "ANTHROPIC_AUTH_TOKEN": api_key,
                "ANTHROPIC_API_KEY": "",
            }
        else:
            env["ANTHROPIC_API_KEY"] = api_key
        return Invocation(argv=argv, env=env)

    argv = ["codex", "exec"]
    if session_id:
        argv += ["resume", session_id]
    argv += ["--json", "--skip-git-repo-check"]
    argv += (
        ["-c", 'sandbox_mode="read-only"']
        if mode == "plan"
        else ["--dangerously-bypass-approvals-and-sandbox"]
    )
    if model:
        argv += ["-m", model]
    argv.append(task)
    return Invocation(argv=argv, env={} if api_key is None else {"CODEX_API_KEY": api_key})


def codex_auth_file(credentials: OpenAICodexCredentials) -> str:
    """A ChatGPT sign-in as the Codex CLI's `auth.json`.

    The CLI also wants an `id_token`, which the platform's sign-in does not keep:
    it reads only the claims - the account, the plan - and checks no signature,
    so one is made of the access token's own claims, account id included.
    `last_refresh` is when the access token was issued, so the CLI refreshes it
    on its own schedule rather than taking a stale one for fresh.
    """
    claims = _jwt_claims(credentials.access_token)
    auth = _mapping(claims.get(_OPENAI_AUTH_CLAIM))
    identity: dict[str, Any] = {
        _OPENAI_AUTH_CLAIM: {**auth, "chatgpt_account_id": credentials.account_id}
    }
    email = _text(_mapping(claims.get(_OPENAI_PROFILE_CLAIM)).get("email"))
    if email:
        identity["email"] = email
    issued = claims.get("iat")
    refreshed = (
        datetime.fromtimestamp(issued, UTC) if isinstance(issued, int) else datetime.now(UTC)
    )
    return json.dumps(
        {
            "OPENAI_API_KEY": None,
            "tokens": {
                "id_token": ".".join((_b64({"alg": "none"}), _b64(identity), _b64("agenticos"))),
                "access_token": credentials.access_token,
                "refresh_token": credentials.refresh_token,
                "account_id": credentials.account_id,
            },
            "last_refresh": refreshed.isoformat().replace("+00:00", "Z"),
        }
    )


def rotated_sign_in(
    auth_file: str, written: OpenAICodexCredentials
) -> OpenAICodexCredentials | None:
    """The tokens Codex left in its `auth.json`, when they differ from what was written."""
    try:
        data = json.loads(auth_file)
    except ValueError:
        return None
    if not isinstance(data, Mapping):
        return None
    try:
        current = OpenAICodexCredentials.from_codex_cli_auth(data)
    except UserError:
        return None
    unchanged = (
        current.access_token == written.access_token
        and current.refresh_token == written.refresh_token
    )
    return None if unchanged else current


def read_events(log: str) -> list[dict[str, Any]]:
    """The JSON objects in a harness's output, skipping anything else it printed."""
    events: list[dict[str, Any]] = []
    for line in log.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def claude_report(
    events: Iterable[dict[str, Any]], *, mode: Mode, base_url: str | None
) -> tuple[CodingReport, Usage]:
    """Claude Code's stream, from its `init` to its `result`."""
    steps: dict[str, CodingStep] = {}
    order: list[str] = []
    files: list[str] = []
    plan: str | None = None
    texts: list[str] = []
    session_id: str | None = None
    result: dict[str, Any] | None = None
    for event in events:
        session_id = _text(event.get("session_id")) or session_id
        kind = event.get("type")
        if kind == "result":
            result = event
            continue
        content = _content(event)
        for part in content:
            if kind == "assistant" and part.get("type") == "text":
                texts.append(_text(part.get("text")) or "")
            elif kind == "assistant" and part.get("type") == "tool_use":
                name = _text(part.get("name")) or "tool"
                arguments = _mapping(part.get("input"))
                if name == "ExitPlanMode":
                    plan = _text(arguments.get("plan")) or plan
                if name in _CLAUDE_QUIET:
                    continue
                step = _claude_step(name, arguments)
                if step.kind == "edit" and step.title not in files:
                    files.append(step.title)
                key = _text(part.get("id")) or str(len(order))
                steps[key] = step
                order.append(key)
            elif kind == "user" and part.get("type") == "tool_result" and part.get("is_error"):
                key = _text(part.get("tool_use_id"))
                if key in steps:
                    steps[key] = steps[key].model_copy(update={"failed": True})

    usage = Usage(provider=None if base_url else "anthropic")
    if result is None:
        return _unfinished("claude_code", mode, session_id, [steps[key] for key in order]), usage
    for model, spent in (result.get("modelUsage") or {}).items():
        if isinstance(spent, dict):
            usage.by_model[str(model)] = _claude_usage(spent)
    refused = [
        _text(denial.get("tool_name")) or "tool"
        for denial in result.get("permission_denials") or []
        if isinstance(denial, dict) and denial.get("tool_name") not in _CLAUDE_QUIET
    ]
    answer = _text(result.get("result")) or plan or "\n\n".join(texts)
    failed = bool(result.get("is_error")) or result.get("subtype") != "success"
    return (
        CodingReport(
            harness="claude_code",
            mode=mode,
            outcome="failed" if failed else "completed",
            answer=_bounded(answer or "(Claude Code sent no answer.)"),
            session_id=_text(result.get("session_id")) or session_id,
            steps=_last([steps[key] for key in order]),
            files_changed=files if mode == "apply" else [],
            refused=sorted(set(refused)),
        ),
        usage,
    )


def codex_report(
    events: Iterable[dict[str, Any]], *, mode: Mode, model: str | None
) -> tuple[CodingReport, Usage]:
    """Codex's stream, from `thread.started` to `turn.completed` or `turn.failed`."""
    steps: list[CodingStep] = []
    files: list[str] = []
    messages: list[str] = []
    session_id: str | None = None
    error: str | None = None
    finished = False
    usage = Usage(provider="openai")
    for event in events:
        kind = event.get("type")
        if kind == "thread.started":
            session_id = _text(event.get("thread_id"))
        elif kind == "item.completed" and (item := _mapping(event.get("item"))):
            message, step, changed = _codex_item(item)
            if message:
                messages.append(message)
            if step is not None:
                steps.append(step)
            files += [path for path in changed if path not in files]
        elif kind == "turn.completed":
            finished = True
            spent = _mapping(event.get("usage"))
            # Codex names no model in its events, so the one asked for is the one
            # booked; with none asked for it is booked unpriced, which marks the
            # run's cost partial rather than guessing at Codex's default.
            name = model or "codex"
            previous = usage.by_model.get(name, RequestUsage())
            usage.by_model[name] = previous + RequestUsage(
                input_tokens=_count(spent.get("input_tokens")),
                cache_read_tokens=_count(spent.get("cached_input_tokens")),
                output_tokens=_count(spent.get("output_tokens")),
            )
        elif kind in ("turn.failed", "error"):
            detail = _mapping(event.get("error")) or event
            error = _text(detail.get("message")) or "Codex stopped with an error."

    if error is not None:
        outcome: Literal["completed", "failed"] = "failed"
        answer = error
    elif finished:
        outcome = "completed"
        answer = messages[-1] if messages else "(Codex sent no answer.)"
    else:
        return _unfinished("codex", mode, session_id, steps), usage
    return (
        CodingReport(
            harness="codex",
            mode=mode,
            outcome=outcome,
            answer=_bounded(answer),
            session_id=session_id,
            steps=_last(steps),
            files_changed=files if mode == "apply" else [],
        ),
        usage,
    )


def _claude_step(name: str, arguments: dict[str, Any]) -> CodingStep:
    kind = _CLAUDE_KINDS.get(name, "other")
    title = (
        _text(arguments.get("command"))
        or _text(arguments.get("file_path"))
        or _text(arguments.get("notebook_path"))
        or _text(arguments.get("pattern"))
        or _text(arguments.get("url"))
        or _text(arguments.get("query"))
        or _text(arguments.get("description"))
        or name
    )
    return CodingStep(kind=kind, title=_clip(title))


def _codex_item(item: dict[str, Any]) -> tuple[str | None, CodingStep | None, list[str]]:
    """An item's answer text, its step, and the files it changed."""
    kind = item.get("type")
    failed = item.get("status") == "failed"
    if kind == "agent_message":
        return _text(item.get("text")), None, []
    if kind == "command_execution":
        exit_code = item.get("exit_code")
        step = CodingStep(
            kind="command",
            title=_clip(_text(item.get("command")) or "command"),
            failed=failed or (isinstance(exit_code, int) and exit_code != 0),
        )
        return None, step, []
    if kind == "file_change":
        changes = item.get("changes")
        changes = changes if isinstance(changes, list) else []
        paths = list(
            dict.fromkeys(
                path
                for change in changes
                if isinstance(change, dict) and (path := _text(change.get("path")))
            )
        )
        step = CodingStep(kind="edit", title=_clip(", ".join(paths) or "files"), failed=failed)
        return None, step, paths
    if kind == "web_search":
        return None, CodingStep(kind="web", title=_clip(_text(item.get("query")) or "web")), []
    if kind == "mcp_tool_call":
        title = _text(item.get("tool")) or "tool"
        return None, CodingStep(kind="other", title=_clip(title), failed=failed), []
    return None, None, []


def _unfinished(
    harness: Harness, mode: Mode, session_id: str | None, steps: list[CodingStep]
) -> CodingReport:
    """A session that stopped before it said it was done - killed, or crashed."""
    return CodingReport(
        harness=harness,
        mode=mode,
        outcome="failed",
        answer=f"{LABELS[harness]} stopped before it finished.",
        session_id=session_id,
        steps=_last(steps),
    )


def _claude_usage(spent: dict[str, Any]) -> RequestUsage:
    # Pydantic AI counts cached tokens inside `input_tokens`, as Anthropic's own
    # model class does; Claude Code reports the three apart.
    fresh = _count(spent.get("inputTokens"))
    read = _count(spent.get("cacheReadInputTokens"))
    written = _count(spent.get("cacheCreationInputTokens"))
    return RequestUsage(
        input_tokens=fresh + read + written,
        cache_read_tokens=read,
        cache_write_tokens=written,
        output_tokens=_count(spent.get("outputTokens")),
    )


def _content(event: dict[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), list):
        return []
    return [part for part in message["content"] if isinstance(part, dict)]


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _jwt_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    try:
        decoded = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except ValueError:
        return {}
    return _mapping(decoded)


def _b64(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _count(value: object) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def _clip(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= MAX_TITLE_CHARS else f"{line[: MAX_TITLE_CHARS - 1]}…"


def _bounded(text: str) -> str:
    if len(text) <= MAX_ANSWER_CHARS:
        return text
    return f"{text[:MAX_ANSWER_CHARS]}\n\n[The answer went on for {len(text) - MAX_ANSWER_CHARS} more characters.]"


def _last(steps: list[CodingStep]) -> list[CodingStep]:
    return steps[-MAX_STEPS:]
