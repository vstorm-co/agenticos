"""`core.input`: where a graph begins, holding what the run was started with.

It has no input of its own. The invoking surface - an API call, the Run
dialog, a WebSocket - supplied a payload when it admitted the run, and this node
hands it to the graph as `payload`, with `triggered_by` naming the surface.

With no `fields` configured the payload is any JSON object: nodes downstream
bind to fields of it by path (`payload.question`), and a path the payload does
not have is refused when that node is dispatched. Declared `fields` make it a
contract instead. The run is refused at the start when its input does not fit
them (`input_problems`), and the `out` port carries a `payload` typed by them
(`ports_for`), so a binding to `payload.seats` is checked against its target's
type at publish rather than when the run reaches it.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    create_model,
    model_validator,
)

from app.services.workflow_execution import context
from app.workflows.contracts.definition import Port
from app.workflows.contracts.io import WorkflowInputPayload
from app.workflows.contracts.results import Completed, NodeResult

MAX_FIELDS = 50
MAX_OPTIONS = 50

InputFieldType = Literal["text", "number", "integer", "boolean", "date", "choice"]

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

STATIC_PORTS = (Port(id="out", label="Out", kind="output", schema=WorkflowInputPayload),)


class InputField(BaseModel):
    """One value a run starts with, asked for by name in the Run dialog."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(
        pattern=r"^[a-z][a-z0-9_]{0,63}$",
        description="The key in the run's input, and in payload for a binding",
    )
    label: str | None = Field(default=None, max_length=120, description="Shown in the Run form")
    type: InputFieldType = "text"
    required: bool = True
    description: str | None = Field(default=None, max_length=500)
    options: list[str] = Field(
        default_factory=list, max_length=MAX_OPTIONS, description="What a choice offers"
    )

    @model_validator(mode="after")
    def _fits_its_type(self) -> InputField:
        # A name the generated payload model would inherit from `BaseModel`
        # (`copy`, `json`, ...) cannot be one of its fields.
        if hasattr(BaseModel, self.name):
            raise ValueError(f"{self.name!r} is reserved; name the field something else")
        if self.type == "choice":
            if not self.options or any(not option.strip() for option in self.options):
                raise ValueError("A choice needs at least one option, and none of them blank")
            if len(set(self.options)) != len(self.options):
                raise ValueError("A choice offers each option once")
        elif self.options:
            raise ValueError("Only a choice has options")
        return self


class TriggerInputConfig(BaseModel):
    """The typed fields a run starts with, or none for any JSON object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fields: list[InputField] = Field(default_factory=list, max_length=MAX_FIELDS)

    @model_validator(mode="after")
    def _names_are_unique(self) -> TriggerInputConfig:
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
    return {"text": str, "number": float, "integer": int, "boolean": bool}[field.type]


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


def input_problems(config: TriggerInputConfig, run_input: dict[str, Any]) -> list[dict[str, str]]:
    """What is wrong with `run_input` against the declared fields, one entry a field.

    Empty when it fits, or when no fields are declared.
    """
    if not config.fields:
        return []
    try:
        payload_model(config.fields).model_validate(run_input)
    except ValidationError as exc:
        return [
            {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
            for error in exc.errors(include_url=False, include_input=False)
        ]
    return []


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand the graph the run's frozen input."""
    current = context.current()
    return Completed[WorkflowInputPayload](
        output=WorkflowInputPayload(payload=current.run_input, triggered_by=current.triggered_by)
    )
