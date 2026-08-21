"""How a chat attachment reaches a browser, decided in one place.

Two routes serve these bytes, because they authorise different callers: the
uploader reads their own file by id, and a colleague reviewing a run reads a file
that arrived with one of that run's turns. What a browser is then allowed to
*display* must not depend on which route answered - the reasoning
`_workspace_bytes.py` opens with - so the disposition, the framing headers and the
404 for bytes the row still points at live here rather than twice.
"""

from typing import Literal

from fastapi import HTTPException, status
from fastapi.responses import FileResponse

from app.api.responses import content_disposition
from app.db.models.chat_file import ChatFile
from app.services.file_storage import RENDER_SAFE_MIME_TYPES
from app.services.file_upload import FileUploadService


def chat_file_response(
    service: FileUploadService, chat_file: ChatFile, *, disposition: str
) -> FileResponse:
    """One attachment as an HTTP response, however the caller was authorised.

    `inline` by default so a PDF, an image or a media file renders where it is
    referenced - the chat's preview panel and the run timeline both embed this
    URL - and `?disposition=attachment` for the explicit download, which is the
    reason the header is built by hand: `FileResponse(filename=...)` always says
    `attachment`.

    The name reaches the header through `content_disposition`, which is the whole
    of why: built by hand here, `filename="…"` raised `UnicodeEncodeError` on the
    first character outside latin-1, so every attachment with a Polish name was a
    500 on preview and on download alike.

    Raises:
        HTTPException: 404 where the row points at bytes the storage no longer
            has. A row and its file can part company (a restored database, a
            cleaned volume), and a response of zero bytes reads as an empty
            document rather than as a missing one.
    """
    file_path = service.get_file_path(chat_file.storage_path)
    if not file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")

    # `text/html`, an SVG or a spreadsheet is a valid attachment - the agent reads
    # it - but must never render inline: the frontend serves this from the app's
    # own origin, whose CSP allows inline script, so an inline `text/html` is a
    # stored script (#702). Only a render-safe type is shown inline; everything
    # else is forced to download, `nosniff` on both so the type cannot be sniffed
    # past. The `mime_type` was set from the client's declared header, not the
    # bytes, which is why the type alone cannot be trusted here.
    render_safe = chat_file.mime_type in RENDER_SAFE_MIME_TYPES
    mode: Literal["inline", "attachment"] = (
        "inline" if disposition != "attachment" and render_safe else "attachment"
    )
    # The preview embeds this URL in an iframe for a PDF, which `X-Frame-Options:
    # DENY` from `SecurityHeadersMiddleware` would refuse. Opted down to the same
    # origin the app itself runs on, no wider; the CSP is the modern spelling of it
    # and browsers honour whichever they recognise.
    headers = {
        "Content-Disposition": content_disposition(mode, chat_file.filename),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": "frame-ancestors 'self'",
    }
    return FileResponse(path=file_path, media_type=chat_file.mime_type, headers=headers)
