"""A rejected call can be corrected without starting it or ending the conversation."""

import json
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel, JsonValue, TypeAdapter
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_core import SchemaValidator

from app.agents.capabilities.approval import ApprovalGate
from app.agents.deps import AgentDeps
from app.agents.tool_errors import (
    TOOL_ERROR_METADATA,
    ToolErrorEnvelope,
    ToolErrors,
    _expected_type,
    _field_schema,
)
from app.agents.voice import AnswerUnknownTools
from app.core.exceptions import AuthorizationError, RateLimitError
from app.services.transcript import tool_calls_in

pytestmark = pytest.mark.anyio


def _model(*calls: ToolCallPart) -> FunctionModel:
    turns = iter(calls)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        call = next(turns, None)
        return ModelResponse(parts=[call] if call is not None else [TextPart("done")])

    return FunctionModel(respond)


def _errors(messages: list[ModelMessage]) -> list[ToolErrorEnvelope]:
    return [
        ToolErrorEnvelope.model_validate_json(part.content)
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.outcome == "failed"
    ]


async def test_invalid_uuid_names_the_field_and_lookup_before_approval() -> None:
    executed: list[UUID] = []
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("run_workflow", {"workflow_id": "netverify"}, "bad")),
        capabilities=[ToolErrors(), ApprovalGate(gate_every_tool=True)],
    )

    @agent.tool_plain
    def run_workflow(workflow_id: UUID) -> str:
        executed.append(workflow_id)
        return "started"

    @agent.tool_plain
    def list_workflow_definitions() -> str:
        return "workflows"

    result = await agent.run("run workflow", deps=AgentDeps())
    (envelope,) = _errors(result.all_messages())
    error = envelope.error
    assert executed == []
    assert error.code == "invalid_arguments"
    assert error.execution == "not_started"
    assert error.recovery == "correct_arguments"
    assert error.issues[0].field == "workflow_id"
    assert error.issues[0].code == "uuid_parsing"
    assert error.issues[0].expected_type == "UUID"
    assert "list_workflow_definitions" in error.message
    assert "netverify" not in error.message
    assert "no tool execution started" in error.message
    recorded = tool_calls_in(result.new_messages())
    assert json.loads(recorded[0].result or "") == envelope.model_dump(exclude_none=True)


async def test_a_model_corrects_an_array_argument_using_the_failure() -> None:
    executed: list[list[str]] = []
    seen: list[ToolErrorEnvelope] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        errors = _errors(messages)
        if not errors:
            return ModelResponse(
                parts=[ToolCallPart("netbox", {"fields": "name,primary_ip"}, "bad")]
            )
        if not seen:
            seen.extend(errors)
            return ModelResponse(
                parts=[ToolCallPart("netbox", {"fields": ["name", "primary_ip"]}, "fixed")]
            )
        return ModelResponse(parts=[TextPart("done")])

    agent = Agent[AgentDeps, str](FunctionModel(respond), capabilities=[ToolErrors()])

    @agent.tool_plain
    def netbox(fields: list[str]) -> str:
        executed.append(fields)
        return "found"

    result = await agent.run("look up devices", deps=AgentDeps())
    assert result.output == "done"
    assert executed == [["name", "primary_ip"]]
    assert seen[0].error.issues[0].expected_type == "array of strings"
    assert '["name", "primary_ip"]' in seen[0].error.message


async def test_repeated_unknown_names_are_unavailable_without_permission_claims() -> None:
    agent = Agent[AgentDeps, str](
        _model(
            ToolCallPart("discovered_workflow", {}, "one"),
            ToolCallPart("discovered_workflow", {}, "two"),
        ),
        capabilities=[ToolErrors(), AnswerUnknownTools(structured=True)],
    )
    result = await agent.run("run discovered workflow", deps=AgentDeps())
    errors = _errors(result.all_messages())
    assert len(errors) == 2
    for envelope in errors:
        assert envelope.error.code == "tool_unavailable"
        assert envelope.error.execution == "not_started"
        assert envelope.error.recovery == "rediscover_tools"
        assert "not registered for direct invocation" in envelope.error.message
        assert "permission" not in envelope.error.message
    assert errors[0].error.id != errors[1].error.id


@pytest.mark.parametrize(
    ("failure", "code", "recovery"),
    [
        (PermissionError("private path /server/secret"), "permission_denied", "stop"),
        (AuthorizationError(message="Access denied"), "permission_denied", "stop"),
        (
            TimeoutError("https://private/?key=secret"),
            "transient_failure",
            "inspect_execution_status",
        ),
        (ConnectionError("private host"), "transient_failure", "inspect_execution_status"),
        (RateLimitError(message="Rate limited"), "transient_failure", "inspect_execution_status"),
        (
            RuntimeError("https://private/?key=secret"),
            "execution_unknown",
            "inspect_execution_status",
        ),
    ],
)
async def test_execution_failures_keep_outcomes_uncertain_and_diagnostics_private(
    failure: Exception, code: str, recovery: str, caplog: pytest.LogCaptureFixture
) -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("submit", {}, "call")), capabilities=[ToolErrors()]
    )

    @agent.tool_plain
    def submit() -> str:
        raise failure

    result = await agent.run("submit", deps=AgentDeps())
    (envelope,) = _errors(result.all_messages())
    error = envelope.error
    assert error.code == code
    assert error.recovery == recovery
    assert error.execution == "unknown"
    assert error.exception_type == type(failure).__name__
    assert "private" not in error.message
    assert "secret" not in error.message
    assert error.id in caplog.text
    (part,) = [p for m in result.all_messages() for p in m.parts if isinstance(p, ToolReturnPart)]
    assert (part.metadata or {}).get(TOOL_ERROR_METADATA) is True


