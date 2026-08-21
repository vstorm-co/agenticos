"""Shared response builders for routes that return something other than a model.

A route module owns request handlers; the turn from a finished value into a
`Response` is not one, and repeating it per handler is how a header drifts
between two endpoints that should send the same one. This is the one place a
CSV export becomes a download.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from urllib.parse import quote

from fastapi import Response

if TYPE_CHECKING:
    from app.services.run_export import ExportResult


def content_disposition(mode: Literal["inline", "attachment"], filename: str) -> str:
    """The header that names a download, for a name that may hold anything.

    **`filename*` and nothing else.** An ASGI server encodes headers as latin-1,
    so the bare `filename="..."` form raises `UnicodeEncodeError` on the first
    character outside it - which is a 500 on every attempt to preview or download
    the file, for a name a person chose: `AI-Engineer-plan-nauki-pełny-eksport.pdf`
    died on its `ł`, and the browser was shown `FILE_NOT_FOUND` about a file that
    was there. RFC 5987's form carries the whole of UTF-8 and every browser in use
    reads it.

    It is also the safer form. A quote or a newline in a bare `filename` is a
    header-injection primitive; percent-encoding leaves nothing to inject with.
    """
    return f"{mode}; filename*=UTF-8''{quote(filename)}"


def csv_response(result: ExportResult) -> Response:
    """A finished export as a downloadable CSV.

    `Response` rather than a `response_model`: the body is text the service
    already built, not a model to serialise, and it carries the disposition that
    makes a browser save it under the stamped name instead of rendering it.
    """
    return Response(
        content=result.content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": content_disposition("attachment", result.filename)},
    )
