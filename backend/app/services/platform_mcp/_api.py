"""The public API, called in-process with the MCP caller's own token.

A tool is a call to a route of the public API rather than a second path into
the services, so it is held to everything a key is held to over HTTP - the
public-route check, the key's scopes and its issuer's current role, resource
grants, budgets, rate limits and the audit trail - and cannot drift from it.
"""

from __future__ import annotations

from typing import Any

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError
from starlette.types import ASGIApp

from app.core.config import settings

_TIMEOUT = httpx.Timeout(300.0, connect=10.0)
"""A run can take minutes; nothing here leaves the process, so connect is instant."""


class PlatformApi:
    def __init__(self, app: ASGIApp) -> None:
        self._transport: httpx.AsyncBaseTransport = httpx.ASGITransport(app=app)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> Any:
        """One public API call as the MCP caller; a refusal becomes a tool error.

        Raises:
            ToolError: The API refused. Its own message is passed through - it is
                written in this repository for whoever made the request.
        """
        token = get_access_token()
        if token is None:
            raise ToolError("This tool needs an authenticated MCP connection")
        async with httpx.AsyncClient(
            transport=self._transport,
            base_url=f"http://agenticos{settings.API_V1_STR}",
            headers={"Authorization": f"Bearer {token.token}"},
            timeout=_TIMEOUT,
        ) as client:
            response = await client.request(method, path, json=json, params=params, files=files)
        if response.status_code == 204:
            return None
        body = response.json()
        if response.is_error:
            error = body.get("error", {}) if isinstance(body, dict) else {}
            raise ToolError(
                f"{response.status_code} {error.get('code', 'ERROR')}: "
                f"{error.get('message', 'The request was refused')}"
            )
        return body
