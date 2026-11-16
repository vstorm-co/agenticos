"""A coding task over the Agent Client Protocol, on the person's own computer (#2576).

The desktop app starts the agent's ACP adapter and hands this module a pipe; the
protocol is spoken here, so the app stays a thin process runner. A task initializes
the adapter, creates or loads its session, then prompts it. While the prompt
runs the agent's `session/update` notifications become the steps the chat shows
and its `session/request_permission` requests are answered by policy.

Permissions are decided once, before the task, by the capability's approval and
its `access`. The agent's requests in between are not put to a person one by one
- a run that is parked for each would have to keep the session alive across runs
- they are answered from `access`: `edit` allows, `read_only` allows only what
reads. That is the same trade the sandbox harness makes, for the same reason.
"""

import itertools
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import anyio

from app.agents.capabilities.coding_agent._harness import (
    Access,
    CodingReport,
    CodingStep,
    Harness,
    LiveItem,
    Said,
    StepEnded,
    StepKind,
    StepStarted,
    bounded,
    clip,
    last_steps,
)
from app.agents.model_context import check_model_context
from app.agents.steering import SteeringInbox, screen_steer

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
POLL_WAIT_MS = 20_000
"""How long the app holds one poll open; shorter than the call's own timeout."""

POLL_TIMEOUT_SECONDS = 40.0
CALL_TIMEOUT_SECONDS = 30.0
LAUNCH_TIMEOUT_SECONDS = 300.0
MAX_SESSION_EVENTS = 16_384
MAX_SESSION_BYTES = 8 << 20
"""Cumulative inbound ASCII JSON budget, including replay and permission requests."""

_METHOD_NOT_FOUND = -32601

_READING_KINDS = frozenset({"read", "search", "think", "fetch"})
"""What an agent may do at `read_only`: look, never change or run."""

_STEP_KINDS: dict[str, StepKind] = {
    "read": "read",
    "search": "search",
    "edit": "edit",
    "delete": "edit",
    "move": "edit",
    "execute": "command",
    "fetch": "web",
}

_READ_ONLY_NOTE = (
    "You are running read-only: you cannot change files or run commands, and nobody "
    "can approve anything else. Read and search the code and answer. Where a change or "
    "a command would be needed, say what it would be.\n\n"
)


class AcpError(Exception):
    """The protocol could not be carried on: the agent said no, or went away."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AgentExited(AcpError):
    """The agent's process ended before it answered.

    What it printed on stderr is deliberately not kept: an adapter's diagnostics routinely
    hold home-directory paths and registry addresses, and this message reaches the model
    and the conversation. The person gets what to check instead.
    """

    def __init__(self, code: int) -> None:
        super().__init__(
            f"The agent stopped with exit code {code} before it answered. Prepare coding "
            "tools and check the agent sign-in under Settings → Desktop app."
        )
        self.code = code


class Pipe(Protocol):
    """The agent's stdin and stdout, as whole JSON messages."""

    async def send(self, message: dict[str, Any]) -> None: ...

    async def receive(self) -> dict[str, Any]:
        """The next message the agent wrote.

        Raises:
            AgentExited: The process ended and everything it wrote was read.
        """
        ...

    async def close(self) -> None: ...


class AgentCalls(Protocol):
    """What the device can be asked about an agent: `agent.*` operations."""

    async def agent_call(
        self, op: str, args: dict[str, Any], *, timeout: float, root: str | None = None
    ) -> dict[str, Any]: ...


