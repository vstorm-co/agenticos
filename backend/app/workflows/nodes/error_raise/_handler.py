"""`error.raise`: fail the branch it sits on with a typed error the author wrote.

What an author reaches for when a run should stop for a reason of their own - a
record that fails a business rule, a value no branch expects - rather than
letting a later step fail on it with a message about something else. The error
carries only the configured fields; `details` may be bound, and is bounded in
size like every other stored result.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.workflows.contracts.results import Failed, NodeResult, WorkflowError

MAX_DETAILS_BYTES = 16_384


class ErrorRaiseConfig(BaseModel):
    """The error this step fails with."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(
        pattern=r"^[A-Z][A-Z0-9_]{0,63}$",
        description="An upper-case code an error.handle branch can match, like ORDER_REJECTED.",
    )
    message: str = Field(min_length=1, max_length=500)
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = Field(
        default=False, description="Whether the step's retry policy may try again."
    )

    @field_validator("details")
    @classmethod
    def _bounded(cls, details: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(details, default=str)) > MAX_DETAILS_BYTES:
            raise ValueError(f"details hold at most {MAX_DETAILS_BYTES} bytes")
        return details


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Fail with the configured error, and nothing the runtime would add to it."""
    if not isinstance(config, ErrorRaiseConfig):
        return Failed(
            error=WorkflowError(code="ERROR_NOT_CONFIGURED", message="This step names no error")
        )
    return Failed(
        error=WorkflowError(
            code=config.code,
            message=config.message,
            details=config.details,
            retryable=config.retryable,
        )
    )
