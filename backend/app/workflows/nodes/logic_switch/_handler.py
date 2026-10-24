"""`logic.switch`: send the run down the first of many branches whose rule holds.

Each rule is a named JMESPath condition (`_expr`) over the bound `value`, tried in
order; the first that holds names the branch, and `otherwise` takes the run when
none does. Like `logic.if`, the branch is part of the stored output and `routes`
reads it back, so the other branches are skipped down to the `logic.merge` that
rejoins them. A rule that fails on its data fails the step rather than guessing.
"""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.workflows.contracts.definition import Port
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.nodes import _expr

OTHERWISE = "otherwise"
MAX_RULES = 20
_RESERVED = frozenset({"in", OTHERWISE})


class SwitchRule(BaseModel):
    """One named way out, taken when its condition is the first to hold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$", description="The branch's port id")
    condition: str = Field(
        min_length=1,
        max_length=_expr.MAX_EXPRESSION_LENGTH,
        description="A JMESPath expression over the input, such as value.country == 'PL'",
        # The console builds it from rows over the `value` (conditions.ts).
        json_schema_extra={"x-condition": "value"},
    )

    @field_validator("condition")
    @classmethod
    def _checked(cls, condition: str) -> str:
        return _expr.check(condition)


class LogicSwitchConfig(BaseModel):
    """The rules, tried in order; the first that holds wins."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rules: tuple[SwitchRule, ...] = Field(min_length=1, max_length=MAX_RULES)

    @model_validator(mode="after")
    def _distinct_names(self) -> Self:
        names = [rule.name for rule in self.rules]
        if len(set(names)) != len(names):
            raise ValueError("Each rule needs a name of its own")
        if _RESERVED & set(names):
            raise ValueError("A rule cannot be called 'in' or 'otherwise'")
        return self


class LogicSwitchInput(BaseModel):
    """What the rules read, bound from any upstream output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Any = None


class LogicSwitchOutput(BaseModel):
    """Which branch was taken, and the value that decided it, passed on unchanged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    branch: str
    value: Any = None


STATIC_PORTS = (
    Port(id="in", label="In", kind="input", schema=None),
    Port(id=OTHERWISE, label="Otherwise", kind="output", schema=LogicSwitchOutput),
)


def ports_for(config: BaseModel | None) -> tuple[Port, ...]:
    """`in`, one output per rule in order, and `otherwise`."""
    rules = config.rules if isinstance(config, LogicSwitchConfig) else ()
    return (
        STATIC_PORTS[0],
        *(
            Port(id=rule.name, label=rule.name, kind="output", schema=LogicSwitchOutput)
            for rule in rules
        ),
        STATIC_PORTS[1],
    )


def routes(output: dict[str, Any] | None) -> frozenset[str]:
    """The one port the stored output chose."""
    branch = (output or {}).get("branch")
    return frozenset({branch}) if isinstance(branch, str) else frozenset()


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Try each rule in order and name the branch of the first that holds."""
    if not isinstance(config, LogicSwitchConfig):
        return Failed(error=WorkflowError(code="SWITCH_NOT_CONFIGURED", message="No rules"))
    value = node_input.value if isinstance(node_input, LogicSwitchInput) else None
    for rule in config.rules:
        try:
            held = _expr.truthy(_expr.evaluate(rule.condition, {"value": value}))
        except _expr.ExpressionError as exc:
            return Failed(
                error=WorkflowError(
                    code="CONDITION_FAILED", message=str(exc), details={"rule": rule.name}
                )
            )
        if held:
            return Completed[LogicSwitchOutput](
                output=LogicSwitchOutput(branch=rule.name, value=value)
            )
    return Completed[LogicSwitchOutput](output=LogicSwitchOutput(branch=OTHERWISE, value=value))
