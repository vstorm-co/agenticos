"""Convert an office document to PDF through LibreOffice, and kill it on timeout.

The RAG parser and the chat attachment path both need to turn a `.doc`/`.xls`/
`.pptx` (and friends) into a PDF before anything can read it, and the only tool
that does it is a `soffice` (LibreOffice) subprocess. The reason this lives here
rather than being left to the parser library is teardown: `liteparse` is an
external Rust wheel whose office conversion spawns `soffice` with no kill hook,
so a conversion that hangs runs to completion (default 600s) and ties up an
ingestion worker while an orphaned `soffice` lingers (#1685).

This module owns the subprocess instead. It starts `soffice` in its **own
session** (`start_new_session=True`, so the child is the leader of a fresh
process group), bounds the wait with `asyncio.wait_for`, and on timeout *or*
cancellation tears the whole group down - `SIGTERM`, a short grace, then
`SIGKILL` - so `soffice` and anything it forked (`soffice.bin`, `oosplash`) die
together rather than outliving the request.

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
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# How long `soffice` is given to exit after `SIGTERM` before the group is
# `SIGKILL`ed. A clean LibreOffice exits well inside this; the ceiling exists for
# the one that has wedged, which is the whole reason for the kill.
_KILL_GRACE_SECONDS = 5.0

# The macOS bundle, checked last, mirroring liteparse's own discovery order
# (`find_libre_office_command`) so this module and the parser agree on whether a
# machine can convert at all.
_MACOS_SOFFICE = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")


class OfficeConversionError(Exception):
    """LibreOffice could not turn the source document into a PDF.

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


async def convert_to_pdf(source: Path, out_dir: Path, *, timeout_seconds: float) -> Path:
    """Convert `source` to a PDF in `out_dir` and return the PDF's path.

    Runs `soffice --headless --convert-to pdf` in its own process group and
    enforces `timeout_seconds` by killing that group, so a hung conversion
    frees the caller instead of blocking it.

    Args:
        source: The office document to convert.
        out_dir: A directory the PDF is written into. The caller owns it.
        timeout_seconds: The ceiling on the conversion.

    Returns:
        The path of the produced PDF, `out_dir / f"{source.stem}.pdf"`.

    Raises:
        OfficeConversionTimeout: The conversion exceeded `timeout_seconds`;
            its process group has been terminated.
        OfficeConversionError: LibreOffice is not installed, exited non-zero, or
            produced no PDF.
    """
    command = soffice_command()
    if command is None:
        raise OfficeConversionError(
            f"Cannot convert {source.name}: LibreOffice (soffice) is not installed"
        )

    # LibreOffice refuses to run two instances that share a user profile, so a
    # per-call profile directory is what lets concurrent ingestions convert at
    # the same time instead of the second one failing to acquire the lock.
    profile_dir = Path(tempfile.mkdtemp(prefix="soffice-profile-"))
    try:
        proc = await asyncio.create_subprocess_exec(
            command,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            f"-env:UserInstallation=file://{profile_dir}",
            str(source),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            await _terminate_process_group(proc)
            raise OfficeConversionTimeout(
                f"Converting {source.name} to PDF exceeded {timeout_seconds:g}s"
            ) from None
        except asyncio.CancelledError:
            # The ingest was cancelled (collection torn down, worker draining).
            # The subprocess must not outlive the coroutine that started it.
            await _terminate_process_group(proc)
            raise

        if proc.returncode != 0:
            logger.warning(
                "LibreOffice exited %s converting %s: %s",
                proc.returncode,
                source.name,
                stderr.decode("utf-8", "replace").strip(),
            )
            raise OfficeConversionError(f"LibreOffice could not convert {source.name} to PDF")

        pdf_path = out_dir / f"{source.stem}.pdf"
        if not pdf_path.exists():
            raise OfficeConversionError(f"LibreOffice produced no PDF for {source.name}")
        return pdf_path
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)


async def _terminate_process_group(proc: asyncio.subprocess.Process) -> None:
    """Kill the subprocess and everything it spawned, then reap it.

    `start_new_session=True` made `proc` a process-group leader whose group id
    equals its pid, so signalling the group reaches `soffice.bin` and any helper
    it forked - not just the `soffice` launcher. `SIGTERM` first for a clean
    shutdown, a grace for the launcher to take it, then `SIGKILL` over the whole
    group unconditionally: the launcher can exit on `SIGTERM` while a helper that
    ignores it keeps running, and waiting only on the launcher would return with
    that helper still alive - the very orphan this function exists to prevent. A
    final `SIGKILL` to an already-empty group is a harmless no-op.
    """
    _signal_group(proc.pid, signal.SIGTERM)
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(proc.wait(), timeout=_KILL_GRACE_SECONDS)
    _signal_group(proc.pid, signal.SIGKILL)
    await proc.wait()


def _signal_group(pid: int, sig: signal.Signals) -> None:
    """Send `sig` to the whole process group led by `pid`.

    A group that has already exited between the check and the signal is not an
    error - the work of the signal is already done.
    """
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, sig)