class DevicePipe:
    """An agent running on the person's computer, reached through the device hub."""

    def __init__(
        self,
        device: AgentCalls,
        harness: Harness,
        *,
        resume_key: str | None = None,
        fresh_session: bool = False,
        root: str | None = None,
    ) -> None:
        self._resume_key = resume_key
        self._root = root
        self._fresh_session = fresh_session
        self.session_id: str | None = None
        self._device = device
        self._harness = harness
        self._id: str | None = None
        self._cursor = 0
        self._pending: deque[dict[str, Any]] = deque()

    async def open(self) -> None:
        args: dict[str, Any] = {"agent": self._harness}
        if self._resume_key is not None:
            args.update(resume_key=self._resume_key, fresh_session=self._fresh_session)
        opened = await self._device.agent_call(
            "agent.open", args, timeout=LAUNCH_TIMEOUT_SECONDS, root=self._root
        )
        previous = opened.get("session_id")
        self.session_id = (
            previous if isinstance(previous, str) and not self._fresh_session else None
        )
        identifier = opened.get("id")
        if not isinstance(identifier, str):
            raise AcpError("The computer's app did not start the agent.")
        self._id = identifier

    async def remember(self, session_id: str) -> None:
        if self._resume_key is not None:
            await self._device.agent_call(
                "agent.remember",
                {"id": self._id, "session_id": session_id},
                timeout=CALL_TIMEOUT_SECONDS,
                root=self._root,
            )

    async def send(self, message: dict[str, Any]) -> None:
        await self._device.agent_call(
            "agent.send",
            {"id": self._id, "message": message},
            timeout=CALL_TIMEOUT_SECONDS,
            root=self._root,
        )

    async def receive(self) -> dict[str, Any]:
        while not self._pending:
            answer = await self._device.agent_call(
                "agent.poll",
                {"id": self._id, "cursor": self._cursor, "wait_ms": POLL_WAIT_MS},
                timeout=POLL_TIMEOUT_SECONDS,
                root=self._root,
            )
            cursor = answer.get("cursor")
            if isinstance(cursor, int):
                self._cursor = cursor
            for line in answer.get("lines") or []:
                try:
                    message = json.loads(line)
                except TypeError, ValueError:
                    logger.debug("An agent wrote a line that is not JSON")
                    continue
                if isinstance(message, dict):
                    self._pending.append(message)
            exit_code = answer.get("exit")
            if not self._pending and isinstance(exit_code, int):
                raise AgentExited(exit_code)
        return self._pending.popleft()

    async def close(self) -> None:
        if self._id is not None:
            await self._device.agent_call(
                "agent.close", {"id": self._id}, timeout=15.0, root=self._root
            )


def permission_reply(access: Access, request: dict[str, Any]) -> dict[str, Any]:
    """The answer to `session/request_permission`, from the task's access.

    `edit` takes the agent's own "allow once". `read_only` allows only a request
    to look. Anything else is rejected, which the agent reads as a refusal and
    reports, rather than the whole task being cancelled.
    """
    options = [option for option in request.get("options") or [] if isinstance(option, dict)]
    kind = (request.get("toolCall") or {}).get("kind")
    allowed = access == "edit" or kind in _READING_KINDS
    wanted = ("allow_once", "allow_always") if allowed else ("reject_once", "reject_always")
    for preferred in wanted:
        for option in options:
            if option.get("kind") == preferred and isinstance(option.get("optionId"), str):
                return {"outcome": {"outcome": "selected", "optionId": option["optionId"]}}
    return {"outcome": {"outcome": "cancelled"}}


@dataclass
class _Tool:
    key: str
    step: CodingStep
    edits: list[str] = field(default_factory=list)


