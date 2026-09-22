"""Chat's caller of the one LibreOffice manager: bytes in, text out.

DOC has no light, pure-Python reader, so a `.doc` attachment is converted to text
by `soffice`. This used to own that subprocess itself, which made two managers of
the same binary a week apart, each with a safety property the other lacked
(#1767). `app/core/office_convert.py` is the only one now; what is left here is
the shape chat needs - bytes rather than a path, text rather than a file, and a
`None` rather than a raise.

Absent `soffice` - a non-Docker dev box - the convert returns `None`, and the
caller tells the model the text could not be extracted, the same graceful
degradation RAG documents. It never raises for a conversion failure; a caller
cancellation still propagates, with the subprocess group killed and reaped first.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from app.core.blocking import create_cancel_safe, run_blocking
from app.core.config import settings
from app.core.office_convert import OfficeConversionError, convert

logger = logging.getLogger(__name__)


async def libreoffice_convert(data: bytes, *, suffix: str, timeout: float) -> str | None:
    """Convert an office document (`data`, named with `suffix`) to plain text.

    Returns the extracted text, or `None` when LibreOffice is absent, the
    conversion fails or times out, or the output is missing or oversized.
    """
    # The temp-dir create, the source write (up to CHAT_MAX_UPLOAD_SIZE_MB), the
    # output read (up to CHAT_CONVERT_OUTPUT_MAX_BYTES) and the cleanup are all
    # blocking filesystem syscalls; they run on the dedicated file pool rather
    # than the request loop, the same rule `parse_content` and `file_storage`
    # follow, so a slow or contended container filesystem cannot stall unrelated
    # requests (#1108, #1591).
    #
    # Created cancellation-safe: `run_blocking` cannot interrupt a submitted job,
    # so a task cancelled while `mkdtemp` was in flight would leave
    # `/tmp/chatconv-*` created but never assigned and never cleaned, and
    # repeated cancelled DOC uploads would leak temp storage. `create_cancel_safe`
    # shields the create and, on cancellation, removes what it made before the
    # cancel propagates - the holder carries the generated path out, since it
    # returns None (#1654).
    holder: list[str] = []
    await create_cancel_safe(
        lambda: holder.append(_make_tmpdir()),
        lambda: shutil.rmtree(holder[0], ignore_errors=True) if holder else None,
    )
    tmp = holder[0]
    try:
        tmpdir = Path(tmp)
        source = tmpdir / f"input{suffix}"
        await run_blocking(source.write_bytes, data)
        try:
            produced = await convert(
                source,
                tmpdir,
                convert_to="txt:Text",
                extension="txt",
                timeout_seconds=timeout,
                output_max_bytes=settings.CHAT_CONVERT_OUTPUT_MAX_BYTES,
            )
        except OfficeConversionError as exc:
            # Never a raise for this caller: the model is told the text could not
            # be extracted, which is an answer, where a 500 on an attachment is
            # not. The manager's own message is a controlled string naming the
            # file, so it is safe in the log line.
            logger.warning("libreoffice_convert_failed", extra={"reason": str(exc)})
            return None
        return await run_blocking(_read_output, produced)
    finally:
        await run_blocking(shutil.rmtree, tmp, True)


def _make_tmpdir() -> str:
    return tempfile.mkdtemp(prefix="chatconv-")


def _read_output(output: Path) -> str | None:
    """Read the converted `.txt`, bounding the read at `CHAT_CONVERT_OUTPUT_MAX_BYTES`.

    The `RLIMIT_FSIZE` the manager sets stops the child *writing* past the bound;
    this is the reader's own check, because a limit the kernel enforced on one
    process is not a fact about the file this one is about to read into memory.
    """
    if output.stat().st_size > settings.CHAT_CONVERT_OUTPUT_MAX_BYTES:
        logger.warning("libreoffice_convert_output_too_large")
        return None
    return output.read_text("utf-8", errors="replace").strip() or None
