"""A script run as a durable job on a sandbox host - what the sandbox code steps share.

For a script that needs packages or reads the run's files. It runs on the
organization's `sandboxd` connection, in the runtime the connection or the step
names, and it is handed only what it needs: the bound `args`, the input files,
and the script. No platform credential or token is ever staged into it.

A job can outlive one dispatch, so a step never waits on it. The first dispatch
stages the inputs and starts the script in the background, and every later one
- the dispatcher coming back after a backoff - checks on it. The session is
named after the step's stable operation key, so a worker that died between two
checks, or a retry, finds the same session. The launch is proven by the
`job.pid` it writes, not by the session existing, so a crash between staging
and starting is completed rather than waited on forever. That is what makes the
steps `idempotent`: a dispatch is always check-then-launch.

`timeout_seconds` bounds the job's whole wall clock, measured from the launch
time the job keeps beside itself. Past it the session is purged and the step
fails. CPU, memory, processes and `/tmp` are the runtime's own per-sandbox
limits. The full log is stored as a file, and only its tail travels inline.

What differs between languages is a `ScriptLanguage`: the runner that executes
the script and writes its answer, the interpreter that starts it, and the
prefix of the step's own failure codes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.session import get_worker_db_context
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService
from app.services.workflow_execution import context
from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Failed, Waiting

logger = logging.getLogger(__name__)

ROOT = "/workspace/job"
MAX_INPUT_FILES = 20
MAX_INPUT_BYTES = 100_000_000
MAX_OUTPUT_FILES = 20
MAX_OUTPUT_BYTES = 100_000_000
MAX_LOG_BYTES = 10_000_000
LOG_TAIL_CHARS = 4000

# What the job left, measured inside the sandbox before a byte of it is fetched:
# the output count, their total size, the answer's size and the log's, one per
# line. Only counts, never names - a script chooses its files' names.
_MEASURE = (
    f"cd {ROOT} && find outputs -maxdepth 1 -type f | wc -l"
    " && { cat outputs/* 2>/dev/null || true; } | wc -c"
    " && { wc -c < result.json 2>/dev/null || echo 0; }"
    " && { wc -c < log.txt 2>/dev/null || echo 0; }"
)


@dataclass(frozen=True)
class ScriptLanguage:
    """What one sandbox code step runs its script with.

    The runner reads `args.json`, runs `script`, and writes `result.json` -
    `{"ok": true, "result": ...}`, or `ok: false` with an `error` and, for an
    answer that is no JSON value, `not_json` - and then a `done` marker however
    the script ended.
    """

    code_prefix: str
    script: str
    runner_name: str
    runner: str
    interpreter: str


@dataclass(frozen=True)
class JobResult:
    """What a finished job answered, with its log and files already stored."""

    result: Any
    stdout_tail: str
    log_file: FileRef
    output_files: tuple[FileRef, ...]


def session_key(idempotency_key: str) -> str:
    """The sandbox session for one logical step - the same across every dispatch."""
    return "wf-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]


async def _connection(ctx: AuthContext, connection_id: UUID | None) -> ResolvedConnection:
    async with get_worker_db_context() as db:
        return await SandboxConnectionService(db).resolve(ctx, connection_id)


async def check_connection(
    db: AsyncSession, ctx: AuthContext, connection_id: UUID | None
) -> list[tuple[str, str]]:
    """Refuse a sandbox host the graph's author cannot use, or one that is not `sandboxd`."""
    try:
        resolved = await SandboxConnectionService(db).resolve(ctx, connection_id)
    except AppException as exc:
        return [("connection_id", exc.message)]
    if resolved.kind != "sandboxd":
        return [("connection_id", "Workflow scripts run on a sandboxd connection")]
    return []


def _open(resolved: ResolvedConnection, key: str, runtime: str | None, tenant: str) -> Any:
    from pydantic_ai_backends.remote import RemoteSandbox

    return RemoteSandbox(
        resolved.row.base_url or "",
        token=resolved.token,
        session_id=key,
        runtime=runtime or resolved.row.default_runtime,
        tenant=tenant,
        reuse=True,
    )


