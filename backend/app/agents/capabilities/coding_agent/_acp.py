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

import hashlib
import itertools
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import anyio
from anyio.abc import TaskGroup

from app.agents.capabilities.coding_agent._harness import (
    Access,
    AcpHarness,
    CodingReport,
    CodingStep,
    LiveItem,
    RuntimeCredentials,
    Said,
    StepEnded,
    StepKind,
    StepStarted,
    bounded,
    clip,
    last_steps,
)
from app.agents.deps import AgentDeps
from app.agents.model_context import check_model_context
from app.agents.pi_keys import NativeRuntimeKey
from app.agents.runtime_questions import RuntimeQuestionsCallback
from app.agents.runtime_tools import RuntimeTools
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


def private_state_scope(deps: AgentDeps) -> str | None:
    audience = deps.audience
    if (
        deps.organization_id is None
        or deps.run_person is None
        or deps.conversation_id is None
        or deps.user_id != str(deps.run_person)
        or deps.impersonated
        or audience is None
        or audience.user_id != deps.run_person
        or audience.room_key is not None
        or audience.shared_transcript
    ):
        return None
    identity = [
        str(deps.organization_id),
        str(deps.run_person),
        str(deps.agent_id),
        str(deps.conversation_id),
    ]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


class DevicePipe:
    """An agent running on the person's computer, reached through the device hub."""

    def __init__(
        self,
        device: AgentCalls,
        harness: AcpHarness,
        *,
        state_scope: str | None = None,
        resume_key: str | None = None,
        fresh_session: bool = False,
        root: str | None = None,
        custom_agent_id: str | None = None,
        pi_key: NativeRuntimeKey | None = None,
        pi_model: str | None = None,
        platform_tools: bool = False,
        runtime_model: str | None = None,
    ) -> None:
        self._runtime_model = runtime_model
        self._platform_tools = platform_tools
        self._pi_model = pi_model
        self._pi_key = pi_key
        self._custom_agent_id = custom_agent_id
        self._resume_key = resume_key
        self._root = root
        self._fresh_session = fresh_session
        self._state_scope = state_scope
        self.session_id: str | None = None
        self.auth_method: str | None = None
        self.runtime_name: str | None = None
        self.model_prefix: str | None = None
        self.configuration_policy: Literal["session", "cli", "launch"] = "session"
        self.protocol: Literal["acp", "pi_rpc"] = "acp"
        self.refresh_catalog: bool = False
        self._device = device
        self._harness = harness
        self._id: str | None = None
        self._cursor = 0
        self._pending: deque[dict[str, Any]] = deque()

    async def open(self) -> None:
        args: dict[str, Any] = {"agent": self._harness}
        if self._runtime_model is not None:
            args["runtime_model"] = self._runtime_model
        if self._state_scope is not None:
            args["state_scope"] = self._state_scope
        if self._platform_tools:
            args["platform_tools"] = True
        if self._harness == "custom":
            args["accepted_protocols"] = ["acp", "pi_rpc"]
            args["supports_auth_modes"] = True
            args["supports_model_constraints"] = True
            args["supports_configuration_policy"] = True
        if self._pi_key is not None and self._pi_key.pi_provider is None:
            # Desktop sets it as GEMINI_API_KEY for the Antigravity key template only.
            args["gemini_key"] = self._pi_key.api_key.get_secret_value()
        elif self._pi_key is not None:
            if self._pi_model is None:
                raise AcpError("A Pi selected-key launch requires an exact model ID.")
            args["pi_key"] = self._pi_key.native_payload(self._pi_model)
        if self._custom_agent_id is not None:
            args["custom_agent_id"] = self._custom_agent_id
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
        if self._platform_tools and opened.get("platform_tools_version") != 1:
            await self.close()
            raise AcpError(
                "Update Desktop to admit this run-scoped platform tool bridge. No prompt was sent."
            )
        protocol = opened.get("protocol", "acp")
        if not isinstance(protocol, str) or protocol not in {"acp", "pi_rpc"}:
            await self.close()
            raise AcpError("The Desktop app requires an unsupported runtime protocol.")
        self.protocol = protocol
        if self._pi_key is not None and (
            (self._pi_key.pi_provider is None and opened.get("gemini_key") is not True)
            or (
                self._pi_key.pi_provider is not None
                and (protocol != "pi_rpc" or opened.get("pi_provider") != self._pi_key.provider)
            )
        ):
            await self.close()
            raise AcpError(
                "The Desktop registration did not admit this exact vault-key provider. No prompt was sent."
            )

        label = opened.get("runtime_name")
        if isinstance(label, str) and 0 < len(label) <= 120:
            self.runtime_name = label
        prefix = opened.get("model_prefix")
        if prefix is not None:
            if prefix != "opencode-go/":
                await self.close()
                raise AcpError("The Desktop app requires unsupported model constraints.")
            self.model_prefix = prefix
        policy = opened.get(
            "configuration_policy",
            "cli" if opened.get("auth_method") == "browser-auth" else "session",
        )
        if not isinstance(policy, str) or policy not in {"session", "cli", "launch"}:
            await self.close()
            raise AcpError("The Desktop app requires unsupported configuration policy.")
        self.configuration_policy = policy
        self.refresh_catalog = opened.get("refresh_catalog") is True
        method = opened.get("auth_method")
        if method is not None:
            if not isinstance(method, str) or method not in {
                "oauth-personal",
                "cursor_login",
                "cline",
                "browser-auth",
                "cached_token",
                "xai.api_key",
                "login",
                "devin-browser",
                "muse-cli",
                "muse-api-key",
            }:
                await self.close()
                raise AcpError("The Desktop app requires an unsupported authentication mode.")
            self.auth_method = method

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

    credentials: RuntimeCredentials | None = None
    cursor_account: bool = False

    tools: dict[str, _Tool] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    said: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    task_updates: list[str] = field(default_factory=list)
    config_options: object = None
    config_generation: int = 0

    def update(self, update: dict[str, Any]) -> list[LiveItem]:
        match update.get("sessionUpdate"):
            case "config_option_update":
                self.config_options = update.get("configOptions")
                self.config_generation += 1
                return []
            case "agent_message_chunk":
                text = (update.get("content") or {}).get("text")
                if isinstance(text, str):
                    if self.cursor_account and (
                        text.strip()
                        in {
                            "Please sign in to continue",
                            "Upgrade your plan to continue",
                            "Add a payment method to continue",
                            "Add a payment method to continue.",
                        }
                        or text.startswith(
                            "\n\nError: [unauthenticated] Backend rejected authentication."
                        )
                    ):
                        raise AcpError(
                            "Cursor requires account sign-in or a billing change. Check agent status and your plan; no other account was selected."
                        )
                    meta = update.get("_meta")
                    if isinstance(meta, dict) and meta.get("agenticosFinalAnswer") is True:
                        self.said = [text]
                    else:
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
        self,
        *,
        harness: AcpHarness,
        access: Access,
        outcome: str,
        answer: str,
        session_id: str | None,
    ) -> CodingReport:
        steps = [self.tools[key].step for key in self.order]
        changed = list(dict.fromkeys(path for key in self.order for path in self.tools[key].edits))
        return CodingReport(
            harness=harness,
            credentials=self.credentials,
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

    def __init__(
        self,
        pipe: Pipe,
        *,
        access: Access,
        collector: _Collector,
        shown: Shown,
        runtime_questions: RuntimeQuestionsCallback | None = None,
        platform_tools: RuntimeTools | None = None,
    ) -> None:
        self._pipe = pipe
        self._access = access
        self._collector = collector
        self._shown = shown
        self._platform_tools = platform_tools
        self._runtime_questions = runtime_questions
        self._human_scopes: dict[str | int, anyio.CancelScope] = {}
        self._ids = itertools.count(1)
        self._received_events = 0
        self._received_bytes = 0

    async def request(
        self, method: str, params: dict[str, Any], *, sent: anyio.Event | None = None
    ) -> dict[str, Any] | None:
        """Send a request and read until its answer, handling everything between."""
        if method == "session/prompt":
            await check_model_context()
        identifier = next(self._ids)
        await self._pipe.send(
            {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}
        )
        if sent is not None:
            sent.set()
        if self._runtime_questions is None and self._platform_tools is None:
            return await self._receive_result(identifier)
        try:
            async with anyio.create_task_group() as group:
                try:
                    return await self._receive_result(identifier, group)
                finally:
                    group.cancel_scope.cancel()
        except BaseExceptionGroup as errors:
            if len(errors.exceptions) == 1:
                raise errors.exceptions[0] from None
            raise

    @staticmethod
    def _human_request(message: Mapping[str, object]) -> bool:
        method = message.get("method")
        if method in (
            "cursor/ask_question",
            "cursor/create_plan",
            "x.ai/ask_user_question",
            "_agenticos/request_questions",
            "_agenticos/tools/list",
            "_agenticos/tools/call",
        ):
            return True
        raw = message.get("params")
        call = raw.get("toolCall") if isinstance(raw, dict) else None
        return (
            method == "session/request_permission"
            and isinstance(call, dict)
            and call.get("title") == "AskUserQuestion"
        )

    async def _answer_human(
        self, message: dict[str, Any], identifier: str | int, scope: anyio.CancelScope
    ) -> None:
        try:
            with scope:
                await self._handle(message)
        finally:
            self._human_scopes.pop(identifier, None)

    async def _receive_result(
        self, identifier: int, group: TaskGroup | None = None
    ) -> dict[str, Any] | None:
        while True:
            message = await self._pipe.receive()
            self._consume(message)
            if group is not None and message.get("method") == "_agenticos/cancel_request":
                params = message.get("params")
                native_id = params.get("id") if isinstance(params, dict) else None
                if (
                    type(native_id) in (str, int)
                    and (scope := self._human_scopes.get(native_id)) is not None
                ):
                    scope.cancel()
            elif group is not None and "id" in message and self._human_request(message):
                native_id = message["id"]
                if (
                    type(native_id) not in (str, int)
                    or len(str(native_id)) > 256
                    or native_id in self._human_scopes
                    or len(self._human_scopes) >= 8
                ):
                    raise AcpError(
                        "The runtime exceeded the human-input request limit or reused a pending identifier."
                    )
                scope = anyio.CancelScope()
                self._human_scopes[native_id] = scope
                group.start_soon(self._answer_human, message, native_id, scope)
            elif "method" in message:
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
                result = message.get("result")
                if result is not None and not isinstance(result, dict):
                    raise AcpError("The agent returned a non-object protocol result.")
                return result

    async def receive_update(self) -> None:
        """Consume a bounded unsolicited update, without submitting another prompt."""
        message = await self._pipe.receive()
        self._consume(message)
        await self._handle(message)

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
        if method in {"_agenticos/tools/list", "_agenticos/tools/call"}:
            if self._platform_tools is None:
                raise AcpError("This run has not enabled platform tools for the native runtime")
            result = await self._platform_tools.dispatch(method, params)
            await self._pipe.send({"jsonrpc": "2.0", "id": message["id"], "result": result})
            return
        human_permission = (
            method == "session/request_permission"
            and isinstance(params.get("toolCall"), dict)
            and params["toolCall"].get("title") == "AskUserQuestion"
        )
        if self._runtime_questions is not None and (
            method
            in {
                "cursor/ask_question",
                "cursor/create_plan",
                "x.ai/ask_user_question",
                "_agenticos/request_questions",
            }
            or human_permission
        ):
            from app.agents.capabilities.external_acp import _human

            handler = (
                _human.permission_question
                if human_permission
                else {
                    "cursor/ask_question": _human.cursor_questions,
                    "cursor/create_plan": _human.cursor_plan,
                    "x.ai/ask_user_question": _human.grok_questions,
                    "_agenticos/request_questions": _human.muse_questions,
                }[method]
            )
            try:
                human_reply = await handler(params, self._runtime_questions)
                await check_model_context()
            except ValueError, TypeError:
                cancelled = (
                    {"cancelled": True, "answers": []}
                    if method == "_agenticos/request_questions"
                    else {"outcome": "cancelled"}
                    if method == "x.ai/ask_user_question"
                    else {"outcome": {"outcome": "cancelled"}}
                )
                await self._pipe.send({"jsonrpc": "2.0", "id": message["id"], "result": cancelled})
                raise AcpError(
                    "The runtime's human-input request was unsupported or malformed. No answer or approval was invented."
                ) from None
            await self._pipe.send({"jsonrpc": "2.0", "id": message["id"], "result": human_reply})
            return
        if method == "session/request_permission":
            tool_call = params.get("toolCall")
            if isinstance(tool_call, dict) and tool_call.get("title") == "AskUserQuestion":
                await self._pipe.send(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {"outcome": {"outcome": "cancelled"}},
                    }
                )
                raise AcpError(
                    "The runtime needs a human answer. Its question was cancelled; continue in its CLI to review it."
                )
            reply = permission_reply(self._access, params)
            if reply["outcome"]["outcome"] == "cancelled" or _was_rejected(params, reply):
                title = (params.get("toolCall") or {}).get("title")
                self._collector.refused.append(clip(str(title or "a request")))
            await self._pipe.send({"jsonrpc": "2.0", "id": message["id"], "result": reply})
            return
        if method == "x.ai/ask_user_question":
            await self._pipe.send(
                {"jsonrpc": "2.0", "id": message["id"], "result": {"outcome": "cancelled"}}
            )
            raise AcpError(
                "Grok needs a human answer. Its request was cancelled; continue in the Grok CLI to review it."
            )
        if method in {"cursor/ask_question", "cursor/create_plan"}:
            await self._pipe.send(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {"outcome": {"outcome": "cancelled"}},
                }
            )
            raise AcpError(
                "Cursor needs a human answer or plan approval. Its request was cancelled; no answer or approval was invented. Continue in the Cursor CLI to review it."
            )
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
) -> Mapping[str, object]:
    """Apply choices and return the runtime's acknowledged session settings."""
    state: dict[str, object] = {}
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
        if category == "model" and option is None:
            legacy = (opened or {}).get("models")
            advertised = legacy.get("availableModels") if isinstance(legacy, dict) else None
            if isinstance(legacy, dict) and isinstance(advertised, list):
                if not any(
                    isinstance(item, dict) and item.get("modelId") == value for item in advertised
                ):
                    raise AcpError("This coding agent does not advertise the selected model")
                await conversation.request(
                    "session/set_model", {"sessionId": session_id, "modelId": value}
                )
                state["models"] = {**legacy, "currentModelId": value}
                continue
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
    return {**state, "configOptions": options}


