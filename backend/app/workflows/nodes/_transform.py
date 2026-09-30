"""The list contract the Transform steps share, and the field lookup they all use.

Every Transform step takes `items` - a list of JSON objects bound from an earlier
step - and most hand on `items` in the same shape, so they chain without a code
step in between. A field is named by a dotted path (`customer.email`); an item
that lacks it is treated the same way by every step, as `MISSING` rather than as
`null`, so a missing key and a key holding `null` stay two different things.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MAX_ITEMS = 10_000
FIELD_PATH = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$"


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING: Any = _Missing()
"""What `lookup` answers for a path an item does not have."""


class ItemsInput(BaseModel):
    """The list a Transform step works on, bound from an earlier step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[dict[str, Any]] = Field(max_length=MAX_ITEMS)


class ItemsOutput(BaseModel):
    """The list the step made."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[dict[str, Any]]


def items_of(node_input: BaseModel | None) -> list[dict[str, Any]]:
    return node_input.items if isinstance(node_input, ItemsInput) else []


def lookup(item: dict[str, Any], path: str) -> Any:
    """The value at a dotted `path` in `item`, or `MISSING`."""
    value: Any = item
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return MISSING
        value = value[part]
    return value


def assign(item: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """A copy of `item` with `value` at a dotted `path`, making objects on the way."""
    head, _, rest = path.partition(".")
    copy = dict(item)
    if not rest:
        copy[head] = value
        return copy
    inner = copy.get(head)
    copy[head] = assign(inner if isinstance(inner, dict) else {}, rest, value)
    return copy


def without(item: dict[str, Any], path: str) -> dict[str, Any]:
    """A copy of `item` without the field at a dotted `path`, if it has one."""
    head, _, rest = path.partition(".")
    if head not in item:
        return item
    copy = dict(item)
    if not rest:
        del copy[head]
    elif isinstance(copy[head], dict):
        copy[head] = without(copy[head], rest)
    return copy
