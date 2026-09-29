"""`code.python.sandbox`: full Python with files, as a durable job on a sandbox host.

For a script Monty cannot run - one that needs packages or reads the run's
files. It runs on the organization's `sandboxd` connection, in the runtime the
connection or the step names, and it is handed only what it needs: the bound
`args`, the input files, and the script. No platform credential or token is
ever staged into it.

A job can outlive one dispatch, so the step never waits on it. The first
dispatch stages the inputs and starts the script in the background, and every
later one - the dispatcher coming back after a backoff - checks on it. The
session is named after the step's stable operation key, so a worker that died
between two checks, or a retry, finds the same session. The launch is proven by
the `job.pid` it writes, not by the session existing, so a crash between
staging and starting is completed rather than waited on forever. That is what
makes the step `idempotent`: a dispatch is always check-then-launch.

`timeout_seconds` bounds the job's whole wall clock, measured from the launch
time the job keeps beside itself. Past it the session is purged and the step
fails. CPU, memory, processes and `/tmp` are the runtime's own per-sandbox
limits. The full log is stored as a file, and only its tail travels inline.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.session import get_worker_db_context
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService
from app.services.workflow_execution import context
from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed, NodeResult, Waiting

logger = logging.getLogger(__name__)

ROOT = "/workspace/job"
MAX_INPUT_FILES = 20
MAX_INPUT_BYTES = 100_000_000
MAX_OUTPUT_FILES = 20
MAX_OUTPUT_BYTES = 100_000_000
MAX_LOG_BYTES = 10_000_000

# What the job left, measured inside the sandbox before a byte of it is fetched:
# the output count, their total size, the answer's size and the log's, one per
# line. Only counts, never names - a script chooses its files' names.
_MEASURE = (
    f"cd {ROOT} && find outputs -maxdepth 1 -type f | wc -l"
    " && { cat outputs/* 2>/dev/null || true; } | wc -c"
    " && { wc -c < result.json 2>/dev/null || echo 0; }"
    " && { wc -c < log.txt 2>/dev/null || echo 0; }"
)
LOG_TAIL_CHARS = 4000

# What runs the script: its arguments and file folders as globals, `result`
# read back as JSON, and a marker written however it ends, so a check can tell
# a finished job from a running one.
RUNNER = """import json, pathlib
root = pathlib.Path(__file__).parent
scope = {
    "args": json.loads((root / "args.json").read_text()),
    "inputs": str(root / "inputs"),
    "outputs": str(root / "outputs"),
}
try:
    exec(compile((root / "main.py").read_text(), "main.py", "exec"), scope)
    value = scope.get("result")
    try:
        answer = {"ok": True, "result": json.loads(json.dumps(value, allow_nan=False))}
    except (TypeError, ValueError):
        answer = {"ok": False, "not_json": True, "error": type(value).__name__}
except BaseException as exc:
    answer = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
(root / "result.json").write_text(json.dumps(answer))
(root / "done").write_text("done")
"""


class PythonSandboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(
        min_length=1,
        max_length=200_000,
        json_schema_extra={
            "x-textarea": True,
            "x-placeholder": "import csv, os\nresult = len(os.listdir(inputs))",
        },
        description=(
            "Read the bound values as `args`, input files from the `inputs` folder, and "
            "write files to `outputs`. Set `result` to the answer."
        ),
    )
    timeout_seconds: float = Field(default=300.0, gt=0, le=1800)
    connection_id: UUID | None = Field(
        default=None,
        description="The sandbox host to run on. The organization's default when empty.",
    )
    runtime: str | None = Field(
        default=None,
        max_length=64,
        description="The host's runtime to run in. The connection's default when empty.",
    )


class PythonSandboxInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    args: dict[str, Any] = Field(default_factory=dict)
    files: tuple[FileRef, ...] = Field(default=(), max_length=MAX_INPUT_FILES)


class PythonSandboxOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    result: Any = None
    stdout_tail: str = Field(description="The end of what the script printed")
    log_file: FileRef = Field(description="Everything it printed, as a file")
    output_files: tuple[FileRef, ...] = ()


def session_key(idempotency_key: str) -> str:
    """The sandbox session for one logical step - the same across every dispatch."""
    return "wf-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]


async def _connection(ctx: AuthContext, connection_id: UUID | None) -> ResolvedConnection:
    async with get_worker_db_context() as db:
        return await SandboxConnectionService(db).resolve(ctx, connection_id)


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a sandbox host the graph's author cannot use, or one that is not `sandboxd`."""
    if not isinstance(config, PythonSandboxConfig):
        return []
    try:
        resolved = await SandboxConnectionService(db).resolve(ctx, config.connection_id)
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


