"""The platform's own MCP server, at `/mcp` (#2058).

Claude Code or any MCP client - and, through the same door, the in-app
assistant - operates AgenticOS through a curated set of tools. Each one is a call
to the public API made in-process with the caller's own token, so an MCP caller
can do exactly what that token can do over HTTP and nothing more.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.services.platform_mcp._api import PlatformApi
from app.services.platform_mcp._oauth import PlatformOAuthProvider
from app.services.platform_mcp._tools import PlatformTool, platform_tools

MCP_PATH = "/mcp"

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


def build_platform_mcp(app: ASGIApp) -> tuple[MCPServer, Starlette]:
    """The MCP server, and the ASGI app serving it, calling `app`'s public API."""
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    server = MCPServer(
        name="agenticos",
        title="AgenticOS",
        instructions=INSTRUCTIONS,
        auth_server_provider=PlatformOAuthProvider(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(base),
            resource_server_url=AnyHttpUrl(f"{base}{MCP_PATH}"),
            # A key pasted into a client is not issued for an audience, so there is
            # no resource on it to compare; the public API decides instead.
            validate_token_resource=False,
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
        ),
    )
    api = PlatformApi(app, token=_mcp_token, on_refusal=_tool_error)
    for tool in platform_tools(api):
        server.add_tool(tool.function, annotations=_WRITE if tool.writes else _READ)
    # Stateless, answering in JSON: a tool call is one request and one answer,
    # so any worker of any replica can serve it, with nothing to keep in memory.
    # The host is not localhost, so the SDK's DNS-rebinding guard stays off - it
    # protects unauthenticated local servers, and every request here carries a
    # bearer token a rebinding page could not attach.
    starlette = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        host="0.0.0.0",  # noqa: S104 - see above; this binds nothing
    )
    return server, starlette


ROUTE_PATHS = (
    MCP_PATH,
    f"/.well-known/oauth-protected-resource{MCP_PATH}",
    "/.well-known/oauth-authorization-server",
    "/authorize",
    "/token",
    "/register",
    "/revoke",
)
"""What the MCP app answers, registered on the API app so it is served beside it."""


@asynccontextmanager
async def serve_platform_mcp(app: ASGIApp, state: object) -> AsyncGenerator[None, None]:
    """Run the MCP server for one lifespan of `app`, reachable through :func:`forward`.

    Built per lifespan rather than once: its session manager runs once per
    instance, and a process can run the lifespan more than once (a reload, a test).
    """
    server, starlette = build_platform_mcp(app)
    async with server.session_manager.run():
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
