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


async def test_a_model_repairs_numeric_bounds_from_the_exact_returned_limits() -> None:
    executions: list[tuple[int, int]] = []
    received: list[ToolErrorEnvelope] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        errors = _errors(messages)
        if not errors:
            return ModelResponse(parts=[ToolCallPart("read_page", {"offset": -1, "limit": 20001})])
        if not received:
            received.extend(errors)
            return ModelResponse(parts=[ToolCallPart("read_page", {"offset": 0, "limit": 8000})])
        return ModelResponse(parts=[TextPart("done")])

    agent = Agent[AgentDeps, str](FunctionModel(respond), capabilities=[ToolErrors()])

    @agent.tool_plain
    def read_page(
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=20000)] = 8000,
    ) -> str:
        executions.append((offset, limit))
        return "page"

    result = await agent.run("read", deps=AgentDeps())

    assert result.output == "done"
    assert executions == [(0, 8000)]
    issues = received[0].error.issues
    assert [(issue.field, issue.code) for issue in issues] == [
        ("offset", "greater_than_equal"),
        ("limit", "less_than_equal"),
    ]
    assert [issue.expected_type for issue in issues] == ["integer", "integer"]
    assert issues[0].message == "`offset` must be at least 0."
    assert issues[1].message == "`limit` must be at most 20000."
    assert "-1" not in received[0].model_dump_json()
    assert "20001" not in received[0].model_dump_json()
    assert tool_calls_in(result.all_messages())[0].result == received[0].model_dump_json(
        exclude_none=True
    )


@pytest.mark.parametrize(
    ("field_schema", "value", "correction"),
    [
        ({"type": "integer", "minimum": 0}, -1, "at least 0"),
        ({"type": "integer", "maximum": 20000}, 20001, "at most 20000"),
        ({"type": "integer", "exclusiveMinimum": 0}, 0, "greater than 0"),
        ({"type": "integer", "exclusiveMaximum": 10}, 10, "less than 10"),
        ({"type": "number", "multipleOf": 0.5}, 0.3, "a multiple of 0.5"),
        (
            {"type": "array", "items": {"type": "string"}, "minItems": 3},
            ["a"],
            "at least 3 items",
        ),
        (
            {"type": "array", "items": {"type": "string"}, "maxItems": 2},
            ["a", "b", "c"],
            "at most 2 items",
        ),
    ],
)
async def test_mcp_numeric_and_list_constraints_state_the_schema_bound(
    field_schema: dict[str, JsonValue], value: JsonValue, correction: str
) -> None:
    remote = _RemoteSchemaToolset({"type": "object", "properties": {"value": field_schema}})

    (envelope,) = await _invoke(remote, {"value": value})

    assert correction in envelope.error.message
    assert envelope.error.issues[0].field == "value"
    assert remote.executed is False


