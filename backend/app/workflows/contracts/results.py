"""What a node handler returns: one discriminated result, never a bare exception.

`app.core.exceptions.AppException` is `message` + `details`; `WorkflowError`
mirrors that shape on purpose rather than inventing a second one, so a handler
that wraps a caught `AppException` maps it field for field instead of writing a
translation layer per node.

No execution logic lives here. `Waiting` and `Uncertain` are interpreted by the
durable-execution engine this package does not contain - this module only
defines the vocabulary every node handler and every future consumer share.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkflowError(BaseModel):
    """Why a node failed, in the same shape `AppException` carries.

    `details` follows the same rule as everywhere else in this codebase
    (`.claude/rules/exceptions-security.md`): a value that explains the
    failure, never a row, a caller's own submission or a raw exception object.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class Completed[T: BaseModel](BaseModel):
    """The node ran to completion and produced a typed output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["completed"] = "completed"
    output: T


class Waiting(BaseModel):
    """The node started an effect whose outcome has not arrived yet.

    `resume_token` is what a later event or approval decision is matched
    against to continue the node - opaque here, owned by the execution engine
    that issues and consumes it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["waiting"] = "waiting"
    reason: Literal["approval", "external_event", "retry_backoff"]
    resume_token: str


class Failed(BaseModel):
    """The node failed, with a typed error rather than a bare exception."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["failed"] = "failed"
    error: WorkflowError


class Uncertain(BaseModel):
    """An external effect of unknown outcome.

    Distinct from `Failed`: the node does not know whether its effect landed -
    a webhook call that timed out after the remote may have already acted. The
    execution engine must reconcile this, never retry it blindly, since a
    retry could double the effect.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["uncertain"] = "uncertain"
    detail: str


NodeResult = Annotated[Completed[Any] | Waiting | Failed | Uncertain, Field(discriminator="status")]
"""What every node handler returns. `status` decides which variant, so a
consumer can `match` on it without probing fields that only exist on one arm."""
