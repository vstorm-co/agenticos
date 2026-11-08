"""Bound raw-schema admission work without blocking the API event loop."""

import asyncio
import contextlib
import json
import logging
import math
import sys
import weakref

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError

from app.core.exceptions import RateLimitError
from app.services.workflow_execution.exceptions import WorkflowInputValidationUnavailableError
from app.workflows.contracts.input_schema import InputSchema
from app.workflows.contracts.input_schema_worker import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    ValidationRequest,
    validation_limit,
)

VALIDATION_SECONDS = 2
MAX_VALIDATIONS = 2
_ADDRESS_SPACE_BYTES = 256 * 1024**2

logger = logging.getLogger(__name__)

# As with the HTML parser, limits are installed before importing the validator.
# A process deadline can interrupt regex and reference evaluation; a thread cannot.
_LAUNCHER = """
import os, resource, sys
cpu, memory = int(sys.argv[1]), int(sys.argv[2])
for kind, value in ((resource.RLIMIT_CPU, cpu), (resource.RLIMIT_AS, memory)):
    # Darwin rejects RLIMIT_AS; Linux production keeps the hard memory ceiling.
    if sys.platform == "darwin" and kind == resource.RLIMIT_AS:
        continue
    _, hard = resource.getrlimit(kind)
    ceiling = value if hard == resource.RLIM_INFINITY else min(value, hard)
    resource.setrlimit(kind, (ceiling, ceiling))
os.execv(sys.argv[3], sys.argv[3:])
"""

# Tests and workers own different loops; a contended semaphore binds to its loop.
_gates: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


class _Problem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    message: str
    type: str


_PROBLEMS = TypeAdapter(list[_Problem])


def _gate() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop)
    if gate is None:
        gate = asyncio.Semaphore(MAX_VALIDATIONS)
        _gates[loop] = gate
    return gate


async def _kill_and_reap(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    # Hold the admission slot until the child has actually stopped, even if a
    # disconnect sends a second cancellation while the first is being cleaned up.
    waiter = asyncio.ensure_future(process.wait())
    cancelled = False
    while not waiter.done():
        try:
            await asyncio.shield(waiter)
        except asyncio.CancelledError:
            cancelled = True
    waiter.result()
    if cancelled:
        raise asyncio.CancelledError


async def schema_problems(
    schema: InputSchema, payload: dict[str, JsonValue]
) -> list[dict[str, str]]:
    """Evaluate one contract in a killable child before a run can be admitted.

    Two children at most per API/worker loop; a saturated validator refuses
    immediately with 429. Wall time includes process startup and communication.
    Time, CPU and protocol size are bounded independently of schema depth.
    Linux also enforces a hard address-space limit; macOS does not support it.
    """
    request: ValidationRequest = {"schema": schema, "input": payload}
    encoded = json.dumps(
        request, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()
    if len(encoded) > MAX_REQUEST_BYTES:
        return validation_limit()
    gate = _gate()
    if gate.locked():
        raise RateLimitError(
            message="Every workflow input-validation slot is busy; retry in a moment",
            details={"stage": "workflow_input_validation", "retry_after_seconds": 1},
        )
    async with gate:
        process: asyncio.subprocess.Process | None = None
        try:
            async with asyncio.timeout(VALIDATION_SECONDS):
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-c",
                    _LAUNCHER,
                    str(math.ceil(VALIDATION_SECONDS) + 1),
                    str(_ADDRESS_SPACE_BYTES),
                    sys.executable,
                    "-I",
                    "-m",
                    "app.workflows.contracts.input_schema_worker",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await process.communicate(encoded)
        except TimeoutError:
            if process is not None:
                await _kill_and_reap(process)
            return validation_limit()
        except OSError as exc:
            logger.exception("workflow_input_validator_not_started")
            raise WorkflowInputValidationUnavailableError(reason="not_started") from exc
        finally:
            if process is not None and process.returncode is None:
                await _kill_and_reap(process)
        if process.returncode != 0:
            logger.error(
                "workflow_input_validator_failed", extra={"returncode": process.returncode}
            )
            raise WorkflowInputValidationUnavailableError(reason="failed")
        if len(stdout) > MAX_RESPONSE_BYTES:
            raise WorkflowInputValidationUnavailableError(reason="invalid_output")
        try:
            problems = _PROBLEMS.validate_json(stdout)
        except ValidationError as exc:
            raise WorkflowInputValidationUnavailableError(reason="invalid_output") from exc
        return [{"field": p.field, "message": p.message, "type": p.type} for p in problems]
