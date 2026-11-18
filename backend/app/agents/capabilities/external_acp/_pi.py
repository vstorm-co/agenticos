"""Pi's native JSONL RPC lifecycle, separate from ACP and direct model APIs."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

import anyio
from anyio.abc import TaskGroup
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.agents.capabilities.coding_agent._acp import AcpError, Pipe, Shown
from app.agents.capabilities.coding_agent._harness import (
    CodingReport,
    CodingStep,
    LiveItem,
    RuntimeCredentials,
    Said,
    StepEnded,
    StepStarted,
    bounded,
    last_steps,
)
from app.agents.capabilities.external_acp._catalog import AcpCatalog, AcpChoice
from app.agents.model_context import check_model_context
from app.agents.pi_keys import PiKeyProvider
from app.agents.runtime_questions import RuntimeQuestionsCallback
from app.agents.runtime_tools import RuntimeTools


class _Record(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, strict=True)
    type: str
    id: str | None = None
    command: str | None = None
    success: bool | None = None
    data: dict[str, JsonValue] = Field(default_factory=dict)
    method: str | None = None
    message: dict[str, JsonValue] | str = Field(default_factory=dict)
    title: str | None = None
    options: list[str] = Field(default_factory=list, max_length=128)
    prefill: str | None = Field(default=None, max_length=32000)
    secret: bool = False
    isPassword: bool = False
    timeout: float | None = Field(default=None, gt=0, le=3600000)
    assistantMessageEvent: dict[str, JsonValue] = Field(default_factory=dict)
    aborted: bool = False
    toolCallId: str | None = None
    toolName: str | None = None
    isError: bool = False


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, strict=True)
    provider: str = Field(min_length=1, max_length=120)
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.id}"


class _State(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, strict=True)
    model: _Model | None = None
    sessionId: str = Field(min_length=1, max_length=256)
    sessionFile: str | None = Field(default=None, max_length=4096)
    isStreaming: bool
    isCompacting: bool
    pendingMessageCount: int = Field(ge=0)


class _Models(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, strict=True)
    models: list[_Model] = Field(max_length=2048)


@dataclass
class _Session:
    pipe: Pipe
    shown: Shown
    runtime_questions: RuntimeQuestionsCallback | None = None
    platform_tools: RuntimeTools | None = None
    tool_scopes: dict[str, anyio.CancelScope] = field(default_factory=dict)
    retired_tools: set[str] = field(default_factory=set)
    question_group: TaskGroup | None = None
    pending_questions: set[str] = field(default_factory=set)
    settled: bool = False
    received: int = 0
    sequence: int = 0
    answer: str = ""
    stop_reason: str | None = None
    steps: list[CodingStep] = field(default_factory=list)
    active: dict[str, CodingStep] = field(default_factory=dict)

    async def receive(self) -> _Record:
        self.received += 1
        if self.received > 16384:
            raise AcpError("Pi exceeded the task event limit. Narrow the task before retrying.")
        raw = await self.pipe.receive()
        if raw.get("method") == "_agenticos/cancel_request":
            params = raw.get("params")
            identifier = params.get("id") if isinstance(params, dict) else None
            if (
                isinstance(identifier, str)
                and (scope := self.tool_scopes.get(identifier)) is not None
            ):
                scope.cancel()
            return _Record(type="agenticos_bridge")
        if raw.get("method") in {"_agenticos/tools/list", "_agenticos/tools/call"}:
            identifier = raw.get("id")
            if (
                not isinstance(identifier, str)
                or len(identifier) > 256
                or identifier in self.tool_scopes
                or identifier in self.retired_tools
                or len(self.tool_scopes) >= 8
                or len(self.retired_tools) >= 4096
                or self.question_group is None
                or self.platform_tools is None
            ):
                raise AcpError(
                    "This Pi platform request is unadmitted or exceeded its lifetime limits"
                )
            scope = anyio.CancelScope()
            self.tool_scopes[identifier] = scope
            self.question_group.start_soon(self.answer_tool, raw, identifier, scope)
            return _Record(type="agenticos_bridge")
        try:
            record = _Record.model_validate(raw)
        except ValidationError as invalid:
            raise AcpError(
                "Pi returned an unsupported RPC record. Check the installed Pi version."
            ) from invalid
        if record.type == "extension_ui_request":
            if record.method in {"select", "confirm", "input", "editor"}:
                if record.id is None:
                    raise AcpError("Pi sent a dialog without an identifier.")
                if self.runtime_questions is not None and self.question_group is not None:
                    if record.id in self.pending_questions or len(self.pending_questions) >= 8:
                        raise AcpError(
                            "Pi exceeded the pending human-input limit or reused a dialog identifier."
                        )
                    self.pending_questions.add(record.id)
                    self.question_group.start_soon(self.answer_dialog, record)
                    return record
                await self.pipe.send(
                    {"type": "extension_ui_response", "id": record.id, "cancelled": True}
                )
                raise AcpError(
                    "Pi requested human input. Continue in its CLI; no answer or approval was invented."
                )
        elif record.type == "extension_error":
            raise AcpError("A Pi extension failed. Review the extension in Pi before continuing.")
        return record

    async def answer_tool(
        self, message: dict[str, object], identifier: str, scope: anyio.CancelScope
    ) -> None:
        try:
            with scope:
                params = message.get("params")
                method = message.get("method")
                if (
                    not isinstance(params, dict)
                    or not isinstance(method, str)
                    or self.platform_tools is None
                ):
                    raise AcpError("Malformed Pi platform tool request")
                result = await self.platform_tools.dispatch(method, params)
                await self.pipe.send({"jsonrpc": "2.0", "id": identifier, "result": result})
        finally:
            self.tool_scopes.pop(identifier, None)
            self.retired_tools.add(identifier)

    async def answer_dialog(self, record: _Record) -> None:
        from ._human import pi_dialog

        reply: dict[str, object] = {"cancelled": True}
        try:
            with anyio.move_on_after(record.timeout / 1000 if record.timeout is not None else None):
                try:
                    reply = await pi_dialog(record.model_dump(), self.runtime_questions)
                    await check_model_context()
                except ValueError, TypeError:
                    await self.pipe.send(
                        {"type": "extension_ui_response", "id": record.id, "cancelled": True}
                    )
                    raise AcpError(
                        "Pi sent an unsupported human-input request. No answer was invented."
                    ) from None
            await self.pipe.send({"type": "extension_ui_response", "id": record.id, **reply})
        finally:
            if record.id is not None:
                self.pending_questions.discard(record.id)

    async def request(self, command: str, **params: JsonValue) -> dict[str, JsonValue]:
        self.sequence += 1
        identifier = f"agenticos-{self.sequence}"
        await self.pipe.send({"id": identifier, "type": command, **params})
        while True:
            record = await self.receive()
            if record.type == "response":
                if (
                    record.id != identifier
                    or record.command != command
                    or record.success is not True
                ):
                    raise AcpError(
                        "Pi refused or mismatched an RPC command. Check its login, version and selected model."
                    )
                return record.data
            # The reader is installed before prompt submission: fast updates may
            # precede acceptance. Never drop them while waiting for its response.
            await self.event(record)

    async def event(self, record: _Record) -> None:
        items: list[LiveItem] = []
        if record.type == "agent_settled":
            self.settled = True
            if record.aborted:
                self.stop_reason = "aborted"
        elif record.type == "message_update":
            event = record.assistantMessageEvent
            delta = event.get("delta")
            if event.get("type") == "text_delta" and isinstance(delta, str):
                items.append(Said(delta[:32000]))
        elif (
            record.type == "message_end"
            and isinstance(record.message, dict)
            and record.message.get("role") == "assistant"
        ):
            content = record.message.get("content")
            if not isinstance(content, list):
                raise AcpError("Pi returned malformed assistant content.")
            if any(not isinstance(part, dict) for part in content):
                raise AcpError("Pi returned malformed assistant content.")
            text = "".join(
                text
                for part in content
                if isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(text := part.get("text"), str)
            )
            if len(text) > 128000:
                raise AcpError("Pi's answer exceeded the retained output limit.")
            self.answer = text
            reason = record.message.get("stopReason")
            self.stop_reason = reason if isinstance(reason, str) else None
        elif record.type == "tool_execution_start":
            key, name = record.toolCallId, record.toolName
            if key is None or name is None or key in self.active or len(self.steps) >= 512:
                raise AcpError("Pi returned an invalid or excessive tool lifecycle.")
            step = CodingStep(kind="other", title=name[:200])
            self.steps.append(step)
            self.active[key] = step
            items.append(StepStarted(key, step))
        elif record.type == "tool_execution_end":
            key = record.toolCallId
            if key is None or key not in self.active:
                raise AcpError("Pi ended an unknown tool call.")
            self.active.pop(key).failed = record.isError
            items.append(StepEnded(key, record.isError))
        if items:
            await self.shown(items)

    async def state(self) -> _State:
        try:
            state = _State.model_validate(await self.request("get_state"))
        except ValidationError as invalid:
            raise AcpError("Pi returned an unsupported session state.") from invalid
        if state.isStreaming or state.isCompacting or state.pendingMessageCount:
            raise AcpError(
                "Pi's session is already active. Finish it in Pi or start a fresh session explicitly."
            )
        return state

    async def stop(self) -> None:
        # Abort alone continues queued work in Pi. Clear it first, then stop the
        # active turn; the Desktop close also reaps this owned process tree.
        await self.pipe.send({"type": "clear_queue"})
        await self.pipe.send({"type": "abort"})


async def _ignore(_items: list[LiveItem]) -> None:
    return None


async def inspect_pi(
    pipe: Pipe, *, timeout_seconds: int, key_provider: PiKeyProvider | None = None
) -> AcpCatalog:
    session = _Session(pipe, _ignore)
    try:
        with anyio.fail_after(timeout_seconds):
            state = await session.state()
            try:
                models = _Models.model_validate(
                    await session.request("get_available_models")
                ).models
            except ValidationError as invalid:
                raise AcpError(
                    "Pi returned an unsupported or excessive model catalog. Narrow its configured models."
                ) from invalid
            choices = [
                AcpChoice(id=model.key, name=model.name)
                for model in models
                if key_provider is None or model.provider == key_provider
            ]
            if len({choice.id for choice in choices}) != len(choices):
                raise AcpError("Pi returned duplicate model identities.")
            if (
                key_provider is not None
                and state.model is not None
                and state.model.provider != key_provider
            ):
                raise AcpError("Pi opened another provider in a selected-key session.")
            current = state.model.key if state.model else None
            if current is not None:
                choices = sorted(choices, key=lambda choice: choice.id != current)
            return AcpCatalog(
                credentials=RuntimeCredentials(
                    kind="api_key", source="vault", sign_out_available=False
                )
                if key_provider is not None
                else None,
                models_truncated=len(choices) > 128,
                configuration_policy="session" if key_provider is not None else "cli",
                models_exposed=True,
                models=choices[:128],
                current_model=state.model.key if state.model else None,
            )
    finally:
        with anyio.CancelScope(shield=True):
            await pipe.close()


async def run_pi(
    pipe: Pipe,
    *,
    task: str,
    timeout_seconds: int,
    shown: Shown,
    previous_session: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    remember: Callable[[str], Awaitable[None]] | None = None,
    runtime_questions: RuntimeQuestionsCallback | None = None,
    key_provider: PiKeyProvider | None = None,
    platform_tools: RuntimeTools | None = None,
) -> CodingReport:
    session = _Session(
        pipe, shown, runtime_questions=runtime_questions, platform_tools=platform_tools
    )
    timed_out = False
    identifier: str | None = None
    try:
        with anyio.move_on_after(timeout_seconds) as deadline:
            async with anyio.create_task_group() as group:
                session.question_group = group
                try:
                    if (model is not None or effort is not None) and key_provider is None:
                        raise AcpError(
                            "Pi model settings belong to its CLI. Choose the provider/model there and leave the external model ID empty."
                        )
                    await check_model_context()
                    opened = (
                        await session.request("switch_session", sessionPath=previous_session)
                        if previous_session is not None
                        else await session.request("new_session")
                    )
                    if opened.get("cancelled") is not False:
                        raise AcpError(
                            "A Pi extension refused to open the requested session. No prompt was sent."
                        )
                    if key_provider is not None:
                        if (
                            model is None
                            or not model.startswith(f"{key_provider}/")
                            or effort is not None
                        ):
                            raise AcpError(
                                "Select an exact model from this Pi key provider without a reasoning override."
                            )
                        try:
                            available = _Models.model_validate(
                                await session.request("get_available_models")
                            ).models
                        except ValidationError as invalid:
                            raise AcpError("Pi returned an unsupported model catalog.") from invalid
                        if sum(entry.key == model for entry in available) != 1:
                            raise AcpError(
                                "The selected model is not uniquely available from this Pi provider. No prompt was sent."
                            )
                        await session.request(
                            "set_model", provider=key_provider, modelId=model.partition("/")[2]
                        )
                    state = await session.state()
                    if key_provider is not None and (
                        state.model is None or state.model.key != model
                    ):
                        raise AcpError(
                            "Pi did not acknowledge the selected API-key provider and model. No prompt was sent."
                        )
                    identifier = state.sessionId
                    if state.model is None:
                        raise AcpError(
                            "Pi has no configured model. Choose a provider, complete its login and select a model in Pi first."
                        )
                    if remember is not None:
                        if not state.sessionFile:
                            raise AcpError(
                                "Pi did not expose persistent session storage. No prompt was sent."
                            )
                        await remember(state.sessionFile)
                    await check_model_context()
                    session.settled = False
                    session.answer = ""
                    session.stop_reason = None
                    session.steps.clear()
                    session.active.clear()
                    accepted = await session.request("prompt", message=task)
                    if accepted.get("disposition") != "started":
                        raise AcpError(
                            "Pi did not start this prompt. An extension handled it or queued it; completion was not confirmed."
                        )
                    while not session.settled:
                        record = await session.receive()
                        if record.type == "response":
                            raise AcpError(
                                "Pi returned an unexpected RPC response during the task."
                            )
                        await session.event(record)
                finally:
                    group.cancel_scope.cancel()
        timed_out = deadline.cancel_called
        completed = session.settled and session.stop_reason == "stop" and not session.active
        outcome: Literal["completed", "failed", "timed_out"] = (
            "timed_out" if timed_out else "completed" if completed else "failed"
        )
        answer = (
            bounded(session.answer)
            if completed
            else "Pi did not complete this task. Check its CLI account, model and quota; work may already have occurred."
        )
        return CodingReport(
            credentials=RuntimeCredentials(kind="api_key", source="vault", sign_out_available=False)
            if key_provider is not None
            else None,
            harness="custom",
            access="edit",
            outcome=outcome,
            answer=answer,
            session_id=identifier,
            steps=last_steps(session.steps),
        )
    except BaseExceptionGroup as errors:
        if len(errors.exceptions) == 1:
            raise errors.exceptions[0] from None
        raise
    finally:
        with anyio.CancelScope(shield=True):
            try:
                if not session.settled:
                    await session.stop()
            finally:
                await pipe.close()
