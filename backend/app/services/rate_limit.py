"""How often one caller may reach a public surface.

Three of this platform's surfaces are reachable without a session: the public
run API, the widget's config endpoint and the widget's socket. Between them and
somebody else's model budget there was, until #39, nothing at all - a limiter
was constructed in `app/core/rate_limit.py`, registered on the app, and used by
no route, while a second Redis-backed one sat unimported in
`app/services/rate_limit/` and could not have been imported anyway: it read
`get_redis` from a module that does not define one.

What replaced both is this module, and the shape is deliberately
`app/services/channels/dedupe.py`:

*The count is in the deployment's shared Redis, never in this process.*
Production runs `uvicorn --workers 4`, so a per-process counter lets through
four times what it says it does - and a limit that is wrong by the worker count
is worse than no limit, because it reads as one that holds. The channel
router's own `_rate_buckets` is per-process and is not a model to follow here,
which that module already says.

*A fixed window, not a rolling one.* `INCR` plus an `EXPIRE … NX`, two
commands, and a caller who arrives at the end of one window and again at the
start of the next gets up to twice the allowance across that boundary. That is
the honest cost of the simplest correct thing, and it is acceptable for what
these limits are: a ceiling on how fast a stranger may open sockets and spend
somebody's money, not a traffic shaper.

*It fails open, loudly.* A Redis nobody can reach means the limit is not
applied and a warning is logged. Refusing a visitor their answer because a
cache blipped is the worse failure of the two, and it is the same trade-off,
for the same reason, as the deduplication claim.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from starlette.requests import HTTPConnection

from app.clients.redis import RedisClient
from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: RedisClient | None = None


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
    """Whether this attempt is allowed, and when to try again if not."""

    allowed: bool
    retry_after_seconds: int


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

    Works for a WebSocket as well as a request: both are `HTTPConnection`, and
    the socket handshake needs the same answer.
    """
    if settings.RATE_LIMIT_TRUST_FORWARDED_FOR:
        forwarded = connection.headers.get("x-forwarded-for")
        if forwarded:
            # The leftmost hop is the original client; everything after it is
            # the chain of proxies that carried the request.
            return forwarded.split(",")[0].strip()
    return connection.client.host if connection.client else "unknown"


async def consume(*, surface: str, caller: str, limit: Limit) -> Decision:
    """Count one attempt by `caller` against `surface`, and say whether it may.

    Allowed when the limiter cannot count - see the module docstring. The log
    line is the only thing that distinguishes "under the limit" from "not
    limited at all", so it is a warning rather than a debug.
    """
    if _redis is None:
        logger.warning("Rate limiting not configured - %s reached unmetered by %s", surface, caller)
        return Decision(allowed=True, retry_after_seconds=0)

    key = f"ratelimit:{surface}:{caller}"
    try:
        used = await _redis.count_in_window(key, ttl=limit.window_seconds)
    except Exception:
        logger.warning("rate_limit_redis_unavailable", exc_info=True)
        return Decision(allowed=True, retry_after_seconds=0)

    if used > limit.attempts:
        return Decision(allowed=False, retry_after_seconds=limit.window_seconds)
    return Decision(allowed=True, retry_after_seconds=0)


def run_limit() -> Limit:
    """What one caller may spend the public run API on, per minute."""
    return Limit(attempts=settings.RATE_LIMIT_RUN_PER_MINUTE)


async def embed_admission_allowed(connection: HTTPConnection) -> bool:
    """Whether this address may ask to be admitted to a widget right now.

    Admission, not messages: what a visitor may *say* once admitted is the
    embed's own `rate_limit_per_minute`, counted per visitor inside the socket.
    This is the ceiling on the step before that, which anybody can attempt
    without a valid key at all.

    Counted before the key is looked up, which is why it lives here rather than
    inside the admission service: doing the database read first would make an
    unbounded probe for live keys free.
    """
    decision = await consume(
        surface="embed_admission",
        caller=f"ip:{caller_ip(connection)}",
        limit=Limit(attempts=settings.RATE_LIMIT_EMBED_PER_MINUTE),
    )
    return decision.allowed
