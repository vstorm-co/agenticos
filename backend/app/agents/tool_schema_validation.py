"""Bounded, killable JSONSchema validation for untrusted tool schemas.

A remote MCP server advertises an argument schema. Evaluating a pathological
`pattern` (catastrophic backtracking) in-process can wedge the event loop on the
GIL: `to_thread` and wall timeouts cannot stop a running regex.
This module runs the validation in a separate, killed-on-timeout subprocess, so a
hostile pattern costs a bounded wall-clock budget and one dead child, never the
loop.

The child is `_schema_validator_worker.py`: a standalone script importing only
the standard library, `jsonschema` and `referencing` - never `app` - which
speaks one JSON request/response over stdin/stdout, disables remote reference
retrieval, and applies its own POSIX CPU/address-space limits before doing any
work. The parent bounds everything - the admission queue, the spawn, the stdin
transfer, the child's `check_schema`/`iter_errors` and the result parse - under
one deadline, and kills and reaps the child before releasing its slot on timeout
or cancellation, including repeated cancellation.
"""

import asyncio
import contextlib
import json
import sys
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from pydantic import JsonValue

_WORKER_PATH = Path(__file__).with_name("_schema_validator_worker.py")

DEFAULT_TIMEOUT_SECONDS = 3.0
"""The whole call's wall-clock budget, tests shorten it via monkeypatch."""

MAX_CONCURRENCY = 4
"""How many validation children may run at once, per event loop."""

REQUEST_MAX_BYTES = 4 * 1024 * 1024
"""The largest request the parent will serialize onto the child's stdin."""

RESPONSE_MAX_BYTES = 1024 * 1024
"""The largest reply the parent will read from the child's stdout."""

MAX_PROBLEMS = 10
"""The most problems one validation reports, in the child and the parent."""

_CPU_GRACE_SECONDS = 5
"""Added to the remaining wall budget for the child's own RLIMIT_CPU backstop."""

type UnavailableReason = Literal["timeout", "invalid_schema", "worker_failed"]


@dataclass(frozen=True)
class SchemaProblem:
    """One safe, formatable descriptor of an argument that failed validation.

    Carries only the advertised schema's own constraints, never the submitted
    instance, the validator's rendered message, its context, or anything read
    from a remote schema document.
    """

    path: list[str | int]
    validator: str
    schema: dict[str, JsonValue]
    missing: list[str] = field(default_factory=list)


class SchemaValidationUnavailable(Exception):
    """The schema could not be validated within the safety bounds.

    `reason` names the class of failure for the caller to map to
    `tool_unavailable` / `execution=not_started`. `message` and `details` are
    written in this repository and carry nothing from the submission or the
    child.
    """

    def __init__(
        self,
        reason: UnavailableReason,
        message: str,
        details: dict[str, JsonValue] | None = None,
    ) -> None:
        self.reason = reason
        self.message = message
        self.details = details or {}
        super().__init__(message)


_semaphores: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _semaphore() -> asyncio.Semaphore:
    """One admission gate per event loop, keyed weakly as `blocking.py` does.

    The child runs off the event loop's default pool with no other bound, so N
    concurrent validations would otherwise spawn N Python processes.
    """
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        _semaphores[loop] = semaphore
    return semaphore


async def validate_tool_schema(
    schema: dict[str, JsonValue], arguments: dict[str, JsonValue]
) -> list[SchemaProblem]:
    """Validate `arguments` against `schema` in a bounded, killable child.

    Returns at most `MAX_PROBLEMS` problems, empty when the arguments are valid.
    Raises `SchemaValidationUnavailable` when the schema cannot be validated
    safely: too large, malformed, unresolved, or the child exceeds the shared
    wall-clock budget.

    Waiting for a slot, spawning the child, transferring stdin and reading the
    result all share one `DEFAULT_TIMEOUT_SECONDS` budget. On timeout or
    cancellation the child is killed and reaped before the slot is released.
    Request serialization is synchronous and precedes the deadline. It stops
    retaining output at `REQUEST_MAX_BYTES`; no schema evaluation happens there.
    """
    payload = _encode_request(schema, arguments)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + DEFAULT_TIMEOUT_SECONDS
    semaphore = _semaphore()
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=DEFAULT_TIMEOUT_SECONDS)
    except TimeoutError:
        raise SchemaValidationUnavailable(
            "timeout",
            "The tool's argument schema could not be validated before a validator freed up.",
        ) from None
    try:
        return await _validate_child(payload, deadline)
    except TimeoutError:
        raise SchemaValidationUnavailable(
            "timeout",
            "The tool's argument schema could not be validated within its time budget.",
        ) from None
    finally:
        semaphore.release()


