"""Serving an image an agent generated back to the interface.

Scoped to the caller's organization and nothing finer: the directory the bytes
are read from is built from `ctx.organization_id`, never from the path, so a
filename only ever resolves within the caller's own tenant and another
organization's leaf name is a 404. Which types may be *displayed* rather than
downloaded is `_workspace_bytes.INLINE_TYPES`, shared with the workspace routes so
the answer cannot differ by surface.
"""

from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.deps import Auth
from app.api.routes.v1._workspace_bytes import file_response
from app.services.generated_media import load_generated_image

router = APIRouter()


@router.get("/{filename}", response_model=None)
async def get_generated_image(
    filename: str,
    ctx: Auth,
    download: bool = Query(False, description="Force a download rather than a preview"),
) -> Response:
    """One generated image, as bytes a browser can display or download.

    Raises:
        NotFoundError: If this organization has no image under `filename` - the
            same answer a wrong tenant's name gets, so a name is not a way to
            learn what another organization has generated.
    """
    organization_id: UUID = ctx.organization_id
    data = await load_generated_image(organization_id, filename)
    return file_response(data, path=filename, download=download)
