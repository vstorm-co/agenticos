"""The platform's own MCP server, at `/mcp` (#2058), built on FastMCP.

Claude Code or any MCP client operates AgenticOS through a curated set of tools,
and the in-app assistant is handed the same ones. Each is a call to the public
API made in-process with the caller's own token, so an MCP caller can do exactly
what that token can do over HTTP and nothing more.

FastMCP serves the protocol over streamable HTTP and the OAuth 2.1 endpoints
around it; :mod:`._oauth` answers its authorization-server decisions from the
database.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.http import StarletteWithLifespan
from mcp.types import ToolAnnotations
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services import rate_limit
from app.services.api_key import is_api_key
from app.services.platform_mcp._api import PlatformApi
from app.services.platform_mcp._oauth import PlatformOAuthProvider
from app.services.platform_mcp._tools import PlatformTool, platform_tools

MCP_PATH = "/mcp"
REGISTER_PATH = "/register"
"""Dynamic client registration: open to anyone, so limited per address."""

_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)


def _mcp_token() -> str | None:
    """The bearer the MCP request arrived with, which every tool call presents again."""
    token = get_access_token()
    return token.token if token is not None else None


def _tool_error(message: str) -> dict[str, Any]:
    """An MCP client is told a refusal as a tool error, carrying the API's reason."""
    raise ToolError(message)


INSTRUCTIONS = """\
Tools for operating an AgenticOS organization: its agents, runs, knowledge bases,
skills and members. Every call acts as the person who issued the connection's key,
within that key's permissions - a refusal names the permission that was missing.
Start with `whoami` to see the organization and what this connection may do.
"""


def build_platform_mcp(app: ASGIApp) -> tuple[FastMCP, StarletteWithLifespan]:
    """The MCP server, and the ASGI app serving it, calling `app`'s public API."""
    server = FastMCP(
        name="AgenticOS",
        instructions=INSTRUCTIONS,
        auth=PlatformOAuthProvider(),
    )
    api = PlatformApi(app, token=_mcp_token, on_refusal=_tool_error)
    for tool in platform_tools(api):
        # A held read is announced as no read-only tool, which is what holds it
        # for approval under `writes` - see `HELD`.
        server.tool(tool.function, annotations=_WRITE if tool.writes or tool.held else _READ)
    # Stateless, answering in JSON: a tool call is one request and one answer,
    # so any worker of any replica can serve it, with nothing to keep in memory.
    # FastMCP's Host/Origin guard stays off: it protects unauthenticated local
    # servers from DNS rebinding, and every request here carries a bearer token
    # a rebinding page could not attach.
    starlette = server.http_app(
        path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        host_origin_protection=False,
    )
    return server, starlette


ROUTE_PATHS = (
    MCP_PATH,
    f"/.well-known/oauth-protected-resource{MCP_PATH}",
    "/.well-known/oauth-authorization-server",
    "/authorize",
    "/token",
    REGISTER_PATH,
    "/revoke",
)
"""What the MCP app answers, registered on the API app so it is served beside it."""


@asynccontextmanager
async def serve_platform_mcp(app: ASGIApp, state: object) -> AsyncGenerator[None]:
    """Run the MCP server for one lifespan of `app`, reachable through :func:`forward`.

    Built per lifespan rather than once: FastMCP's session manager runs once per
    app, and a process can run the lifespan more than once (a reload, a test).
    """
    _server, starlette = build_platform_mcp(app)
    async with starlette.router.lifespan_context(starlette):
        setattr(state, "platform_mcp", starlette)  # noqa: B010 - Starlette's State is dynamic
        try:
            yield
        finally:
            setattr(state, "platform_mcp", None)  # noqa: B010


_UNAUTHENTICATED_LIMITS: dict[tuple[str, str], tuple[str, str]] = {
    (REGISTER_PATH, "POST"): ("oauth_register", "Too many registrations. Try again shortly."),
    ("/authorize", "GET"): (
        "oauth_authorize",
        "Too many authorization requests. Try again shortly.",
    ),
    ("/authorize", "POST"): (
        "oauth_authorize",
        "Too many authorization requests. Try again shortly.",
    ),
}
"""The OAuth endpoints anyone may call without a credential, each writing a row:
limited per address, beside the per-client bound `start` keeps on requests."""

_TOKEN_PATHS = frozenset({("/token", "POST"), ("/revoke", "POST")})
"""The OAuth endpoints a client presents a code or a token to, each looked up in
the database. A refusal is counted per address and an address over the line is
turned away before the lookup; a client refreshing as it should is never counted."""