def current_session_model(opened: Mapping[str, object] | None) -> str | None:
    """The session's advertised model, without guessing from a global default."""
    legacy = (opened or {}).get("models")
    if isinstance(legacy, dict) and isinstance(legacy.get("currentModelId"), str):
        return legacy["currentModelId"]
    options = (opened or {}).get("configOptions")
    if isinstance(options, list):
        for option in options:
            if isinstance(option, dict) and option.get("category") == "model":
                value = option.get("currentValue")
                return value if isinstance(value, str) else None
    return None


async def initialize_session(
    conversation: Conversation, *, require_version: bool = True, auth_method: str | None = None
) -> Mapping[str, object]:
    """Negotiate ACP and select an advertised login method without a billing fallback."""
    result = await conversation.request(
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "clientCapabilities": {},
            "clientInfo": {"name": "agenticos", "title": "AgenticOS"},
        },
    )
    initialized = result if isinstance(result, dict) else {}
    if require_version and (
        type(initialized.get("protocolVersion")) is not int
        or initialized["protocolVersion"] != PROTOCOL_VERSION
    ):
        raise AcpError("This program did not negotiate supported ACP protocol version 1.")
    if auth_method is not None:
        methods = initialized.get("authMethods")
        if not isinstance(methods, list) or not any(
            isinstance(method, dict) and method.get("id") == auth_method for method in methods
        ):
            raise AcpError(
                "This agent does not advertise the configured login method. Check its version and sign-in settings; no other account or billing mode was selected."
            )
        parameters: dict[str, object] = {"methodId": auth_method}
        if auth_method == "cached_token":
            if any(
                isinstance(method, dict) and method.get("id") == "xai.api_key" for method in methods
            ):
                raise AcpError(
                    "Grok account mode requires API-key authentication to be disabled. Check its version and configuration; no prompt was submitted."
                )
            parameters["_meta"] = {"headless": True}
        if auth_method == "xai.api_key":
            parameters["_meta"] = {"headless": True}
        await conversation.request("authenticate", parameters)
    return initialized


