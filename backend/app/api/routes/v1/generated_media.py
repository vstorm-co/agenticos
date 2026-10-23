"""Serving media an agent generated back to the interface.

Scoped to the caller's organization and nothing finer: the directory the bytes
are read from is built from `ctx.organization_id`, never from the path, so a
filename only ever resolves within the caller's own tenant and another
organization's leaf name is a 404. Which types may be *displayed* rather than
downloaded is `_workspace_bytes.INLINE_TYPES`, shared with the workspace routes so
the answer cannot differ by surface.

Streamed, never loaded (#2310): a clip can be hundreds of megabytes and this route
has no rate limit of its own, so a ranged request reads only its range from the
store rather than the whole file once per request.
"""

from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from app.api.deps import Auth
from app.api.routes.v1._workspace_bytes import streamed_file_response
from app.core.exceptions import NotFoundError
from app.services.generated_media import open_generated_media

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
    stored = await open_generated_media(organization_id, filename)
    try:
        return await streamed_file_response(
            stored.storage_path,
            size=stored.size,
            path=filename,
            download=download,
            byte_range=range_header,
        )
    except FileNotFoundError as exc:
        # Gone between being measured and being opened - a retention sweep, a
        # deleted conversation. Nothing has gone out yet, so it is still a 404.
        raise NotFoundError(
            message="Generated file not found", details={"filename": filename}
        ) from exc