class _Forward:
    """The ASGI endpoint for :data:`ROUTE_PATHS`: hand the request to the running server.

    A class, not a function: Starlette wraps a plain function as a request handler,
    and this has to pass the raw ASGI call through - streaming and all.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limited = _UNAUTHENTICATED_LIMITS.get((scope["path"], scope.get("method", "")))
        if limited is not None:
            surface, message = limited
            decision = await rate_limit.consume(
                surface=surface,
                caller=f"ip:{rate_limit.caller_ip(HTTPConnection(scope))}",
                limit=rate_limit.auth_limit(),
            )
            if not decision.allowed:
                # RFC 6749's error shape, which is what an OAuth client parses.
                refused = JSONResponse(
                    {"error": "temporarily_unavailable", "error_description": message},
                    status_code=429,
                    headers={"Retry-After": str(decision.retry_after_seconds)},
                )
                await refused(scope, receive, send)
                return
        if (scope["path"], scope.get("method", "")) in _TOKEN_PATHS:
            connection = HTTPConnection(scope)
            address = f"ip:{rate_limit.caller_ip(connection)}"
            if await rate_limit.exhausted(
                surface="oauth_token_refused", caller=address, limit=rate_limit.auth_limit()
            ):
                refused_token = JSONResponse(
                    {
                        "error": "temporarily_unavailable",
                        "error_description": "Too many refused token requests. Try again shortly.",
                    },
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
                await refused_token(scope, receive, send)
                return
            send = _counting_refusals(
                send, connection, surface="oauth_token_refused", statuses=(400, 401)
            )
        token = _bearer(scope)
        if token is not None and is_api_key(token):
            # The limits a key meets on the API, met before the MCP server opens a
            # database session to look it up; a token it refuses (401) is counted
            # against the address that sent it. The key's own allowance is read,
            # not spent: each tool call is counted where it reaches the API.
            connection = HTTPConnection(scope)
            refused = await rate_limit.key_attempt_refused(connection, token, count=False)
            if refused is not None:
                decision, message = refused
                response = JSONResponse(
                    {"error": "temporarily_unavailable", "error_description": message},
                    status_code=429,
                    headers={"Retry-After": str(decision.retry_after_seconds)},
                )
                await response(scope, receive, send)
                return
            send = _counting_refusals(send, connection, surface="api_key_refused", statuses=(401,))
        starlette = getattr(scope["app"].state, "platform_mcp", None)
        if starlette is None:
            response = JSONResponse(
                {
                    "error": {
                        "code": "SERVICE_UNAVAILABLE",
                        "message": "The MCP server is not running",
                    }
                },
                status_code=503,
            )
            await response(scope, receive, send)
            return
        await starlette(scope, receive, send)


def _bearer(scope: Scope) -> str | None:
    """The bearer token a request carries, if it carries one."""
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            return token.strip() if scheme.lower() == "bearer" else None
    return None


def _counting_refusals(
    send: Send, connection: HTTPConnection, *, surface: str, statuses: tuple[int, ...]
) -> Send:
    """`send`, counting a refused credential against its address.

    `statuses` are what a refusal is answered with there: a bearer the MCP server
    does not accept is a 401; OAuth answers a bad code or token with a 400
    (`invalid_grant`) and an unknown client with a 401.
    """

    async def counted(message: Message) -> None:
        if message["type"] == "http.response.start" and message["status"] in statuses:
            await rate_limit.consume(
                surface=surface,
                caller=f"ip:{rate_limit.caller_ip(connection)}",
                limit=rate_limit.auth_limit(),
            )
        await send(message)

    return counted


forward = _Forward()


async def _unreachable(scope: Scope, receive: Receive, send: Send) -> None:
    raise RuntimeError("The tool catalog is read for its descriptions; nothing is called")


def platform_tool_catalog() -> tuple[PlatformTool, ...]:
    """Every tool the platform's server offers, for the Builder to list beside a binding.

    Read off the same definitions `/mcp` serves - names, first lines and which
    ones change something - so the list a person picks from is the list a run
    reaches. Bound to an API that cannot be called, because describing a tool
    must never be a way to run one.
    """
    return platform_tools(PlatformApi(_unreachable, token=lambda: None, on_refusal=_tool_error))


__all__ = [
    "MCP_PATH",
    "ROUTE_PATHS",
    "PlatformApi",
    "PlatformTool",
    "build_platform_mcp",
    "forward",
    "platform_tool_catalog",
    "platform_tools",
    "serve_platform_mcp",
]