type CredentialProbe = Callable[[Conversation, str | None], Awaitable[RuntimeCredentials | None]]


async def run_task(
    pipe: Pipe,
    *,
    harness: AcpHarness,
    access: Access,
    root: str,
    task: str,
    timeout_seconds: int,
    shown: Shown,
    model: str | None = None,
    effort: str | None = None,
    previous_session: str | None = None,
    auth_method: str | None = None,
    model_prefix: str | None = None,
    credential_probe: CredentialProbe | None = None,
    configuration_policy: Literal["session", "cli", "launch"] = "session",
    remember: Callable[[str], Awaitable[None]] | None = None,
    steering: SteeringInbox | None = None,
    runtime_questions: RuntimeQuestionsCallback | None = None,
    platform_tools: RuntimeTools | None = None,
) -> CodingReport:
    """One task as one ACP session, ended however the task ends.

    Raises:
        AcpError: The agent could not be spoken to, or ended before it answered.
    """
    collector = _Collector(cursor_account=auth_method == "cursor_login")
    conversation = Conversation(
        pipe,
        access=access,
        collector=collector,
        shown=shown,
        runtime_questions=runtime_questions,
        platform_tools=platform_tools,
    )
    session_id: str | None = None
    try:
        stop = "timed_out"
        # One deadline from the first request: an adapter that never answers `initialize`
        # or `session/new` ends the task like one that never finishes the prompt.
        with anyio.move_on_after(timeout_seconds):
            if configuration_policy == "cli" and (model is not None or effort is not None):
                raise AcpError(
                    "This runtime manages model settings in its CLI configuration. Choose its model in the CLI and leave the external model ID empty; no configuration or prompt was sent."
                )
            initialized = await initialize_session(
                conversation, require_version=harness == "custom", auth_method=auth_method
            )
            if credential_probe is not None:
                collector.credentials = await credential_probe(conversation, auth_method)
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
            raw_capabilities = initialized.get("agentCapabilities")
            capabilities = raw_capabilities if isinstance(raw_capabilities, dict) else {}
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
            if model_prefix is not None:
                selected = model or current_session_model(opened)
                if (
                    selected is None
                    or not selected.startswith(model_prefix)
                    or selected == model_prefix
                ):
                    raise AcpError(
                        "This registration requires an opencode-go primary model. Inspect its catalog and set an exact Go model ID; no other provider was selected."
                    )
            if configuration_policy == "launch":
                if effort is not None:
                    raise AcpError(
                        "This runtime selects its model at launch; separate reasoning overrides are not supported"
                    )
                if model is not None and current_session_model(opened) != model:
                    raise AcpError(
                        "The runtime did not confirm the requested launch model. No prompt was sent"
                    )
                configured = opened or {}
            else:
                configured = await _configure_session(
                    conversation, session_id, opened, model=model, effort=effort
                )
            if model_prefix is not None and current_session_model(configured) != selected:
                raise AcpError(
                    "The agent did not confirm the selected Go model. No prompt was submitted."
                )
            if remember is not None:
                await remember(session_id)
            prompt = f"{_READ_ONLY_NOTE}{task}" if access == "read_only" else task
            result = await conversation.prompt(session_id, prompt, steering)
            reason = (result or {}).get("stopReason")
            if not isinstance(reason, str):
                raise AcpError("The agent did not report how its task ended.")
            stop = reason
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
        if auth_method == "cached_token" and stop == "end_turn" and not answer.strip():
            raise AcpError(
                "Grok returned no answer. Check its CLI authentication, plan and gateway; completion was not confirmed."
            )
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
