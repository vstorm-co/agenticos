"""Controlled tool failures, shared by the model, live frames and stored history.

Validation is rejected before execution. An exception after dispatch does not
prove that an external action failed, so its disposition remains unknown.
Only errors built here carry the provenance used by transcript rendering;
matching JSON from an external server is still untrusted diagnostic text.
"""

import logging
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

from jsonschema import FormatChecker, validators
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from pydantic_ai import AgentRunResult, RunContext
from pydantic_ai.capabilities import (
    AbstractCapability,
    RawToolArgs,
    ValidatedToolArgs,
    WrapRunHandler,
    WrapToolValidateHandler,
)
from pydantic_ai.exceptions import ToolFailed
from pydantic_ai.messages import ModelMessage, ToolCallPart, ToolReturnPart
from pydantic_ai.tools import ToolDefinition
from referencing import Registry
from referencing.exceptions import Unresolvable

from app.agents.deps import AgentDeps
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

type ErrorCode = Literal[
    "invalid_arguments",
    "tool_unavailable",
    "permission_denied",
    "transient_failure",
    "execution_unknown",
]
type ExecutionDisposition = Literal["not_started", "started", "unknown"]
type Recovery = Literal[
    "correct_arguments", "rediscover_tools", "stop", "retry", "inspect_execution_status"
]

TOOL_ERROR_METADATA = "agenticos_tool_error"


class ToolArgumentIssue(BaseModel):
    """A correction without the submitted value or validator context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    code: str
    expected_type: str
    message: str


class ToolError(BaseModel):
    """What the runtime knows about a failed call and its next safe step.

    For a nested call, `tool` and `execution` describe the model-visible
    `run_code` script; `cause_tool` and `cause_execution` retain the nested
    tool's identity and disposition. Propagation preserves its original error
    reference and argument issues, even when earlier script effects make the
    script's overall outcome unknown.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^err_[0-9a-f]{32}$")
    code: ErrorCode
    tool: str
    execution: ExecutionDisposition
    message: str
    recovery: Recovery
    issues: list[ToolArgumentIssue] = Field(default_factory=list)
    exception_type: str | None = None
    cause_tool: str | None = None
    cause_execution: ExecutionDisposition | None = None


