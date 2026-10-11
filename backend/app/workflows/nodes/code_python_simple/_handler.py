"""`code.python.simple`: a short Python script over JSON values, in the Monty sandbox.

The script reads the bound `args` as a variable and its last expression is the
step's `result`, which must be JSON - a value the next step can bind - or the
step fails with `PYTHON_OUTPUT_NOT_JSON`. Monty has no filesystem, no network
and no imports beyond a small standard-library subset, so a script can compute
and nothing else, within its time and memory limits: the step is `pure`, and
running it twice is running it once.

A problem in the script - a syntax error, a `NameError`, a limit it ran past -
fails the step with `PYTHON_ERROR`, since only a different script fixes it. The
sandbox itself failing is `PYTHON_SANDBOX_FAILED`, and is retried.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_monty import MontyError

from app.agents.capabilities.code_execution._sandbox import MAX_OUTPUT_CHARS, MODEL_ERRORS, execute
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError

logger = logging.getLogger(__name__)


class PythonSimpleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(
        min_length=1,
        max_length=50_000,
        json_schema_extra={
            "x-code": "python",
            "x-placeholder": "sum(args['scores']) / len(args['scores'])",
        },
        description="Read the bound values as `args`; the last expression is the result.",
    )
    timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    max_memory_mb: int = Field(default=256, ge=16, le=512)


class PythonSimpleInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    args: dict[str, Any] = Field(default_factory=dict)


class PythonSimpleOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    result: Any = Field(description="The value of the script's last expression")
    stdout: str = Field(description="What the script printed, clipped")


def _failed(code: str, message: str, *, retryable: bool = False) -> Failed:
    return Failed(
        error=WorkflowError(code=code, message=message[:MAX_OUTPUT_CHARS], retryable=retryable)
    )


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, PythonSimpleConfig):
        return _failed("PYTHON_NOT_CONFIGURED", "This step has no script")
    args = node_input.args if isinstance(node_input, PythonSimpleInput) else {}
    try:
        result, stdout = await execute(
            config.code,
            inputs={"args": args},
            timeout_secs=config.timeout_seconds,
            max_memory_mb=config.max_memory_mb,
        )
    except MODEL_ERRORS as exc:
        return _failed("PYTHON_ERROR", f"The script failed: {exc}")
    except MontyError as exc:  # pragma: no cover - the sandbox process dying, unprovokable
        logger.exception("code.python.simple sandbox failed")
        return _failed("PYTHON_SANDBOX_FAILED", f"The sandbox failed: {exc}", retryable=True)
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError):
        return _failed(
            "PYTHON_OUTPUT_NOT_JSON",
            f"The script's result is a {type(result).__name__}, which is not a JSON value",
        )
    return Completed[PythonSimpleOutput](
        output=PythonSimpleOutput(result=result, stdout=stdout[:MAX_OUTPUT_CHARS])
    )
