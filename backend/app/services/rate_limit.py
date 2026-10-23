"""How often one caller may reach a public surface.

Eleven of this platform's surfaces are reachable without a session: the public run
API, the widget's script, its config endpoint, its socket, a hosted page's config,
that page's logo and its file upload, the dictation a page and a widget share, a
public artifact link, the signed address an artifact's page is served from, and
the signed link a visitor's socket hands out for a file the agent generated. Every
one of them answers a caller nobody signed in, most read a row before they decide
anything, and between them and somebody else's model budget there was, until #39,
nothing at all - a limiter was constructed in `app/core/rate_limit.py`,
registered on the app, and used by no route, while a second Redis-backed one sat
unimported in `app/services/rate_limit/` and could not have been imported anyway:
it read `get_redis` from a module that does not define one.

The count is load-bearing rather than decorative: it said "three" while five
existed, which is how a public route acquires no gate - nothing complains, and
the next reader takes the number for the sweep.

What replaced both is this module, and the shape is deliberately
`app/services/channels/dedupe.py`:

*The count is in the deployment's shared Redis, never in this process.*
Production runs `uvicorn --workers 4`, so a per-process counter lets through
four times what it says it does - and a limit that is wrong by the worker count
is worse than no limit, because it reads as one that holds. The channel
router's per-account allowance counts through here too, for the same reason:
its own per-process dict was off by the worker count and never forgot a caller.

*A fixed window, not a rolling one.* `INCR` plus an `EXPIRE … NX`, two
commands, and a caller who arrives at the end of one window and again at the
start of the next gets up to twice the allowance across that boundary. That is
the honest cost of the simplest correct thing, and it is acceptable for what
these limits are: a ceiling on how fast a stranger may open sockets and spend
somebody's money, not a traffic shaper.

*It fails open, loudly.* A Redis nobody can reach means the limit is not
applied and a warning is logged. Refusing a visitor their answer because a
cache blipped is the worse failure of the two, and it is the same trade-off,
for the same reason, as the deduplication claim. The `Decision` says when that
happened (`metered=False`), so a surface whose per-caller limit is a production
control - a channel bot's `rate_limit_rpm` - can keep a per-process floor under
the caller for as long as the outage lasts rather than none at all.
"""

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from starlette.requests import HTTPConnection

from app.clients.redis import RedisClient
from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: RedisClient | None = None