class ToolErrorEnvelope(BaseModel):
    """The JSON contract preserved through tool returns and approval replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error: ToolError


class ControlledToolError(str):
    """In-process provenance; external MCP JSON cannot construct this type."""


_captured_errors: ContextVar[list[ControlledToolError] | None] = ContextVar(
    "captured_tool_errors", default=None
)


@contextmanager
def capture_tool_errors() -> Generator[list[ControlledToolError]]:
    """Keep trusted failures across a sandbox boundary that erases Python types."""
    errors: list[ControlledToolError] = []
    token = _captured_errors.set(errors)
    try:
        yield errors
    finally:
        _captured_errors.reset(token)


def nested_tool_error(
    content: ControlledToolError, *, tool: str, calls_started: bool, error: Exception
) -> ControlledToolError:
    """Retain a child's error reference and corrections on its script's return."""
    child = ToolErrorEnvelope.model_validate_json(content).error
    message = f"Nested tool `{child.tool}` failed: {child.message}"
    if calls_started:
        message += " Earlier tool calls started; inspect their execution status before retrying the script."
    outer = child.model_copy(
        update={
            "tool": tool,
            "cause_tool": child.tool,
            "cause_execution": child.execution,
            "message": message,
            "execution": "unknown" if calls_started else "started",
            "code": "execution_unknown" if calls_started else child.code,
            "recovery": "inspect_execution_status" if calls_started else child.recovery,
        }
    )
    logger.warning(
        "Tool error %s propagated from %s through %s (execution=%s)",
        outer.id,
        child.tool,
        tool,
        outer.execution,
        exc_info=(type(error), error, error.__traceback__),
    )
    return ControlledToolError(ToolErrorEnvelope(error=outer).model_dump_json(exclude_none=True))


def controlled_tool_error(part: ToolReturnPart) -> ToolErrorEnvelope | None:
    """Read a local error, accepting its persisted provenance after JSON replay."""
    marked = isinstance(part.metadata, dict) and part.metadata.get(TOOL_ERROR_METADATA) is True
    if not isinstance(part.content, ControlledToolError) and not marked:
        return None
    try:
        envelope = (
            ToolErrorEnvelope.model_validate_json(part.content)
            if isinstance(part.content, str)
            else ToolErrorEnvelope.model_validate(part.content)
        )
    except ValidationError:
        return None
    return envelope if envelope.error.tool == part.tool_name else None


def mark_tool_errors(messages: Sequence[ModelMessage]) -> None:
    """Keep local provenance when a string subclass is serialized as plain JSON."""
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolReturnPart) and isinstance(part.content, ControlledToolError):
                part.metadata = {**(part.metadata or {}), TOOL_ERROR_METADATA: True}


def tool_error(
    *,
    tool: str,
    code: ErrorCode,
    execution: ExecutionDisposition,
    message: str,
    recovery: Recovery,
    issues: list[ToolArgumentIssue] | None = None,
    exception_type: str | None = None,
    error: Exception | None = None,
) -> ControlledToolError:
    """Build one error reference and log it beside its private diagnostic cause."""
    envelope = ToolErrorEnvelope(
        error=ToolError(
            id=f"err_{uuid4().hex}",
            code=code,
            tool=tool,
            execution=execution,
            message=message,
            recovery=recovery,
            issues=issues or [],
            exception_type=exception_type,
        )
    )
    logger.warning(
        "Tool error %s: %s (%s, execution=%s)",
        envelope.error.id,
        tool,
        code,
        execution,
        exc_info=(type(error), error, error.__traceback__) if error is not None else None,
    )
    content = ControlledToolError(envelope.model_dump_json(exclude_none=True))
    captured = _captured_errors.get()
    if captured is not None:
        captured.append(content)
    return content


def _field_schema(
    schema: dict[str, JsonValue], location: tuple[str | int, ...]
) -> dict[str, JsonValue]:
    current = schema
    for item in location:
        current = _local_schema(schema, current)
        properties = current.get("properties")
        child = (
            properties.get(item)
            if isinstance(properties, dict) and isinstance(item, str)
            else current.get("items")
        )
        if not isinstance(child, dict):
            return {}
        current = child
    return _local_schema(schema, current)


def _local_schema(root: dict[str, JsonValue], schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/$defs/"):
        definitions = root.get("$defs")
        resolved = (
            definitions.get(reference.removeprefix("#/$defs/"))
            if isinstance(definitions, dict)
            else None
        )
        return resolved if isinstance(resolved, dict) else {}
    return schema


def _expected_type(schema: dict[str, JsonValue], code: str) -> str:
    alternatives = schema.get("anyOf")
    if isinstance(alternatives, list):
        expected = [
            _expected_type(alternative, code)
            for alternative in alternatives
            if isinstance(alternative, dict) and alternative.get("type") != "null"
        ]
        if expected:
            return " or ".join(dict.fromkeys(expected))
    if schema.get("format") == "uuid" or code.startswith("uuid_"):
        return "UUID"
    kind = schema.get("type")
    if kind == "array":
        items = schema.get("items")
        return (
            "array of strings"
            if isinstance(items, dict) and items.get("type") == "string"
            else "array"
        )
    if isinstance(kind, str):
        return kind
    return {"list_type": "array", "string_type": "string", "int_parsing": "integer"}.get(
        code, "schema-compatible value"
    )


@dataclass
class ToolErrors(AbstractCapability[AgentDeps]):
    """Report invalid arguments before approval and uncertain outcomes after dispatch."""

    _tool_names: set[str] = field(default_factory=set, init=False, repr=False)

    async def prepare_tools(
        self, ctx: RunContext[AgentDeps], tool_defs: list[ToolDefinition]
    ) -> list[ToolDefinition]:
        self._tool_names = {tool.name for tool in tool_defs}
        return tool_defs

    async def wrap_tool_validate(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: RawToolArgs,
        handler: WrapToolValidateHandler,
    ) -> ValidatedToolArgs:
        try:
            validated = await handler(args)
        except ValidationError as error:
            issues: list[ToolArgumentIssue] = []
            for problem in error.errors(
                include_url=False, include_input=False, include_context=False
            )[:10]:
                location = problem["loc"]
                name = ".".join(str(item) for item in location) or "arguments"
                code = problem["type"]
                expected = _expected_type(
                    _field_schema(tool_def.parameters_json_schema, location), code
                )
                issues.append(self._issue(name, code, expected))
            raise ToolFailed(self._invalid_arguments(call.tool_name, issues)) from error
        # MCPToolset validates the JSON container, leaving its advertised input
        # schema to the remote server. Check that schema before approval or dispatch
        # so a remote type refusal has the same actionable, local contract.
        metadata = tool_def.metadata or {}
        if tool_def.capability_id is None and "annotations" in metadata and "meta" in metadata:
            schema = tool_def.parameters_json_schema
            issues = []
            try:
                validator = validators.validator_for(schema)
                validator.check_schema(schema)
                # MCP schemas are server-controlled. An empty registry keeps
                # local references while preventing jsonschema's default URL
                # retriever from reading files or dialing an unchecked host.
                checker = validator(schema, format_checker=FormatChecker(), registry=Registry())
                for problem in checker.iter_errors(validated):
                    location = tuple(problem.absolute_path)
                    name = ".".join(str(item) for item in location) or "arguments"
                    field_schema = _field_schema(schema, location)
                    code = (
                        "uuid_parsing"
                        if problem.validator == "format" and problem.validator_value == "uuid"
                        else str(problem.validator)
                    )
                    expected = _expected_type(field_schema, code)
                    issues.append(self._issue(name, code, expected))
                    if len(issues) == 10:
                        break
            except (SchemaError, Unresolvable) as error:
                raise ToolFailed(
                    tool_error(
                        tool=call.tool_name,
                        code="tool_unavailable",
                        execution="not_started",
                        message="The tool's advertised argument schema cannot be validated safely. Rediscover the tool before invoking it.",
                        recovery="rediscover_tools",
                        error=error,
                    )
                ) from error
            if issues:
                raise ToolFailed(self._invalid_arguments(call.tool_name, issues))
        return validated

    def _issue(self, name: str, code: str, expected: str) -> ToolArgumentIssue:
        message = f"Invalid `{name}`: expected {expected}."
        if expected == "array of strings":
            example = '["name", "primary_ip"]' if name == "fields" else '["value"]'
            message = f"`{name}` must be an array of strings, for example {example}."
        if name == "workflow_id" and expected == "UUID":
            lookup = next(
                (
                    tool
                    for tool in sorted(self._tool_names)
                    if tool.endswith("list_workflow_definitions")
                ),
                None,
            )
            if lookup is not None:
                message += f" Use an ID returned by `{lookup}`."
        return ToolArgumentIssue(field=name, code=code, expected_type=expected, message=message)

    @staticmethod
    def _invalid_arguments(tool: str, issues: list[ToolArgumentIssue]) -> ControlledToolError:
        return tool_error(
            tool=tool,
            code="invalid_arguments",
            execution="not_started",
            message=" ".join(issue.message for issue in issues)
            + " Request rejected during validation; no tool execution started.",
            recovery="correct_arguments",
            issues=issues,
        )

    async def on_tool_execute_error(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        error: Exception,
    ) -> object:
        code: ErrorCode = "execution_unknown"
        recovery: Recovery = "inspect_execution_status"
        if isinstance(error, PermissionError) or (
            isinstance(error, AppException) and error.status_code in (401, 403)
        ):
            code, recovery = "permission_denied", "stop"
        elif isinstance(error, TimeoutError | ConnectionError) or (
            isinstance(error, AppException) and error.status_code in (429, 503)
        ):
            code = "transient_failure"
        message = (
            error.message
            if isinstance(error, AppException)
            else f"Tool execution failed: {type(error).__name__}."
        )
        raise ToolFailed(
            tool_error(
                tool=call.tool_name,
                code=code,
                execution="unknown",
                message=message
                + " The execution outcome is unknown; check its status before retrying.",
                recovery=recovery,
                exception_type=type(error).__name__,
                error=error,
            )
        ) from error

    async def wrap_run(
        self, ctx: RunContext[AgentDeps], *, handler: WrapRunHandler
    ) -> AgentRunResult[object]:
        """Persist provenance before a completed or parked run is serialized for replay."""
        result = await handler()
        mark_tool_errors(result.all_messages())
        return result
