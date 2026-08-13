"""A ceiling on how large a request body this API will accept at all.

Every size limit in this codebase is checked on bytes that have already arrived:
`FileUploadService.upload` measures `len(data)`, and `AgentEmbedService.accept_upload`
narrows that further for a stranger's upload to a hosted page. Those bound what gets
*stored*, and until this existed nothing bounded what a caller could make the process
receive - Starlette's multipart parser resolves an `UploadFile` parameter before the
handler runs, so by the time any of those checks executes the whole body has been
spooled to a temporary file and `await file.read()` has copied it into memory.

That is not much of a risk behind a session. It is one on
`POST /api/v1/embed/{key}/files` (#517), which is the first route on a public
surface that writes bytes: five uploads a minute per address, each of them
arbitrarily large, with no account behind any of them.

So the declared length is read before the body is, which is early enough to be worth
doing and not a complete answer:

*It trusts `Content-Length`, which a caller sets.* Lying downwards does not help
them - the per-route caps still measure the bytes - and a chunked request declares no
length at all, so this refuses the easy version and the per-route checks remain the
ones that hold. A deployment that wants the guarantee rather than the courtesy sets
`client_max_body_size` on the proxy in front of it, which is what
`docs/configuration.md` says.

*The cap is derived, not configured.* It is the largest upload the API accepts plus
the slack a multipart envelope needs, so raising `MAX_UPLOAD_SIZE_MB` raises this
with it. A second number to keep in step with the first is a number that ends up
below it.
"""

from __future__ import annotations

import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings

logger = logging.getLogger(__name__)

# What a multipart envelope costs on top of the file inside it: the boundaries, the
# per-part headers, and any other fields the form carries. Generous, because the
# failure of being too tight is refusing a legitimate upload at its documented size.
_ENVELOPE_ALLOWANCE = 5 * 1024 * 1024


def max_body_bytes() -> int:
    """The largest request body this API will accept.

    Derived from `MAX_UPLOAD_SIZE_MB` rather than set beside it, so the two cannot
    disagree: a deployment that raises the upload limit has raised this.
    """
    return settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024 + _ENVELOPE_ALLOWANCE


class BodySizeLimitMiddleware:
    """Refuse an over-large request before its body is read.

    Pure ASGI rather than `BaseHTTPMiddleware`: that one wraps the receive channel in
    a task and reads the request to hand it on, which is the buffering this exists to
    avoid.

    A refusal is the API's own error envelope, because a client parsing our errors
    should not need to know which layer produced one. It is built here rather than
    raised, since a middleware sits above the exception handlers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _declared_length(scope)
        limit = max_body_bytes()
        if declared is not None and declared > limit:
            logger.warning(
                "request_body_too_large",
                extra={"declared_bytes": declared, "limit_bytes": limit, "path": scope.get("path")},
            )
            response = JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "REQUEST_TOO_LARGE",
                        "message": "That request is too large.",
                        "details": {"limit_mb": settings.MAX_UPLOAD_SIZE_MB},
                    }
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def _declared_length(scope: Scope) -> int | None:
    """What this request says its body weighs, or `None` if it does not say.

    `None` covers a chunked request and a malformed header alike, and both are let
    through: this is the cheap half of the answer, and refusing a request for having
    an unparsable `Content-Length` would be a new way to fail on a header the route
    does not otherwise read.
    """
    for name, value in scope.get("headers", []):
        if name != b"content-length":
            continue
        try:
            return int(value)
        except ValueError:
            return None
    return None
