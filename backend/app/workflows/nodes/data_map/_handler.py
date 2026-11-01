"""`data.map`: pick values out of upstream outputs and give them a type.

Each mapping reads one value with a JMESPath expression (`_expr`) over the bound
`source`, coerces it to a declared type, and stores it under `target_field` in
`values`. Nothing is evaluated as code, and a coercion is a conversion with a
fixed meaning - `"42"` to `42`, `1` to `true` - not a format string.

A value the expression does not find takes the mapping's `default`. A value that
cannot become the declared type fails the node naming the field, before anything
downstream reads it.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from app.workflows.contracts.io import FileRef, TableIORef
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.nodes import _expr

Coercion = Literal["string", "number", "integer", "boolean", "json", "file_ref", "table_ref"]

_ADAPTERS: dict[Coercion, TypeAdapter[Any]] = {
    "string": TypeAdapter(str),
    "number": TypeAdapter(float),
    "integer": TypeAdapter(int),
    "boolean": TypeAdapter(bool),
    "json": TypeAdapter(Any),
    "file_ref": TypeAdapter(FileRef),
    "table_ref": TypeAdapter(TableIORef),
}


class FieldMapping(BaseModel):
    """One output field: where its value comes from, and what type it becomes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_field: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    source_path: str = Field(
        min_length=1,
        max_length=_expr.MAX_EXPRESSION_LENGTH,
        description="A JMESPath expression over the input, for example source.payload.email.",
    )
    coerce_to: Coercion = "json"
    default: Any = None

    @field_validator("source_path")
    @classmethod
    def _checked(cls, source_path: str) -> str:
        return _expr.check(source_path)


class DataMapConfig(BaseModel):
    """The fields to build, in order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mappings: tuple[FieldMapping, ...] = Field(min_length=1, max_length=100)

    @field_validator("mappings")
    @classmethod
    def _distinct_targets(cls, mappings: tuple[FieldMapping, ...]) -> tuple[FieldMapping, ...]:
        targets = [mapping.target_field for mapping in mappings]
        if len(set(targets)) != len(targets):
            raise ValueError("Each mapping needs its own target field")
        return mappings


class DataMapInput(BaseModel):
    """What the mappings read, bound from any upstream output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Any = None


class DataMapOutput(BaseModel):
    """The mapped fields, by `target_field`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    values: dict[str, Any]


def coerce(value: Any, to: Coercion) -> Any:
    """`value` as the declared type, or `ValueError` naming why it cannot be.

    Lax, the way a form field is: `"42"` is an integer, `"true"` and `1` are
    booleans, and a number or a structure becomes text as JSON writes it. A
    value that is already the right type passes unchanged.

    Raises:
        ValueError: `value` has no reading as that type.
    """
    if to == "string" and not isinstance(value, str):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    adapter = _ADAPTERS[to]
    try:
        return adapter.dump_python(adapter.validate_python(value), mode="json")
    except ValidationError as exc:
        raise ValueError(f"cannot be read as {to}") from exc


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Build every mapped field, or fail on the first that does not fit."""
    if not isinstance(config, DataMapConfig):
        return Failed(error=WorkflowError(code="MAPPING_MISSING", message="No fields are mapped"))
    data = {"source": node_input.source if isinstance(node_input, DataMapInput) else None}
    values: dict[str, Any] = {}
    for mapping in config.mappings:
        try:
            found = _expr.evaluate(mapping.source_path, data)
        except _expr.ExpressionError as exc:
            return Failed(
                error=WorkflowError(
                    code="MAPPING_FAILED",
                    message=str(exc),
                    details={"target_field": mapping.target_field},
                )
            )
        if found is None:
            found = mapping.default
        try:
            values[mapping.target_field] = (
                None if found is None else coerce(found, mapping.coerce_to)
            )
        except ValueError as exc:
            return Failed(
                error=WorkflowError(
                    code="MAPPING_COERCION_FAILED",
                    message=f"The value for {mapping.target_field} {exc}",
                    details={"target_field": mapping.target_field, "coerce_to": mapping.coerce_to},
                )
            )
    return Completed[DataMapOutput](output=DataMapOutput(values=values))