@pytest.mark.parametrize(
    ("value", "correction"),
    [(0, "greater than 0"), (10, "less than 10")],
)
async def test_builtin_strict_numeric_bounds_are_preserved(value: int, correction: str) -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {"value": value})), capabilities=[ToolErrors()]
    )

    @agent.tool_plain
    def configure(value: Annotated[int, Field(gt=0, lt=10)]) -> str:
        pytest.fail("Invalid constrained arguments must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert correction in envelope.error.message


async def test_builtin_multiple_of_states_the_factor() -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {"value": 0.3})), capabilities=[ToolErrors()]
    )

    @agent.tool_plain
    def configure(value: Annotated[float, Field(multiple_of=0.5)]) -> str:
        pytest.fail("Invalid constrained arguments must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert "a multiple of 0.5" in envelope.error.message


async def test_a_short_list_names_its_minimum_item_count() -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {"value": ["a"]})), capabilities=[ToolErrors()]
    )

    @agent.tool_plain
    def configure(value: Annotated[list[str], Field(min_length=3)]) -> str:
        pytest.fail("Invalid constrained arguments must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert "at least 3 items" in envelope.error.message
    assert "for example" not in envelope.error.message


async def test_a_long_list_names_its_maximum_item_count() -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {"value": ["a", "b", "c"]})),
        capabilities=[ToolErrors()],
    )

    @agent.tool_plain
    def configure(value: Annotated[list[str], Field(max_length=2)]) -> str:
        pytest.fail("Invalid constrained arguments must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert "at most 2 items" in envelope.error.message
    assert "for example" not in envelope.error.message


async def test_a_string_array_example_respects_a_tiny_maximum() -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {"fields": "name,primary_ip"})),
        capabilities=[ToolErrors()],
    )

    @agent.tool_plain
    def configure(fields: Annotated[list[str], Field(max_length=1)]) -> str:
        pytest.fail("Invalid constrained arguments must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert 'for example ["name"]' in envelope.error.message
    assert "name,primary_ip" not in envelope.model_dump_json()


async def test_a_string_array_example_respects_a_zero_maximum() -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {"value": "name"})), capabilities=[ToolErrors()]
    )

    @agent.tool_plain
    def configure(value: Annotated[list[str], Field(max_length=0)]) -> str:
        pytest.fail("Invalid constrained arguments must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert "for example []" in envelope.error.message


async def test_a_string_array_example_is_padded_to_a_tiny_minimum() -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {"value": "name"})), capabilities=[ToolErrors()]
    )

    @agent.tool_plain
    def configure(value: Annotated[list[str], Field(min_length=2)]) -> str:
        pytest.fail("Invalid constrained arguments must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert 'for example ["value", "value_1"]' in envelope.error.message


async def test_a_string_array_example_fits_loose_item_bounds() -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {"value": "name"})), capabilities=[ToolErrors()]
    )

    @agent.tool_plain
    def configure(value: Annotated[list[str], Field(min_length=1, max_length=3)]) -> str:
        pytest.fail("Invalid constrained arguments must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert 'for example ["value"]' in envelope.error.message


async def test_a_string_array_example_is_omitted_when_the_minimum_is_large() -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {"value": "name"})), capabilities=[ToolErrors()]
    )

    @agent.tool_plain
    def configure(value: Annotated[list[str], Field(min_length=3)]) -> str:
        pytest.fail("Invalid constrained arguments must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert "at least 3 items" in envelope.error.message
    assert "for example" not in envelope.error.message


async def test_an_optional_string_array_keeps_its_item_bounds() -> None:
    agent = Agent[AgentDeps, str](
        _model(ToolCallPart("configure", {"value": ["a"]})), capabilities=[ToolErrors()]
    )

    @agent.tool_plain
    def configure(value: Annotated[list[str], Field(min_length=3)] | None = None) -> str:
        pytest.fail("Invalid constrained arguments must not execute")

    result = await agent.run("configure", deps=AgentDeps())

    (envelope,) = _errors(result.all_messages())
    assert "at least 3 items" in envelope.error.message
    assert "for example" not in envelope.error.message


async def test_a_huge_minimum_item_schema_states_the_bound_without_materializing_an_example() -> (
    None
):
    remote = _RemoteSchemaToolset(
        {
            "type": "object",
            "properties": {
                "value": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1_000_000_000,
                }
            },
        }
    )

    (envelope,) = await _invoke(remote, {"value": "a,b"})

    assert "at least 1000000000 items" in envelope.error.message
    assert "for example" not in envelope.error.message
    assert len(envelope.error.message) < 200
    assert remote.executed is False


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("too_short", "array"),
        ("too_long", "array"),
        ("greater_than_equal", "integer"),
        ("less_than_equal", "integer"),
        ("greater_than", "integer"),
        ("less_than", "integer"),
        ("multiple_of", "number"),
    ],
)
def test_constraint_codes_without_an_advertised_bound_fall_back_to_the_type(
    code: str, expected: str
) -> None:
    issue = ToolErrors()._issue("value", code, expected, schema={"type": expected})
    assert issue.message == f"Invalid `value`: expected {expected}."
