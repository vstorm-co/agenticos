"""The platform's own MCP server, at `/mcp` (#2058), built on FastMCP.

Claude Code or any MCP client operates AgenticOS through a curated set of tools,
and the in-app assistant is handed the same ones. Each is a call to the public
API made in-process with the caller's own token, so an MCP caller can do exactly
what that token can do over HTTP and nothing more.

FastMCP serves the protocol over streamable HTTP and the OAuth 2.1 endpoints
around it; :mod:`._oauth` answers its authorization-server decisions from the
database.
"""

from __future__ import annotations

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
from starlette.types import ASGIApp, Receive, Scope, Send

from app.services import rate_limit
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
        server.tool(tool.function, annotations=_WRITE if tool.writes else _READ)
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
async def serve_platform_mcp(app: ASGIApp, state: object) -> AsyncGenerator[None, None]:
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


class _Forward:
    """The ASGI endpoint for :data:`ROUTE_PATHS`: hand the request to the running server.

    A class, not a function: Starlette wraps a plain function as a request handler,
    and this has to pass the raw ASGI call through - streaming and all.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["path"] == REGISTER_PATH and scope.get("method") == "POST":
            decision = await rate_limit.consume(
                surface="oauth_register",
                caller=f"ip:{rate_limit.caller_ip(HTTPConnection(scope))}",
                limit=rate_limit.auth_limit(),
            )
            if not decision.allowed:
                # RFC 6749's error shape, which is what a registering client parses.
                refused = JSONResponse(
                    {
                        "error": "temporarily_unavailable",
                        "error_description": "Too many registrations. Try again shortly.",
                    },
                    status_code=429,
                    headers={"Retry-After": str(decision.retry_after_seconds)},
                )
                await refused(scope, receive, send)
                return
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


forward = _Forward()


__all__ = [
    "MCP_PATH",
    "ROUTE_PATHS",
    "PlatformApi",
    "PlatformTool",
    "build_platform_mcp",
    "forward",
    "platform_tools",
    "serve_platform_mcp",
]
