"""`NodePolicy`: how one node instance retries, times out and fails.

Per instance, beside `config`, because it is the author's decision about this
step in this graph - how patient to be with this API, whether a failure here is
handled downstream - where `NodeDefinition.retry_guarantee` is a fact about the
node kind: whether trying again is safe at all. The guarantee caps the policy:
publishing refuses retries on a step whose call is not safe to repeat.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ERROR_PORT = "error"
"""The output port a node with `on_error="route"` fails through, carrying its
`WorkflowError` - never its declared output, so nothing on the error branch can
bind to a result that does not exist."""


class RetryPolicy(BaseModel):
    """How many tries a failing step gets, and how long it waits between them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(ge=1, le=10, description="Tries in total, the first included.")
    backoff: Literal["fixed", "exponential"] = "exponential"
    base_delay_seconds: float = Field(default=2.0, gt=0, le=3600)
    max_delay_seconds: float = Field(default=60.0, gt=0, le=86_400)

    @model_validator(mode="after")
    def _ceiling_covers_the_base(self) -> Self:
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds cannot be below base_delay_seconds")
        return self

    def delay_seconds(self, failures: int) -> float:
        """The wait after the `failures`-th failed try."""
        if self.backoff == "fixed":
            return self.base_delay_seconds
        return min(self.base_delay_seconds * 2 ** (max(failures, 1) - 1), self.max_delay_seconds)


class NodePolicy(BaseModel):
    """What happens around one node's call: its time limit, its retries, its failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    retry: RetryPolicy | None = None
    on_error: Literal["fail_run", "route"] = Field(
        default="fail_run",
        description=(
            "`route` sends a failure that retries did not settle out of this node's "
            "`error` port instead of failing the run."
        ),
    )
