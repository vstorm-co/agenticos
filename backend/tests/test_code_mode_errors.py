"""Sandbox failures stay useful to the model and to the stored conversation."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_monty import MontyRuntimeError

from app.agents.code_mode import CodeCalls, _code_operation, code_mode
from app.agents.deps import AgentDeps
from app.agents.manifest import RunRecorder
from app.agents.tool_errors import ToolErrors, capture_tool_errors, tool_error
from app.services.transcript import tool_calls_in

pytestmark = pytest.mark.anyio


async def _failed_script(code: str) -> tuple[dict[str, Any], str, list[int]]:
    received: list[str] = []
    updates: list[int] = []

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("run_code", {"code": code})])
        received.extend(
            str(part.content)
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart) and part.tool_name == "run_code"
        )
        return ModelResponse(parts=[TextPart("done")])

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        response = respond(messages, info)
        for part in response.parts:
            if isinstance(part, ToolCallPart):
                yield {0: DeltaToolCall(name=part.tool_name, json_args=part.args_as_json_str())}
            elif isinstance(part, TextPart):
                yield part.content

    agent = Agent[AgentDeps, str](
        FunctionModel(respond, stream_function=stream),
        capabilities=[
            ToolErrors(),
            code_mode(approval_required=frozenset(), asking=frozenset(), max_tool_calls=10),
            CodeCalls(recorder=RunRecorder()),
        ],
    )

    @agent.tool_plain
    def update_record(n: int) -> str:
        """Update one record."""
        updates.append(n)
        return "updated"

    @agent.tool_plain
    def run_workflow(workflow_id: UUID) -> str:
        raise AssertionError("Invalid workflow arguments must not execute")

    @agent.tool_plain
    def netbox(fields: list[str]) -> str:
        raise AssertionError("Invalid field arguments must not execute")

    result = await agent.run("Run the program.", deps=AgentDeps())
    (seen,) = received
    (stored,) = tool_calls_in(result.new_messages())
    assert stored.result == seen
    return json.loads(seen)["error"], seen, updates


async def test_a_filesystem_refusal_names_the_exception_and_the_submitted_operation(caplog) -> None:
    error, rendered, _ = await _failed_script(
        "from pathlib import Path\nlist(Path('/workspace').iterdir())"
    )

    assert error["message"] == "Code execution failed: PermissionError while listing '/workspace'."
    assert error["exception_type"] == "PermissionError"
    assert error["code"] == "permission_denied"
    assert error["execution"] == "started"
    assert error["recovery"] == "stop"
    assert error["id"] in caplog.text
    assert "Traceback" not in rendered


async def test_a_runtime_failure_does_not_echo_exception_text_or_traceback() -> None:
    error, rendered, _ = await _failed_script(
        "raise RuntimeError('https://internal.invalid/?api_key=secret')"
    )

    assert error["message"] == "Code execution failed: RuntimeError."
    assert error["exception_type"] == "RuntimeError"
    assert error["code"] == "invalid_arguments"
    assert error["execution"] == "started"
    assert error["recovery"] == "correct_arguments"
    assert "internal.invalid" not in rendered
    assert "secret" not in rendered


async def test_a_script_that_already_called_a_tool_requires_execution_inspection() -> None:
    error, _, updates = await _failed_script("await update_record(n=1)\n1 / 0")

    assert updates == [1]
    assert error["code"] == "execution_unknown"
    assert error["execution"] == "unknown"
    assert error["recovery"] == "inspect_execution_status"
    assert "Tool calls started before the failure" in error["message"]


@pytest.mark.parametrize(
    ("code", "child", "field", "expected"),
    [
        ("await run_workflow(workflow_id='netverify')", "run_workflow", "workflow_id", "UUID"),
        (
            "import json\nawait netbox(fields=json.loads('\"name,primary_ip\"'))",
            "netbox",
            "fields",
            "array of strings",
        ),
    ],
)
async def test_nested_validation_retains_the_child_reference_and_corrections(
    code: str, child: str, field: str, expected: str, caplog: pytest.LogCaptureFixture
) -> None:
    error, _, _ = await _failed_script(code)

    assert error["tool"] == "run_code"
    assert error["cause_tool"] == child
    assert error["execution"] == "started"
    assert error["cause_execution"] == "not_started"
    assert error["code"] == "invalid_arguments"
    assert error["recovery"] == "correct_arguments"
    assert error["issues"][0]["field"] == field
    assert error["issues"][0]["expected_type"] == expected
    assert set(re.findall(r"err_[0-9a-f]{32}", caplog.text)) == {error["id"]}


async def test_a_nested_rejection_after_an_effect_retains_its_issues_and_requires_inspection() -> (
    None
):
    error, _, updates = await _failed_script(
        "await update_record(n=1)\nawait run_workflow(workflow_id='netverify')"
    )

    assert updates == [1]
    assert error["execution"] == "unknown"
    assert error["cause_execution"] == "not_started"
    assert error["cause_tool"] == "run_workflow"
    assert error["code"] == "execution_unknown"
    assert error["recovery"] == "inspect_execution_status"
    assert error["issues"][0]["field"] == "workflow_id"
    assert error["issues"][0]["expected_type"] == "UUID"


async def test_a_handled_nested_rejection_does_not_replace_an_unrelated_local_exception() -> None:
    error, _, _ = await _failed_script(
        "from pathlib import Path\ntry:\n    await run_workflow(workflow_id='netverify')\n"
        "except Exception:\n    pass\nlist(Path('/workspace').iterdir())"
    )

    assert error["exception_type"] == "PermissionError"
    assert error["code"] == "permission_denied"
    assert error["issues"] == []
    assert "cause_tool" not in error
    assert "private diagnostics" not in error["message"]


async def test_a_cancelled_capture_does_not_collect_later_tool_errors() -> None:
    with pytest.raises(asyncio.CancelledError), capture_tool_errors() as captured:
        tool_error(
            tool="cancelled",
            code="tool_unavailable",
            execution="not_started",
            message="Unavailable",
            recovery="rediscover_tools",
        )
        raise asyncio.CancelledError

    tool_error(
        tool="later",
        code="tool_unavailable",
        execution="not_started",
        message="Unavailable",
        recovery="rediscover_tools",
    )
    assert len(captured) == 1


def test_nested_captures_restore_the_enclosing_collector() -> None:
    with capture_tool_errors() as outer:
        with capture_tool_errors() as inner:
            child = tool_error(
                tool="child",
                code="tool_unavailable",
                execution="not_started",
                message="Unavailable",
                recovery="rediscover_tools",
            )
        parent = tool_error(
            tool="parent",
            code="tool_unavailable",
            execution="not_started",
            message="Unavailable",
            recovery="rediscover_tools",
        )

    assert inner == [child]
    assert outer == [parent]


@pytest.mark.parametrize("code", ["if", "len(1)"])
async def test_code_rejected_before_execution_can_be_corrected_without_replaying_effects(
    code: str,
) -> None:
    error, _, updates = await _failed_script(code)

    assert updates == []
    assert error["code"] == "invalid_arguments"
    assert error["execution"] == "not_started"
    assert error["recovery"] == "correct_arguments"
    assert "Correct the `code` argument" in error["message"]


async def test_non_sandbox_errors_are_left_for_their_own_handler() -> None:
    async def fail(_args: dict[str, Any]) -> object:
        raise RuntimeError("host failure")

    with pytest.raises(RuntimeError, match="host failure"):
        await CodeCalls(recorder=RunRecorder()).wrap_tool_execute(
            MagicMock(),
            call=ToolCallPart("run_code", {"code": "1 + 1"}),
            tool_def=ToolDefinition(name="run_code"),
            args={"code": "1 + 1"},
            handler=fail,
        )


@pytest.mark.parametrize(
    ("code", "column", "operation"),
    [
        ("os.listdir('/workspace')", 1, " while listing '/workspace'"),
        ("path.iterdir()", 1, " while listing a path in the submitted code"),
        ("Path(variable).read_text()", 1, " while reading a path in the submitted code"),
        (
            "Path('https://host/?token=secret').read_text()",
            1,
            " while reading a path in the submitted code",
        ),
        (f"Path('/{'x' * 200}').read_text()", 1, " while reading a path in the submitted code"),
        (
            r"Path('/workspace\nsecret').read_text()",
            1,
            " while reading a path in the submitted code",
        ),
        (
            r"Path('/workspace\rsecret').read_text()",
            1,
            " while reading a path in the submitted code",
        ),
        ("path.unknown()", 1, ""),
        ("Path('/workspace').iterdir()", 2, ""),
        ("1 / 0", 1, ""),
    ],
)
def test_only_the_failing_operation_and_a_short_literal_path_are_described(
    code: str, column: int, operation: str
) -> None:
    error = MagicMock(spec=MontyRuntimeError)
    error.traceback.return_value = [MagicMock(line=1, column=column)]

    assert _code_operation(code, error) == operation


def test_a_resource_failure_without_a_source_location_names_no_operation() -> None:
    error = MagicMock(spec=MontyRuntimeError)
    error.traceback.return_value = []

    assert _code_operation("1 + 1", error) == ""
