"""A managed LibreOffice subprocess for the one chat format with no in-process reader.

DOC has no light, pure-Python reader, so it is converted to text by `soffice`.
Unlike RAG's `LiteParseParser`, this helper owns the subprocess directly, which is
the whole reason it exists: a bounded timeout with a *real* kill, a new session and
process group so a hung child's descendants die with it, a per-call user profile so
concurrent conversions do not hit LibreOffice's single-instance lock, a semaphore so
N uploads cannot spawn N LibreOffice processes (the subprocess bypasses the
`run_blocking` admission gate), and OS resource limits applied in a fresh
single-threaded launcher rather than an unsafe `preexec_fn` (arbitrary Python between
fork and exec is documented-unsafe in the multithreaded file pool).

Absent `soffice` - a non-Docker dev box - the convert returns `None`, and the caller
tells the model the text could not be extracted, the same graceful degradation RAG
documents. It never raises for a conversion failure; a caller cancellation still
propagates, with the subprocess group killed and reaped first.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
import sys
import tempfile
import weakref
from pathlib import Path
from typing import cast

from app.core.blocking import run_blocking
from app.core.config import settings

logger = logging.getLogger(__name__)

_STDERR_MAX_BYTES = 8192
"""How much of the child's stderr is retained for the diagnostic log.

