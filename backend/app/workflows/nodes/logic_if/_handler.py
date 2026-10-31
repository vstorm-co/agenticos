"""`logic.if`: send the run down one of two branches, decided by an expression.

The condition is a JMESPath expression (`_expr`), evaluated against the bound
`value` and read for truthiness - null, false and an empty string, list or
object are false, anything else true. The branch taken is part of the stored
output, and `routes` reads it back: the dispatcher follows only the edges
leaving that port and skips the other branch, node by node, down to the
`logic.merge` that rejoins them.

A condition that fails on its data - `length()` handed a number - fails the
node rather than quietly choosing a branch: which way a malformed decision
should have gone is not something to guess.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.nodes import _expr


class LogicIfConfig(BaseModel):
    """The decision, as a JMESPath expression over `{"value": ...}`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: str = Field(
        min_length=1,
        max_length=_expr.MAX_EXPRESSION_LENGTH,
        description=(
            "A JMESPath expression over the input, read for truthiness - for example "
            "value.status == 'approved'."
        ),
        # The console builds it from rows over the `value` (conditions.ts).
        json_schema_extra={"x-condition": "value"},
    )

    @field_validator("condition")
    @classmethod
    def _checked(cls, condition: str) -> str:
        return _expr.check(condition)


class LogicIfInput(BaseModel):
    """What the condition reads, bound from any upstream output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Any = None


class LogicIfOutput(BaseModel):
    """Which branch was taken, and the value that decided it, passed on unchanged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    branch: Literal["true", "false"]
    value: Any = None


def routes(output: dict[str, Any] | None) -> frozenset[str]:
    """The one port the stored output chose: `true` or `false`."""
    branch = (output or {}).get("branch")
    return frozenset({branch}) if branch in ("true", "false") else frozenset()


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Evaluate the condition and name the branch it chose."""
    if not isinstance(config, LogicIfConfig):
        return Failed(
            error=WorkflowError(
                code="CONDITION_MISSING", message="This condition has no expression"
            )
        )
    value = node_input.value if isinstance(node_input, LogicIfInput) else None
    try:
        result = _expr.evaluate(config.condition, {"value": value})
    except _expr.ExpressionError as exc:
        return Failed(error=WorkflowError(code="CONDITION_FAILED", message=str(exc)))
    return Completed[LogicIfOutput](
        output=LogicIfOutput(branch="true" if _expr.truthy(result) else "false", value=value)
    )
