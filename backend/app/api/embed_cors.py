"""The CORS header a widget's refusals need, and nothing wider (#1797).

A widget runs on somebody else's site and posts a recording to this API from
there. The global `CORSMiddleware` only knows this deployment's own origins, so
the dictation route answers its success with the visitor's origin itself, the
way `/config` does - but a refusal is written by an exception handler, which
knew nothing about that origin. Without the header the browser hides the whole
response, `fetch` throws a `TypeError`, and a recording that was too long, a
provider that timed out and a rate limit all reach the visitor as "offline".

So the route records on the request the origin it admitted, and the handlers
copy it onto whatever refusal follows. **Only an admitted origin is recorded**:
a refusal of admission itself stays unreadable to the site that was refused,
exactly as a refused `/config` does. The one exception is the 429 from the rate
limit, which runs before admission and is the same answer for every origin, so
saying it to whoever asked tells them nothing about the embed.
"""

from __future__ import annotations

from starlette.requests import HTTPConnection

_STATE_KEY = "embed_cors_origin"


def allow_embed_origin(connection: HTTPConnection, origin: str | None) -> None:
    """Let the response to this request, refusals included, be read by `origin`."""
    if origin:
        setattr(connection.state, _STATE_KEY, origin)


def embed_cors_headers(connection: HTTPConnection) -> dict[str, str]:
    """The headers for an origin this request admitted, or none."""
    origin = getattr(connection.state, _STATE_KEY, None)
    if not isinstance(origin, str):
        return {}
    return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
