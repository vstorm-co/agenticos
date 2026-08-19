"""What a run actually handed its model, recorded from the wire.

A run row says what an agent cost and how it ended. A transcript says what was
asked and what came back. Neither answers the question an operator asks third
and asks hardest: **what did the model actually get** - which system prompt,
which tools, described how, under which settings, and how many times was it
asked before it answered.

That is not derivable after the fact. The spec is versioned, but the prompt the
model saw is the spec's instructions plus the platform's own, plus whatever a
channel binding appended, plus the skills that were bound, plus a system
reminder that fires every N requests; and the tool schemas are assembled from
the capability registry, the MCP servers the organization connected and whatever
tool search decided to reveal. Reconstructing all of that from the stored spec is
a second implementation of the builder, and a second implementation is a thing
that disagrees.

So it is recorded rather than reconstructed. :class:`RecordingModel` wraps the
model the agent was built with - the same trick `MeteredModel` uses to book a
sub-agent's spend - and writes down each request as it passes: the instructions,
the tool definitions exactly as the provider was handed them, the settings, and
what came back. What is stored is therefore what was sent, and cannot drift from
it.

**Nothing here reads a secret, and one thing here actively drops them.**
`ModelSettings` carries `extra_headers` and `extra_body`, which is where a
provider-specific credential rides; :func:`_settings` keeps the documented
scalars and discards the rest, so the manifest cannot become the second place a
key is written down.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    ToolCallPart,
)
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext

# What a model setting may be, when it is written down. Everything else on
# `ModelSettings` - `extra_headers`, `extra_body` - is provider passthrough, and
# passthrough is exactly where a credential travels.
_RECORDED_SETTINGS = frozenset(
    {
        "frequency_penalty",
        "logit_bias",
        "max_tokens",
        "parallel_tool_calls",
        "presence_penalty",
        "seed",
        "service_tier",
        "stop_sequences",
        "temperature",
        "thinking",
        "timeout",
        "tool_choice",
        "top_k",
        "top_p",
    }
)


@dataclass(slots=True)
class RecordedTool:
    """One tool as the provider was told about it.

    The description is the half nobody can see anywhere else and the half that
    decides behaviour: an agent that never calls a tool it has is usually an
    agent whose tool describes itself badly, and until this was recorded the only
    way to read that sentence was to run the agent again with a debugger
    attached.
    """

    name: str
    description: str | None
    parameters_json_schema: dict[str, Any]
    #: `output` for the tool that carries a structured answer, `function` otherwise.
    kind: str


@dataclass(slots=True)
class RecordedRequest:
    """One model request, and what it cost in time.

    A run is one row with one duration, and a run that took forty seconds is
    either one slow request or nine quick ones with eight tool calls between
    them. Those are opposite problems and the run row cannot tell them apart.
    """

    index: int
    started_at: datetime
    duration_ms: int
    model: str | None
    #: How much history the request carried - the size the run is really paying for.
    message_count: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    #: What the model asked to call next. Empty on the request that answered.
    tool_calls: list[str]
    finish_reason: str | None
    #: The exception class, where the request raised. Never its message: a
    #: provider SDK puts the failing URL, and therefore a key, in that string.
    failed: str | None = None


@dataclass
class RunRecorder:
    """Everything one run handed a model, gathered as it happened.

    Built per run and held on :class:`~app.agents.factory.BuiltAgent`, so the
    surface that persists a run is the surface that has it. Empty for a run that
    never reached a model - refused by a budget before its first request - which
    is a true statement about that run rather than a gap.
    """

    instructions: str | None = None
    system_prompts: list[str] = field(default_factory=list)
    tools: list[RecordedTool] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    requests: list[RecordedRequest] = field(default_factory=list)
    #: The last request's messages, dumped. The whole of what the model saw at
    #: the end of the run - retries, tool returns and reminders included, which
    #: the conversation transcript deliberately does not show.
    messages: list[dict[str, Any]] = field(default_factory=list)

    def observe_request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        parameters: ModelRequestParameters,
    ) -> None:
        """Take down what is about to be sent.

        The prompt and the tools are overwritten rather than appended: they are
        properties of the agent, not of one request, and a run whose tool set
        changes mid-way - tool search revealing a deferred server - should read
        as what the model ended up with. What each request *cost* is appended,
        because that is per request and is the whole of the waterfall.
        """
        self.instructions = _instructions(messages) or self.instructions
        self.system_prompts = _system_prompts(messages) or self.system_prompts
        self.tools = _tools(parameters)
        self.settings = _settings(model_settings)
        self.messages = ModelMessagesTypeAdapter.dump_python(messages, mode="json")

    def observe_response(
        self, response: ModelResponse, *, started: datetime, elapsed_ms: int, messages: int
    ) -> None:
        """Take down what came back, and how long it took."""
        usage = response.usage
        self.requests.append(
            RecordedRequest(
                index=len(self.requests),
                started_at=started,
                duration_ms=elapsed_ms,
                model=response.model_name,
                message_count=messages,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                tool_calls=[
                    part.tool_name for part in response.parts if isinstance(part, ToolCallPart)
                ],
                finish_reason=response.finish_reason,
            )
        )

    def observe_failure(
        self, exc: BaseException, *, started: datetime, elapsed_ms: int, messages: int
    ) -> None:
        """Take down a request that never came back.

        Recorded because it is the request an operator is looking for. A run that
        failed after four successful requests and one that failed on its first
        are the same red row otherwise.
        """
        self.requests.append(
            RecordedRequest(
                index=len(self.requests),
                started_at=started,
                duration_ms=elapsed_ms,
                model=None,
                message_count=messages,
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                tool_calls=[],
                finish_reason=None,
                failed=type(exc).__name__,
            )
        )


class RecordingModel(WrapperModel):
    """The agent's model, writing down what passes through it.

    Wrapping the model rather than reading the agent is what makes this
    trustworthy: `ModelRequestParameters.function_tools` is the list the provider
    is handed, after every `prepare` hook, after tool search has hidden what it
    hides, and after the output tool has been added. Anything assembled from the
    spec instead would be a good guess.

    `perf_counter` measures the interval and a wall clock stamps it: one is
    monotonic and the only honest way to time a request, the other is what a
    reader compares against the run's own start time.
    """

    def __init__(self, wrapped: Model, recorder: RunRecorder) -> None:
        super().__init__(wrapped)
        self.recorder = recorder

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        self.recorder.observe_request(messages, model_settings, model_request_parameters)
        started, clock = datetime.now(UTC), time.perf_counter()
        try:
            response = await self.wrapped.request(
                messages, model_settings, model_request_parameters
            )
        except Exception as exc:
            self.recorder.observe_failure(
                exc, started=started, elapsed_ms=_since(clock), messages=len(messages)
            )
            raise
        self.recorder.observe_response(
            response, started=started, elapsed_ms=_since(clock), messages=len(messages)
        )
        return response

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        self.recorder.observe_request(messages, model_settings, model_request_parameters)
        started, clock = datetime.now(UTC), time.perf_counter()
        async with self.wrapped.request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as stream:
            yield stream
            # After the block, because a streamed response is only complete once
            # the caller has consumed it: read before that, the usage is zero and
            # the finish reason is not yet known.
            self.recorder.observe_response(
                stream.get(), started=started, elapsed_ms=_since(clock), messages=len(messages)
            )


def _since(clock: float) -> int:
    """Milliseconds since a `perf_counter` mark."""
    return int((time.perf_counter() - clock) * 1000)


def _instructions(messages: list[ModelMessage]) -> str | None:
    """The instructions on the last request, which is where they are carried."""
    for message in reversed(messages):
        if isinstance(message, ModelRequest) and message.instructions:
            return message.instructions
    return None


def _system_prompts(messages: list[ModelMessage]) -> list[str]:
    """Whatever was sent as a system part, in order.

    Separate from the instructions because they are separate on the wire: an
    agent built with `system_prompt=` sends one of these, and a capability that
    injects a reminder sends another. A reader comparing what the spec says with
    what the model was told needs both halves.
    """
    return [
        part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, SystemPromptPart)
    ]


def _tools(parameters: ModelRequestParameters) -> list[RecordedTool]:
    """Every tool the provider was told about, function tools and output alike."""
    return [
        RecordedTool(
            name=tool.name,
            description=tool.description,
            parameters_json_schema=dict(tool.parameters_json_schema),
            kind=kind,
        )
        for kind, tools in (
            ("function", parameters.function_tools),
            ("output", parameters.output_tools),
        )
        for tool in tools
    ]


def _settings(model_settings: ModelSettings | None) -> dict[str, Any]:
    """The settings that were sent, minus anything that could carry a key."""
    if model_settings is None:
        return {}
    return {key: value for key, value in model_settings.items() if key in _RECORDED_SETTINGS}


def as_payload(recorder: RunRecorder) -> dict[str, Any]:
    """The recording, as one JSON document for a row and a response.

    Assembled here rather than by the caller so the stored shape has one
    definition. `ToolDefinition` and `RecordedRequest` are dataclasses of scalars
    and plain containers, which `jsonable_encoder` would reach through `vars()`
    anyway; doing it explicitly is what keeps a field somebody adds to the
    dataclass from silently appearing on the wire.
    """
    return {
        "instructions": recorder.instructions,
        "system_prompts": list(recorder.system_prompts),
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters_json_schema": tool.parameters_json_schema,
                "kind": tool.kind,
            }
            for tool in recorder.tools
        ],
        "settings": dict(recorder.settings),
        "requests": [
            {
                "index": request.index,
                "started_at": request.started_at.isoformat(),
                "duration_ms": request.duration_ms,
                "model": request.model,
                "message_count": request.message_count,
                "input_tokens": request.input_tokens,
                "output_tokens": request.output_tokens,
                "cache_read_tokens": request.cache_read_tokens,
                "tool_calls": list(request.tool_calls),
                "finish_reason": request.finish_reason,
                "failed": request.failed,
            }
            for request in recorder.requests
        ],
        "messages": recorder.messages,
    }


#: How large a stored manifest may be, as JSON bytes.
#:
#: A run of a hundred steps carrying a long context ends with a message list of
#: megabytes, and a manifest is written for every run in the deployment. The
#: ceiling is what keeps an observability record from costing more storage than
#: the product it observes; what it drops, it says it dropped.
MAX_PAYLOAD_BYTES = 512_000


def fit(payload: dict[str, Any], limit: int = MAX_PAYLOAD_BYTES) -> tuple[dict[str, Any], bool]:
    """The payload, trimmed to fit, and whether anything was cut.

    Trimmed in the order things are worth keeping. The messages go first: they
    are the largest by far, and the transcript beside them already says what was
    asked and answered. The tool schemas go second, leaving each tool's name and
    description - which is the half that explains behaviour and the half readable
    nowhere else. The instructions, the settings and the request waterfall are
    never dropped; a record that cannot say what the prompt was is not worth
    keeping at all.
    """
    if _size(payload) <= limit:
        return payload, False
    trimmed = {**payload, "messages": []}
    if _size(trimmed) <= limit:
        return trimmed, True
    return {
        **trimmed,
        "tools": [{**tool, "parameters_json_schema": {}} for tool in trimmed.get("tools", [])],
    }, True


def _size(payload: dict[str, Any]) -> int:
    """How many bytes this document is, as it will be stored."""
    return len(json.dumps(payload, default=str).encode())