# The longest a caller may be before it is replaced by a digest. The auth limiter
# counts a submitted login identifier, which an unauthenticated caller controls
# and need not keep short - so a raw interpolation lets one request store the
# whole value as a Redis key, and the body limit permits tens of megabytes. Past
# this bound the caller becomes a fixed-size hash; a real identifier (an email is
# at most 254 characters, plus a short prefix) never reaches it (#947).
_MAX_CALLER_LEN = 320


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`.

    Called by the lifespan next to where the client is created, and for the same
    reason as `channel_dedupe.configure`: the limit is only as wide as the Redis
    every worker already shares, and a second pool to the same server would be
    one more thing the shutdown path has to know about.
    """
    global _redis
    _redis = redis


@dataclass(frozen=True)
class Limit:
    """How many attempts one caller gets, and over how long."""

    attempts: int
    window_seconds: int = 60


@dataclass(frozen=True)
class Decision:
    """Whether this attempt is allowed, and when to try again if not.

    `metered` says whether the answer came from a count at all. It is `False`
    on the two fail-open paths - no limiter configured, a Redis that could not
    be reached - where `allowed` is a default rather than a decision, so a
    surface that must keep a floor under a caller while Redis is down can tell
    the two apart and count locally instead of reading "allowed" as "inside".
    """

    allowed: bool
    retry_after_seconds: int
    metered: bool = True


def caller_ip(connection: HTTPConnection) -> str:
    """The address a per-IP limit counts against.

    `X-Forwarded-For` is read only when `RATE_LIMIT_TRUST_FORWARDED_FOR` says
    to, and the default is not to, because the header is set by whoever is
    calling: trusting it unconditionally turns a per-IP limit into a per-header
    limit that anybody bypasses by varying one string.

    The cost of the default is the mirror image, and a deployment behind a proxy
    has to know about it: every caller then arrives as the proxy, shares one
    bucket, and a busy site behind a CDN exhausts the widget's allowance for
    everybody at once. Turn the setting on when a proxy in front of this
    deployment is the only thing that can reach it - `docs/configuration.md`
    has the sentence.

    The **rightmost** hop is read, not the leftmost. `X-Forwarded-For` is a list
    the client starts and each proxy appends to, and nginx's
    `$proxy_add_x_forwarded_for` and Cloudflare both *add* the peer address
    rather than replacing the list - so the leftmost entry is whatever the client
    typed, and counting it hands the limiter back to anyone willing to vary a
    header. The last entry is the one the trusted proxy itself wrote, which is why
    this setting is only safe with exactly one such proxy in front; a deployment
    with two has to collapse the header to one hop at its edge.

    Works for a WebSocket as well as a request: both are `HTTPConnection`, and
    the socket handshake needs the same answer.
    """
    if settings.RATE_LIMIT_TRUST_FORWARDED_FOR:
        forwarded = connection.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[-1].strip() or "unknown"
    return connection.client.host if connection.client else "unknown"


def _bounded(caller: str) -> str:
    """A caller short enough to be a Redis key, digesting anything oversized."""
    if len(caller) <= _MAX_CALLER_LEN:
        return caller
    return f"h:{hashlib.sha256(caller.encode()).hexdigest()}"


async def consume(*, surface: str, caller: str, limit: Limit) -> Decision:
    """Count one attempt by `caller` against `surface`, and say whether it may.

    Allowed when the limiter cannot count - see the module docstring. The log
    line is the only thing that distinguishes "under the limit" from "not
    limited at all", so it is a warning rather than a debug.
    """
    if _redis is None:
        # The surface, never the caller: a caller is an address, a sign-in email,
        # a key's digest or a visitor's subject, and none of it says more about a
        # limiter nobody configured than which surface went unmetered.
        logger.warning("Rate limiting not configured - %s reached unmetered", surface)
        return Decision(allowed=True, retry_after_seconds=0, metered=False)

    key = f"ratelimit:{surface}:{_bounded(caller)}"
    try:
        used = await _redis.count_in_window(key, ttl=limit.window_seconds)
    except Exception:
        logger.warning("rate_limit_redis_unavailable", exc_info=True)
        return Decision(allowed=True, retry_after_seconds=0, metered=False)

    if used > limit.attempts:
        return Decision(allowed=False, retry_after_seconds=limit.window_seconds)
    return Decision(allowed=True, retry_after_seconds=0)


class LocalWindows:
    """A per-process fixed window, for the attempts the shared limiter could not count.

    `consume` is the limit that holds across workers, and it fails open when
    Redis is down or nobody configured one. For a public widget's socket that is
    the documented trade; where the limit is a production control - a channel
    bot's per-sender `rate_limit_rpm` (`SECURITY.md`), and every surface where a
    stranger's attempt is a paid call (`consume_floored`) - a limiter that
    vanishes for the length of a Redis outage lets a caller go as fast as they
    like until it recovers. So this stands in for exactly that stretch: wrong by
    the worker count, which is the defect the shared limiter exists to fix, and
    still a floor where there would have been none.

    Bounded: every write drops the windows that have expired, so the map is the
    size of the callers seen in the last minute, not of every caller since the
    process started - which is what the dict this replaces did.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._windows: dict[str, tuple[int, float]] = {}
        self._clock = clock

    def __len__(self) -> int:
        return len(self._windows)

    def consume(self, caller: str, *, attempts: int, window_seconds: int) -> bool:
        now = self._clock()
        for key in [
            k for k, (_n, opened) in self._windows.items() if now - opened >= window_seconds
        ]:
            del self._windows[key]
        count, opened = self._windows.get(caller, (0, now))
        self._windows[caller] = (count + 1, opened)
        return count < attempts


_floor = LocalWindows()


async def consume_floored(*, surface: str, caller: str, limit: Limit) -> Decision:
    """`consume`, with a per-process floor for as long as it cannot count.

    For the surfaces where a stranger's attempt costs the organization money -
    a dictation, a voice call - and the limit is all that bounds it: failing
    open there turns a Redis outage into unlimited paid calls on a public link.
    """
    decision = await consume(surface=surface, caller=caller, limit=limit)
    if decision.metered:
        return decision
    if _floor.consume(
        f"{surface}:{_bounded(caller)}",
        attempts=limit.attempts,
        window_seconds=limit.window_seconds,
    ):
        return decision
    return Decision(allowed=False, retry_after_seconds=limit.window_seconds, metered=False)


async def exhausted(*, surface: str, caller: str, limit: Limit) -> bool:
    """Whether `caller` has used all of `limit` on `surface`, without counting a hit.

    For a check made before work that may not happen: an attempt is counted only
    once it has failed, but a caller already over the line is turned away before
    the work. False when the limiter cannot read, as `consume` allows then.
    """
    if _redis is None:
        return False
    try:
        used = await _redis.get(f"ratelimit:{surface}:{_bounded(caller)}")
    except Exception:
        logger.warning("rate_limit_redis_unavailable", exc_info=True)
        return False
    return used is not None and int(used) >= limit.attempts


def run_limit() -> Limit:
    """What one caller may spend the public run API on, per minute."""
    return Limit(attempts=settings.RATE_LIMIT_RUN_PER_MINUTE)


def api_key_limit() -> Limit:
    """Requests per minute one organization API key may make, on any public route."""
    return Limit(attempts=settings.RATE_LIMIT_API_KEY_PER_MINUTE)


def ml_limit() -> Limit:
    """What one caller may ask the standalone ML services for, per minute."""
    return Limit(attempts=settings.RATE_LIMIT_ML_PER_MINUTE)


def dictation_limit() -> Limit:
    """What one person may dictate into the composer, per minute."""
    return Limit(attempts=settings.RATE_LIMIT_DICTATION_PER_MINUTE)


def voice_preview_limit() -> Limit:
    """How many voices one person may listen to in the Builder, per minute."""
    return Limit(attempts=settings.RATE_LIMIT_VOICE_PREVIEW_PER_MINUTE)


def export_limit() -> Limit:
    """What one caller may ask for a personal-data export, per hour.

    Per hour rather than per minute, because the thing being rationed is not
    load: assembling everything about a person into one document is cheap and is
    the shape of a data breach when the caller is not who they claim to be. A
    person exporting themselves does it once; a stolen session walking the
    deployment's people does it repeatedly (#1421).
    """
    return Limit(attempts=settings.RATE_LIMIT_EXPORT_PER_HOUR, window_seconds=3_600)


def auth_limit() -> Limit:
    """How many auth attempts one caller gets per minute.

    The one surface where the cost of an attempt is the defence rather than a
    detail: `verify_password` is bcrypt, ~170ms with no suspension point, so an
    unmetered `/login` flood saturates a worker's event loop with no credentials
    at all. Counted per IP and per submitted address both - see
    `deps.enforce_auth_limit` - because the two stop different attacks.
    """
    return Limit(attempts=settings.RATE_LIMIT_AUTH_PER_MINUTE)


async def hosted_admission_allowed(public_key: str) -> Decision:
    """Whether this hosted page may be configured again right now.

    Keyed on the page rather than on the caller's address, because on this one
    route the caller is not the visitor: the page's config is fetched
    server-side, so `request.client.host` is the frontend's own address and every
    visitor in the deployment shares one bucket. At the widget's allowance that
    was ten page loads a minute for the whole deployment, answered as a 404 by
    the page - and `RATE_LIMIT_TRUST_FORWARDED_FOR` could not fix it, because a
    server-side `fetch` sends no such header to read.

    What this bounds is therefore one page, not one visitor, so the allowance is
    its own and a much wider one: it exists to stop a single key being hammered
    into a database load, not to ration visitors. **Nothing here rations spend** -
    that is the socket, counted per address, and the key's 192 bits are what make
    guessing one a non-strategy.
    """
    return await consume(
        surface="hosted_config",
        caller=f"key:{public_key}",
        limit=Limit(attempts=settings.RATE_LIMIT_HOSTED_PAGE_PER_MINUTE),
    )


async def public_artifact_allowed(public_key: str) -> Decision:
    """Whether a public artifact link may be opened again right now.

    Keyed on the link, for `hosted_admission_allowed`'s reason: the page asks for
    it server-side, so the address is the frontend's own. What it bounds is one
    link being hammered into database reads; the key's 192 bits are what make
    finding one by guessing a non-strategy.
    """
    return await consume(
        surface="public_artifact",
        caller=f"key:{public_key}",
        limit=Limit(attempts=settings.RATE_LIMIT_HOSTED_PAGE_PER_MINUTE),
    )


ARTIFACT_CONTENT_LOADS_PER_MINUTE = 10
"""How often one signed artifact address may be loaded in a minute.

A frame loads its address once and a reload or two after that; the console and
the public page mint a fresh one each time they draw the frame. Ten is room for
that and no more.
"""


async def artifact_content_allowed(token: str) -> Decision:
    """Whether the page behind this signed address may be served again right now.

    Keyed on the address, not the caller's. The token is minted by this server -
    behind a grant, or behind the public link's own limit - so it cannot be
    varied for free the way a visitor key can, and one leaked address replayed
    from anywhere spends one allowance. Getting more means minting more, which
    is metered where it happens. The address is also the one thing every viewer
    has of their own: counting per network address would put a whole office
    behind one proxy in one bucket.

    The address is a bearer credential for minutes, so it is counted by its
    digest and never written into a Redis key as it is.
    """
    return await consume(
        surface="artifact_content",
        caller=f"token:{hashlib.sha256(token.encode()).hexdigest()}",
        limit=Limit(attempts=ARTIFACT_CONTENT_LOADS_PER_MINUTE),
    )


EMBED_GENERATED_MEDIA_LOADS_PER_MINUTE = 120
"""How often one signed link to a generated file may be fetched in a minute.

Wider than an artifact address's because a player does not fetch once: a clip is
requested in byte ranges - a probe, the body in pieces, more on every seek and
every replay - so a single play is a dozen requests or more. A hundred and twenty
is room for a visitor scrubbing through a video, and a ceiling on one leaked link
replayed into whole-file reads, which every range still costs on the server.
"""


async def embed_generated_media_allowed(token: str) -> Decision:
    """Whether the file behind this signed link may be served again right now.

    Keyed on the link, for `artifact_content_allowed`'s reasons: the request
    reaches this deployment through the hosted page's own proxy, so its address
    is the frontend's; and the link is minted here, for one stored file, so it
    cannot be varied for free. A link has one spelling - the expiry carries no
    leading zero - and `limit_embed_generated_media` counts only a link whose
    signature holds, so any other string is refused uncounted. A bearer
    credential for hours, so it is counted by its digest.
    """
    return await consume(
        surface="embed_generated_media",
        caller=f"token:{hashlib.sha256(token.encode()).hexdigest()}",
        limit=Limit(attempts=EMBED_GENERATED_MEDIA_LOADS_PER_MINUTE),
    )


async def hosted_logo_allowed(public_key: str) -> Decision:
    """Whether this hosted page's logo may be served again right now.

    Keyed on the page, not the address, for the same reason as
    `hosted_admission_allowed`: the browser fetches the logo from the page's own
    origin, so the request that reaches this deployment comes from the frontend
    server's own `fetch` and carries its address. Per address that was one bucket
    for every hosted page's logo at once, answered as the broken-image glyph the
    proxy route exists to remove. Its own surface rather than sharing the config
    one, so a page's logo fetches and its config fetches do not spend each other's
    allowance.
    """
    return await consume(
        surface="hosted_logo",
        caller=f"key:{public_key}",
        limit=Limit(attempts=settings.RATE_LIMIT_HOSTED_PAGE_PER_MINUTE),
    )


async def embed_upload_allowed(
    connection: HTTPConnection, *, public_key: str, visitor: str
) -> Decision:
    """Whether this caller may store another file on this page right now.

    **Two counters, and one of them is not optional.** This is the first thing on
    a public surface that writes bytes to the deployment's own disk, and the two
    things a stranger has are an address and a continuity key. Counting only the
    key bounds nothing at all: the key is minted by the browser and any 32 hex
    characters is a valid one, so a script that varies it gets the allowance again
    per file. Counting only the address is the limit that holds, and the key is
    what stops one browser on a shared address from spending everybody's.

    So both, and both have to allow it. The address is counted first, because it
    is the one that cannot be varied for free.

    Beside `embed_admission_allowed` rather than folded into it, on the same
    reasoning as messages against admissions: what somebody may *say* and what
    they may *store* have nothing to do with each other, and one number for both
    is a number chosen for whichever matters less.
    """
    limit = Limit(attempts=settings.RATE_LIMIT_EMBED_UPLOAD_PER_MINUTE)
    by_address = await consume(
        surface="embed_upload", caller=f"ip:{caller_ip(connection)}", limit=limit
    )
    if not by_address.allowed:
        return by_address
    return await consume(
        surface="embed_upload", caller=f"key:{public_key}:visitor:{visitor}", limit=limit
    )


async def embed_dictation_allowed(connection: HTTPConnection) -> Decision:
    """Whether this address may send another dictation to a page or widget now.

    **Every dictation is a paid call** to the organization's speech-to-text
    provider, and it is not part of any model budget - so the counters here and
    in `embed_dictation_link_allowed` are the whole of what bounds a stranger's
    spend on it. The address is counted before the key is looked up, because it
    is the one a stranger cannot vary for free.

    The link's own ceiling is spent only once the visitor is admitted
    (`embed_dictation_link_allowed`): spent before, anybody holding a `jwt`
    widget's public key could exhaust its minute for every signed-in visitor
    without a valid token (Codex on #2204).
    """
    return await consume_floored(
        surface="embed_dictation",
        caller=f"ip:{caller_ip(connection)}",
        limit=Limit(attempts=settings.RATE_LIMIT_EMBED_DICTATION_PER_MINUTE),
    )


async def embed_dictation_link_allowed(*, public_key: str) -> Decision:
    """Whether an admitted visitor's dictation fits the link's minute.

    The ceiling no visitor can vary: whatever addresses a script rotates
    through, one page or widget accepts at most
    `RATE_LIMIT_EMBED_DICTATION_PER_LINK_PER_MINUTE` recordings a minute from
    everybody together, and that number times the organization's longest
    dictation is the worst a leaked link can cost - `docs/channels.md` works it
    through. A `jwt` widget's visitor is counted on their own first
    (`embed_dictation_visitor_allowed`), so one of them takes at most
    `RATE_LIMIT_EMBED_DICTATION_PER_MINUTE` of it.
    """
    return await consume_floored(
        surface="embed_dictation",
        caller=f"key:{public_key}",
        limit=Limit(attempts=settings.RATE_LIMIT_EMBED_DICTATION_PER_LINK_PER_MINUTE),
    )


async def embed_dictation_visitor_allowed(*, public_key: str, visitor: str) -> Decision:
    """Whether this verified `jwt` visitor may send another dictation now.

    Keyed on the token's subject, which the customer's backend signed and a
    visitor cannot mint - unlike a hosted page's continuity key, which is why a
    page has no counter of this kind.
    """
    return await consume_floored(
        surface="embed_dictation",
        caller=f"key:{public_key}:visitor:{visitor}",
        limit=Limit(attempts=settings.RATE_LIMIT_EMBED_DICTATION_PER_MINUTE),
    )


async def embed_voice_allowed(connection: HTTPConnection) -> Decision:
    """Whether this address may start another voice call on a page or widget now (#54).

    **Every call is a paid realtime session**, so this is the
    `embed_dictation_allowed` shape with counters of its own: the address before
    the key is looked up, and the link's ceiling (`embed_voice_link_allowed`) only
    once the visitor is admitted, so nobody without a valid `jwt` token can spend
    it for the visitors who have one.
    """
    return await consume_floored(
        surface="embed_voice",
        caller=f"ip:{caller_ip(connection)}",
        limit=Limit(attempts=settings.RATE_LIMIT_EMBED_VOICE_PER_MINUTE),
    )


async def embed_voice_link_allowed(*, public_key: str) -> Decision:
    """Whether an admitted visitor's call fits the link's minute (#54).

    Whatever addresses a script rotates through, one page or widget starts at
    most `RATE_LIMIT_EMBED_VOICE_PER_LINK_PER_MINUTE` calls a minute, and that
    number times the agent's longest call - inside the agent's and the
    organization's budgets - is the worst a leaked link can cost.
    """
    return await consume_floored(
        surface="embed_voice",
        caller=f"key:{public_key}",
        limit=Limit(attempts=settings.RATE_LIMIT_EMBED_VOICE_PER_LINK_PER_MINUTE),
    )


async def embed_voice_visitor_allowed(*, public_key: str, visitor: str) -> Decision:
    """Whether this verified `jwt` visitor may start another voice call now (#54).

    Keyed on the token's subject, which the customer's backend signed and a
    visitor cannot mint - so one signed-in visitor takes at most
    `RATE_LIMIT_EMBED_VOICE_PER_MINUTE` of the link's starts, wherever they
    connect from. Their open calls are bounded with everybody's by
    `VOICE_MAX_CALLS_PER_EMBED`.
    """
    return await consume_floored(
        surface="embed_voice",
        caller=f"key:{public_key}:visitor:{visitor}",
        limit=Limit(attempts=settings.RATE_LIMIT_EMBED_VOICE_PER_MINUTE),
    )


async def map_tiles_allowed(connection: HTTPConnection) -> Decision:
    """Whether this address may fetch another map tile through the deployment right now.

    Per address: the tile route is cookieless and token-free - every page, saved
    or shared, loads it - so the network address is the one thing to count.
    """
    return await consume(
        surface="map_tiles",
        caller=f"ip:{caller_ip(connection)}",
        limit=Limit(attempts=settings.RATE_LIMIT_MAP_TILES_PER_MINUTE),
    )


async def embed_script_allowed(connection: HTTPConnection) -> Decision:
    """Whether this address may fetch a widget's script right now.

    **Its own counter rather than admission's, and that is the point of it.** The
    script, the config and the socket handshake used to share one key, so a number
    an operator sets to twenty admissions a minute bought about seven page loads: a
    cold browser spends all three, and a warm one two. A limit wrong by a factor of
    three is this module's own failure mode one layer up - it reads as the number
    that was configured.

    The script is the one to separate rather than the socket, for two reasons: it is
    cacheable, so it is the cheapest of the three to be generous with, and being
    refused it breaks the widget outright rather than delaying a message.
    """
    return await consume(
        surface="embed_script",
        caller=f"ip:{caller_ip(connection)}",
        limit=Limit(attempts=settings.RATE_LIMIT_EMBED_PER_MINUTE),
    )


async def embed_admission_allowed(connection: HTTPConnection) -> Decision:
    """Whether this address may ask to be admitted to a widget right now.

    Admission, not messages: what a visitor may *say* once admitted is the
    embed's own `rate_limit_per_minute`, counted per visitor inside the socket.
    This is the ceiling on the step before that, which anybody can attempt
    without a valid key at all.

    The widget's `/config` and the socket handshake share this counter, because
    together they are one admission: a browser that fetched a config and did not
    open a socket did not get in. The *script* has its own - see
    `embed_script_allowed`.

    Counted before the key is looked up, which is why it lives here rather than
    inside the admission service: doing the database read first would make an
    unbounded probe for live keys free.
    """
    return await consume(
        surface="embed_admission",
        caller=f"ip:{caller_ip(connection)}",
        limit=Limit(attempts=settings.RATE_LIMIT_EMBED_PER_MINUTE),
    )


async def key_attempt_refused(
    connection: HTTPConnection, token: str, *, count: bool = True
) -> tuple[Decision, str] | None:
    """Why a key is turned away before it is looked up, or `None` to look it up.

    Both limits come before the lookup, so neither a key over its allowance nor
    a flood of made-up ones costs a database query - on a request, a socket
    handshake and the MCP endpoint alike. A key is counted by a digest of the
    whole token, readable without the database - not by its prefix, which
    listings and audit entries show, so knowing it would let anybody spend a real
    key's allowance with made-up tokens. Made-up keys are counted per address
    once refused (:func:`count_refused_key`), and an address over the line is
    turned away here.

    `count=False` checks the key's allowance without spending it: the MCP
    endpoint's tool calls each reach the API with the same key, which counts
    them there, and charging the outer request too halved the allowance.
    """
    address = f"ip:{caller_ip(connection)}"
    if await exhausted(surface="api_key_refused", caller=address, limit=auth_limit()):
        return (
            Decision(allowed=False, retry_after_seconds=60),
            "Too many requests with invalid API keys. Wait and try again.",
        )
    caller = f"key:{hashlib.sha256(token.encode()).hexdigest()}"
    if not count:
        if await exhausted(surface="api_key", caller=caller, limit=api_key_limit()):
            return (
                Decision(allowed=False, retry_after_seconds=60),
                "Too many requests with this API key. Wait and try again.",
            )
        return None
    decision = await consume(surface="api_key", caller=caller, limit=api_key_limit())
    if not decision.allowed:
        return decision, "Too many requests with this API key. Wait and try again."
    return None


async def count_refused_key(connection: HTTPConnection) -> None:
    """Count a key that failed its lookup against the address that presented it."""
    await consume(
        surface="api_key_refused",
        caller=f"ip:{caller_ip(connection)}",
        limit=auth_limit(),
    )