def _encode_request(schema: dict[str, JsonValue], arguments: dict[str, JsonValue]) -> bytes:
    """Serialize the request, refusing one too large to validate safely."""
    payload = bytearray()
    try:
        for chunk in json.JSONEncoder().iterencode({"schema": schema, "arguments": arguments}):
            encoded = chunk.encode("utf-8")
            if len(payload) + len(encoded) > REQUEST_MAX_BYTES:
                raise SchemaValidationUnavailable(
                    "invalid_schema",
                    "The tool's argument schema and arguments exceed the validation size limit.",
                )
            payload.extend(encoded)
    except ValueError, RecursionError:
        raise SchemaValidationUnavailable(
            "invalid_schema", "The tool's argument schema or arguments cannot be serialized safely."
        ) from None
    return bytes(payload)


async def _validate_child(payload: bytes, deadline: float) -> list[SchemaProblem]:
    proc = await _spawn(deadline)
    try:
        response = await _exchange(proc, payload, deadline)
        return _parse_response(response)
    except asyncio.CancelledError:
        # Cancellation between the spawn and the exchange, or re-raised by the
        # exchange after its own reap: the child must not outlive this coroutine.
        await _reap_on_cancel(proc)
        raise


async def _spawn(deadline: float) -> asyncio.subprocess.Process:
    """Spawn the worker within the budget, reaping it if the spawn is interrupted.

    Waiting never cancels `create_subprocess_exec`, so cancellation racing it
    still yields the process and its pid rather than orphaning a child. If
    the budget expires or a cancellation lands before the process exists, the
    spawn is allowed to settle and whatever appeared is killed and reaped.
    """
    loop = asyncio.get_running_loop()
    remaining = deadline - loop.time()
    spawn = asyncio.ensure_future(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(_WORKER_PATH),
            str(int(remaining) + _CPU_GRACE_SECONDS),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    )
    try:
        async with asyncio.timeout(remaining):
            await asyncio.wait({spawn})
        return spawn.result()
    except TimeoutError, asyncio.CancelledError:
        proc = await _settle_spawn(spawn)
        if proc is not None:
            await _reap_on_cancel(proc)
        raise
    except OSError:
        raise SchemaValidationUnavailable(
            "worker_failed", "The schema validator could not be started."
        ) from None


async def _settle_spawn(
    spawn: asyncio.Task[asyncio.subprocess.Process],
) -> asyncio.subprocess.Process | None:
    """Wait out a shielded spawn, absorbing repeated cancellations."""
    while not spawn.done():
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait({spawn})
    try:
        return spawn.result()
    except Exception, asyncio.CancelledError:
        return None


async def _exchange(
    proc: asyncio.subprocess.Process, payload: bytes, deadline: float
) -> dict[str, JsonValue]:
    """Write the request, read the bounded reply, and map the child's outcome."""
    remaining = deadline - asyncio.get_running_loop().time()
    try:
        return await asyncio.wait_for(_transfer(proc, payload), timeout=remaining)
    except TimeoutError:
        await _reap_on_cancel(proc)
        raise
    except asyncio.CancelledError:
        await _reap_on_cancel(proc)
        raise
    except OSError:
        # A broken pipe or reset connection means the child died mid-write; it
        # still has to be reaped before the slot is released.
        await _reap_on_cancel(proc)
        raise SchemaValidationUnavailable(
            "worker_failed", "The schema validator exited before replying."
        ) from None


async def _transfer(proc: asyncio.subprocess.Process, payload: bytes) -> dict[str, JsonValue]:
    writer = cast(asyncio.StreamWriter, proc.stdin)
    writer.write(payload)
    await writer.drain()
    writer.close()
    await writer.wait_closed()

    reader = cast(asyncio.StreamReader, proc.stdout)
    captured, exceeded = await _read_bounded(reader, RESPONSE_MAX_BYTES)
    returncode = await proc.wait()
    if exceeded:
        raise SchemaValidationUnavailable(
            "worker_failed", "The schema validator produced an unexpectedly large response."
        )
    if returncode != 0:
        raise SchemaValidationUnavailable(
            "worker_failed", "The schema validator exited without a result."
        )
    try:
        decoded = json.loads(captured.decode("utf-8"))
    except UnicodeDecodeError, json.JSONDecodeError:
        raise SchemaValidationUnavailable(
            "worker_failed", "The schema validator returned a malformed result."
        ) from None
    if not isinstance(decoded, dict):
        raise SchemaValidationUnavailable(
            "worker_failed", "The schema validator returned a malformed result."
        )
    return decoded