def _write(sandbox: Any, path: str, content: str | bytes) -> None:
    written = sandbox.write(path, content)
    if written.error:
        raise RuntimeError(f"Could not stage {path}: {written.error}")


def _launch(
    sandbox: Any,
    language: ScriptLanguage,
    code: str,
    args: dict[str, Any],
    inputs: list[tuple[str, bytes]],
) -> None:
    """Stage everything, then start the job in the background and record its pid.

    The shell starts it only while no `job.pid` exists, so a check that wrongly
    saw no launch - a host answering nothing for a moment - stages again but
    never starts a second job beside the first.
    """
    _write(sandbox, f"{ROOT}/args.json", json.dumps(args))
    _write(sandbox, f"{ROOT}/{language.script}", code)
    _write(sandbox, f"{ROOT}/{language.runner_name}", language.runner)
    for name, data in inputs:
        _write(sandbox, f"{ROOT}/inputs/{name}", data)
    _write(sandbox, f"{ROOT}/started_at", datetime.now(UTC).isoformat())
    started = sandbox.execute(
        f"cd {ROOT} && mkdir -p outputs && "
        f"{{ [ -f job.pid ] || (nohup {language.interpreter} {language.runner_name} "
        "> log.txt 2>&1 & echo $! > job.pid); }"
    )
    if started.exit_code != 0:
        raise RuntimeError(f"Could not start the job: {started.output[:500]}")


class _TooLarge(Exception):
    """What the job left is over the bounds, measured before any of it was fetched."""


def _measure(sandbox: Any) -> None:
    """Refuse a job's leftovers that are over the bounds before any of them is
    fetched into this worker's memory.

    Raises:
        _TooLarge: Too many outputs, too many bytes of them with the answer, or
            too long a log.
        RuntimeError: The sandbox could not measure them.
    """
    measured = sandbox.execute(_MEASURE)
    try:
        count, total, answer, log = (int(line) for line in measured.output.split())
    except ValueError:
        raise RuntimeError(f"Could not measure the job's files: {measured.output[:200]}") from None
    if count > MAX_OUTPUT_FILES or total + answer > MAX_OUTPUT_BYTES or log > MAX_LOG_BYTES:
        raise _TooLarge


def _collect(sandbox: Any) -> tuple[dict[str, Any], bytes, list[tuple[str, bytes]]]:
    _measure(sandbox)
    answer = json.loads(sandbox.read_bytes(f"{ROOT}/result.json"))
    log = sandbox.read_bytes(f"{ROOT}/log.txt") if sandbox.exists(f"{ROOT}/log.txt") else b""
    produced: list[tuple[str, bytes]] = []
    for entry in sandbox.ls_info(f"{ROOT}/outputs"):
        if entry["is_dir"]:
            continue
        path = entry["path"]
        produced.append((path.rsplit("/", 1)[-1], sandbox.read_bytes(path)))
    return answer, log, produced


def _too_large(language: ScriptLanguage) -> Failed:
    return files.failed(
        f"{language.code_prefix}_OUTPUT_TOO_LARGE",
        f"The script wrote more than {MAX_OUTPUT_FILES} files or {MAX_OUTPUT_BYTES} bytes, "
        f"or printed more than {MAX_LOG_BYTES} bytes",
    )


def _started(sandbox: Any) -> datetime:
    return datetime.fromisoformat(sandbox.read_bytes(f"{ROOT}/started_at").decode().strip())


async def _inputs(refs: tuple[FileRef, ...]) -> list[tuple[str, bytes]] | Failed:
    staged: list[tuple[str, bytes]] = []
    total = 0
    for index, ref in enumerate(refs):
        stored = await files.load(ref, max_bytes=MAX_INPUT_BYTES)
        if isinstance(stored, Failed):
            return stored
        total += len(stored.data)
        if total > MAX_INPUT_BYTES:
            return files.failed(
                files.FILE_TOO_LARGE,
                f"The input files come to more than {MAX_INPUT_BYTES} bytes",
                max_bytes=MAX_INPUT_BYTES,
            )
        name = (stored.filename or f"input-{index}").replace("/", "_")
        staged.append((f"{index:02d}-{name}", stored.data))
    return staged


async def run_job(
    language: ScriptLanguage,
    *,
    code: str,
    timeout_seconds: float,
    connection_id: UUID | None,
    runtime: str | None,
    args: dict[str, Any],
    input_files: tuple[FileRef, ...],
) -> JobResult | Waiting | Failed:
    """Launch the step's job, check on it, or collect what it finished with."""
    current = context.current()
    try:
        resolved = await _connection(current.auth, connection_id)
    except AppException as exc:
        return files.failed("SANDBOX_UNAVAILABLE", exc.message)
    if resolved.kind != "sandboxd":
        return files.failed("SANDBOX_UNAVAILABLE", "Workflow scripts run on a sandboxd connection")
    key = session_key(current.idempotency_key)
    waiting = Waiting(reason="retry_backoff", resume_token=str(current.node_run_id))
    try:
        sandbox = _open(resolved, key, runtime, str(current.organization_id))
        launched = await asyncio.to_thread(sandbox.exists, f"{ROOT}/job.pid")
        if not launched:
            inputs = await _inputs(input_files)
            if isinstance(inputs, Failed):
                return inputs
            await asyncio.to_thread(_launch, sandbox, language, code, args, inputs)
            return waiting
        if not await asyncio.to_thread(sandbox.exists, f"{ROOT}/done"):
            started = await asyncio.to_thread(_started, sandbox)
            if datetime.now(UTC) - started > timedelta(seconds=timeout_seconds):
                await asyncio.to_thread(sandbox.stop, True)
                return files.failed(
                    f"{language.code_prefix}_SANDBOX_TIMEOUT",
                    f"The script ran longer than {timeout_seconds:g} seconds and was stopped",
                )
            return waiting
        answer, log, produced = await asyncio.to_thread(_collect, sandbox)
    except _TooLarge:
        await asyncio.to_thread(sandbox.stop, True)
        return _too_large(language)
    except (OSError, RuntimeError) as exc:
        # The host went away mid-conversation: nothing about the job is known to
        # have changed, and the next dispatch checks again.
        logger.warning("A sandbox script step could not reach its host: %s", exc)
        return files.failed(
            "SANDBOX_UNREACHABLE", "The sandbox host could not be reached", retryable=True
        )

    # Measured before it was fetched, and checked again as it arrived: a process
    # the script left behind can still be writing after the job was measured.
    if (
        len(produced) > MAX_OUTPUT_FILES
        or sum(len(data) for _n, data in produced) > MAX_OUTPUT_BYTES
        or len(log) > MAX_LOG_BYTES
    ):
        await asyncio.to_thread(sandbox.stop, True)
        return _too_large(language)
    log_file = await files.save(log, content_type="text/plain", filename="log.txt")
    outputs = [
        await files.save(data, content_type=files.sniff(data), filename=name)
        for name, data in produced
    ]
    await asyncio.to_thread(sandbox.stop, True)
    if not answer.get("ok"):
        if answer.get("not_json"):
            return files.failed(
                f"{language.code_prefix}_OUTPUT_NOT_JSON",
                f"The script's result is a {answer.get('error')}, which is not a JSON value",
            )
        return files.failed(
            f"{language.code_prefix}_ERROR", f"The script failed: {answer.get('error')}"
        )
    return JobResult(
        result=answer.get("result"),
        stdout_tail=log.decode("utf-8", errors="replace")[-LOG_TAIL_CHARS:],
        log_file=log_file,
        output_files=tuple(outputs),
    )
