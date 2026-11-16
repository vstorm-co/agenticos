"""`core.input`: where a graph begins, holding what the run was started with.

It has no input of its own. The invoking surface - an API call, the Run
dialog, a WebSocket - supplied a payload when it admitted the run, and this node
hands it to the graph as `payload`, with `triggered_by` naming the surface.

With neither `fields` nor `input_schema` configured the payload is any JSON object: nodes downstream
bind to fields of it by path (`payload.question`), and a path the payload does
not have is refused when that node is dispatched. Declared `fields` make it a
contract instead. The run is refused at the start when its input does not fit
them (`input_problems`), and the `out` port carries a `payload` typed by them
(`ports_for`), so a binding to `payload.seats` is checked against its target's
type at publish rather than when the run reaches it.

`input_schema` instead accepts a portable JSON Schema Draft 2020-12 contract
for a JSON object, including nested arrays and local references. Admission validates
it directly; its payload port stays open for path bindings without generating Python models.
"""

import re
from copy import deepcopy
from datetime import date
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    create_model,
    field_validator,
    model_validator,
)

from app.services.workflow_execution import context
from app.workflows.contracts.definition import Port
from app.workflows.contracts.fields import InputField
from app.workflows.contracts.input_schema import (
    InputSchema,
    check_input_schema,
    schema_input_problems,
)
from app.workflows.contracts.io import WorkflowInputPayload
from app.workflows.contracts.results import Completed, NodeResult

MAX_FIELDS = 50

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Draft 2020-12 `format` is an annotation for ordinary validators. Preserve the
# legacy calendar assertion without requiring clients to opt into format checks.
_CALENDAR_DATE_PATTERN = (
    r"^(?:(?!0000)[0-9]{4}-(?:"
    r"(?:0[13578]|1[02])-(?:0[1-9]|[12][0-9]|3[01])|"
    r"(?:0[469]|11)-(?:0[1-9]|[12][0-9]|30)|"
    r"02-(?:0[1-9]|1[0-9]|2[0-8]))|"
    r"(?:[0-9]{2}(?:0[48]|[2468][048]|[13579][26])|"
    r"(?:0[48]|[2468][048]|[13579][26])00)-02-29)$"
)

STATIC_PORTS = (Port(id="out", label="Out", kind="output", schema=WorkflowInputPayload),)


class TriggerInputConfig(BaseModel):
    """Simple fields, a portable Draft 2020-12 contract, or an open JSON object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fields: list[InputField] = Field(default_factory=list, max_length=MAX_FIELDS)
    input_schema: InputSchema | None = Field(
        default=None,
        description="JSON Schema Draft 2020-12 contract for JSON object input; references must be local to this document",
    )

    @field_validator("input_schema")
    @classmethod
    def _valid_schema(cls, schema: InputSchema | None) -> InputSchema | None:
        if schema is not None:
            check_input_schema(schema)
        return schema

    @model_validator(mode="after")
    def _names_are_unique(self) -> TriggerInputConfig:
        if self.fields and self.input_schema is not None:
            raise ValueError("Declare either simple fields or input_schema, not both")
        names = [field.name for field in self.fields]
        if len(set(names)) != len(names):
            raise ValueError("Two fields have the same name")
        return self


def _iso_date(value: str) -> str:
    if not _ISO_DATE.match(value):
        raise ValueError("A date is written YYYY-MM-DD")
    date.fromisoformat(value)
    return value


def _value_type(field: InputField) -> Any:
    """The type one field's value has in the payload model.

    A date and a choice are strings a later step binds to as strings, checked
    on the way in rather than typed apart.
    """
    if field.type == "choice":
        options = frozenset(field.options)

        def _offered(value: str) -> str:
            if value not in options:
                raise ValueError("Not one of the options")
            return value

        return Annotated[str, AfterValidator(_offered)]
    if field.type == "date":
        return Annotated[str, AfterValidator(_iso_date)]
    return {
        "text": str,
        "string_list": list[str],
        "number": float,
        "integer": int,
        "boolean": bool,
    }[field.type]


def payload_model(fields: list[InputField]) -> type[BaseModel]:
    """The model a run's input must fit: every declared field, and nothing else.

    Strict, so `"3"` is not a whole number and `1` is not `true`: the input is
    JSON, and a caller sends each value as its own type.
    """
    definitions: dict[str, Any] = {
        field.name: (
            _value_type(field) if field.required else _value_type(field) | None,
            Field(... if field.required else None, title=field.label or field.name),
        )
        for field in fields
    }
    return create_model(
        "Payload",
        __config__=ConfigDict(extra="forbid", strict=True, protected_namespaces=()),
        **definitions,
    )


def ports_for(config: BaseModel | None) -> tuple[Port, ...]:
    """`out`, carrying a `payload` typed by the declared fields when there are any."""
    if not isinstance(config, TriggerInputConfig) or not config.fields:
        return STATIC_PORTS
    typed = create_model(
        "WorkflowInputPayload",
        __config__=ConfigDict(frozen=True, extra="forbid"),
        payload=(payload_model(config.fields), ...),
        triggered_by=(str, ...),
    )
    return (Port(id="out", label="Out", kind="output", schema=typed),)


def effective_input_schema(config: TriggerInputConfig) -> dict[str, JsonValue]:
    """The portable input contract callers can inspect before execution.

    Legacy fields retain optional nulls and a closed object. Their strict integer
    token requirement is marked by `x-agenticos-strict-integer`, since ordinary
    JSON Schema treats integral floating-point numbers as integers too.
    With neither contract, callers may submit any JSON object. Schema defaults
    are annotations; admission never inserts or coerces values.
    """
    if config.input_schema is not None:
        return deepcopy(config.input_schema)
    if not config.fields:
        return {"type": "object"}
    properties: dict[str, JsonValue] = {}
    required: list[JsonValue] = []
    types = {
        "text": "string",
        "string_list": "array",
        "number": "number",
        "integer": "integer",
        "boolean": "boolean",
        "date": "string",
        "choice": "string",
    }
    for field in config.fields:
        value: InputSchema = {"type": types[field.type]}
        if field.type == "string_list":
            value["items"] = {"type": "string"}
        elif field.type == "integer":
            value["x-agenticos-strict-integer"] = True
        elif field.type == "choice":
            value["enum"] = list(field.options)
        elif field.type == "date":
            value["format"] = "date"
            value["pattern"] = _CALENDAR_DATE_PATTERN
            value["maxLength"] = 10
        if not field.required:
            value = {"anyOf": [value, {"type": "null"}]}
        else:
            required.append(field.name)
        value["title"] = field.label or field.name
        if field.description:
            value["description"] = field.description
        properties[field.name] = value
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def input_problems(config: TriggerInputConfig, run_input: dict[str, Any]) -> list[dict[str, str]]:
    """What is wrong with `run_input` against the selected input contract.

    Each entry is `{field, message, type}`, `type` being the validator's own error
    type (`missing`, `int_type`, `extra_forbidden`, ...), so a form can say per answer
    what it needed. A refused value is never quoted.

    Empty when it fits, or when neither simple fields nor a schema are declared.
    """
    if config.input_schema is not None:
        return schema_input_problems(config.input_schema, run_input)
    if not config.fields:
        return []
    try:
        payload_model(config.fields).model_validate(run_input)
    except ValidationError as exc:
        return [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors(include_url=False, include_input=False)
        ]
    return []


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand the graph the run's frozen input."""
    current = context.current()
    return Completed[WorkflowInputPayload](
        output=WorkflowInputPayload(payload=current.run_input, triggered_by=current.triggered_by)
    )
