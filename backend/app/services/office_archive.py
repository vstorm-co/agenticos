"""The bounded unzip every ZIP-backed office file is opened through.

Its own module, with nothing but the settings behind it, so that the ingestion
child - which imports only its own handlers (#2225) - can guard a DOCX without
importing the chat's attachment pipeline to reach it.
"""

import io
import zipfile

from app.core.config import settings

_ARCHIVE_CHUNK = 1024 * 1024
"""How much of a ZIP member is read at a time when measuring its real size."""


def safe_unzip(data: bytes) -> io.BytesIO:
    """Validate a ZIP-backed office file's decompression, then hand back a stream.

    ODF and OOXML are ZIP+XML, and a small upload can decompress to a huge amount of
    memory. Every member is read through a bounded stream — never trusting the
    forgeable `ZipInfo.file_size` in the central directory — and the member count and
    running total are capped. Returns a fresh stream over the *validated* bytes for
    the parser to open; raises `ValueError` when a bound is exceeded, which each
    parser turns into a caught `None`.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        if len(names) > settings.CHAT_ARCHIVE_MAX_MEMBERS:
            raise ValueError("archive has too many members")
        total = 0
        for name in names:
            member_total = 0
            with archive.open(name) as member:
                while chunk := member.read(_ARCHIVE_CHUNK):
                    member_total += len(chunk)
                    if member_total > settings.CHAT_ARCHIVE_MEMBER_MAX_BYTES:
                        raise ValueError("archive member too large")
                    total += len(chunk)
                    if total > settings.CHAT_ARCHIVE_TOTAL_MAX_BYTES:
                        raise ValueError("archive too large")
    return io.BytesIO(data)