`communicate()` would accumulate the *whole* stream in memory before the `[:2000]`
log slice, so a child flooding stderr for the length of the timeout could exhaust
the worker despite the output-file limit; the drain reads to EOF (no pipe-buffer
deadlock) but keeps only this prefix (#1591)."""

# Run as a fresh, single-threaded Python process between fork and exec: it sets the
# resource limits (skipping any the platform will not accept) and then `execv`s
# soffice. Kept a string so it is never measured as coverage - it runs only in the
# child. RLIMIT_CPU bounds runaway conversions and RLIMIT_FSIZE the output file;
# address space is deliberately left unset, since a too-low bound simply kills
# LibreOffice, which needs a lot of memory.
_LAUNCHER = """
import os, resource, sys
cpu, fsize = int(sys.argv[1]), int(sys.argv[2])
argv = sys.argv[3:]
for res, value in ((resource.RLIMIT_CPU, cpu), (resource.RLIMIT_FSIZE, fsize)):
    if value <= 0:
        continue
    try:
        _, hard = resource.getrlimit(res)
        ceiling = value if hard == resource.RLIM_INFINITY else min(value, hard)
        resource.setrlimit(res, (ceiling, ceiling))
    except (ValueError, OSError):
        pass
os.execv(argv[0], argv)
"""

_semaphores: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _semaphore() -> asyncio.Semaphore:
    """One concurrency gate per event loop, keyed weakly as `blocking.py` does.

    Separate from `FILE_IO_MAX_WORKERS`: the subprocess runs off the file pool, so
    without its own bound N concurrent DOC uploads would spawn N LibreOffice
    processes.
    """
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(settings.CHAT_CONVERT_MAX_CONCURRENCY)
        _semaphores[loop] = semaphore
    return semaphore


def _soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


async def libreoffice_convert(data: bytes, *, suffix: str, timeout: float) -> str | None:
    """Convert an office document (`data`, named with `suffix`) to plain text.

    Returns the extracted text, or `None` when LibreOffice is absent, the conversion
    fails or times out, or the output is missing/oversized.
    """
    soffice = _soffice()
    if soffice is None:
        logger.warning("libreoffice_absent")
        return None
    async with _semaphore():
        return await _convert(soffice, data, suffix, timeout)


async def _convert(soffice: str, data: bytes, suffix: str, timeout: float) -> str | None:
    # The temp-dir create, the source write (up to CHAT_MAX_UPLOAD_SIZE_MB), the
    # output read (up to CHAT_CONVERT_OUTPUT_MAX_BYTES) and the cleanup are all
    # blocking filesystem syscalls; they run on the dedicated file pool rather than
    # the request loop, the same rule `parse_content` and `file_storage` follow, so
    # a slow or contended container filesystem cannot stall unrelated requests
    # (#1108, #1591).
    tmp = await run_blocking(_make_tmpdir)
    try:
        tmpdir = Path(tmp)
        source = tmpdir / f"input{suffix}"
        await run_blocking(source.write_bytes, data)
        argv = [
            sys.executable,
            "-c",
            _LAUNCHER,
            str(int(timeout) + 5),
            str(settings.CHAT_CONVERT_OUTPUT_MAX_BYTES),
            soffice,
            "--headless",
            "--norestore",
            "--convert-to",
            "txt:Text",
            "--outdir",
            str(tmpdir),
            f"-env:UserInstallation={(tmpdir / 'profile').as_uri()}",
            str(source),
        ]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        stderr = await _run(proc, timeout)
        if stderr is None:
            return None
        if proc.returncode != 0:
            logger.warning(
                "libreoffice_convert_failed",
                extra={"stderr": stderr[:2000].decode("utf-8", "replace")},
            )
            return None
        return await run_blocking(_read_output, tmpdir / f"{source.stem}.txt")
    finally:
        await run_blocking(shutil.rmtree, tmp, True)


def _make_tmpdir() -> str:
    return tempfile.mkdtemp(prefix="chatconv-")


def _read_output(output: Path) -> str | None:
    """Read the converted `.txt`, bounding the read at `CHAT_CONVERT_OUTPUT_MAX_BYTES`."""
    if not output.exists():
        logger.warning("libreoffice_convert_no_output")
        return None
    if output.stat().st_size > settings.CHAT_CONVERT_OUTPUT_MAX_BYTES:
        logger.warning("libreoffice_convert_output_too_large")
        return None
    return output.read_text("utf-8", errors="replace").strip() or None


async def _run(proc: asyncio.subprocess.Process, timeout: float) -> bytes | None:
    """Await the process draining stderr; kill the group on timeout or cancellation.

    Returns the captured stderr prefix, or `None` when the process timed out (and
    was killed). The drain reads stderr to EOF so a child flooding the pipe cannot
    deadlock the wait, while retaining only `_STDERR_MAX_BYTES`. On cancellation the
    group is killed and reaped before the cancellation propagates.
    """
    try:
        stderr = await asyncio.wait_for(_drain(proc), timeout=timeout)
    except TimeoutError:
        await _terminate(proc)
        logger.warning("libreoffice_convert_timeout")
        return None
    except asyncio.CancelledError:
        await _terminate(proc)
        raise
    else:
        return stderr


async def _drain(proc: asyncio.subprocess.Process) -> bytes:
    """Read stderr to EOF, keeping at most `_STDERR_MAX_BYTES`, then reap the process."""
    # `stderr=PIPE` guarantees a reader; the cast narrows away the Optional the
    # subprocess API declares, without an unreachable None branch.
    stream = cast(asyncio.StreamReader, proc.stderr)
    captured = bytearray()
    while chunk := await stream.read(65536):
        if len(captured) < _STDERR_MAX_BYTES:
            captured.extend(chunk[: _STDERR_MAX_BYTES - len(captured)])
    await proc.wait()
    return bytes(captured)


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Kill the process group and reap it, shielded so a cancellation cannot orphan it."""
    await asyncio.shield(asyncio.ensure_future(_teardown(proc)))


async def _teardown(proc: asyncio.subprocess.Process) -> None:
    # The group id is read *once*, up front, while the leader is certainly alive.
    # Deriving it again after `_reap` has waited the leader is unsafe: the pid is
    # gone (or recycled) by then, so a later `os.getpgid(proc.pid)` would raise or
    # name a different group.
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    _killpg(pgid, signal.SIGTERM)
    if not await _reap(proc, settings.CHAT_CONVERT_KILL_GRACE_SECONDS):
        _killpg(pgid, signal.SIGKILL)
        await _reap(proc, settings.CHAT_CONVERT_KILL_GRACE_SECONDS)
    else:
        # The leader exited within the grace, but a descendant that ignored TERM is
        # still in the group. The final group KILL is sent regardless of the leader,
        # so a lingering child cannot survive the timeout/cancellation the group
        # kill promises (#1591).
        _killpg(pgid, signal.SIGKILL)


def _killpg(pgid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)


async def _reap(proc: asyncio.subprocess.Process, grace: float) -> bool:
    """Wait up to `grace` for the process to exit; `True` if it did, `False` on timeout."""
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace)
    except TimeoutError:
        return False
    else:
        return True
