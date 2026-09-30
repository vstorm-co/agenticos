"""The Transform steps: reshape a list of objects without a code step.

Each is pure and typed, and all share one list contract (`_transform`): `items`
in, and - apart from Aggregate, Date & time and Crypto, which hand on one value -
`items` out, so they chain. A field is a dotted path; an item without it is
handled the same way by every step, described on each.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.nodes import _expr
from app.workflows.nodes._transform import (
    FIELD_PATH,
    MISSING,
    ItemsOutput,
    assign,
    items_of,
    lookup,
    without,
)

MAX_FIELDS = 50

FieldPath = Annotated[str, StringConstraints(pattern=FIELD_PATH, max_length=200)]
"""A field of an item, by a dotted path such as customer.email."""


class _Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _items(items: list[dict[str, Any]]) -> Completed[ItemsOutput]:
    return Completed[ItemsOutput](output=ItemsOutput(items=items))


def _not_configured(step: str) -> Failed:
    return Failed(
        error=WorkflowError(
            code="TRANSFORM_NOT_CONFIGURED", message=f"This {step} step is not set up"
        )
    )


# Edit fields


class SetField(_Config):
    """One field to set on every item, from an expression over the item."""

    name: FieldPath
    expression: str = Field(
        min_length=1,
        max_length=_expr.MAX_EXPRESSION_LENGTH,
        description="A JMESPath expression over the item, such as item.first_name",
    )

    @field_validator("expression")
    @classmethod
    def _checked(cls, expression: str) -> str:
        return _expr.check(expression)


class EditFieldsConfig(_Config):
    """The fields to set and the fields to remove, on every item."""

    set: tuple[SetField, ...] = Field(default=(), max_length=MAX_FIELDS)
    remove: tuple[FieldPath, ...] = Field(default=(), max_length=MAX_FIELDS)
    only_set: bool = Field(
        default=False, description="Keep only the fields set here, dropping every other"
    )


async def edit_fields(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Set each field from its expression - null where the item has nothing for it -
    then remove the ones named. A field to remove that an item lacks is skipped."""
    if not isinstance(config, EditFieldsConfig):
        return _not_configured("Edit fields")
    edited: list[dict[str, Any]] = []
    for index, item in enumerate(items_of(node_input)):
        result: dict[str, Any] = {} if config.only_set else item
        for field in config.set:
            try:
                value = _expr.evaluate(field.expression, {"item": item, "index": index})
            except _expr.ExpressionError as exc:
                return Failed(
                    error=WorkflowError(
                        code="CONDITION_FAILED",
                        message=str(exc),
                        details={"index": index, "field": field.name},
                    )
                )
            result = assign(result, field.name, value)
        for path in config.remove:
            result = without(result, path)
        edited.append(result)
    return _items(edited)


# Sort


class SortKey(_Config):
    field: FieldPath
    descending: bool = False


class SortConfig(_Config):
    """The fields to sort by, the first deciding first."""

    by: tuple[SortKey, ...] = Field(min_length=1, max_length=10)


def _rank(value: Any) -> tuple[int, Any]:
    """An order that never compares a number with a string: numbers, then text,
    then true and false, then anything else by its text."""
    if isinstance(value, bool):
        return (2, value)
    if isinstance(value, int | float):
        return (0, value)
    if isinstance(value, str):
        return (1, value)
    return (3, str(value))


