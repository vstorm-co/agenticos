"""Shared response builders for routes that return something other than a model.

A route module owns request handlers; the turn from a finished value into a
`Response` is not one, and repeating it per handler is how a header drifts
between two endpoints that should send the same one. This is the one place a
CSV export becomes a download.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Response

if TYPE_CHECKING:
    from app.services.run_export import ExportResult


def csv_response(result: ExportResult) -> Response:
    """A finished export as a downloadable CSV.

    `Response` rather than a `response_model`: the body is text the service
    already built, not a model to serialise, and it carries the disposition that
    makes a browser save it under the stamped name instead of rendering it.
    """
    return Response(
        content=result.content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )
