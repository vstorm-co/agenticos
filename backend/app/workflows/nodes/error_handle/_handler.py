"""`error.handle`: send a failure down the branch its error matches.

Wired to another node's `error` port, it receives that node's `WorkflowError`
(`DispatchContext.arrived_output`) and leaves by the first configured branch
whose `code` and `retryable` both match - an unset one matches anything - or by
`default`, which publishing requires to be connected, so no failure reaching a
handler goes nowhere. Every branch carries the same `HandledError`: the error,
and the branch it took.

What a handler never sees is what no graph may route around: a revoked
principal, a spent budget, a cancelled run or an effect of unknown outcome end
the run however the graph is wired (`WorkflowError.bypassable`).
"""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic import ValidationError as PydanticValidationError

from app.services.workflow_execution import context
from app.workflows.contracts.definition import Port
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError

DEFAULT_BRANCH = "default"
_RESERVED = frozenset({"in", DEFAULT_BRANCH})


class ErrorBranch(BaseModel):
    """One named way out, taken by an error matching both of its conditions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$", description="The branch's port id.")
    code: str | None = Field(default=None, max_length=64)
    retryable: bool | None = None

    def matches(self, error: WorkflowError) -> bool:
        return (self.code is None or self.code == error.code) and (
            self.retryable is None or self.retryable == error.retryable
        )


class ErrorHandleConfig(BaseModel):
    """The branches, tried in order; the first match wins."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    branches: tuple[ErrorBranch, ...] = Field(default=(), max_length=10)

    @model_validator(mode="after")
    def _distinct_names(self) -> Self:
        names = [branch.name for branch in self.branches]
        if len(set(names)) != len(names):
            raise ValueError("Each branch needs a name of its own")
        if _RESERVED & set(names):
            raise ValueError("A branch cannot be called 'in' or 'default'")
        return self


class HandledError(BaseModel):
    """The error that arrived, and the branch it was sent down."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    branch: str
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


STATIC_PORTS = (
    Port(id="in", label="Error", kind="input", schema=WorkflowError),
    Port(id=DEFAULT_BRANCH, label="Default", kind="output", schema=HandledError),
)


def ports_for(config: BaseModel | None) -> tuple[Port, ...]:
    """`in` and `default`, and one output port per configured branch."""
    branches = config.branches if isinstance(config, ErrorHandleConfig) else ()
    return STATIC_PORTS + tuple(
        Port(id=branch.name, label=branch.name, kind="output", schema=HandledError)
        for branch in branches
    )


def routes(output: dict[str, Any] | None) -> frozenset[str]:
    branch = (output or {}).get("branch")
    return frozenset({branch}) if isinstance(branch, str) else frozenset()


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Pick the branch the arriving error matches."""
    try:
        error = WorkflowError.model_validate(context.current().arrived_output)
    except PydanticValidationError:
        return Failed(
            error=WorkflowError(
                code="NO_ERROR_TO_HANDLE",
                message="This step was reached without an error; wire it to an error port",
            )
        )
    branches = config.branches if isinstance(config, ErrorHandleConfig) else ()
    chosen = next((branch.name for branch in branches if branch.matches(error)), DEFAULT_BRANCH)
    return Completed[HandledError](
        output=HandledError(
            branch=chosen,
            code=error.code,
            message=error.message,
            details=error.details,
            retryable=error.retryable,
        )
    )
