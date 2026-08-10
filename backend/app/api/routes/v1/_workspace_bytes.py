"""How a workspace file reaches a browser, decided in one place.

Two routes serve these bytes - one addressed by a workspace's own id, one through
the conversation that holds them - because they authorise different callers. What a
browser is then allowed to *display* must not depend on which route answered, so it
is decided here rather than twice: the second copy is where `.svg` would have stayed
displayable.
"""

from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import Response

INLINE_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}
"""The only types served for display, and the list is short on purpose.

A raster image cannot execute. A PDF is here because the browser renders it in its
own viewer, which shows the document without handing it the embedding page's DOM -
so a report an agent wrote can be read where it was written rather than only
downloaded, which is what people expect of the one format they already read in a
browser.

`.svg` and `.html` are deliberately absent and stay `attachment`: either one served
inline from this origin is a document *with script in it* on the application's own
origin - stored cross-site scripting with the agent as the author, and "the agent
wrote it" is not a trust boundary.
"""


# routes-helper: the shared display-vs-download decision for both workspace-bytes
# routes, deliberately in one place (see the module docstring).
def file_response(data: bytes, *, path: str, download: bool) -> Response:
    """One workspace file as an HTTP response.

    Args:
        data: The file's bytes.
        path: Its path inside the workspace, which names the download.
        download: Force an attachment even for a type that could be displayed,
            which is what a Download control asks for.
    """
    name = PurePosixPath(path).name or "file"
    suffix = PurePosixPath(path).suffix.lower()
    inline = not download and suffix in INLINE_TYPES
    return Response(
        content=data,
        media_type=INLINE_TYPES[suffix] if inline else "application/octet-stream",
        headers={
            # `filename*` and nothing else: a workspace path can hold any UTF-8, and
            # the bare `filename` form has no way to say so - a quote or a newline in
            # it is a header-injection primitive rather than a filename.
            "Content-Disposition": (
                f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(name)}"
            ),
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
