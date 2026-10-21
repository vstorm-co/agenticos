"""How a workspace file reaches a browser, decided in one place.

Two routes serve these bytes - one addressed by a workspace's own id, one through
the conversation that holds them - because they authorise different callers. What a
browser is then allowed to *display* must not depend on which route answered, so it
is decided here rather than twice: the second copy is where `.svg` would have stayed
displayable.
"""

import re
from pathlib import PurePosixPath
from typing import Literal

from fastapi import Response

from app.api.responses import content_disposition

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
    name = PurePosixPath(path).name or "file"
    suffix = PurePosixPath(path).suffix.lower()
    inline = not download and suffix in INLINE_TYPES
    span = _byte_range(byte_range, len(data))
    if span is False:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{len(data)}"})
    status, ranged = 200, {}
    if span is not None:
        start, end = span
        ranged = {"Content-Range": f"bytes {start}-{end}/{len(data)}"}
        status, data = 206, data[start : end + 1]
    return Response(
        content=data,
        status_code=status,
        media_type=INLINE_TYPES[suffix] if inline else "application/octet-stream",
        headers={
            **({"Accept-Ranges": "bytes"} if serves_ranges else {}),
            **ranged,
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
        },
    )