async def sort(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Sort by each key in turn. Items missing a key, or holding null, go last
    whichever way it sorts; items that tie keep their order."""
    if not isinstance(config, SortConfig):
        return _not_configured("Sort")
    items = list(items_of(node_input))
    for key in reversed(config.by):
        present = [item for item in items if lookup(item, key.field) not in (MISSING, None)]
        absent = [item for item in items if lookup(item, key.field) in (MISSING, None)]
        present.sort(key=lambda item: _rank(lookup(item, key.field)), reverse=key.descending)
        items = present + absent
    return _items(items)


# Limit


class LimitConfig(_Config):
    count: int = Field(ge=1, le=10_000, description="How many items to keep")
    from_end: bool = Field(default=False, description="Keep the last items instead of the first")


async def limit(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """The first `count` items, or the last."""
    if not isinstance(config, LimitConfig):
        return _not_configured("Limit")
    items = items_of(node_input)
    return _items(items[-config.count :] if config.from_end else items[: config.count])


# Remove duplicates


class RemoveDuplicatesConfig(_Config):
    fields: tuple[FieldPath, ...] = Field(
        default=(),
        max_length=MAX_FIELDS,
        description="The fields two items must share to be duplicates; the whole item when empty",
    )


def _identity(value: Any) -> str:
    """A value as text two equal values share, whatever order their keys are in."""
    return json.dumps(value, sort_keys=True, default=str)


async def remove_duplicates(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Keep the first of each run of items equal on the fields named. A field an
    item lacks counts as a value of its own, the same for every item without it."""
    fields = config.fields if isinstance(config, RemoveDuplicatesConfig) else ()
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for item in items_of(node_input):
        found = [lookup(item, path) for path in fields]
        key = _identity(
            [["missing"] if value is MISSING else ["value", value] for value in found]
            if fields
            else item
        )
        if key not in seen:
            seen.add(key)
            kept.append(item)
    return _items(kept)


# Aggregate


class AggregateConfig(_Config):
    fields: tuple[FieldPath, ...] = Field(min_length=1, max_length=MAX_FIELDS)


class AggregateOutput(_Config):
    """Each field's values across the items, by field."""

    values: dict[str, list[Any]]


async def aggregate(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Collect each field's values across the items into one list per field, in
    order. An item without the field adds nothing to its list."""
    if not isinstance(config, AggregateConfig):
        return _not_configured("Aggregate")
    items = items_of(node_input)
    values = {
        path: [found for item in items if (found := lookup(item, path)) is not MISSING]
        for path in config.fields
    }
    return Completed[AggregateOutput](output=AggregateOutput(values=values))


# Split out


class SplitOutConfig(_Config):
    field: FieldPath
    keep_other_fields: bool = Field(
        default=True, description="Copy the item's other fields onto each new item"
    )


async def split_out(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """One item per element of a list field: an object element becomes the item,
    anything else sits under the field's own name. An item whose field is missing
    or not a list is kept as it is."""
    if not isinstance(config, SplitOutConfig):
        return _not_configured("Split out")
    name = config.field.rsplit(".", 1)[-1]
    split: list[dict[str, Any]] = []
    for item in items_of(node_input):
        elements = lookup(item, config.field)
        if not isinstance(elements, list):
            split.append(item)
            continue
        base = without(item, config.field) if config.keep_other_fields else {}
        for element in elements:
            split.append(
                {**base, **element} if isinstance(element, dict) else {**base, name: element}
            )
    return _items(split)


# Summarize


Operation = Literal["count", "sum", "min", "max", "average", "count_distinct"]


class Summary(_Config):
    operation: Operation
    field: FieldPath | None = Field(default=None, description="Not needed to count")

    @model_validator(mode="after")
    def _a_field_to_summarize(self) -> Self:
        if self.operation != "count" and self.field is None:
            raise ValueError(f"{self.operation} needs the field it summarizes")
        return self

    @property
    def key(self) -> str:
        return self.operation if self.field is None else f"{self.operation}_{self.field}"


class SummarizeConfig(_Config):
    group_by: tuple[FieldPath, ...] = Field(default=(), max_length=10)
    summaries: tuple[Summary, ...] = Field(min_length=1, max_length=MAX_FIELDS)


def _numbers(values: list[Any]) -> list[float]:
    return [
        value for value in values if isinstance(value, int | float) and not isinstance(value, bool)
    ]


_SUMMARIES: dict[str, Callable[[list[Any]], Any]] = {
    "count": len,
    "sum": lambda values: sum(_numbers(values)),
    "min": lambda values: min(_numbers(values), default=None),
    "max": lambda values: max(_numbers(values), default=None),
    "average": lambda values: (
        sum(_numbers(values)) / len(_numbers(values)) if _numbers(values) else None
    ),
    "count_distinct": lambda values: len({_identity(value) for value in values}),
}


async def summarize(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """One item per group: its group fields and each summary, named
    `operation_field`. Sum, min, max and average read numbers only; a field an
    item lacks is left out of its summary, and a missing group field groups as null."""
    if not isinstance(config, SummarizeConfig):
        return _not_configured("Summarize")
    groups: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    for item in items_of(node_input):
        values = {
            path: None if (found := lookup(item, path)) is MISSING else found
            for path in config.group_by
        }
        groups.setdefault(_identity(values), (values, []))[1].append(item)
    summarized: list[dict[str, Any]] = []
    for group_values, members in groups.values():
        row = dict(group_values)
        for summary in config.summaries:
            present = (
                members
                if summary.field is None
                else [
                    found
                    for item in members
                    if (found := lookup(item, summary.field)) is not MISSING
                ]
            )
            row[summary.key] = _SUMMARIES[summary.operation](present)
        summarized.append(row)
    return _items(summarized)


# Date & time


Unit = Literal["seconds", "minutes", "hours", "days", "weeks"]


class DateTimeConfig(_Config):
    operation: Literal["now", "add", "subtract", "format"] = "now"
    amount: int = Field(default=0, ge=0, le=100_000)
    unit: Unit = "days"
    format: str = Field(
        default="%Y-%m-%d %H:%M",
        max_length=100,
        description="How to write it out, such as %d.%m.%Y",
    )
    timezone: str | None = Field(
        default=None,
        max_length=64,
        description="An IANA timezone, such as Europe/Warsaw. Empty: the workflow's own",
    )

    @field_validator("timezone")
    @classmethod
    def _a_timezone_that_exists(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"{value} is not a timezone") from exc
        return value


class DateTimeInput(_Config):
    value: datetime | None = None


class DateTimeOutput(_Config):
    """The moment, as a timestamp and written out in the timezone asked for."""

    value: datetime
    formatted: str


async def date_time(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Now, or the bound moment moved by an amount, written out in a timezone -
    the step's, else the run's (the workflow's setting when it started), else UTC
    outside a run. A moment with no timezone of its own is read as UTC."""
    settings = config if isinstance(config, DateTimeConfig) else DateTimeConfig()
    bound = node_input.value if isinstance(node_input, DateTimeInput) else None
    if settings.operation != "now" and bound is None:
        return Failed(
            error=WorkflowError(
                code="DATETIME_NEEDS_A_VALUE", message="Bind the moment this step works on"
            )
        )
    moment = datetime.now(UTC) if settings.operation == "now" or bound is None else bound
    moment = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    shift = timedelta(**{settings.unit: settings.amount})
    if settings.operation == "add":
        moment += shift
    elif settings.operation == "subtract":
        moment -= shift
    running = context.active()
    zone = settings.timezone or (running.timezone if running is not None else "UTC")
    local = moment.astimezone(ZoneInfo(zone))
    return Completed[DateTimeOutput](
        output=DateTimeOutput(value=local, formatted=local.strftime(settings.format))
    )


# Crypto


class CryptoConfig(_Config):
    operation: Literal[
        "sha256", "sha1", "md5", "sha512", "base64_encode", "base64_decode", "uuid", "random_hex"
    ] = "sha256"
    length: int = Field(default=16, ge=1, le=256, description="Bytes of randomness, for random_hex")


class CryptoInput(_Config):
    text: str = Field(default="", max_length=1_000_000)


class CryptoOutput(_Config):
    value: str


async def crypto(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """A digest or an encoding of the bound text, or a fresh id or random value.
    Not for secrets: nothing here is keyed, and a digest of a guessable value is
    guessable."""
    settings = config if isinstance(config, CryptoConfig) else CryptoConfig()
    text = node_input.text if isinstance(node_input, CryptoInput) else ""
    operation = settings.operation
    if operation in ("sha256", "sha1", "md5", "sha512"):
        # A checksum, not a password: `usedforsecurity` says so to the hash library.
        value = hashlib.new(operation, text.encode(), usedforsecurity=False).hexdigest()
    elif operation == "base64_encode":
        value = base64.b64encode(text.encode()).decode()
    elif operation == "base64_decode":
        try:
            value = base64.b64decode(text.encode(), validate=True).decode()
        except (ValueError, UnicodeDecodeError):
            return Failed(
                error=WorkflowError(
                    code="NOT_BASE64", message="The text is not base64 of UTF-8 text"
                )
            )
    elif operation == "uuid":
        value = str(uuid.uuid4())
    else:
        value = secrets.token_hex(settings.length)
    return Completed[CryptoOutput](output=CryptoOutput(value=value))
