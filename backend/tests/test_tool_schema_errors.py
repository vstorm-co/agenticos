"""A remote MCP schema must not turn argument validation into unchecked I/O."""

import urllib.request
from typing import Any

import pytest
from pydantic import JsonValue, TypeAdapter
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_core import SchemaValidator

from app.agents.deps import AgentDeps
from app.agents.tool_errors import ToolErrorEnvelope, ToolErrors

pytestmark = pytest.mark.anyio


class _RemoteSchemaToolset(AbstractToolset[AgentDeps]):
    def __init__(self, schema: dict[str, JsonValue]) -> None:
        self.schema = schema
        self.executed = False

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
        self.executed = True
        return "started"


async def _invoke(
    remote: _RemoteSchemaToolset, arguments: dict[str, JsonValue]
) -> list[ToolErrorEnvelope]:
    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("remote", arguments)])
        return ModelResponse(parts=[TextPart("done")])

    agent = Agent[AgentDeps, str](
        FunctionModel(respond), toolsets=[remote], capabilities=[ToolErrors()]
    )
    result = await agent.run("run remote", deps=AgentDeps())
    return [
        ToolErrorEnvelope.model_validate_json(part.content)
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.outcome == "failed"
    ]


@pytest.mark.security
@pytest.mark.parametrize(
    "reference",
    [
        "http://127.0.0.1/private?token=secret",
        "https://internal.invalid/private",
        "file:///etc/passwd",
    ],
)
async def test_a_remote_schema_reference_is_refused_without_network_or_file_access(
    reference: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def refuse_io(*_args: object, **_kwargs: object) -> object:
        pytest.fail("Schema validation attempted unchecked network or file access")

    monkeypatch.setattr(urllib.request, "urlopen", refuse_io)
    remote = _RemoteSchemaToolset({"type": "object", "properties": {"value": {"$ref": reference}}})

    (envelope,) = await _invoke(remote, {"value": "submitted"})

    assert remote.executed is False
    assert envelope.error.code == "tool_unavailable"
    assert envelope.error.execution == "not_started"
    assert envelope.error.recovery == "rediscover_tools"
    assert envelope.error.id in caplog.text
    assert reference not in envelope.model_dump_json()
    assert "secret" not in envelope.model_dump_json()


async def test_a_local_schema_reference_still_validates_arguments_and_dispatches() -> None:
    remote = _RemoteSchemaToolset(
        {
            "type": "object",
            "$defs": {"names": {"type": "array", "items": {"type": "string"}}},
            "properties": {"value": {"$ref": "#/$defs/names"}},
        }
    )

    errors = await _invoke(remote, {"value": ["one", "two"]})

    assert errors == []
    assert remote.executed is True


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {"value": {"type": "invalid-type"}}},
        {"type": "object", "properties": {"value": {"$ref": "#/$defs/missing"}}},
    ],
)
async def test_invalid_or_unresolvable_schemas_are_tool_failures_instead_of_run_failures(
    schema: dict[str, JsonValue],
) -> None:
    remote = _RemoteSchemaToolset(schema)

    (envelope,) = await _invoke(remote, {"value": "submitted"})

    assert remote.executed is False
    assert envelope.error.code == "tool_unavailable"
    assert envelope.error.execution == "not_started"
    assert "cannot be validated safely" in envelope.error.message
