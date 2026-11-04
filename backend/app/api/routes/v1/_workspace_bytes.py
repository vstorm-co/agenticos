"""How a workspace file reaches a browser, decided in one place.

Two routes serve these bytes - one addressed by a workspace's own id, one through
the conversation that holds them - because they authorise different callers. What a
browser is then allowed to *display* must not depend on which route answered, so it
is decided here rather than twice: the second copy is where `.svg` would have stayed
displayable.

Generated media is served from here too, streamed rather than loaded: a clip can be
hundreds of megabytes, so :func:`streamed_file_response` reads only the range a
player asked for (#2310).
"""

import re
from pathlib import PurePosixPath
from typing import Literal

from fastapi import Response
from fastapi.responses import StreamingResponse

from app.api.responses import content_disposition
from app.services.file_storage import get_file_storage

INLINE_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}
"""The only types served for display, and the list is short on purpose.

A raster image cannot execute, and neither can audio or video: the browser hands
those to its media pipeline, which plays them and runs nothing in the page. They are
here so a clip an agent generated (#2259, #2260) plays in the file viewer rather
than arriving as a download. A PDF is here because the browser renders it in its
own viewer, which shows the document without handing it the embedding page's DOM -
so a report an agent wrote can be read where it was written rather than only
downloaded, which is what people expect of the one format they already read in a
browser.

`.svg` and `.html` are deliberately absent and stay `attachment`: either one served
inline from this origin is a document *with script in it* on the application's own
origin - stored cross-site scripting with the agent as the author, and "the agent
wrote it" is not a trust boundary.
"""


_BYTE_RANGE = re.compile(r"bytes=([0-9]{0,18})-([0-9]{0,18})")
"""One plain byte range. Eighteen digits is past any file this serves; a longer
number is not a range to honour, and `int()` refuses one past 4,300 digits."""


def _byte_range(header: str | None, size: int) -> tuple[int, int] | Literal[False] | None:
    """The single byte range a `Range` header asks for, inclusive.

    `None` where there is no header or it is not one plain byte range - a
    multi-range or another unit is answered whole, which RFC 9110 allows - and
    `False` where the range lies past the end, which is answered 416.
    """
    if header is None:
        return None
    match = _BYTE_RANGE.fullmatch(header.strip())
    if match is None or match.group(1) == match.group(2) == "":
        return None
    first, last = match.group(1), match.group(2)
    if first == "":
        # A suffix range: the last N bytes.
        start, end = max(size - int(last), 0), size - 1
    else:
        start, end = int(first), min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        return False
    return start, end


def file_response(
    data: bytes,
    *,
    path: str,
    download: bool,
    byte_range: str | None = None,
    serves_ranges: bool = False,
) -> Response:
    """One workspace file as an HTTP response.

    Args:
        data: The file's bytes.
        path: Its path inside the workspace, which names the download.
        download: Force an attachment even for a type that could be displayed,
            which is what a Download control asks for.
        byte_range: The request's `Range` header. Answered `206` with that
            slice, because a `<video>` in Safari - and in the desktop app,
            which is WebKit - plays an MP4 only from ranged responses.
        serves_ranges: Whether the route passes `byte_range` on, which is what
            `Accept-Ranges` promises - so only such a route sends it.
    """
    media_type, headers = _served_as(path, download=download)
    span = _byte_range(byte_range, len(data))
    if span is False:
        return _not_satisfiable(len(data))
    status, ranged = 200, {}
    if span is not None:
        start, end = span
        ranged = {"Content-Range": f"bytes {start}-{end}/{len(data)}"}
        status, data = 206, data[start : end + 1]
    return Response(
        content=data,
        status_code=status,
        media_type=media_type,
        headers={**({"Accept-Ranges": "bytes"} if serves_ranges else {}), **ranged, **headers},
    )


async def streamed_file_response(
    storage_path: str, *, size: int, path: str, download: bool, byte_range: str | None
) -> Response:
    """One stored file as a streamed response, reading only the range asked for.

    The same answer :func:`file_response` gives - status, type, disposition,
    `Content-Range`, `416` - without the file in memory (#2310). The span is
    decided from `size` before anything is read, and only that span is read,
    a chunk at a time: from disk for the local backend, by a ranged `GetObject`
    for S3. So a request for the first megabyte of a 300 MB clip holds about a
    chunk of it, however many such requests arrive at once.

    Args:
        storage_path: Where the backend holds the file.
        size: Its length in bytes, read from the backend beforehand.
        path: The name it is served under, which types it and names a download.
        download: Force an attachment, as for :func:`file_response`.
        byte_range: The request's `Range` header.

    Raises:
        FileNotFoundError: The backend no longer holds the file. Raised before
            the response starts, so the caller can still answer 404.
    """
    # Not `FileResponse`, even for the local backend: its own Range handling
    # answers a multi-range request and a bad range differently from
    # `file_response`, and the two routes must give the same answers.
    media_type, headers = _served_as(path, download=download)
    span = _byte_range(byte_range, size)
    if span is False:
        return _not_satisfiable(size)
    if size == 0:
        return Response(
            content=b"",
            media_type=media_type,
            headers={"Accept-Ranges": "bytes", **headers},
        )
    status, ranged = 200, {}
    start, end = 0, size - 1
    if span is not None:
        start, end = span
        status, ranged = 206, {"Content-Range": f"bytes {start}-{end}/{size}"}
    chunks = await get_file_storage().open_range(storage_path, start, end)
    return StreamingResponse(
        chunks,
        status_code=status,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            **ranged,
            # Stated, because a streamed body has no length of its own: a player
            # reads it to size its buffer and a browser to show progress.
            "Content-Length": str(end - start + 1),
            **headers,
        },
    )


def _not_satisfiable(size: int) -> Response:
    """A range that starts past the end, answered with the length it was measured against."""
    return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})


def _served_as(path: str, *, download: bool) -> tuple[str, dict[str, str]]:
    """The type a file is served as and the headers every answer for it carries."""
    name = PurePosixPath(path).name or "file"
    suffix = PurePosixPath(path).suffix.lower()
    inline = not download and suffix in INLINE_TYPES
    return INLINE_TYPES[suffix] if inline else "application/octet-stream", {
        "Content-Disposition": content_disposition("inline" if inline else "attachment", name),
        # Everything off the list above is typed `application/octet-stream`, and
        # this is what stops a browser deciding such a body is HTML after all -
        # sniffing would hand back the inline-script hole the list refuses.
        "X-Content-Type-Options": "nosniff",
        # Belt to the allowlist's braces. `sandbox` with no allow-list drops the
        # response into a unique opaque origin, so script inside a document an
        # agent produced cannot reach this application's DOM, cookies or storage
        # even if a viewer would have run it.
        #
        # It is here for `.pdf`, the one entry above that is a *document* rather
        # than a raster image: a PDF may carry JavaScript, and while every
        # current browser viewer refuses to run it, "the agent wrote it" is not
        # a trust boundary and the header costs nothing. Chrome and Firefox both
        # still render a sandboxed PDF in their own viewer.
        "Content-Security-Policy": "sandbox",
    }
