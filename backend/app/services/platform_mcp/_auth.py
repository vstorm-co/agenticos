"""Who an MCP request is: the bearer token, checked the way the HTTP API checks it."""

from __future__ import annotations

from mcp.server.auth.provider import AccessToken

from app.core.exceptions import AuthenticationError
from app.db.session import get_db_context
from app.services.api_key import ApiKeyService, is_api_key


class PlatformTokenVerifier:
    """Accept an organization API key; anything else is refused with a 401.

    The verdict here only admits the connection. Every tool call then sends the
    same token to the public API, which authenticates it again - so a key revoked
    mid-session stops working on the next call, not the next connection.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        if not is_api_key(token):
            return None
        async with get_db_context() as db:
            try:
                caller = await ApiKeyService(db).authenticate(token)
            except AuthenticationError:
                return None
        scopes = sorted(scope.value for scope in caller.context.key_scopes or ())
        return AccessToken(
            token=token,
            client_id=caller.prefix,
            scopes=scopes,
            subject=str(caller.user.id),
        )
