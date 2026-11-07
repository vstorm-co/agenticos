"""Corrections name missing fields and constraints without echoing submitted values."""

from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, Field, JsonValue, field_validator
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_core import PydanticCustomError

from app.agents.deps import AgentDeps
from app.agents.tool_errors import ToolErrorEnvelope, ToolErrors
from app.services.transcript import tool_calls_in
from tests.test_tool_errors import _errors, _model
from tests.test_tool_schema_errors import _invoke, _RemoteSchemaToolset

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("nested", [False, True])
async def test_missing_mcp_fields_name_the_required_property_and_its_type(nested: bool) -> None:
    fields: dict[str, JsonValue] = {
        "type": "object",
        "required": ["workflow_id", "title"],
        "properties": {
            "workflow_id": {"type": "string", "format": "uuid"},
            "title": {"type": "string"},
        },
    }
    schema: dict[str, JsonValue] = (
        {"type": "object", "properties": {"options": fields}} if nested else fields
    )
    remote = _RemoteSchemaToolset(schema)

    (envelope,) = await _invoke(remote, {"options": {}} if nested else {})

    prefix = "options." if nested else ""
    issues = envelope.error.issues
    assert [(issue.field, issue.expected_type) for issue in issues] == [
        (f"{prefix}workflow_id", "UUID"),
        (f"{prefix}title", "string"),
    ]
    assert all(issue.code == "required" for issue in issues)
    assert all("Missing required" in issue.message for issue in issues)
    assert envelope.error.execution == "not_started"
    assert remote.executed is False


