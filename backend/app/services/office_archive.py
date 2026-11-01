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

_EOCD_SIGNATURE = b"PK\x05\x06"
# The end-of-central-directory record is 22 bytes plus a comment of at most 65535.
_EOCD_SEARCH_BYTES = 22 + 65_535
# What the 16-bit count and the 32-bit directory size hold when the archive is ZIP64
# and the real values lie in the ZIP64 end record.
_ZIP64_ENTRY_MARKER = 0xFFFF
_ZIP64_SIZE_MARKER = 0xFFFFFFFF
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_ZIP64_RECORD_SIGNATURE = b"PK\x06\x06"
# The most central-directory bytes a member may take on average: a 46-byte header
# and a name. Office files name their parts in a few dozen bytes.
_DIRECTORY_BYTES_PER_MEMBER = 512
# What a record we cannot read reports: more than any limit, so it is refused.
_UNREADABLE = (2**64, 2**64)


def _directory_extent(data: bytes) -> tuple[int, int] | None:
    """How many members a ZIP's end record claims, and how many bytes their directory takes.

    Found the way `zipfile` finds it: the last 22 bytes when they are a record
    with no comment, otherwise the last signature within the longest comment a
    record may carry. `None` when there is no end record, which `zipfile` then
    refuses as no archive. A record that is cut short, or a ZIP64 marker the ZIP64
    record does not back up, reports more than any limit: it is read as too big
    rather than as nothing.
    """
    tail = data[-22:]
    if len(tail) == 22 and tail.startswith(_EOCD_SIGNATURE) and tail[-2:] == b"\0\0":
        position = len(data) - 22
    else:
        position = data.rfind(_EOCD_SIGNATURE, max(0, len(data) - _EOCD_SEARCH_BYTES))
        if position < 0:
            return None
        if position + 22 > len(data):
            return _UNREADABLE
    record = data[position : position + 22]
    count = int.from_bytes(record[10:12], "little")
    directory_bytes = int.from_bytes(record[12:16], "little")
    if count != _ZIP64_ENTRY_MARKER and directory_bytes != _ZIP64_SIZE_MARKER:
        return count, directory_bytes
    locator = data[max(0, position - 20) : position]
    if len(locator) != 20 or not locator.startswith(_ZIP64_LOCATOR_SIGNATURE):
        return _UNREADABLE
    offset = int.from_bytes(locator[8:16], "little")
    zip64 = data[offset : offset + 56]
    if len(zip64) != 56 or not zip64.startswith(_ZIP64_RECORD_SIGNATURE):
        return _UNREADABLE
    return int.from_bytes(zip64[32:40], "little"), int.from_bytes(zip64[40:48], "little")


def zip_has_too_many_members(data: bytes) -> bool:
    """Whether the ZIP declares more members than `CHAT_ARCHIVE_MAX_MEMBERS` allows.

    The member count alone is forgeable - `zipfile` walks the directory by its
    byte size, not by the count - so the directory's size is bounded as well.
    """
    extent = _directory_extent(data)
    if extent is None:
        return False
    count, directory_bytes = extent
    limit = settings.CHAT_ARCHIVE_MAX_MEMBERS
    return count > limit or directory_bytes > limit * _DIRECTORY_BYTES_PER_MEMBER


def safe_unzip(data: bytes) -> io.BytesIO:
    """Validate a ZIP-backed office file's decompression, then hand back a stream.

    ODF and OOXML are ZIP+XML, and a small upload can decompress to a huge amount of
    memory. Every member is read through a bounded stream — never trusting the
    forgeable `ZipInfo.file_size` in the central directory — and the member count and
    running total are capped. Returns a fresh stream over the *validated* bytes for
    the parser to open; raises `ValueError` when a bound is exceeded, which each
    parser turns into a caught `None`.
    """
    if zip_has_too_many_members(data):
        raise ValueError("archive has too many members")
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
