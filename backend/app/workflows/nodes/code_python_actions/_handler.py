"""Drive Monty to its next workflow call, or return its final JSON value.

Only the dispatcher owns effects. The interpreter yields a snapshot *before*
an action is admitted; the action result is fed into that same call on wake.
A failed restore must never fall back to running the source from the beginning.
"""

import base64
import hashlib
import logging
from importlib.metadata import version
from typing import Literal

from pydantic import BaseModel, JsonValue, TypeAdapter
from pydantic_monty import (
    AsyncFunctionSnapshot,
    AsyncMonty,
    AsyncMontySession,
    AsyncNameLookupSnapshot,
    ExternalReturnValue,
    MontyComplete,
    MontyCrashedError,
    MontyError,
)

from app.agents.capabilities.code_execution._sandbox import MAX_OUTPUT_CHARS, MODEL_ERRORS
from app.core.config import settings
from app.services.workflow_execution import context
from app.workflows.contracts.payload import PayloadTooLarge, json_byte_size
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.contracts.script import MAX_ACTION_CALLS, ScriptActionRequest, ScriptResume
from app.workflows.graph.model import jsonb_value_fits
from app.workflows.nodes.code_python_simple import PythonSimpleInput, PythonSimpleOutput
from app.workflows.python_actions import PythonActionsConfig

logger = logging.getLogger(__name__)
_MAX_SNAPSHOT = 512 * 1024
_RUNTIME = version("pydantic-monty")
_JSON = TypeAdapter(JsonValue)
_KWARGS = TypeAdapter(dict[str, JsonValue])


def _failed(code: str, message: str, *, bypassable: bool = True, retryable: bool = False) -> Failed:
    return Failed(
        error=WorkflowError(
            code=code,
            message=message[:MAX_OUTPUT_CHARS],
            bypassable=bypassable,
            retryable=retryable,
        )
    )


def _json_output(value: object) -> JsonValue:
    # Strict (no converting tuples, dates or custom objects to strings) and
    # finite: workflow outputs persist as PostgreSQL JSONB.
    json_byte_size(value, limit=settings.WORKFLOW_NODE_MAX_OUTPUT_BYTES)
    value = _JSON.validate_python(value, strict=True)
    jsonb_value_fits(value)
    return value


