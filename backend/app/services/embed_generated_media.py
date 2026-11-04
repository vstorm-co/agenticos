"""Generated media on surfaces with no session: a hosted page, a widget, a socket.

The console reads a generated file through `/api/v1/generated/{filename}`, which
is authenticated and organization-scoped (`generated_media`). A visitor on a
hosted page has no session, so the card the page drew for an image, a clip of
speech or a video asked that route and got a 401 for a file the provider had
already been paid for (#2309).

**A link is minted for one file, on one embed, for a while - and only for a file
the run streaming to that socket stored itself.** `EmbedSession._emit` hands
every `tool_result` to :func:`signed_media_result` with the run's
`AgentDeps.generated_files` - the leaf names `store_generated` recorded as this
run's own tools wrote them - and a payload naming a file is signed only when the
file is in that set. Which tool's result it is does not decide it: an MCP tool or
a renamed one can be *called* `generate_image` and return any filename it likes,
and a name is not provenance. The link itself is an HMAC, under the deployment's
existing `SECRET_KEY`, of the embed's public key, the file's leaf name and an
expiry. The serving route checks the signature before it reads anything, so:

- another conversation's file is a different leaf name this run never stored,
  and no token minted in this one signs it;
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
from collections.abc import Callable
from collections.abc import Set as AbstractSet
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.image_generation._toolset import (
    GeneratedImage,
    parse_generated_image,
)
from app.agents.capabilities.text_to_speech._toolset import (
    GeneratedSpeech,
    parse_generated_speech,
)
from app.agents.capabilities.video_generation._toolset import (
    GeneratedVideo,
    parse_generated_video,
)
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.repositories import agent_embed as agent_embed_repo
from app.services.generated_media import StoredGeneratedMedia, open_generated_media

LINK_TTL = timedelta(hours=6)
"""How long a link a visitor was handed keeps opening its file.

Long enough for a tab left open over a working session - a clip is fetched again
in ranges each time it is played, so a link that lapsed mid-visit would leave a
player that stops working - and short enough that a link copied out of the page
stops being one the same day.
"""

_MEDIA_PAYLOADS: tuple[
    Callable[[str], GeneratedImage | GeneratedSpeech | GeneratedVideo | None], ...
] = (
    parse_generated_image,
    parse_generated_speech,
    parse_generated_video,
)
"""What a result naming a generated file looks like: each tool's own parser.

Read by the tools' parsers rather than a copy of their `kind` strings here, so a
media payload that changes shape changes what is signed with it.
"""

_TOKEN = re.compile(r"([1-9][0-9]{0,11})\.([0-9a-f]{64})")
"""An expiry in Unix seconds, and a SHA-256 HMAC in hex.

The expiry has no leading zero, as `media_token` writes it, so a link has one
spelling: `0<expiry>` signs the same `int`, and accepting it would hand one link
a fresh rate-limit bucket per zero (`rate_limit.embed_generated_media_allowed`).

A bare HMAC rather than one of `app.core.security`'s typed JWTs because it rides
in a URL a player requests over and over: a JWT's header and claims would treble
its length and carry nothing the signed message here does not already pin.
"""


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
    """The API path one generated file is fetched from with a link token.

    Written into the payload as `url` for a client that drives a page's socket
    itself and fetches from this deployment directly. The hosted page does not use
    it: it builds its own same-origin address from `token`, through the frontend's
    proxy.
    """
    return f"/api/v1/embed/{public_key}/generated/{filename}?token={token}"


def signed_media_result(
    public_key: str, content: str, *, stored: AbstractSet[str], now: datetime
) -> str:
    """A tool result as a visitor receives it: with a link to a file it names, if it may.

    Signed only when `content` is a media tool's payload (see `_MEDIA_PAYLOADS`)
    and the file it names is in `stored` - the leaf names the run's own tools
    stored. Anything else comes back unchanged: an error string, a payload with no
    filename (a run with nothing to scope storage to), another tool's text, and a
    media-shaped payload naming a file this run did not make, whatever the tool
    that returned it is called.

    Every key the payload carries is kept. `url` is replaced rather than left
    beside the token: the console's address is one this visitor cannot open.
    """
    if not stored:
        return content
    filename = _named_file(content)
    if filename is None or filename not in stored:
        return content
    token = media_token(public_key, filename, now=now)
    payload = json.loads(content)
    return json.dumps({**payload, "url": media_path(public_key, filename, token), "token": token})


def _named_file(content: str) -> str | None:
    """The stored file a media tool's payload names, or `None` if it is not one."""
    for parse in _MEDIA_PAYLOADS:
        parsed = parse(content)
        if parsed is not None:
            return parsed.filename
    return None


class EmbedGeneratedMediaService:
    """Reads a generated file for a visitor holding a link minted on their socket."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def open(self, public_key: str, filename: str, token: str | None) -> StoredGeneratedMedia:
        """Where one generated file is and how long, if `token` opens it - never its bytes.

        A route streams it from there (#2310): a link may be fetched 120 times a
        minute, and reading a long clip whole for each would hold it once per
        request.

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
        return await open_generated_media(embed.organization_id, filename)