@dataclass
class _Collector:
    """What a session's updates add up to: the steps, the files, the answer."""

    tools: dict[str, _Tool] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    said: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    task_updates: list[str] = field(default_factory=list)

    def update(self, update: dict[str, Any]) -> list[LiveItem]:
        match update.get("sessionUpdate"):
            case "agent_message_chunk":
                text = (update.get("content") or {}).get("text")
                if isinstance(text, str):
                    self.said.append(text)
                return []
            case "tool_call":
                return self._started(update)
            case "tool_call_update":
                return self._changed(update)
            case _:
                return []

    def _started(self, update: dict[str, Any]) -> list[LiveItem]:
        key = str(update.get("toolCallId") or "")
        if not key or key in self.tools:
            return self._changed(update)
        items: list[LiveItem] = []
        if self.said and "".join(self.said).strip():
            items.append(Said("".join(self.said)))
        self.said = []
        kind = _STEP_KINDS.get(str(update.get("kind")), "other")
        step = CodingStep(kind=kind, title=clip(str(update.get("title") or kind)))
        tool = _Tool(key, step, edits=_paths(update) if kind == "edit" else [])
        self.tools[key] = tool
        self.order.append(key)
        items.append(StepStarted(key, step))
        return [*items, *self._changed(update)]

    def _changed(self, update: dict[str, Any]) -> list[LiveItem]:
        tool = self.tools.get(str(update.get("toolCallId") or ""))
        if tool is None:
            return []
        title = update.get("title")
        if isinstance(title, str) and title:
            tool.step = tool.step.model_copy(update={"title": clip(title)})
        if tool.step.kind == "edit":
            tool.edits = [*tool.edits, *(p for p in _paths(update) if p not in tool.edits)]
        status = update.get("status")
        if status in ("completed", "failed"):
            failed = status == "failed"
            tool.step = tool.step.model_copy(update={"failed": failed})
            return [StepEnded(tool.key, failed=failed)]
        return []

    def report(
        self, *, harness: Harness, access: Access, outcome: str, answer: str, session_id: str | None
    ) -> CodingReport:
        steps = [self.tools[key].step for key in self.order]
        changed = list(dict.fromkeys(path for key in self.order for path in self.tools[key].edits))
        return CodingReport(
            harness=harness,
            access=access,
            outcome="completed" if outcome == "completed" else "failed",
            answer=bounded(answer),
            session_id=session_id,
            steps=last_steps(steps),
            files_changed=[] if access == "read_only" else changed,
            refused=self.refused,
            task_updates=self.task_updates,
        )