def _decode(checkpoint: str) -> tuple[str, bytes]:
    runtime, digest, encoded = checkpoint.split(":", 2)
    if len(encoded) > 4 * ((_MAX_SNAPSHOT + 2) // 3):
        raise ValueError("Incompatible checkpoint")
    raw = base64.b64decode(encoded, validate=True)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Damaged checkpoint")
    return runtime, raw


async def _segment(
    session: AsyncMontySession,
    config: PythonActionsConfig,
    args: PythonSimpleInput,
    saved: ScriptResume | None,
) -> NodeResult:
    index = 0
    stdout = saved.stdout if saved else ""

    def capture(_stream: Literal["stdout", "stderr"], text: str) -> None:
        nonlocal stdout
        stdout += text[: MAX_OUTPUT_CHARS - len(stdout)]

    if saved is None:
        progress = await session.feed_start(
            config.code, inputs={"args": args.args}, print_callback=capture
        )
    else:
        try:
            runtime, raw = _decode(saved.checkpoint)
            if runtime != _RUNTIME:
                return _failed(
                    "PYTHON_CHECKPOINT_INVALID",
                    "The checkpoint was saved by another interpreter version. Use Retry from failed step.",
                    bypassable=False,
                )
            # Monty restores the feed's elapsed execution time, not time spent parked.
            progress = await session.load_snapshot(raw, print_callback=capture)
        except MontyCrashedError:
            # Losing the local worker is not evidence of a damaged checkpoint.
            raise
        except ValueError, MontyError:
            return _failed(
                "PYTHON_CHECKPOINT_INVALID",
                "Cannot restore the saved action call",
                bypassable=False,
            )
        if (
            not isinstance(progress, AsyncFunctionSnapshot)
            or progress.is_os_function
            or progress.function_name != saved.alias
            or saved.alias not in config.actions
        ):
            return _failed(
                "PYTHON_CHECKPOINT_INVALID",
                "The saved action does not match the call",
                bypassable=False,
            )
        index = saved.index + 1
        progress = await progress.resume(ExternalReturnValue(return_value=saved.output))

    while not isinstance(progress, MontyComplete):
        if isinstance(progress, AsyncNameLookupSnapshot):
            progress = await progress.resume()
            continue
        if not isinstance(progress, AsyncFunctionSnapshot):
            return _failed("PYTHON_ACTION_ASYNC", "Call workflow actions sequentially")
        if progress.is_os_function:
            # No mounts or OS handler. Never route an OS request to an action.
            progress = await progress.resume_auto()
            continue
        alias = progress.function_name
        if alias not in config.actions or progress.object_id is not None:
            return _failed("PYTHON_ACTION_UNKNOWN", f"No action is bound as {alias!r}")
        if progress.args:
            return _failed(
                "PYTHON_ACTION_ARGUMENTS", "Call workflow actions with keyword arguments"
            )
        if index >= MAX_ACTION_CALLS:
            return _failed(
                "PYTHON_ACTION_LIMIT", f"A script can call at most {MAX_ACTION_CALLS} actions"
            )
        try:
            kwargs = progress.kwargs
            json_byte_size(kwargs, limit=settings.WORKFLOW_NODE_MAX_OUTPUT_BYTES)
            inputs = _KWARGS.validate_python(kwargs, strict=True)
            jsonb_value_fits(inputs)
            jsonb_value_fits(stdout)
        except PayloadTooLarge:
            return _failed(
                "PYTHON_ACTION_INPUT_TOO_LARGE", "The action inputs exceed the inline byte limit"
            )
        except ValueError, RecursionError, TypeError:
            return _failed("PYTHON_ACTION_ARGUMENTS", "Action inputs must be JSON values")
        raw = progress.dump()
        if len(raw) > _MAX_SNAPSHOT:
            return _failed(
                "PYTHON_CHECKPOINT_TOO_LARGE", "The script state is too large to suspend"
            )
        encoded = base64.b64encode(raw).decode("ascii")
        return ScriptActionRequest(
            reason="external_event",
            resume_token=str(context.current().node_run_id),
            index=index,
            alias=alias,
            inputs=inputs,
            checkpoint=f"{_RUNTIME}:{hashlib.sha256(raw).hexdigest()}:{encoded}",
            stdout=stdout,
        )
    try:
        result = _json_output(progress.output)
    except PayloadTooLarge:
        return _failed("NODE_OUTPUT_TOO_LARGE", "The script result exceeds the inline byte limit")
    except ValueError, RecursionError, TypeError:
        return _failed("PYTHON_OUTPUT_NOT_JSON", "The last expression must be a JSON value")
    return Completed[PythonSimpleOutput](output=PythonSimpleOutput(result=result, stdout=stdout))


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, PythonActionsConfig):
        return _failed("PYTHON_NOT_CONFIGURED", "This step has no script")
    args = node_input if isinstance(node_input, PythonSimpleInput) else PythonSimpleInput()
    try:
        async with (
            AsyncMonty() as monty,
            monty.checkout(
                limits={
                    "max_feed_duration_secs": config.timeout_seconds,
                    "max_total_sleep_secs": 0,
                    "max_memory": config.max_memory_mb * 1024 * 1024,
                }
            ) as session,
        ):
            return await _segment(session, config, args, context.current().script_resume)
    except MODEL_ERRORS as exc:
        return _failed("PYTHON_ERROR", f"The script failed: {exc}")
    except MontyError:
        logger.exception("Workflow action interpreter failed")
        return _failed("PYTHON_SANDBOX_FAILED", "The Python sandbox failed", retryable=True)
