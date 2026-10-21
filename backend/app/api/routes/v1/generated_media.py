"""Serving media an agent generated back to the interface.

Scoped to the caller's organization and nothing finer: the directory the bytes
are read from is built from `ctx.organization_id`, never from the path, so a
filename only ever resolves within the caller's own tenant and another
organization's leaf name is a 404. Which types may be *displayed* rather than
downloaded is `_workspace_bytes.INLINE_TYPES`, shared with the workspace routes so
the answer cannot differ by surface.
"""

from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from app.api.deps import Auth
from app.api.routes.v1._workspace_bytes import file_response
from app.services.generated_media import load_generated_media

router = APIRouter()


@router.get("/{filename}", response_model=None)
async def get_generated_media(
    filename: str,
    ctx: Auth,
    download: bool = Query(False, description="Force a download rather than a preview"),
    range_header: str | None = Header(
        None, alias="Range", description="One byte range, for a player"
    ),
) -> Response:
    """One generated file, as bytes a browser can display or download.

    A `Range` request is answered `206` with that slice: a clip of speech or video
    is played straight from this address, and WebKit plays an MP4 only that way.

    Raises:
        NotFoundError: If this organization has no file under `filename` - the
            same answer a wrong tenant's name gets, so a name is not a way to
            learn what another organization has generated.
    """
    organization_id: UUID = ctx.organization_id
    data = await load_generated_media(organization_id, filename)
    return file_response(data, path=filename, download=download, byte_range=range_header)