async def test_a_missing_builtin_argument_is_identified_as_required() -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {})), capabilities=[ToolErrors()]
    )

    @agent.tool_plain
    def configure(title: str) -> str:
        pytest.fail("A missing argument must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert envelope.error.issues[0].field == "title"
    assert "Missing required `title`: expected string" in envelope.error.message


async def test_a_model_repairs_builtin_literal_and_length_errors_from_the_returned_details() -> (
    None
):
    executions: list[tuple[str, str]] = []
    received: list[ToolErrorEnvelope] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        errors = _errors(messages)
        if not errors:
            return ModelResponse(
                parts=[ToolCallPart("configure", {"kind": "text", "title": "too long"})]
            )
        if not received:
            received.extend(errors)
            assert '["html", "markdown"]' in errors[0].error.message
            assert "at most 5 characters" in errors[0].error.message
            return ModelResponse(
                parts=[ToolCallPart("configure", {"kind": "html", "title": "short"})]
            )
        return ModelResponse(parts=[TextPart("done")])

    agent = Agent[AgentDeps, str](FunctionModel(respond), capabilities=[ToolErrors()])

    @agent.tool_plain
    def configure(
        kind: Literal["html", "markdown"], title: Annotated[str, Field(max_length=5)]
    ) -> str:
        executions.append((kind, title))
        return "configured"

    result = await agent.run("configure", deps=AgentDeps())

    assert result.output == "done"
    assert executions == [("html", "short")]
    assert "too long" not in received[0].error.message
    assert tool_calls_in(result.all_messages())[0].result == received[0].model_dump_json(
        exclude_none=True
    )


@pytest.mark.parametrize(
    ("title", "correction"),
    [("", "at least 1 characters"), ("private-secret", "at most 5 characters")],
)
async def test_optional_string_bounds_are_preserved_in_builtin_corrections(
    title: str, correction: str
) -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {"kind": "text", "title": title})),
        capabilities=[ToolErrors()],
    )

    @agent.tool_plain
    def configure(
        kind: Literal["html"], title: Annotated[str, Field(min_length=1, max_length=5)] | None
    ) -> str:
        pytest.fail("Invalid constrained arguments must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert '["html"]' in envelope.error.message
    assert correction in envelope.error.message
    assert "private-secret" not in envelope.model_dump_json()


@pytest.mark.parametrize(
    ("field_schema", "value", "correction"),
    [
        ({"type": "string", "enum": ["html", "markdown"]}, "text", '["html", "markdown"]'),
        ({"type": "string", "const": "html"}, "text", '["html"]'),
        ({"type": "string", "minLength": 3}, "x", "at least 3 characters"),
        ({"type": "string", "maxLength": 5}, "private-secret", "at most 5 characters"),
    ],
)
async def test_mcp_constraints_offer_the_same_actionable_corrections(
    field_schema: dict[str, JsonValue], value: str, correction: str
) -> None:
    remote = _RemoteSchemaToolset({"type": "object", "properties": {"value": field_schema}})

    (envelope,) = await _invoke(remote, {"value": value})

    assert correction in envelope.error.message
    assert envelope.error.issues[0].field == "value"
    assert envelope.error.issues[0].expected_type == "string"
    assert "private-secret" not in envelope.model_dump_json()
    assert remote.executed is False


async def test_an_ambiguous_string_union_does_not_claim_one_branchs_constraint() -> None:
    remote = _RemoteSchemaToolset(
        {
            "type": "object",
            "properties": {
                "value": {
                    "anyOf": [
                        {"type": "string", "minLength": 3},
                        {"type": "string", "enum": ["ok"]},
                    ]
                }
            },
        }
    )

    (envelope,) = await _invoke(remote, {"value": ""})

    assert envelope.error.issues[0].expected_type == "string"
    assert "at least" not in envelope.error.message
    assert remote.executed is False


@pytest.mark.parametrize(
    "code", ["value_error", "literal_error", "string_too_long", "string_too_short"]
)
async def test_custom_validator_diagnostics_and_unadvertised_constraints_stay_private(
    code: Literal["value_error", "literal_error", "string_too_long", "string_too_short"],
) -> None:
    class Options(BaseModel):
        value: str

        @field_validator("value")
        @classmethod
        def refuse(cls, value: str) -> str:
            raise PydanticCustomError(
                code, "Private diagnostic containing {value}", {"value": value}
            )

    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {"value": "private-secret"})),
        capabilities=[ToolErrors()],
    )

    @agent.tool_plain
    def configure(options: Options) -> str:
        pytest.fail("A custom validator refusal must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert envelope.error.issues[0].field == "value"
    assert envelope.error.issues[0].code == code
    assert envelope.error.issues[0].message == "Invalid `value`: expected string."
    assert "Private diagnostic" not in envelope.model_dump_json()
    assert "private-secret" not in envelope.model_dump_json()


async def test_a_cyclic_mcp_schema_is_a_recoverable_unavailable_tool() -> None:
    remote = _RemoteSchemaToolset(
        {
            "type": "object",
            "$defs": {"cycle": {"$ref": "#/$defs/cycle"}},
            "properties": {"value": {"$ref": "#/$defs/cycle"}},
        }
    )

    (envelope,) = await _invoke(remote, {"value": "submitted"})

    assert envelope.error.code == "tool_unavailable"
    assert envelope.error.execution == "not_started"
    assert envelope.error.recovery == "rediscover_tools"
    assert remote.executed is False


async def test_a_boolean_mcp_field_schema_rejects_arguments_without_exposing_values() -> None:
    remote = _RemoteSchemaToolset({"type": "object", "properties": {"blocked": False}})

    (envelope,) = await _invoke(remote, {"blocked": "private-secret"})

    assert envelope.error.code == "invalid_arguments"
    assert envelope.error.execution == "not_started"
    assert len(envelope.error.issues) == 1
    assert "private-secret" not in envelope.model_dump_json()
    assert remote.executed is False


@pytest.mark.parametrize("value", [{}, "private-secret"])
async def test_union_validation_keeps_each_primitive_type_in_its_correction(
    value: JsonValue,
) -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {"choice": value})), capabilities=[ToolErrors()]
    )

    @agent.tool_plain
    def configure(choice: int | float | bool) -> str:
        pytest.fail("Invalid union members must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert [issue.expected_type for issue in envelope.error.issues] == [
        "integer",
        "number",
        "boolean",
    ]
    assert "private-secret" not in envelope.model_dump_json()