async def _read_bounded(stream: asyncio.StreamReader, limit: int) -> tuple[bytes, bool]:
    """Read `stream` to EOF, keeping at most `limit + 1` bytes and flagging overflow.

    Reads to EOF so the child never deadlocks on a full pipe, but only the
    prefix is retained - a worker flooding stdout for the length of the timeout
    cannot exhaust the parent.
    """
    captured = bytearray()
    exceeded = False
    while chunk := await stream.read(65536):
        if exceeded:
            continue
        captured.extend(chunk)
        if len(captured) > limit:
            exceeded = True
            del captured[limit + 1 :]
    return bytes(captured), exceeded


def _parse_response(response: dict[str, JsonValue]) -> list[SchemaProblem]:
    """Build the problem list from a controlled child response, capped and safe.

    Any malformed descriptor is a failure of the trusted child, so it fails
    closed rather than silently dropping a problem and dispatching on a
    half-validated call.
    """
    if response.get("ok") is not True:
        raise SchemaValidationUnavailable(
            "invalid_schema", "The tool's argument schema cannot be validated safely."
        )
    raw = response.get("problems")
    if not isinstance(raw, list):
        raise SchemaValidationUnavailable(
            "worker_failed", "The schema validator returned a malformed result."
        )
    return [_problem_from_raw(entry) for entry in raw[:MAX_PROBLEMS]]


def _problem_from_raw(entry: JsonValue) -> SchemaProblem:
    if not isinstance(entry, dict):
        raise _malformed()
    path = _path(entry.get("path"))
    if path is None:
        raise _malformed()
    validator = entry.get("validator")
    if not isinstance(validator, str):
        raise _malformed()
    schema = entry.get("schema")
    if not isinstance(schema, dict):
        raise _malformed()
    return SchemaProblem(
        path=path,
        validator=validator,
        schema=schema,
        missing=_missing_names(entry),
    )


def _missing_names(entry: dict[str, JsonValue]) -> list[str]:
    """The missing-name list, empty when the child omitted it, else validated."""
    missing = entry.get("missing")
    if missing is None:
        return []
    names = _strings(missing)
    if names is None:
        raise _malformed()
    return names


def _malformed() -> SchemaValidationUnavailable:
    return SchemaValidationUnavailable(
        "worker_failed", "The schema validator returned a malformed result."
    )


def _path(raw: JsonValue | None) -> list[str | int] | None:
    """A problem path of strings and integers, or None when not one."""
    if not isinstance(raw, list):
        return None
    parts: list[str | int] = []
    for part in raw:
        if isinstance(part, str) or (isinstance(part, int) and not isinstance(part, bool)):
            parts.append(part)
        else:
            return None
    return parts


def _strings(raw: JsonValue | None) -> list[str] | None:
    """A list of strings, or None when not one."""
    if not isinstance(raw, list):
        return None
    result: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            return None
        result.append(item)
    return result


async def _reap_on_cancel(proc: asyncio.subprocess.Process) -> None:
    """Kill and reap `proc`, absorbing further cancellations until it is done.

    A single shield is not enough: a second cancellation while the kill/reap is
    in flight would unwind before the child is gone, orphaning it. The cleanup
    runs as a task, and cancellations arriving while it runs are absorbed until
    it has finished (the `blocking.run_blocking_settled` drain).
    """
    cleanup = asyncio.ensure_future(_kill_and_reap(proc))
    while not cleanup.done():
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait({cleanup})
    cleanup.result()


async def _kill_and_reap(proc: asyncio.subprocess.Process) -> None:
    """Kill the child, then drain its pipes before reaping.

    A child flooding stdout pauses the read transport once the stream buffer
    fills; if the reader was cancelled, `proc.wait()` would wait forever on a
    pipe that never reaches EOF. Closing stdin and reading stdout to EOF here
    lets both pipes disconnect so the reap can finish. Idempotent against an
    already-exited child.
    """
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    cast(asyncio.StreamWriter, proc.stdin).close()
    await _drain_stdout(proc)
    await proc.wait()


async def _drain_stdout(proc: asyncio.subprocess.Process) -> None:
    """Read the child's stdout to EOF, discarding it, to release the pipe."""
    reader = cast(asyncio.StreamReader, proc.stdout)
    while await reader.read(65536):
        pass
