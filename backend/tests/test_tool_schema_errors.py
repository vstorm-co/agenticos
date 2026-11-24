"""A remote MCP schema must not turn argument validation into unchecked I/O."""

import asyncio
import json
from pathlib import Path
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

from app.agents import tool_schema_validation
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
async def test_a_remote_schema_reference_is_refused_without_network_or_file_access(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fetched: list[bool] = []

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        fetched.append(True)
        await reader.readuntil(b"\r\n\r\n")
        body = json.dumps(
            {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "string"}
        ).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    async with await asyncio.start_server(serve, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        reference = f"http://127.0.0.1:{port}/schema?token=secret"
        remote = _RemoteSchemaToolset(
            {"type": "object", "properties": {"value": {"$ref": reference}}}
        )
        (envelope,) = await _invoke(remote, {"value": "submitted"})

    assert fetched == []
    assert remote.executed is False
    assert envelope.error.code == "tool_unavailable"
    assert envelope.error.execution == "not_started"
    assert envelope.error.recovery == "rediscover_tools"
    assert envelope.error.id in caplog.text
    assert reference not in envelope.model_dump_json()
    assert "secret" not in envelope.model_dump_json()


@pytest.mark.security
async def test_a_file_schema_reference_is_refused_even_when_the_file_would_validate(
    tmp_path: Path,
) -> None:
    canary = tmp_path / "schema.json"
    canary.write_text(
        json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "string"})
    )
    reference = canary.as_uri()
    remote = _RemoteSchemaToolset({"type": "object", "properties": {"value": {"$ref": reference}}})

    (envelope,) = await _invoke(remote, {"value": "submitted"})

    assert envelope.error.code == "tool_unavailable"
    assert envelope.error.execution == "not_started"
    assert remote.executed is False
    assert reference not in envelope.model_dump_json()


@pytest.mark.security
async def test_a_schema_timeout_reaches_the_agent_without_dispatching_the_tool(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(tool_schema_validation, "DEFAULT_TIMEOUT_SECONDS", 1.0)
    remote = _RemoteSchemaToolset(
        {"type": "object", "properties": {"value": {"type": "string", "pattern": "(a+)+b"}}}
    )

    (envelope,) = await _invoke(remote, {"value": "a" * 40 + "c"})

    assert remote.executed is False
    assert envelope.error.code == "tool_unavailable"
    assert envelope.error.execution == "not_started"
    assert envelope.error.recovery == "rediscover_tools"
    assert "time budget" in envelope.error.message
    assert envelope.error.id in caplog.text
    assert "aaaa" not in envelope.model_dump_json()


async def test_overlapping_schema_branches_produce_one_actionable_correction() -> None:
    remote = _RemoteSchemaToolset(
        {
            "type": "object",
            "properties": {
                "value": {
                    "allOf": [
                        {"type": "integer", "minimum": 0},
                        {"type": "integer", "maximum": 5},
                    ]
                }
            },
        }
    )

    (envelope,) = await _invoke(remote, {"value": "submitted"})

    assert remote.executed is False
    assert len(envelope.error.issues) == 1
    assert envelope.error.issues[0].field == "value"
    assert envelope.error.issues[0].message == "Invalid `value`: expected integer."


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