class _McpSchemaTools(AbstractToolset[AgentDeps]):
    """The MCP client's generic dictionary validator, with an advertised schema."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema
        self.executed: list[dict[str, Any]] = []

    @property
    def id(self) -> str | None:
        return None

    async def get_tools(self, ctx: RunContext[AgentDeps]) -> dict[str, ToolsetTool[AgentDeps]]:
        definition = ToolDefinition(
            name="remote",
            parameters_json_schema=self.schema,
            metadata={"annotations": {}, "meta": None},
        )
        return {
            "remote": ToolsetTool(
                toolset=self,
                tool_def=definition,
                max_retries=1,
                args_validator=SchemaValidator(TypeAdapter(dict[str, JsonValue]).core_schema),
            )
        }

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[AgentDeps],
        tool: ToolsetTool[AgentDeps],
    ) -> Any:
        self.executed.append(tool_args)
        return "started"


@pytest.mark.parametrize(
    ("schema", "arguments", "expected"),
    [
        ({"type": "string", "format": "uuid"}, {"value": "netverify"}, "UUID"),
        ({"type": "array", "items": {"type": "string"}}, {"value": "a,b"}, "array of strings"),
    ],
)
async def test_mcp_advertised_schema_is_checked_before_remote_dispatch(
    schema: dict[str, Any], arguments: dict[str, Any], expected: str
) -> None:
    remote = _McpSchemaTools({"type": "object", "properties": {"value": schema}})
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("remote", arguments, "bad")),
        toolsets=[remote],
        capabilities=[ToolErrors(), ApprovalGate(gate_every_tool=True)],
    )
    result = await agent.run("run remote", deps=AgentDeps())
    (envelope,) = _errors(result.all_messages())
    assert envelope.error.issues[0].expected_type == expected
    assert envelope.error.execution == "not_started"
    assert remote.executed == []


async def test_valid_mcp_arguments_still_dispatch() -> None:
    remote = _McpSchemaTools({"type": "object", "properties": {"value": {"type": "string"}}})
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("remote", {"value": "valid"}, "good")),
        toolsets=[remote],
        capabilities=[ToolErrors()],
    )
    result = await agent.run("run remote", deps=AgentDeps())
    assert _errors(result.all_messages()) == []
    assert remote.executed == [{"value": "valid"}]


class _Options(BaseModel):
    fields: list[str]


async def test_nested_array_and_union_errors_name_each_invalid_field() -> None:
    agent = Agent[AgentDeps, str](
        _model(
            ToolCallPart(
                "configure",
                {"options": {"fields": "a,b"}, "numbers": "1,2", "choice": {}},
                "bad",
            )
        ),
        capabilities=[ToolErrors()],
    )

    @agent.tool_plain
    def configure(options: _Options, numbers: list[int], choice: str | int) -> str:
        pytest.fail("Invalid arguments must not execute")

    result = await agent.run("configure", deps=AgentDeps())
    (envelope,) = _errors(result.all_messages())
    issues = {issue.field: issue for issue in envelope.error.issues}
    assert issues["options.fields"].expected_type == "array of strings"
    assert issues["numbers"].expected_type == "array"
    assert issues["choice.str"].expected_type == "string"
    assert issues["choice.int"].code == "int_type"


@pytest.mark.parametrize(
    "schema",
    [
        {
            "type": "object",
            "properties": {
                "fields": {
                    "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]
                }
            },
        },
        {
            "type": "object",
            "properties": {"fields": {"$ref": "#/$defs/Fields"}},
            "$defs": {"Fields": {"type": "array", "items": {"type": "string"}}},
        },
    ],
)
async def test_optional_and_referenced_mcp_arrays_still_offer_a_correction_example(
    schema: dict[str, Any],
) -> None:
    remote = _McpSchemaTools(schema)
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("remote", {"fields": "name,primary_ip"}, "bad")),
        toolsets=[remote],
        capabilities=[ToolErrors()],
    )
    result = await agent.run("run remote", deps=AgentDeps())
    (envelope,) = _errors(result.all_messages())
    assert envelope.error.issues[0].expected_type == "array of strings"
    assert '["name", "primary_ip"]' in envelope.error.message
    assert remote.executed == []


async def test_many_mcp_issues_are_bounded_without_exposing_argument_values() -> None:
    remote = _McpSchemaTools({"type": "object", "additionalProperties": {"type": "string"}})
    arguments = {f"field{index}": {"password": "private-secret"} for index in range(15)}
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("remote", arguments, "bad")),
        toolsets=[remote],
        capabilities=[ToolErrors()],
    )
    result = await agent.run("run remote", deps=AgentDeps())
    (envelope,) = _errors(result.all_messages())
    assert len(envelope.error.issues) == 10
    assert "private-secret" not in envelope.model_dump_json()
    assert remote.executed == []


@pytest.mark.parametrize(
    ("schema", "location", "code", "expected"),
    [
        (
            {"type": "object", "properties": {"count": {"type": "integer"}}},
            ("count",),
            "int_type",
            "integer",
        ),
        (
            {"properties": {"value": {"anyOf": [False]}}},
            ("value",),
            "anyOf",
            "schema-compatible value",
        ),
        (
            {"properties": {"value": {"$ref": "#/$defs/Missing"}}},
            ("value",),
            "string_type",
            "string",
        ),
        (
            {"properties": {"value": {"$ref": "#/$defs/Missing"}}, "$defs": {}},
            ("value",),
            "list_type",
            "array",
        ),
    ],
)
def test_type_hints_handle_partial_or_unrepresentable_advertised_schemas(
    schema: dict[str, JsonValue], location: tuple[str | int, ...], code: str, expected: str
) -> None:
    """A schema hint can be incomplete; it must still never echo a rejected value."""
    assert _expected_type(_field_schema(schema, location), code) == expected
