"""Controlled tool errors stay useful in the transcript, including after approval."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic_ai import Agent, FunctionToolCallEvent, FunctionToolResultEvent
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, ToolApproved

from app.agents.ephemeral_media import dump_messages
from app.agents.tool_errors import (
    TOOL_ERROR_METADATA,
    ControlledToolError,
    ToolErrorEnvelope,
    ToolErrors,
)
from app.services import transcript
from app.services.run_stream import RunFrames
from app.services.transcript import (
    TranscriptService,
    settled_calls_in,
    tool_calls_in,
    tool_failure_notice,
)

pytestmark = pytest.mark.anyio

_TOOL = "agenticos_run_workflow"
_CALL = "workflow-call"


def _error() -> dict[str, object]:
    return {
        "error": {
            "id": "err_1234567890abcdef1234567890abcdef",
            "code": "invalid_arguments",
            "tool": _TOOL,
            "execution": "not_started",
            "message": "Invalid workflow_id: expected a UUID. No workflow started.",
            "issues": [
                {
                    "field": "workflow_id",
                    "code": "uuid_parsing",
                    "expected_type": "UUID",
                    "message": "Use an ID returned by list_workflow_definitions.",
                }
            ],
            "recovery": "correct_arguments",
        }
    }


@pytest.mark.parametrize("outcome", ["failed", "retried"])
def test_a_controlled_error_keeps_its_correction_and_reference(
    outcome: Literal["failed", "retried"],
) -> None:
    error = _error()
    part = ToolReturnPart(
        _TOOL,
        ControlledToolError(json.dumps(error)),
        tool_call_id=_CALL,
        outcome=outcome,
    )
    calls = tool_calls_in(
        [
            ModelResponse(parts=[ToolCallPart(_TOOL, {"workflow_id": "netverify"}, _CALL)]),
            ModelRequest(parts=[part]),
        ]
    )

    assert calls[0].result is not None
    assert json.loads(calls[0].result) == error
    assert json.loads(tool_failure_notice(part)) == error


@pytest.mark.parametrize("marker", [None, False, "true"])
def test_a_vendor_cannot_preserve_diagnostics_by_copying_the_error_envelope(
    marker: object,
) -> None:
    part = ToolReturnPart(
        _TOOL,
        json.dumps(_error()),
        tool_call_id=_CALL,
        outcome="failed",
        metadata={TOOL_ERROR_METADATA: marker},
    )

    assert tool_failure_notice(part) == (
        f"The {_TOOL} call failed. The server log has the full error."
    )


async def test_the_live_frame_keeps_the_same_error_before_history_is_serialized() -> None:
    error = _error()
    part = ToolReturnPart(
        _TOOL,
        ControlledToolError(json.dumps(error)),
        tool_call_id=_CALL,
        outcome="failed",
    )

    async def events() -> AsyncIterator[FunctionToolCallEvent | FunctionToolResultEvent]:
        yield FunctionToolCallEvent(ToolCallPart(_TOOL, {}, _CALL))
        yield FunctionToolResultEvent(part)

    emit = AsyncMock()
    frames = RunFrames(emit=emit)
    await frames.tools(events())

    result = emit.await_args_list[-1]
    assert result.args[0] == "tool_result"
    assert json.loads(result.args[1]["content"]) == error
    assert json.loads(frames.tool_calls[0]["result"]) == error


@pytest.mark.parametrize(
    "content",
    [
        "provider error https://provider.invalid/?key=fixture",
        {"error": {"code": "invalid_arguments", "traceback": "private diagnostic"}},
    ],
)
def test_a_marked_but_invalid_error_keeps_vendor_diagnostics_out(content: object) -> None:
    part = ToolReturnPart(
        _TOOL,
        content,
        tool_call_id=_CALL,
        outcome="failed",
        metadata={TOOL_ERROR_METADATA: True},
    )

    assert tool_failure_notice(part) == (
        f"The {_TOOL} call failed. The server log has the full error."
    )


def test_a_controlled_error_cannot_be_attributed_to_another_tool() -> None:
    part = ToolReturnPart(
        "another_tool",
        ControlledToolError(json.dumps(_error())),
        tool_call_id=_CALL,
        outcome="failed",
    )

    assert tool_failure_notice(part) == (
        "The another_tool call failed. The server log has the full error."
    )


@pytest.mark.parametrize("structured", [False, True])
def test_a_serialized_error_keeps_the_same_result_when_its_original_call_is_in_history(
    structured: bool,
) -> None:
    """A resumed call settles an earlier row using only its new return part."""
    error = _error()
    messages = ModelMessagesTypeAdapter.validate_python(
        dump_messages(
            [
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            _TOOL,
                            error if structured else json.dumps(error),
                            tool_call_id=_CALL,
                            outcome="failed",
                            metadata={TOOL_ERROR_METADATA: True},
                        )
                    ]
                )
            ]
        )
    )

    assert json.loads(settled_calls_in(messages)[_CALL]) == error


def test_a_partial_run_preserves_the_error_without_waiting_for_terminal_hooks() -> None:
    error = _error()
    messages = ModelMessagesTypeAdapter.validate_python(
        dump_messages(
            [
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            _TOOL,
                            ControlledToolError(json.dumps(error)),
                            tool_call_id=_CALL,
                            outcome="failed",
                            metadata={"kept": True},
                        )
                    ]
                )
            ]
        )
    )
    part = messages[0].parts[0]
    assert isinstance(part, ToolReturnPart)
    assert type(part.content) is str
    assert part.metadata == {"kept": True, TOOL_ERROR_METADATA: True}
    assert json.loads(settled_calls_in(messages)[_CALL]) == error


@asynccontextmanager
async def _savepoint() -> AsyncIterator[None]:
    yield


@pytest.mark.parametrize("failure", ["invalid_arguments", "permission_denied"])
async def test_an_approved_failure_reaches_the_model_and_settles_the_saved_call(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """Exercise the real model-message path before asserting the transcript result."""
    received: list[ToolErrorEnvelope] = []
    executions: list[str] = []
    workflow_id = uuid4()

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returned = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if returned:
            received.append(ToolErrorEnvelope.model_validate_json(returned[-1].content))
            return ModelResponse(parts=[TextPart("Please choose a workflow ID.")])
        return ModelResponse(parts=[ToolCallPart(_TOOL, {"workflow_id": str(workflow_id)}, _CALL)])

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        response = respond(messages, info)
        for part in response.parts:
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                yield {
                    0: DeltaToolCall(
                        name=part.tool_name,
                        json_args=part.args_as_json_str(),
                        tool_call_id=part.tool_call_id,
                    )
                }

    agent = Agent(
        FunctionModel(respond, stream_function=stream),
        output_type=[str, DeferredToolRequests],
        capabilities=[ToolErrors()],
    )

    @agent.tool_plain(name=_TOOL, requires_approval=True)
    def run_workflow(workflow_id: UUID) -> str:
        executions.append(_CALL)
        raise PermissionError("private diagnostic https://provider.invalid/?key=fixture")

    parked = await agent.run("Run the workflow.")
    assert isinstance(parked.output, DeferredToolRequests)
    assert executions == []
    history = ModelMessagesTypeAdapter.validate_python(dump_messages(parked.all_messages()))
    resumed = await agent.run(
        message_history=history,
        deferred_tool_results=DeferredToolResults(
            approvals={
                _CALL: ToolApproved(
                    override_args={"workflow_id": "netverify"}
                    if failure == "invalid_arguments"
                    else None
                )
            }
        ),
    )

    assert executions == ([] if failure == "invalid_arguments" else [_CALL])
    (envelope,) = received
    error = envelope.model_dump(mode="json", exclude_none=True)
    detail = envelope.error
    assert detail.code == failure
    assert detail.execution == ("not_started" if failure == "invalid_arguments" else "unknown")
    assert "provider.invalid" not in json.dumps(error)
    if failure == "invalid_arguments":
        assert detail.issues[0].field == "workflow_id"
        assert detail.issues[0].expected_type == "UUID"
    else:
        assert detail.exception_type == "PermissionError"
    settled = settled_calls_in(resumed.new_messages())
    assert json.loads(settled[_CALL]) == error
    # Dump and reload the failure too: approval state and recorded model messages
    # use this adapter, which turns a controlled string subclass into plain text.
    restored = ModelMessagesTypeAdapter.validate_python(dump_messages(resumed.new_messages()))
    restored_part = next(
        part for message in restored for part in message.parts if isinstance(part, ToolReturnPart)
    )
    assert restored_part.metadata is not None
    assert restored_part.metadata[TOOL_ERROR_METADATA] is True
    assert json.loads(settled_calls_in(restored)[_CALL]) == error

    db = AsyncMock()
    db.begin_nested = MagicMock(side_effect=_savepoint)
    run = MagicMock(id=uuid4(), conversation_id=uuid4())
    row = MagicMock()
    monkeypatch.setattr(
        transcript.conversation_repo, "get_open_tool_call_in_run", AsyncMock(return_value=row)
    )
    complete = AsyncMock()
    monkeypatch.setattr(transcript.conversation_repo, "complete_tool_call", complete)

    await TranscriptService(db).record(run, prompt=None, answer="", settled=settled)

    stored = complete.await_args.kwargs
    assert stored["db_tool_call"] is row
    assert json.loads(stored["result"]) == error
