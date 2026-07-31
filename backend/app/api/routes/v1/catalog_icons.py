"""Custom brand icons a deployment ships beside its catalogs.

Both endpoints are deliberately unauthenticated, like the embed widget: the
consumer is a CSS mask URL in the browser, which cannot attach a bearer token,
and the payload is brand artwork the deployment chose to draw in its own UI.
What they reveal - which marks exist - is exactly what any signed-in page
renders anyway.

The SVG response carries a CSP that forbids everything: an SVG opened as a
document can run script, and these files are operator-supplied rather than
authored here. As an `<img>` or mask source the header is inert; as a
navigation target it makes the file a picture again.
"""

from typing import Any

from fastapi import APIRouter, Response

from app.core import catalog
from app.core.exceptions import NotFoundError
from app.schemas.catalog import CatalogIconList

router = APIRouter()

# Icons change when the deployment redeploys, so an hour of caching is cheap;
# the list is what the frontend polls once per load and is served fresh.
_SVG_HEADERS = {
    "Cache-Control": "public, max-age=3600",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/icons", response_model=CatalogIconList)
async def list_custom_icons() -> Any:
    """The names with a custom mark, so the client asks only for files that exist."""
    names = catalog.custom_icon_names()
    return CatalogIconList(items=names, total=len(names))


@router.get("/icons/{name}")
async def get_custom_icon(name: str) -> Response:
    """One custom mark, as the SVG the operator dropped in."""
    path = catalog.custom_icon(name)
    if path is None:
        raise NotFoundError(message="No such icon", details={"name": name})
    return Response(content=path.read_bytes(), media_type="image/svg+xml", headers=_SVG_HEADERS)