def _launch(sandbox: Any, code: str, args: dict[str, Any], inputs: list[tuple[str, bytes]]) -> None:
    """Stage everything, then start the job in the background and record its pid.

    The shell starts it only while no `job.pid` exists, so a check that wrongly
    saw no launch - a host answering nothing for a moment - stages again but
    never starts a second job beside the first.
    """
    _write(sandbox, f"{ROOT}/args.json", json.dumps(args))
    _write(sandbox, f"{ROOT}/main.py", code)
    _write(sandbox, f"{ROOT}/run.py", RUNNER)
    for name, data in inputs:
        _write(sandbox, f"{ROOT}/inputs/{name}", data)
    _write(sandbox, f"{ROOT}/started_at", datetime.now(UTC).isoformat())
    started = sandbox.execute(
        f"cd {ROOT} && mkdir -p outputs && "
        "{ [ -f job.pid ] || (nohup python3 run.py > log.txt 2>&1 & echo $! > job.pid); }"
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


def _too_large() -> Failed:
    return files.failed(
        "PYTHON_OUTPUT_TOO_LARGE",
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


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, PythonSandboxConfig):
        return files.failed("PYTHON_NOT_CONFIGURED", "This step has no script")
    node_input = node_input if isinstance(node_input, PythonSandboxInput) else PythonSandboxInput()
    current = context.current()
    try:
        resolved = await _connection(current.auth, config.connection_id)
    except AppException as exc:
        return files.failed("SANDBOX_UNAVAILABLE", exc.message)
    if resolved.kind != "sandboxd":
        return files.failed("SANDBOX_UNAVAILABLE", "Workflow scripts run on a sandboxd connection")
    key = session_key(current.idempotency_key)
    waiting = Waiting(reason="retry_backoff", resume_token=str(current.node_run_id))
    try:
        sandbox = _open(resolved, key, config.runtime, str(current.organization_id))
        launched = await asyncio.to_thread(sandbox.exists, f"{ROOT}/job.pid")
        if not launched:
            inputs = await _inputs(node_input.files)
            if isinstance(inputs, Failed):
                return inputs
            await asyncio.to_thread(_launch, sandbox, config.code, node_input.args, inputs)
            return waiting
        if not await asyncio.to_thread(sandbox.exists, f"{ROOT}/done"):
            started = await asyncio.to_thread(_started, sandbox)
            if datetime.now(UTC) - started > timedelta(seconds=config.timeout_seconds):
                await asyncio.to_thread(sandbox.stop, True)
                return files.failed(
                    "PYTHON_SANDBOX_TIMEOUT",
                    f"The script ran longer than {config.timeout_seconds:g} seconds and was stopped",
                )
            return waiting
        answer, log, produced = await asyncio.to_thread(_collect, sandbox)
    except _TooLarge:
        await asyncio.to_thread(sandbox.stop, True)
        return _too_large()
    except (OSError, RuntimeError) as exc:
        # The host went away mid-conversation: nothing about the job is known to
        # have changed, and the next dispatch checks again.
        logger.warning("code.python.sandbox could not reach its host: %s", exc)
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
        return _too_large()
    log_file = await files.save(log, content_type="text/plain", filename="log.txt")
    outputs = [
        await files.save(data, content_type=files.sniff(data), filename=name)
        for name, data in produced
    ]
    await asyncio.to_thread(sandbox.stop, True)
    if not answer.get("ok"):
        if answer.get("not_json"):
            return files.failed(
                "PYTHON_OUTPUT_NOT_JSON",
                f"The script's result is a {answer.get('error')}, which is not a JSON value",
            )
        return files.failed("PYTHON_ERROR", f"The script failed: {answer.get('error')}")
    return Completed[PythonSandboxOutput](
        output=PythonSandboxOutput(
            result=answer.get("result"),
            stdout_tail=log.decode("utf-8", errors="replace")[-LOG_TAIL_CHARS:],
            log_file=log_file,
            output_files=tuple(outputs),
        )
    )
