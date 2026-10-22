"""Generated media on surfaces with no session: a hosted page, a widget, a socket.

The console reads a generated file through `/api/v1/generated/{filename}`, which
is authenticated and organization-scoped (`generated_media`). A visitor on a
hosted page has no session, so the card the page drew for an image, a clip of
speech or a video asked that route and got a 401 for a file the provider had
already been paid for (#2309).

**A link is minted for one file, on one embed, for a while - and only by the
socket that streamed the result naming it.** `EmbedSession._emit` hands every
`tool_result` of a `generate_image`, `generate_speech` or `generate_video` call
to :func:`signed_media_result`, which adds a `token` to the payload: an HMAC,
under the deployment's existing `SECRET_KEY`, of the embed's public key, the
file's leaf name and an expiry. The serving route checks the signature before it
reads anything, so:

- another conversation's file is a different leaf name, and no token minted in
  this one signs it;
- another organization's file is out of reach twice over - the token names this
  embed's key, and the bytes are read from the directory of the organization
  *that embed* belongs to, never from anything in the request;
- an arbitrary leaf name in the same organization was never signed;
- a forged, truncated, expired or missing token is the same 404 a missing file
  gets, so the route says nothing about which files exist.

Nothing is stored. The token rides in the tool result as it is *sent*, not as it
is recorded: the transcript keeps the result the tool returned, so no credential
lands in a row, and a replayed thread - which on a hosted page carries text only -
has no stale link in it. The cost of a stateless link is that it cannot be
revoked one at a time: pausing the embed or rotating its key ends all of them,
and :data:`LINK_TTL` ends each one on its own.
"""

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.repositories import agent_embed as agent_embed_repo
from app.services.generated_media import load_generated_media

LINK_TTL = timedelta(hours=6)
"""How long a link a visitor was handed keeps opening its file.

Long enough for a tab left open over a working session - a clip is fetched again
in ranges each time it is played, so a link that lapsed mid-visit would leave a
player that stops working - and short enough that a link copied out of the page
stops being one the same day.
"""

MEDIA_TOOLS: dict[str, str] = {
    "generate_image": "generated_image",
    "generate_speech": "generated_speech",
    "generate_video": "generated_video",
}
"""The tools whose result names a file they stored, and the `kind` each returns.

Keyed by the tool, not by the payload: any tool can return text that looks like
`{"kind": "generated_image", "filename": ...}` - an MCP server, a page fetched
from the web - and a link minted from that would open whatever file it named.
These three write the name themselves, from what the store handed back.
"""

_TOKEN = re.compile(r"([0-9]{1,12})\.([0-9a-f]{64})")
"""An expiry in Unix seconds, and a SHA-256 HMAC in hex."""


def _signature(public_key: str, filename: str, expires: int) -> str:
    """This deployment's signature over one file, on one embed, until `expires`.

    Prefixed with what it is for, so a value signed here is never one another use
    of `SECRET_KEY` would accept, nor the reverse.
    """
    message = f"embed-generated-media:{public_key}:{filename}:{expires}"
    return hmac.new(settings.SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()


def media_token(public_key: str, filename: str, *, now: datetime) -> str:
    """A link token for `filename` on the embed `public_key`, valid for :data:`LINK_TTL`."""
    expires = int((now + LINK_TTL).timestamp())
    return f"{expires}.{_signature(public_key, filename, expires)}"


def token_opens(public_key: str, filename: str, token: str | None, *, now: datetime) -> bool:
    """Whether `token` was minted here for this file on this embed, and is still good."""
    match = _TOKEN.fullmatch(token or "")
    if match is None:
        return False
    expires = int(match.group(1))
    if expires <= int(now.timestamp()):
        return False
    return hmac.compare_digest(match.group(2), _signature(public_key, filename, expires))


def media_path(public_key: str, filename: str, token: str) -> str:
    """The API path a visitor's browser fetches one generated file from."""
    return f"/api/v1/embed/{public_key}/generated/{filename}?token={token}"


def signed_media_result(public_key: str, tool_name: str, content: str, *, now: datetime) -> str:
    """A media tool's result as a visitor receives it: with a link that works for them.

    Anything that is not one of :data:`MEDIA_TOOLS` returning its own payload with
    a stored file comes back unchanged - an error string, a result with no
    filename (a run with nothing to scope storage to), or another tool entirely.

    `url` is replaced rather than left beside the token: the console's address is
    one this visitor cannot open, and a socket integration reading the payload
    should be handed the address it can.
    """
    kind = MEDIA_TOOLS.get(tool_name)
    if kind is None:
        return content
    try:
        payload = json.loads(content)
    except ValueError:
        return content
    if not isinstance(payload, dict) or payload.get("kind") != kind:
        return content
    filename = payload.get("filename")
    if not isinstance(filename, str) or not filename:
        return content
    token = media_token(public_key, filename, now=now)
    return json.dumps({**payload, "url": media_path(public_key, filename, token), "token": token})


class EmbedGeneratedMediaService:
    """Reads a generated file for a visitor holding a link minted on their socket."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def load(self, public_key: str, filename: str, token: str | None) -> bytes:
        """The bytes of one generated file, if `token` opens it.

        The signature is checked first, so a guessed address costs no query and no
        read. The organization is read off the embed's row, never from the
        request, and an embed that is paused or gone opens nothing.

        Raises:
            NotFoundError: For every refusal - a bad, expired or missing token, an
                inactive or unknown embed, a missing file - so that none of them
                tells a caller more than another. The token is never in `details`.
        """
        missing = NotFoundError(message="Generated file not found", details={"filename": filename})
        if not token_opens(public_key, filename, token, now=datetime.now(UTC)):
            raise missing
        embed = await agent_embed_repo.get_by_key(self.db, public_key)
        if embed is None or not embed.is_active:
            raise missing
        return await load_generated_media(embed.organization_id, filename)
