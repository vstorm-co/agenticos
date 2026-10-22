"""A generated file, for a visitor on a hosted page or an embed (#2309).

The console's `/generated/{filename}` needs a session, and a visitor has none. This
route needs a link instead: one the visitor's own socket minted for that file, on
that embed - see `app.services.embed_generated_media` for what a link is and what
it opens. It sits beside the embed's other public routes under
`/embed/{public_key}`, in a module of its own.

No rate limit, unlike its neighbours, and on purpose: a player fetches a clip in
ranges, several per play, and a bucket counted per address would count the
frontend server's container for every hosted page at once - the trap
`rate_limit.hosted_admission_allowed` records. A request without a valid
signature is refused before any query or read, so the route offers nothing to
spend.
"""

from typing import Any

from fastapi import APIRouter, Header, Query

from app.api.deps import EmbedGeneratedMediaSvc
from app.api.routes.v1._workspace_bytes import file_response

router = APIRouter()


@router.get("/{public_key}/generated/{filename}", response_model=None)
async def get_embed_generated_media(
    public_key: str,
    filename: str,
    service: EmbedGeneratedMediaSvc,
    token: str | None = Query(
        None, max_length=128, description="The link token the visitor's socket was handed"
    ),
    range_header: str | None = Header(
        None, alias="Range", description="One byte range, for a player"
    ),
) -> Any:
    """One generated file from this visitor's conversation, to display or play.

    Typed for display by the same allowlist as the console's route, and a `Range`
    request is answered `206` with that slice - Safari plays an MP4 only that way.

    Raises:
        NotFoundError: If the token does not open this file on this embed - it was
            minted for another file or another embed, it has expired, it is
            malformed or absent - or the embed is paused, or the file is gone. One
            answer for all of them, the same one a missing file gets.
    """
    data = await service.load(public_key, filename, token)
    return file_response(
        data, path=filename, download=False, byte_range=range_header, serves_ranges=True
    )
