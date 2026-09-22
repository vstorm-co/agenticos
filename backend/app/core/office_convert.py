"""The one managed LibreOffice subprocess, for every caller that needs one.

Two paths in this product turn an office document into something readable: the
RAG parser wants a PDF it can hand to `liteparse`, and a chat attachment wants
plain text because `.doc` has no light pure-Python reader. Both are a `soffice`
subprocess, and for a week they were two of them - one owned here for #1685, one
under `app/services/` for #1591 - each carrying a safety property the other
lacked, so a deployment running both paths had one converter that could be
flooded and one that could not, and a reader had to know which was which (#1767).

This module is now the only one. `app/services/office_convert.py` is a caller,
the same way `app/services/rag/documents.py` is.

Why the subprocess is owned here at all: `liteparse` is an external Rust wheel
whose office conversion spawns `soffice` with no kill hook, so a conversion that
hangs runs to completion (default 600s) and ties up an ingestion worker while an
orphaned `soffice` lingers.

What one conversion is held to, all of it from the two it replaced:

- its **own session** (`start_new_session=True`), so the child leads a fresh
  process group and teardown reaches `soffice.bin` and `oosplash` too;
- a **group kill on timeout *and* on cancellation** - `SIGTERM`, a short grace,
  then `SIGKILL` over the whole group regardless of the leader;
- a **per-call user profile**, because LibreOffice refuses a second instance
  sharing one, so without it concurrent conversions fail on its lock;
- a **semaphore**, because the subprocess runs outside the `run_blocking`
  admission gate and N uploads would otherwise be N LibreOffice processes;
- **OS resource limits**, applied in a fresh single-threaded Python launcher
  rather than an unsafe `preexec_fn` - arbitrary Python between fork and exec is
  documented-unsafe in a multithreaded process;
- a **bounded stderr drain**, read to EOF so the child cannot deadlock on a full
  pipe, retaining only a prefix so it cannot exhaust the worker either.

POSIX only: `os.killpg` and `SIGKILL` do not exist on Windows, and neither does
the LibreOffice deployment this serves. Only the branch that signals is
platform-specific, the same line `app/core/watchdog.py` draws.
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

from app.core.config import settings

logger = logging.getLogger(__name__)

# The macOS bundle, checked last, mirroring liteparse's own discovery order
# (`find_libre_office_command`) so this module and the parser agree on whether a
# machine can convert at all.
_MACOS_SOFFICE = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")

_STDERR_MAX_BYTES = 8192
"""How much of the child's stderr is retained for the diagnostic log.

`communicate()` would accumulate the *whole* stream in memory before the log
slice, so a child flooding stderr for the length of the timeout could exhaust the
worker despite the output-file limit; the drain reads to EOF (no pipe-buffer
deadlock) but keeps only this prefix (#1591)."""

# Run as a fresh, single-threaded Python process between fork and exec: it sets
# the resource limits (skipping any the platform will not accept) and then
# `execv`s soffice. Kept a string so it is never measured as coverage - it runs
# only in the child. RLIMIT_CPU bounds a runaway conversion and RLIMIT_FSIZE the
# output file; address space is deliberately left unset, since a too-low bound
# simply kills LibreOffice, which needs a lot of memory.
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


class OfficeConversionError(Exception):
    """LibreOffice could not turn the source document into what was asked for.

    The message names only the source file, never a temporary path: this is
    re-raised on the ingestion path, where a stored `error_message` is rendered
    to every member who can see the collection (#423).
    """


class OfficeConversionTimeout(OfficeConversionError):
    """The conversion exceeded its deadline and its process group was killed."""


def soffice_command() -> str | None:
    """The LibreOffice command on this machine, or `None` if it has none.

    The two command names first, then the macOS bundle - the order LibreOffice's
    own callers use, so a developer on macOS and a Linux container resolve the
    same binary they would otherwise.
    """
    return (
        shutil.which("libreoffice")
        or shutil.which("soffice")
        or (str(_MACOS_SOFFICE) if _MACOS_SOFFICE.exists() else None)
    )


def _semaphore() -> asyncio.Semaphore:
    """One concurrency gate per event loop, keyed weakly as `blocking.py` does.

    Separate from `FILE_IO_MAX_WORKERS`: the subprocess runs off the file pool,
    so without its own bound N concurrent uploads would spawn N LibreOffice
    processes.
    """
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(settings.CHAT_CONVERT_MAX_CONCURRENCY)
        _semaphores[loop] = semaphore
    return semaphore


async def convert(
    source: Path,
    out_dir: Path,
    *,
    convert_to: str,
    extension: str,
    timeout_seconds: float,
    output_max_bytes: int = 0,
) -> Path:
    """Convert `source` into `out_dir` and return the produced file's path.

    Args:
        source: The office document to convert.
        out_dir: A directory the output is written into. The caller owns it.
        convert_to: LibreOffice's own `--convert-to` value - `pdf`, `txt:Text`.
        extension: The suffix the produced file carries, so the caller does not
            have to parse `convert_to` back apart.
        timeout_seconds: The ceiling on the conversion. The child's CPU limit is
            set five seconds above it, so a runaway is stopped by the kernel
            even if the wait is somehow not reached.
        output_max_bytes: `RLIMIT_FSIZE` for the child, or `0` for no limit.

    Returns:
        `out_dir / f"{source.stem}.{extension}"`.

    Raises:
        OfficeConversionTimeout: The conversion exceeded `timeout_seconds`; its
            process group has been terminated.
        OfficeConversionError: LibreOffice is not installed, exited non-zero, or
            produced no output.
    """
    command = soffice_command()
    if command is None:
        raise OfficeConversionError(
            f"Cannot convert {source.name}: LibreOffice (soffice) is not installed"
        )
    async with _semaphore():
        return await _convert(
            command,
            source,
            out_dir,
            convert_to=convert_to,
            extension=extension,
            timeout_seconds=timeout_seconds,
            output_max_bytes=output_max_bytes,
        )


async def convert_to_pdf(source: Path, out_dir: Path, *, timeout_seconds: float) -> Path:
    """`convert`, for the RAG parser's one shape: a PDF `liteparse` can read."""
    return await convert(
        source,
        out_dir,
        convert_to="pdf",
        extension="pdf",
        timeout_seconds=timeout_seconds,
    )


async def _convert(
    command: str,
    source: Path,
    out_dir: Path,
    *,
    convert_to: str,
    extension: str,
    timeout_seconds: float,
    output_max_bytes: int,
) -> Path:
    # LibreOffice refuses to run two instances that share a user profile, so a
    # per-call profile directory is what lets concurrent conversions run at the
    # same time instead of the second one failing to acquire the lock.
    profile_dir = Path(tempfile.mkdtemp(prefix="soffice-profile-"))
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _LAUNCHER,
            str(int(timeout_seconds) + 5),
            str(output_max_bytes),
            command,
            "--headless",
            "--norestore",
            "--convert-to",
            convert_to,
            "--outdir",
            str(out_dir),
            f"-env:UserInstallation={profile_dir.as_uri()}",
            str(source),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        # The process-group id, captured now rather than derived at teardown.
        # Reading `os.getpgid(proc.pid)` after a timeout could race the child
        # watcher reaping the leader - LibreOffice's launcher exits after forking
        # `soffice.bin` - and raise `ProcessLookupError`, so teardown would
        # return without signalling a survivor still in the group.
        # `start_new_session=True` makes the child a group leader, so its pgid is
        # its pid (#1654).
        pgid = proc.pid
        try:
            stderr = await asyncio.wait_for(_drain(proc), timeout=timeout_seconds)
        except TimeoutError:
            await _terminate(proc, pgid)
            raise OfficeConversionTimeout(
                f"Converting {source.name} exceeded {timeout_seconds:g}s"
            ) from None
        except asyncio.CancelledError:
            # The caller was cancelled (a collection torn down, a worker
            # draining). The subprocess must not outlive the coroutine that
            # started it.
            await _terminate(proc, pgid)
            raise

        if proc.returncode != 0:
            logger.warning(
                "office_convert_failed",
                extra={
                    "source": source.name,
                    "returncode": proc.returncode,
                    "stderr": stderr[:2000].decode("utf-8", "replace").strip(),
                },
            )
            raise OfficeConversionError(f"LibreOffice could not convert {source.name}")

        produced = out_dir / f"{source.stem}.{extension}"
        if not produced.exists():
            raise OfficeConversionError(f"LibreOffice produced no output for {source.name}")
        return produced
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)


async def _drain(proc: asyncio.subprocess.Process) -> bytes:
    """Read stderr to EOF, keeping at most `_STDERR_MAX_BYTES`, then reap."""
    # `stderr=PIPE` guarantees a reader; the cast narrows away the Optional the
    # subprocess API declares, without an unreachable None branch.
    stream = cast(asyncio.StreamReader, proc.stderr)
    captured = bytearray()
    while chunk := await stream.read(65536):
        if len(captured) < _STDERR_MAX_BYTES:
            captured.extend(chunk[: _STDERR_MAX_BYTES - len(captured)])
    await proc.wait()
    return bytes(captured)


async def _terminate(proc: asyncio.subprocess.Process, pgid: int) -> None:
    """Kill the group and reap it, shielded so a cancellation cannot orphan it."""
    await asyncio.shield(asyncio.ensure_future(_teardown(proc, pgid)))


async def _teardown(proc: asyncio.subprocess.Process, pgid: int) -> None:
    """Kill the subprocess and everything it spawned, then reap it.

    `SIGTERM` first for a clean shutdown, a grace for the launcher to take it,
    then `SIGKILL` over the whole group **unconditionally**: the launcher can
    exit on `SIGTERM` while a helper that ignores it keeps running, and waiting
    only on the launcher would return with that helper still alive - the very
    orphan this exists to prevent. A `SIGKILL` to an already-empty group is a
    harmless no-op.

    The `SIGKILL` is in a `finally`, so a second cancellation while the grace
    wait is in progress - an overlapping timeout-and-worker-shutdown race - still
    fires it. `_terminate` shields this whole coroutine for the same reason; the
    `finally` is what holds when it is awaited directly.
    """
    _signal_group(pgid, signal.SIGTERM)
    try:
        await _reap(proc, settings.CHAT_CONVERT_KILL_GRACE_SECONDS)
    finally:
        _signal_group(pgid, signal.SIGKILL)
    await _reap(proc, settings.CHAT_CONVERT_KILL_GRACE_SECONDS)


def _signal_group(pid: int, sig: signal.Signals) -> None:
    """Send `sig` to the whole process group led by `pid`.

    A group that has already exited between the check and the signal is not an
    error - the work of the signal is already done.
    """
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, sig)


async def _reap(proc: asyncio.subprocess.Process, grace: float) -> bool:
    """Wait up to `grace` for the process to exit; `True` if it did."""
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace)
    except TimeoutError:
        return False
    else:
        return True
