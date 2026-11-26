"""A Desktop-owned ACP conversation as the run's primary Pydantic AI model."""

import hashlib
import json
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import anyio
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from pydantic_ai import RunContext
from pydantic_ai.messages import (
    InstructionBaselinePart,
    InstructionDeltaPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStreamEvent,
    RetryFeedbackPart,
    SystemPromptPart,
    TextContent,
    TextPart,
    ThinkingPart,
    ToolAvailabilityDeltaPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.budget import assert_ambient_budget, record_ambient_usage
from app.agents.capabilities.coding_agent._acp import (
    AcpError,
    DevicePipe,
    private_state_scope,
    run_task,
)
from app.agents.capabilities.coding_agent._harness import Access, AcpHarness, LiveItem, Said
from app.agents.capabilities.coding_agent._narration import Narration
from app.agents.capabilities.coding_agent._redaction import redact_text
from app.agents.capabilities.external_acp._keys import selected_key
from app.agents.deps import AgentDeps
from app.agents.isolation import ToolClass
from app.agents.model_context import check_model_context
from app.agents.native_model_spec import current_native_context
from app.agents.runtime_questions import RuntimeQuestionRequest, RuntimeQuestionResponse
from app.agents.runtime_tools import RuntimeTools
from app.schemas.local_target import NativeHarness
from app.services.device_hub import DeviceWorkspace

_RECEIPT = "agenticos_native_conversation"


class NativeReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    scope: str = Field(pattern=r"^[a-f0-9]{64}$")
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    session_id: str = Field(min_length=1, max_length=256)


def history_rows(messages: list[ModelMessage]) -> list[JsonValue]:
    """Normalize conversation evidence independently of instruction checkpoints and usage."""
    rows: list[JsonValue] = []
    for message in messages:
        parts: list[JsonValue] = []
        for part in message.parts:
            if isinstance(part, TextPart):
                parts.append({"text": part.content})
            elif isinstance(part, UserPromptPart):
                content = [part.content] if isinstance(part.content, str) else part.content
                if any(not isinstance(item, (str, TextContent)) for item in content):
                    raise AcpError(
                        "Native conversation runtimes currently accept text only; use platform tools for files"
                    )
                parts.append(
                    {
                        "user": "\n".join(
                            item if isinstance(item, str) else item.content
                            for item in content
                            if isinstance(item, (str, TextContent))
                        )
                    }
                )
            elif isinstance(part, ToolCallPart):
                parts.append(
                    {
                        "tool": part.tool_name,
                        "arguments": part.args_as_json_str(),
                        "id": part.tool_call_id,
                    }
                )
            elif isinstance(part, ToolReturnPart):
                parts.append({"tool_result": part.model_response_str(), "id": part.tool_call_id})
            elif isinstance(part, RetryFeedbackPart) or part.part_kind == "retry-prompt":
                parts.append({"correction": part.model_response()})
            elif isinstance(
                part,
                (
                    SystemPromptPart,
                    InstructionBaselinePart,
                    InstructionDeltaPart,
                    ToolAvailabilityDeltaPart,
                    ThinkingPart,
                ),
            ):
                continue
            else:
                raise AcpError(
                    "This conversation contains content the native text runtime cannot represent safely"
                )
        rows.append({"role": message.kind, "parts": parts})
    return rows


def _digest(rows: list[JsonValue]) -> str:
    return hashlib.sha256(
        json.dumps(
            [row for row in rows if not isinstance(row, dict) or row.get("parts") != []],
            ensure_ascii=True,
            sort_keys=True,
        ).encode()
    ).hexdigest()


class NativeConversationModel(Model):
    def __init__(
        self,
        *,
        harness: NativeHarness,
        epoch: str,
        access: Access,
        native_model: str | None = None,
        readonly_tools: Mapping[str, ToolClass] | None = None,
        timeout_seconds: int = 900,
        registration_id: str | None = None,
        secret_id: UUID | None = None,
    ) -> None:
        super().__init__()
        if (harness == "external") != (registration_id is not None):
            raise AcpError("Only an external runtime runs through a Desktop registration")
        if secret_id is not None and registration_id is None:
            raise AcpError("Only an external runtime receives a vault key")
        self.registration_id = registration_id
        self.secret_id = secret_id
        self.harness = harness
        self.epoch = epoch
        self.access = access
        self.native_model = native_model
        self.readonly_tools = readonly_tools
        self.timeout_seconds = timeout_seconds

    @property
    def model_name(self) -> str:
        return f"native-{self.harness}"

    @property
    def system(self) -> str:
        return self.model_name

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        ctx = current_native_context()
        if ctx is None:
            raise AcpError("A native primary conversation requires its owned run context")

        async def discard(_text: str) -> None:
            return None

        return await self._run(ctx, messages, model_request_parameters, discard)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[AgentDeps] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        ctx = run_context or current_native_context()
        if ctx is None:
            raise AcpError("A native primary conversation requires its owned run context")
        sender, receiver = anyio.create_memory_object_stream[str](16)
        stream = NativeStream(
            model_request_parameters=model_request_parameters, native=self, receiver=receiver
        )

        async def produce(*, task_status: TaskStatus[None]) -> None:
            with anyio.CancelScope() as scope:
                stream.cancel_scope = scope
                task_status.started()
                try:
                    stream.response = await self._run(
                        ctx, messages, model_request_parameters, sender.send
                    )
                except BaseException as error:
                    stream.error = error
                finally:
                    with anyio.CancelScope(shield=True):
                        await sender.aclose()
                        stream.closed.set()

        try:
            async with anyio.create_task_group() as group:
                await group.start(produce)
                try:
                    yield stream
                finally:
                    group.cancel_scope.cancel()
                    await receiver.aclose()
        except BaseExceptionGroup as errors:
            if len(errors.exceptions) == 1:
                raise errors.exceptions[0] from None
            raise

    async def _run(
        self,
        ctx: RunContext[AgentDeps],
        messages: list[ModelMessage],
        parameters: ModelRequestParameters,
        text: Callable[[str], Awaitable[None]],
    ) -> ModelResponse:
        deps = ctx.deps
        audience = deps.audience
        workspace = ctx.workspace.backend if ctx.workspace.attached else None
        if (
            not isinstance(workspace, DeviceWorkspace)
            or not workspace.local_coding_allowed
            or deps.run_person is None
            or workspace.owner_id != deps.run_person
            or deps.user_id != str(deps.run_person)
            or deps.organization_id is None
            or deps.conversation_id is None
            or deps.impersonated
            or audience is None
            or audience.user_id != deps.run_person
            or audience.room_key is not None
            or audience.shared_transcript
        ):
            raise AcpError(
                "Native primary conversations require the initiating member's private approved full-access computer"
            )
        if parameters.output_mode != "text" or parameters.output_tools or parameters.native_tools:
            raise AcpError(
                "This native primary runtime supports text answers and scoped platform function tools"
            )
        await check_model_context()
        await assert_ambient_budget()
        root = await workspace.working_dir()
        instructions = next(
            (
                message.instructions
                for message in reversed(messages)
                if isinstance(message, ModelRequest) and message.instructions
            ),
            "",
        )
        system = [
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, SystemPromptPart)
        ]
        scope = _digest(
            [
                str(deps.organization_id),
                str(deps.run_person),
                str(deps.agent_id),
                str(deps.conversation_id),
                root,
                self.harness,
                self.epoch,
                self.access,
                self.native_model,
                self.registration_id,
                str(self.secret_id) if self.secret_id is not None else None,
            ]
        )
        rows = history_rows(messages)
        previous: NativeReceipt | None = None
        start = 0
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if not isinstance(message, ModelResponse):
                continue
            raw = (message.provider_details or {}).get(_RECEIPT)
            if raw is None:
                continue
            try:
                receipt = NativeReceipt.model_validate(raw)
            except ValidationError as invalid:
                raise AcpError(
                    "The native conversation receipt is incompatible; reset the native session explicitly"
                ) from invalid
            if receipt.scope == scope:
                if _digest(rows[: index + 1]) != receipt.digest:
                    raise AcpError(
                        "Conversation history changed since native settlement; reset the native session explicitly"
                    )
                previous, start = receipt, index + 1
                break
        prompt = json.dumps(
            {
                "agent_instructions": instructions,
                "system_context": system,
                "conversation_context": rows[start:],
            },
            ensure_ascii=False,
        )
        if len(prompt.encode()) > 2 << 20:
            raise AcpError("The native conversation context exceeds the 2 MiB admission limit")
        acp_harness: AcpHarness = "custom" if self.harness == "external" else self.harness
        # Desktop admits a Gemini vault key only for the Antigravity key template.
        key = await selected_key(ctx, "gemini" if self.secret_id else None, self.secret_id)
        pipe = DevicePipe(
            workspace,
            acp_harness,
            resume_key=scope,
            platform_tools=True,
            custom_agent_id=self.registration_id,
            runtime_model=self.native_model,
            # Hermes keeps one home per private conversation; other runtimes ignore it.
            state_scope=private_state_scope(deps),
            pi_key=key,
        )
        narration = Narration.for_call(deps, f"primary-runtime-{uuid4()}", acp_harness)
        said: list[str] = []
        size = 0
        redactions = (key.api_key.get_secret_value(),) if key is not None else ()
        tools = RuntimeTools(
            ctx,
            readonly_tools=(self.readonly_tools or {}) if self.access == "read_only" else None,
            secrets=redactions,
        )

        async def shown(items: list[LiveItem]) -> None:
            nonlocal size
            activity: list[LiveItem] = []
            for item in items:
                if isinstance(item, Said):
                    size += len(item.text)
                    if size > 128000:
                        raise AcpError(
                            "The native conversation answer exceeded its retention limit"
                        )
                    said.append(item.text)
                    # A key can span chunks, so a keyed run shows only the redacted whole answer.
                    if not redactions:
                        await text(item.text)
                else:
                    activity.append(item)
            if not redactions:
                await narration.shown(activity)

        async def questions(request: RuntimeQuestionRequest) -> RuntimeQuestionResponse:
            dumped = request.model_dump_json()
            if any(json.dumps(value)[1:-1] in dumped for value in redactions):
                raise AcpError(
                    "The runtime put credential material in a human-input request. No question was shown."
                )
            callback = deps.runtime_questions
            return (
                await callback(request)
                if callback is not None
                else RuntimeQuestionResponse(cancelled=True)
            )

        await narration.started("Primary conversation runtime")
        settled = False
        try:
            await pipe.open()
            if pipe.protocol != "acp":
                raise AcpError(
                    "This Desktop registration does not speak ACP and can only take delegated tasks. No prompt was sent."
                )
            if pipe.session_id != (previous.session_id if previous is not None else None):
                raise AcpError(
                    "The native session has no matching settled conversation receipt; reset it explicitly before continuing"
                )
            report = await run_task(
                pipe,
                harness=acp_harness,
                access=self.access,
                root=root,
                task=prompt,
                timeout_seconds=self.timeout_seconds,
                shown=shown,
                model=self.native_model,
                previous_session=pipe.session_id,
                auth_method=pipe.auth_method,
                configuration_policy=pipe.configuration_policy,
                model_prefix=pipe.model_prefix,
                remember=pipe.remember,
                runtime_questions=questions if redactions else deps.runtime_questions,
                platform_tools=tools,
            )
            if report.outcome != "completed" or not report.session_id:
                raise AcpError(
                    "The native conversation did not settle successfully; check effects before resetting or continuing"
                )
            answer = redact_text("".join(said) or report.answer, redactions)
            if not answer:
                raise AcpError("The native conversation settled without a text answer")
            if not said or redactions:
                await text(answer)
            response = ModelResponse(
                [TextPart(answer)],
                model_name=self.model_name,
                provider_name=self.system,
                usage=RequestUsage(unmeasured_requests=1),
                finish_reason="stop",
            )
            receipt = NativeReceipt(
                scope=scope,
                digest=_digest([*rows, *history_rows([response])]),
                session_id=report.session_id,
            )
            response.provider_details = {
                _RECEIPT: receipt.model_dump(),
                "native_usage_opaque": True,
            }
            settled = True
            await narration.finished("completed")
            return response
        finally:
            with anyio.CancelScope(shield=True), anyio.fail_after(15):
                try:
                    await pipe.close()
                except BaseException:
                    if settled:
                        record_ambient_usage(
                            self.model_name, RequestUsage(unmeasured_requests=1), self.system
                        )
                    raise
                finally:
                    if not settled:
                        record_ambient_usage(
                            self.model_name, RequestUsage(unmeasured_requests=1), self.system
                        )
                        await narration.finished(
                            "failed",
                            error="Native conversation ended without a settled receipt; verify effects before resetting",
                        )


