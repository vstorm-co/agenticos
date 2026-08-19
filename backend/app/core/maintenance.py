"""A maintenance window this API actually holds shut.

An operator turning maintenance on wants the deployment to stop answering, not
for the console to draw a notice over an API that keeps serving. So the gate is
here, above the routes, and a page a user already has open stops working - which
is the whole difference between a maintenance mode and a banner.

**The allow-list is what keeps it from being a lock-out**, and it is short by
design:

- `/health*` - a readiness probe that fails during a maintenance window is an
  orchestrator restarting the container the operator is trying to work in.
- `/api/v1/branding` - the maintenance page has to be able to say what this
  deployment is called and why it is closed. It is the one route the closed page
  itself depends on.
- `/api/v1/auth/*` - an administrator has to be able to sign in *while* the
  window is open. Turning maintenance on and locking out the only account that
  can turn it off is the failure this whole module has to not have.
- `/api/v1/admin/*` - and then reach the switch.
- The docs and the OpenAPI schema, which serve no data.

Everything else is 503, with a `Retry-After` so a client backs off rather than
hammering.

**What it does not do is check who is asking.** Reading a session would mean
verifying a token in a middleware that sits above the dependency graph, and every
authenticated surface an administrator uses is under `/api/v1/admin` already. A
non-admin reaching `/api/v1/admin` is refused by `CurrentAppAdmin` as it always
was, so widening the path does not widen the authority.

Read straight from the repository rather than through
`DeploymentSettingsService`, which imports this module to publish its own writes:
the gate needs two columns and a cycle for the rest of them is not a trade.

The state is cached in the Redis every worker already shares: the middleware runs
on every request and the settings row changes about once a quarter. It is written
eagerly when an administrator saves - so the switch is immediate - and carries a
TTL as well, so a write that never reached Redis heals on its own instead of
leaving the deployment open during a window somebody scheduled.
"""

from __future__ import annotations

import json
import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.clients.redis import RedisClient
from app.db.session import get_db_context
from app.repositories import deployment_settings_repo

logger = logging.getLogger(__name__)

CACHE_KEY = "deployment:maintenance"

CACHE_TTL_SECONDS = 30
"""How long a cached verdict stands without being re-read.

Short enough that a failed cache write costs half a minute of a window nobody is
in yet, long enough that the middleware is not a query per request. The eager
write on save is what makes the switch feel immediate; this is only the net
under it.
"""

RETRY_AFTER_SECONDS = 120

_ALLOWED_PREFIXES = (
    "/health",
    "/api/v1/health",
    "/api/v1/branding",
    "/api/v1/auth/",
    "/api/v1/admin/",
    "/docs",
    "/redoc",
    "/openapi.json",
)

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`.

    Called by the lifespan beside where the client is created, for
    `rate_limit.configure`'s reason: the cache is only as wide as the Redis every
    worker already shares, and a second pool to the same server is one more thing
    shutdown has to know about.
    """
    global _redis
    _redis = redis


async def publish(*, on: bool, message: str | None) -> None:
    """Push the current verdict into the cache, so a saved change takes effect now.

    Best-effort by construction: the database is the truth and this is derived, so
    a Redis that is down must not fail the administrator's save. What it costs is
    bounded by `CACHE_TTL_SECONDS`, which is why there is a TTL at all.
    """
    if _redis is None:
        return
    try:
        await _redis.set(
            CACHE_KEY, json.dumps({"on": on, "message": message}), ttl=CACHE_TTL_SECONDS
        )
    except Exception:
        logger.exception("maintenance_cache_write_failed")


async def _verdict() -> tuple[bool, str | None]:
    """Whether the deployment is closed, and what it says about it.

    Reads through to the database on a cache miss and writes what it found. With no
    Redis configured - a test client, a process that never ran the lifespan - it
    reads the row every time, which is correct and slower rather than a second
    behaviour.
    """
    if _redis is not None:
        try:
            cached = await _redis.get(CACHE_KEY)
        except Exception:
            logger.exception("maintenance_cache_read_failed")
            cached = None
        if cached is not None:
            state = json.loads(cached)
            return bool(state["on"]), state["message"]

    async with get_db_context() as db:
        row = await deployment_settings_repo.get(db)
    closed = bool(row and row.maintenance_mode)
    message = row.maintenance_message if row else None
    await publish(on=closed, message=message)
    return closed, message


class MaintenanceModeMiddleware:
    """Refuse everything outside the allow-list while a window is open.

    Pure ASGI, matching `BodySizeLimitMiddleware`: `BaseHTTPMiddleware` wraps the
    receive channel in a task to hand the request on, and there is no reason to
    buffer a body that is about to be refused.

    The refusal is the API's own error envelope, because a client parsing our
    errors should not have to know which layer produced one - and it is built here
    rather than raised, since a middleware sits above the exception handlers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path.startswith(_ALLOWED_PREFIXES):
            await self.app(scope, receive, send)
            return

        try:
            closed, message = await _verdict()
        except Exception:
            # A gate that cannot read its own switch must not close the API. The
            # alternative - failing shut - turns a Redis blip or a migration that
            # has not run yet into a total outage nobody asked for.
            logger.exception("maintenance_check_failed")
            await self.app(scope, receive, send)
            return

        if not closed:
            await self.app(scope, receive, send)
            return

        response = JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "MAINTENANCE_MODE",
                    "message": message or "This deployment is under maintenance.",
                    "details": {},
                }
            },
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        )
        await response(scope, receive, send)
