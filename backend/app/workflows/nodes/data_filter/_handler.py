"""`data.filter`: keep the items of a list for which a condition holds.

The condition is a JMESPath expression (`_expr`) over `{"item": ..., "index": ...}`,
read for truthiness. A condition that fails on an item fails the step and names
the item, rather than dropping it quietly.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.nodes import _expr

MAX_ITEMS = 10_000


class DataFilterConfig(BaseModel):
    """What an item must be to be kept."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: str = Field(
        min_length=1,
        max_length=_expr.MAX_EXPRESSION_LENGTH,
        description="A JMESPath expression over each item, such as item.score > `50`",
    )

    @field_validator("condition")
    @classmethod
    def _checked(cls, condition: str) -> str:
        return _expr.check(condition)


class DataFilterInput(BaseModel):
    """The list to filter, bound from an earlier step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[Any] = Field(default_factory=list, max_length=MAX_ITEMS)


class DataFilterOutput(BaseModel):
    """The items kept, in their order, and how many were dropped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[Any]
    dropped: int


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Keep each item the condition holds for."""
    if not isinstance(config, DataFilterConfig):
        return Failed(error=WorkflowError(code="FILTER_NOT_CONFIGURED", message="No condition"))
    items = node_input.items if isinstance(node_input, DataFilterInput) else []
    kept: list[Any] = []
    for index, item in enumerate(items):
        try:
            holds = _expr.truthy(_expr.evaluate(config.condition, {"item": item, "index": index}))
        except _expr.ExpressionError as exc:
            return Failed(
                error=WorkflowError(
                    code="CONDITION_FAILED", message=str(exc), details={"index": index}
                )
            )
        if holds:
            kept.append(item)
    return Completed[DataFilterOutput](
        output=DataFilterOutput(items=kept, dropped=len(items) - len(kept))
    )