@dataclass(kw_only=True)
class NativeStream(StreamedResponse):
    native: NativeConversationModel
    receiver: MemoryObjectReceiveStream[str]
    response: ModelResponse | None = None
    error: BaseException | None = None
    cancel_scope: anyio.CancelScope | None = None
    closed: anyio.Event = field(default_factory=anyio.Event)
    _timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
        async for text in self.receiver:
            for event in self._parts_manager.handle_text_delta(
                vendor_part_id="native-answer", content=text
            ):
                yield event
        if self.cancelled:
            return
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AcpError("The native conversation stream ended without settlement")
        self._usage = self.response.usage

    async def close_stream(self) -> None:
        if self.cancel_scope is not None:
            self.cancel_scope.cancel()
            with anyio.CancelScope(shield=True), anyio.fail_after(20):
                await self.closed.wait()

    def get(self) -> ModelResponse:
        response = super().get()
        return replace(
            response,
            provider_details=self.response.provider_details
            if self.response and not self.cancelled
            else None,
            finish_reason="stop" if self.response and not self.cancelled else None,
            state="interrupted" if self.cancelled else response.state,
        )

    @property
    def model_name(self) -> str:
        return self.native.model_name

    @property
    def provider_name(self) -> str:
        return self.native.system

    @property
    def provider_url(self) -> None:
        return None

    @property
    def timestamp(self) -> datetime:
        return self._timestamp
