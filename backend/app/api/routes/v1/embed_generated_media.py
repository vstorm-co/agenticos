"""A generated file, for a visitor on a hosted page or an embed (#2309).

The console's `/generated/{filename}` needs a session, and a visitor has none. This
route needs a link instead: one the visitor's own socket minted for that file, on
that embed - see `app.services.embed_generated_media` for what a link is and what
it opens. It sits beside the embed's other public routes under
`/embed/{public_key}`, in a module of its own.

Rate-limited per link, not per address (`limit_embed_generated_media`): the
request arrives through the hosted page's proxy, so its address is the frontend
server's, and a bucket counted per address would hold every hosted page at once -
the trap `rate_limit.hosted_admission_allowed` records. The allowance is sized
for a player fetching a clip in ranges, several per play.
"""

from typing import Any

from fastapi import APIRouter, Depends, Header, Query

from app.api.deps import EmbedGeneratedMediaSvc, limit_embed_generated_media
from app.api.routes.v1._workspace_bytes import streamed_file_response
from app.core.exceptions import NotFoundError

router = APIRouter()


@router.get(
    "/{public_key}/generated/{filename}",
    response_model=None,
    dependencies=[Depends(limit_embed_generated_media)],
)
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
    Streamed like the console's route (#2310): only the range asked for is read.

    Raises:
        NotFoundError: If the token does not open this file on this embed - it was
            minted for another file or another embed, it has expired, it is
            malformed or absent - or the embed is paused, or the file is gone. One
            answer for all of them, the same one a missing file gets.
        RateLimitError: If this link has been fetched past its allowance this
            minute.
    """
    stored = await service.open(public_key, filename, token)
    try:
        return await streamed_file_response(
            stored.storage_path,
            size=stored.size,
            path=filename,
            download=False,
            byte_range=range_header,
        )
    except FileNotFoundError as exc:
        # Gone between being measured and being opened - a retention sweep, a
        # deleted conversation. Nothing has gone out yet, so it is the same 404.
        raise NotFoundError(
            message="Generated file not found", details={"filename": filename}
        ) from exc
