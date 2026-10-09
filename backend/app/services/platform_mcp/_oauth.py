"""The MCP SDK's authorization-server protocol, answered by :mod:`app.services.oauth_server`.

The SDK owns the wire - metadata, registration, `/authorize` validation, PKCE and
redirect checks at `/token`, revocation - and calls these methods for every
decision that needs the database. Each opens a session of its own: they run
outside any FastAPI request.

Bearer verification lives here too, because the SDK takes one or the other: an
organization API key and an OAuth access token are both `aos_` keys, so
`load_access_token` admits either.
"""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import datetime
from uuid import UUID

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from app.core.exceptions import AppException, AuthenticationError
from app.db.session import get_db_context
from app.repositories import api_key as api_key_repo
from app.repositories import oauth as oauth_repo
from app.services.api_key import ApiKeyService, is_api_key
from app.services.oauth_server import (
    ACCESS_TOKEN_LIFETIME,
    IssuedTokens,
    OAuthServerService,
)


class PlatformCode(AuthorizationCode):
    grant_id: UUID


class PlatformRefreshToken(RefreshToken):
    grant_id: UUID


class PlatformAccessToken(AccessToken):
    grant_id: UUID | None = None


def _epoch(at: datetime) -> int:
    return int(at.timestamp())


def _token(issued: IssuedTokens) -> OAuthToken:
    return OAuthToken(
        access_token=issued.access_token,
        expires_in=int(ACCESS_TOKEN_LIFETIME.total_seconds()),
        scope=" ".join(issued.scopes),
        refresh_token=issued.refresh_token,
    )


async def _attempt(exchange: Awaitable[IssuedTokens]) -> IssuedTokens | TokenError:
    """The tokens an exchange issued, or the `TokenError` to answer with.

    Returned rather than raised: `TokenError` is a frozen dataclass, and raised
    inside the session's context manager it reaches `__aexit__`, which assigns its
    traceback - a `FrozenInstanceError`, and a 500 where the client was owed an
    `invalid_grant`. It is raised once the session has closed, by :func:`_answer`.
    """
    try:
        return await exchange
    except AppException as exc:
        return TokenError(error="invalid_grant", error_description=exc.message)


def _answer(issued: IssuedTokens | TokenError) -> OAuthToken:
    if isinstance(issued, TokenError):
        raise issued
    return _token(issued)


class PlatformOAuthProvider(
    OAuthAuthorizationServerProvider[PlatformCode, PlatformRefreshToken, PlatformAccessToken]
):
    """Subclassed rather than matched structurally, for the protocol's own default of
    refusing the identity-assertion grant (SEP-990), which this server does not offer."""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with get_db_context() as db:
            row = await OAuthServerService(db).client(client_id)
        return OAuthClientInformationFull.model_validate(row.info) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Register a public client: PKCE, and no secret to keep.

        A client asking for a secret is assigned `none` instead, which RFC 7591
        §3.2.1 allows - the response it receives says so. Not issuing secrets means
        there is no client credential at rest to protect.
        """
        client_info.token_endpoint_auth_method = "none"
        client_info.client_secret = None
        client_info.client_secret_expires_at = None
        async with get_db_context() as db:
            await OAuthServerService(db).register(
                client_info.client_id, client_info.model_dump(mode="json", exclude_none=True)
            )

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        async with get_db_context() as db:
            return await OAuthServerService(db).start(
                client.client_id, params.model_dump(mode="json")
            )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> PlatformCode | None:
        async with get_db_context() as db:
            found = await OAuthServerService(db).code(client.client_id, authorization_code)
        if found is None:
            return None
        return PlatformCode(
            code=authorization_code,
            scopes=list(found.grant.scopes),
            expires_at=found.expires_at.timestamp(),
            client_id=client.client_id,
            code_challenge=found.code_challenge,
            redirect_uri=AnyUrl(found.redirect_uri),
            redirect_uri_provided_explicitly=found.redirect_uri_provided_explicitly,
            resource=found.resource,
            subject=str(found.grant.user_id),
            grant_id=found.grant.id,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: PlatformCode
    ) -> OAuthToken:
        async with get_db_context() as db:
            service = OAuthServerService(db)
            stored = await service.client(client.client_id)
            issued = (
                TokenError(error="invalid_client")
                if stored is None
                else await _attempt(service.exchange_code(stored, authorization_code.code))
            )
        return _answer(issued)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> PlatformRefreshToken | None:
        async with get_db_context() as db:
            found = await OAuthServerService(db).refresh(client.client_id, refresh_token)
        if found is None:
            return None
        return PlatformRefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=found.scopes,
            expires_at=_epoch(found.expires_at),
            subject=str(found.grant.user_id),
            grant_id=found.grant.id,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: PlatformRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        async with get_db_context() as db:
            service = OAuthServerService(db)
            stored = await service.client(client.client_id)
            issued = (
                TokenError(error="invalid_client")
                if stored is None
                else await _attempt(service.exchange_refresh(stored, refresh_token.token, scopes))
            )
        return _answer(issued)

    async def load_access_token(self, token: str) -> PlatformAccessToken | None:
        """Admit an organization API key or an OAuth access token - the same thing here.

        The verdict only opens the MCP request. Each tool call presents the token
        to the public API, which authenticates it again, so revocation takes
        effect on the next call.
        """
        if not is_api_key(token):
            return None
        async with get_db_context() as db:
            try:
                caller = await ApiKeyService(db).authenticate(token)
            except AuthenticationError:
                return None
            row = await api_key_repo.get(
                db, caller.api_key_id, organization_id=caller.organization.id
            )
            grant = (
                await oauth_repo.get_grant(db, row.oauth_grant_id)
                if row is not None and row.oauth_grant_id is not None
                else None
            )
        expires_at = row.expires_at if row is not None else None
        return PlatformAccessToken(
            token=token,
            # The OAuth client a token was issued to - revocation only acts on a
            # token presented by its own client - or the key's prefix for a key a
            # person pasted, which no client may revoke through OAuth.
            client_id=grant.client_id if grant is not None else caller.prefix,
            scopes=sorted(scope.value for scope in caller.context.key_scopes or ()),
            expires_at=_epoch(expires_at) if expires_at else None,
            subject=str(caller.user.id),
            grant_id=row.oauth_grant_id if row is not None else None,
        )

    async def revoke_token(self, token: PlatformAccessToken | PlatformRefreshToken) -> None:
        """Revoke the grant behind either token; a person's own key is not revoked here."""
        if token.grant_id is None:
            return
        async with get_db_context() as db:
            await OAuthServerService(db).revoke_token(token.grant_id)
