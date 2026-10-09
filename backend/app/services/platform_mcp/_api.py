"""The public API, called in-process with the caller's own token.

An operation is a call to a route of the public API rather than a second path
into the services, so it is held to everything a key is held to over HTTP - the
public-route check, the key's scopes and its issuer's current role, resource
grants, budgets, rate limits and the audit trail - and cannot drift from it.

Two callers use it: the MCP server, where the token is the one the MCP request
arrived with, and the `platform` capability, where it is a credential minted for
the person the run acts for. They differ in how a refusal is answered, which is
why that is a parameter: an MCP client is sent a tool error, and a model is
handed the refusal as its result.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from starlette.types import ASGIApp

from app.core.config import settings

_TIMEOUT = httpx.Timeout(300.0, connect=10.0)
"""A run can take minutes; nothing here leaves the process, so connect is instant."""

Refusal = Callable[[str], dict[str, Any]]
"""How a refused call is answered: raise, or return what the caller should see."""


class PlatformApi:
    def __init__(
        self, app: ASGIApp, *, token: Callable[[], str | None], on_refusal: Refusal
    ) -> None:
        self._transport: httpx.AsyncBaseTransport = httpx.ASGITransport(app=app)
        self._token = token
        self._on_refusal = on_refusal

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> Any:
        """One public API call as the caller; a refusal goes to `on_refusal`.

        The refusal carries the API's own message - written in this repository,
        for whoever made the request - and its status and code.
        """
        token = self._token()
        if token is None:
            return self._on_refusal("This tool needs an authenticated caller")
        async with httpx.AsyncClient(
            transport=self._transport,
            base_url=f"http://agenticos{settings.API_V1_STR}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT,
        ) as client:
            response = await client.request(method, path, json=json, params=params, files=files)
        if response.status_code == 204:
            return None
        body = response.json()
        if response.is_error:
            error = body.get("error", {}) if isinstance(body, dict) else {}
            return self._on_refusal(
                f"{response.status_code} {error.get('code', 'ERROR')}: "
                f"{error.get('message', 'The request was refused')}"
            )
        return body
