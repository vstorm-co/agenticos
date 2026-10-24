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

import hashlib
import json
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
from pydantic_ai.workspaces import FileEntry, Workspace, WorkspaceError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.session import get_worker_db_context
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService
from app.services.workflow_execution import context
from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Failed, Waiting

if TYPE_CHECKING:
    from pydantic_ai_backends.workspaces import SandboxdWorkspaceBackend

logger = logging.getLogger(__name__)

ROOT = "/workspace/job"
MAX_INPUT_FILES = 20
MAX_INPUT_BYTES = 100_000_000
MAX_OUTPUT_FILES = 20
MAX_OUTPUT_BYTES = 100_000_000
MAX_LOG_BYTES = 10_000_000
LOG_TAIL_CHARS = 4000

# The connection kind a `sandboxd` service is registered as - the one that runs
# a job; a Daytona connection cannot.
SANDBOXD_KIND = "docker"

# What the job left, measured inside the sandbox before a byte of it is fetched:
# the output count, their total size, the answer's size and the log's, one per
# line. Only counts, never names - a script chooses its files' names.
_MEASURE = (
    f"cd {ROOT} && find outputs -maxdepth 1 -type f | wc -l"
    " && find outputs -maxdepth 1 -type f -exec sh -c "
    "'for path do wc -c < \"$path\"; done' sh {} + | awk '{n += $1} END {print n+0}'"
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
    if resolved.kind != SANDBOXD_KIND:
        return [("connection_id", "Workflow scripts run on a sandboxd connection")]
    return []


class _CappedStream(httpx.AsyncByteStream):
    """Reject oversized responses while HTTPX is still reading their chunks."""

    def __init__(self, stream: httpx.AsyncByteStream, limit: int) -> None:
        self._stream = stream
        self._limit = limit

    async def __aiter__(self) -> AsyncIterator[bytes]:
        total = 0
        async for chunk in self._stream:
            total += len(chunk)
            if total > self._limit:
                raise _TooLarge
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


class _CappedTransport(httpx.AsyncBaseTransport):
    """One attempt's SDK transport; reads have a per-file remaining byte budget."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.read_limit = MAX_OUTPUT_BYTES

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        assert isinstance(response.stream, httpx.AsyncByteStream)
        limit = self.read_limit if request.url.path.endswith("/files/read") else MAX_OUTPUT_BYTES
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=_CappedStream(response.stream, limit),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


class _Sandbox:
    """The one `sandboxd` session a step's job lives in - only what the job needs.

    Files and commands go through the workspace, and purging through its
    backend: the session is named after the step, so purging is how a finished,
    stopped or oversized job gives its sandbox back.
    """

    def __init__(
        self,
        backend: SandboxdWorkspaceBackend,
        client: httpx.AsyncClient,
        transport: _CappedTransport,
    ) -> None:
        self._backend = backend
        self._files = Workspace(backend)
        self._client = client
        self._transport = transport

    async def exists(self, path: str) -> bool:
        return await self._files.exists(path)

    async def write(self, path: str, content: str | bytes) -> None:
        await self._files.write_bytes(
            path, content.encode() if isinstance(content, str) else content
        )

    async def read_bytes(self, path: str, *, max_bytes: int = MAX_OUTPUT_BYTES) -> bytes:
        self._transport.read_limit = max_bytes
        data = await self._files.read_bytes(path)
        # The SDK's shell fallback has its own output cap; enforce the file's
        # remaining budget too, whether this host supports native reads or not.
        if len(data) > max_bytes:
            raise _TooLarge
        return data

    async def close(self) -> None:
        await self._client.aclose()

    async def list_dir(self, path: str) -> Sequence[FileEntry]:
        return await self._files.list_dir(path)

    async def shell(self, command: str) -> tuple[int, str]:
        """Run one line of this module's own shell; its exit code and what it printed.

        Every line is built here from constants and the language's interpreter -
        the script itself is staged as a file, never interpolated.
        """
        result = await self._files.run(["sh", "-c", command])
        return result.exit_code, result.stdout + result.stderr

    async def purge(self) -> None:
        await self._backend.purge()


def _open(resolved: ResolvedConnection, key: str, runtime: str | None, tenant: str) -> _Sandbox:
    from pydantic_ai_backends.workspaces import SandboxdWorkspace

    transport = _CappedTransport(httpx.AsyncHTTPTransport())
    client = httpx.AsyncClient(transport=transport, headers={"Accept-Encoding": "identity"})
    sandbox = SandboxdWorkspace(
        client=client,
        service_url=resolved.row.base_url or "",
        token=resolved.token,
        # One provider name per connection, as an agent's workspace uses, so a
        # session on one host is never read as one on another.
        provider=f"sandboxd:{resolved.row.id}",
        runtime=runtime or resolved.row.default_runtime,
        tenant=tenant,
        session_name=key,
    )
    return _Sandbox(sandbox.backend(), client, transport)


async def _launch(
    sandbox: _Sandbox,
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
    await sandbox.write(f"{ROOT}/args.json", json.dumps(args))
    await sandbox.write(f"{ROOT}/{language.script}", code)
    await sandbox.write(f"{ROOT}/{language.runner_name}", language.runner)
    for name, data in inputs:
        await sandbox.write(f"{ROOT}/inputs/{name}", data)
    await sandbox.write(f"{ROOT}/started_at", datetime.now(UTC).isoformat())
    exit_code, output = await sandbox.shell(
        f"cd {ROOT} && mkdir -p outputs && "
        f"{{ [ -f job.pid ] || (nohup {language.interpreter} {language.runner_name} "
        "> log.txt 2>&1 & echo $! > job.pid); }"
    )
    if exit_code != 0:
        raise RuntimeError(f"Could not start the job: {output[:500]}")


class _TooLarge(Exception):
    """What the job left is over the bounds, measured before any of it was fetched."""


async def _measure(sandbox: _Sandbox) -> None:
    """Refuse a job's leftovers that are over the bounds before any of them is
    fetched into this worker's memory.

    Raises:
        _TooLarge: Too many outputs, too many bytes of them with the answer, or
            too long a log.
        RuntimeError: The sandbox could not measure them.
    """
    _exit, output = await sandbox.shell(_MEASURE)
    try:
        count, total, answer, log = (int(line) for line in output.split())
    except ValueError:
        raise RuntimeError(f"Could not measure the job's files: {output[:200]}") from None
    if count > MAX_OUTPUT_FILES or total + answer > MAX_OUTPUT_BYTES or log > MAX_LOG_BYTES:
        raise _TooLarge


async def _collect(sandbox: _Sandbox) -> tuple[dict[str, Any], bytes, list[tuple[str, bytes]]]:
    await _measure(sandbox)
    raw_answer = await sandbox.read_bytes(f"{ROOT}/result.json", max_bytes=MAX_OUTPUT_BYTES)
    answer = json.loads(raw_answer)
    total = len(raw_answer)
    log = (
        await sandbox.read_bytes(f"{ROOT}/log.txt", max_bytes=MAX_LOG_BYTES)
        if await sandbox.exists(f"{ROOT}/log.txt")
        else b""
    )
    produced: list[tuple[str, bytes]] = []
    for entry in await sandbox.list_dir(f"{ROOT}/outputs"):
        if entry.is_dir:
            continue
        if len(produced) >= MAX_OUTPUT_FILES:
            raise _TooLarge
        data = await sandbox.read_bytes(entry.path, max_bytes=MAX_OUTPUT_BYTES - total)
        total += len(data)
        produced.append((entry.path.rsplit("/", 1)[-1], data))
    return answer, log, produced


def _too_large(language: ScriptLanguage) -> Failed:
    return files.failed(
        f"{language.code_prefix}_OUTPUT_TOO_LARGE",
        f"The script wrote more than {MAX_OUTPUT_FILES} files or {MAX_OUTPUT_BYTES} bytes, "
        f"or printed more than {MAX_LOG_BYTES} bytes",
    )


async def _started(sandbox: _Sandbox) -> datetime:
    return datetime.fromisoformat(
        (await sandbox.read_bytes(f"{ROOT}/started_at", max_bytes=128)).decode().strip()
    )


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
    if resolved.kind != SANDBOXD_KIND:
        return files.failed("SANDBOX_UNAVAILABLE", "Workflow scripts run on a sandboxd connection")
    key = session_key(current.idempotency_key)
    waiting = Waiting(reason="retry_backoff", resume_token=str(current.node_run_id))
    sandbox: _Sandbox | None = None
    try:
        try:
            sandbox = _open(resolved, key, runtime, str(current.organization_id))
            if not await sandbox.exists(f"{ROOT}/job.pid"):
                inputs = await _inputs(input_files)
                if isinstance(inputs, Failed):
                    return inputs
                await _launch(sandbox, language, code, args, inputs)
                return waiting
            if not await sandbox.exists(f"{ROOT}/done"):
                started = await _started(sandbox)
                if datetime.now(UTC) - started > timedelta(seconds=timeout_seconds):
                    await sandbox.purge()
                    return files.failed(
                        f"{language.code_prefix}_SANDBOX_TIMEOUT",
                        f"The script ran longer than {timeout_seconds:g} seconds and was stopped",
                    )
                return waiting
            answer, log, produced = await _collect(sandbox)
        except _TooLarge:
            assert sandbox is not None
            await sandbox.purge()
            return _too_large(language)
        except (OSError, RuntimeError, WorkspaceError, httpx.HTTPError) as exc:
            # The host went away mid-conversation, or refused a write: nothing about
            # the job is known to have changed, and the next dispatch checks again.
            logger.warning("A sandbox script step could not reach its host: %s", exc)
            return files.failed(
                "SANDBOX_UNREACHABLE", "The sandbox host could not be reached", retryable=True
            )

        # Collection checks the aggregate as it streams, before any file is stored.
        log_file = await files.save(log, content_type="text/plain", filename="log.txt")
        outputs = [
            await files.save(data, content_type=files.sniff(data), filename=name)
            for name, data in produced
        ]
        await sandbox.purge()
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
    finally:
        if sandbox is not None:
            await sandbox.close()