def _paths(update: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for location in update.get("locations") or []:
        if isinstance(location, dict) and isinstance(location.get("path"), str):
            found.append(location["path"])
    for content in update.get("content") or []:
        if (
            isinstance(content, dict)
            and content.get("type") == "diff"
            and isinstance(content.get("path"), str)
        ):
            found.append(content["path"])
    return found


Shown = Callable[[list[LiveItem]], Awaitable[None]]


class Conversation:
    """JSON-RPC over a `Pipe`: requests the client makes, and whatever the agent asks back."""

    def __init__(self, pipe: Pipe, *, access: Access, collector: _Collector, shown: Shown) -> None:
        self._pipe = pipe
        self._access = access
        self._collector = collector
        self._shown = shown
        self._ids = itertools.count(1)
        self._received_events = 0
        self._received_bytes = 0

    async def request(
        self, method: str, params: dict[str, Any], *, sent: anyio.Event | None = None
    ) -> Any:
        """Send a request and read until its answer, handling everything between."""
        if method == "session/prompt":
            await check_model_context()
        identifier = next(self._ids)
        await self._pipe.send(
            {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}
        )
        if sent is not None:
            sent.set()
        while True:
            message = await self._pipe.receive()
            self._consume(message)
            if "method" in message:
                await self._handle(message)
            elif message.get("id") == identifier:
                if "error" in message:
                    # The adapter's own words can carry a local path or a configuration
                    # value, and this reaches the model and the saved chat: say what
                    # kind of failure it was, and keep the rest out.
                    detail = message["error"]
                    code = detail.get("code") if isinstance(detail, dict) else None
                    shown = f" (code {code})" if isinstance(code, int) else ""
                    raise AcpError(f"The agent refused the request{shown}.")
                return message.get("result")

    def _consume(self, message: dict[str, object]) -> None:
        # ASCII JSON counts escaped Unicode too, without allocating a second byte copy.
        size = len(json.dumps(message, ensure_ascii=True, separators=(",", ":")))
        if (
            self._received_events >= MAX_SESSION_EVENTS
            or self._received_bytes + size > MAX_SESSION_BYTES
        ):
            raise AcpError(
                "The local coding agent exceeded the session output limit. Give it a narrower task."
            )
        self._received_events += 1
        self._received_bytes += size

    async def prompt(
        self,
        session_id: str,
        text: str,
        steering: SteeringInbox | None,
    ) -> Any:
        """Interrupt the current turn for a correction, then continue the same session.

        Cancel is part of ACP for both adapters. Waiting for its stop response
        before the next prompt avoids overlapping prompts and ambiguous writes.
        """
        if steering is None:
            return await self.request(
                "session/prompt",
                {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
            )
        while True:
            interrupted = False
            sent = anyio.Event()

            async def watch(ready: anyio.Event) -> None:
                nonlocal interrupted
                await ready.wait()
                while True:
                    if steering.unapplied():
                        interrupted = True
                        await self.cancel(session_id)
                        return
                    await anyio.sleep(0.2)

            try:
                async with anyio.create_task_group() as group:
                    group.start_soon(watch, sent)
                    result = await self.request(
                        "session/prompt",
                        {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
                        sent=sent,
                    )
                    group.cancel_scope.cancel()
            except BaseExceptionGroup as errors:
                # The watcher must settle before returning a transport failure;
                # preserve its type for the tool's existing error boundary.
                if len(errors.exceptions) == 1:
                    raise errors.exceptions[0] from None
                raise
            if not interrupted:
                return result
            updates = [screen_steer(steering, item.text) for item in steering.take()]
            self._collector.task_updates.extend(updates)
            self._collector.said.clear()
            text = (
                "The person updated the task while you were working. Continue the original task, "
                "applying these corrections:\n\n" + "\n\n".join(updates)
            )
            if steering.on_applied is not None:
                for update in updates:
                    await steering.on_applied(update)

    async def cancel(self, session_id: str) -> None:
        await self._pipe.send(
            {"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": session_id}}
        )

    async def _handle(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        raw = message.get("params")
        params: dict[str, Any] = raw if isinstance(raw, dict) else {}
        if method == "session/update":
            update = params.get("update")
            if isinstance(update, dict):
                items = self._collector.update(update)
                if items:
                    await self._shown(items)
            return
        if "id" not in message:
            return
        if method == "session/request_permission":
            reply = permission_reply(self._access, params)
            if reply["outcome"]["outcome"] == "cancelled" or _was_rejected(params, reply):
                title = (params.get("toolCall") or {}).get("title")
                self._collector.refused.append(clip(str(title or "a request")))
            await self._pipe.send({"jsonrpc": "2.0", "id": message["id"], "result": reply})
            return
        # The client advertises no files or terminals: the agent uses its own.
        await self._pipe.send(
            {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": _METHOD_NOT_FOUND, "message": f"{method} is not supported"},
            }
        )


def _was_rejected(params: dict[str, Any], reply: dict[str, Any]) -> bool:
    rejecting = {
        option.get("optionId")
        for option in params.get("options") or []
        if isinstance(option, dict) and str(option.get("kind", "")).startswith("reject")
    }
    return reply["outcome"].get("optionId") in rejecting


async def _configure_session(
    conversation: Conversation,
    session_id: str,
    opened: Mapping[str, object] | None,
    *,
    model: str | None,
    effort: str | None,
) -> None:
    """Apply explicit choices through ACP; an unsupported choice is never ignored."""
    options = (opened or {}).get("configOptions")
    for category, value in (("model", model), ("thought_level", effort)):
        if value is None:
            continue
        option = (
            next(
                (
                    item
                    for item in options
                    if isinstance(item, dict) and item.get("category") == category
                ),
                None,
            )
            if isinstance(options, list)
            else None
        )
        identifier = option.get("id") if option is not None else None
        if not isinstance(identifier, str) or not identifier:
            label = "model" if category == "model" else "reasoning level"
            raise AcpError(
                f"This coding agent does not expose a {label} setting. Prepare its latest coding tools or leave the choice on its own setting."
            )
        configured = await conversation.request(
            "session/set_config_option",
            {"sessionId": session_id, "configId": identifier, "value": value},
        )
        options = (configured or {}).get("configOptions", options)


async def run_task(
    pipe: Pipe,
    *,
    harness: Harness,
    access: Access,
    root: str,
    task: str,
    timeout_seconds: int,
    shown: Shown,
    model: str | None = None,
    effort: str | None = None,
    previous_session: str | None = None,
    remember: Callable[[str], Awaitable[None]] | None = None,
    steering: SteeringInbox | None = None,
) -> CodingReport:
    """One task as one ACP session, ended however the task ends.

    Raises:
        AcpError: The agent could not be spoken to, or ended before it answered.
    """
    collector = _Collector()
    conversation = Conversation(pipe, access=access, collector=collector, shown=shown)
    session_id: str | None = None
    try:
        stop = "timed_out"
        # One deadline from the first request: an adapter that never answers `initialize`
        # or `session/new` ends the task like one that never finishes the prompt.
        with anyio.move_on_after(timeout_seconds):
            initialized = await conversation.request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "clientCapabilities": {},
                    "clientInfo": {"name": "agenticos", "title": "AgenticOS"},
                },
            )
            session_params: dict[str, Any] = {"cwd": root, "mcpServers": []}
            if harness == "claude_code" and access == "read_only":
                session_params["_meta"] = {
                    "claudeCode": {
                        "options": {
                            "allowDangerouslySkipPermissions": False,
                            "tools": ["Read", "Glob", "Grep", "WebFetch", "WebSearch"],
                        }
                    }
                }
            capabilities = (initialized or {}).get("agentCapabilities") or {}
            if previous_session is not None:
                if not capabilities.get("loadSession"):
                    raise AcpError(
                        "This adapter cannot resume the earlier session. Start a fresh task explicitly."
                    )
                opened = await conversation.request(
                    "session/load", {**session_params, "sessionId": previous_session}
                )
                identifier = previous_session
                # session/load may replay earlier messages; only this task belongs in its report.
                collector.tools.clear()
                collector.order.clear()
                collector.said.clear()
            else:
                opened = await conversation.request("session/new", session_params)
                identifier = (opened or {}).get("sessionId")
            if not isinstance(identifier, str):
                raise AcpError("The agent did not open a session.")
            session_id = identifier
            if harness == "codex" and access == "read_only":
                await conversation.request(
                    "session/set_mode", {"sessionId": session_id, "modeId": "read-only"}
                )
            await _configure_session(conversation, session_id, opened, model=model, effort=effort)
            if remember is not None:
                await remember(session_id)
            prompt = f"{_READ_ONLY_NOTE}{task}" if access == "read_only" else task
            result = await conversation.prompt(session_id, prompt, steering)
            stop = str((result or {}).get("stopReason", "end_turn"))
        answer = "".join(collector.said).strip()
        if stop == "timed_out":
            if session_id is not None:
                with anyio.CancelScope(shield=True):
                    await conversation.cancel(session_id)
            return collector.report(
                harness=harness,
                access=access,
                outcome="timed_out",
                answer=f"The task was stopped after {timeout_seconds // 60} minutes. "
                "Hand it a narrower task, or split this one.",
                session_id=session_id,
            ).model_copy(update={"outcome": "timed_out"})
        if stop != "end_turn":
            answer = answer or f"The agent stopped before finishing ({stop})."
        return collector.report(
            harness=harness,
            access=access,
            outcome="completed" if stop == "end_turn" else "failed",
            answer=answer,
            session_id=session_id,
        )
    finally:
        with anyio.CancelScope(shield=True):
            try:
                await pipe.close()
            except Exception:
                logger.debug("A local agent could not be closed cleanly", exc_info=True)
