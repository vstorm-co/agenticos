"""`control.foreach`: run a body once per element of a list, one iteration at a time.

The handler only freezes the list: it checks the bound `items` against the
count and size ceilings and returns them as a `ForeachManifest`, which the
dispatcher stores as this node's first attempt before any iteration exists.
Every iteration reads that stored copy, never the source it was bound from, so
a record changed mid-run does not change what the run iterates. The iterations
themselves are the dispatcher's (`app.services.workflow_execution.foreach`):
sequential, each in its own scope path, and collected into `ForeachOutput` in
input order once the last one ends.

A list over a ceiling is refused whole - never truncated, since a loop that
quietly handled the first thousand of ten thousand orders is worse than one that
says it could not start.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError

BODY_PORT = "body"
DONE_PORT = "done"


class ForeachConfig(BaseModel):
    """What a failed iteration does to the loop."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_error_policy: Literal["stop", "collect"] = Field(
        default="stop",
        description=(
            "`stop` fails the loop at the first iteration that fails; `collect` records "
            "the error in that item's place and carries on."
        ),
    )


class ForeachInput(BaseModel):
    """The list to iterate, bound from an upstream output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[Any]


class ForeachManifest(BaseModel):
    """The frozen list, as the loop's first attempt stores it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[Any]


class ForeachItemError(BaseModel):
    """Why one iteration failed, under `collect`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ForeachOutput(BaseModel):
    """Every iteration's result, in input order, and the ones that failed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    results: list[Any] = Field(
        description="What each iteration's loop.yield handed back; null where it failed."
    )
    errors: list[ForeachItemError] = Field(default_factory=list)
    count: int


def routes(output: dict[str, Any] | None) -> frozenset[str]:
    """A finished loop continues through `done`; its body is entered by iteration."""
    return frozenset({DONE_PORT})


def _too_large(code: str, message: str, **details: Any) -> Failed:
    return Failed(error=WorkflowError(code=code, message=message, details=details))


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Freeze the list, or refuse one past a ceiling."""
    items = node_input.items if isinstance(node_input, ForeachInput) else []
    limit = settings.WORKFLOW_FOREACH_MAX_ITEMS
    if len(items) > limit:
        return _too_large(
            "FOREACH_TOO_MANY_ITEMS",
            f"A loop iterates at most {limit} items; this list has {len(items)}",
            limit=limit,
            count=len(items),
        )
    size = len(json.dumps(items, default=str).encode())
    byte_limit = settings.WORKFLOW_FOREACH_MAX_MANIFEST_BYTES
    if size > byte_limit:
        return _too_large(
            "FOREACH_LIST_TOO_LARGE",
            f"A loop's list holds at most {byte_limit} bytes; this one holds {size}",
            limit=byte_limit,
            size=size,
        )
    return Completed[ForeachManifest](output=ForeachManifest(items=items))
