"""The authorization server behind the platform's MCP server (#2059).

OAuth 2.1 with PKCE, public clients only: an MCP client registers itself, sends
a person to the console to consent, and trades the code for an access token and a
refresh token. The access token is an organization API key under the grant - see
:mod:`app.db.models.oauth` - so this module only decides *who consented to what*;
what a token may do is decided where every key's is.

Codes are single-use and refresh tokens rotate. Presenting a spent one is treated
as theft, the way RFC 9700 asks: the whole grant is revoked, so the copy an
attacker holds and the one the client holds both stop working.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from mcp.server.auth.provider import construct_redirect_uri
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator, record_audit
from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.oauth import (
    OAuthAuthorizationCode,
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthGrant,
    OAuthRefreshToken,
)
from app.repositories import oauth as oauth_repo
from app.repositories import organization as organization_repo
from app.schemas.oauth_server import (
    OAuthConsentAnswer,
    OAuthConsentRead,
    OAuthGrantList,
    OAuthGrantRead,
)
from app.services.api_key import ApiKeyService

ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
REFRESH_TOKEN_LIFETIME = timedelta(days=30)
CODE_LIFETIME = timedelta(minutes=10)
REQUEST_LIFETIME = timedelta(minutes=10)
UNCLAIMED_CLIENT_LIFETIME = timedelta(days=1)
"""How long a self-registered client may sit without anybody signing in with it."""

CONSENT_PATH = "/oauth/consent"
"""The console page a person consents on, under `FRONTEND_URL`."""


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _with_query(uri: str, **params: str | None) -> str:
    return construct_redirect_uri(uri, **params)


def client_name(client: OAuthClient) -> str:
    name = client.info.get("client_name")
    return str(name) if name else client.client_id


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    scopes: list[str]


@dataclass(frozen=True)
class CodeGrant:
    """A presented authorization code, with the grant it binds."""

    grant: OAuthGrant
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    resource: str | None
    expires_at: datetime


@dataclass(frozen=True)
class RefreshGrant:
    grant: OAuthGrant
    scopes: list[str]
    expires_at: datetime


class OAuthServerService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register(self, client_id: str, info: dict[str, Any]) -> None:
        """Record a client that registered itself, sweeping the ones nobody signed in with.

        Registration needs no credential, which is what lets Claude Code connect
        unaided - and what lets anyone create rows. The forwarder limits how fast
        one address may register; this bounds how long an unused client stays.
        """
        await oauth_repo.delete_unclaimed_clients(
            self.db, before=datetime.now(UTC) - UNCLAIMED_CLIENT_LIFETIME
        )
        await oauth_repo.create_client(self.db, client_id=client_id, info=info)

    async def client(self, client_id: str) -> OAuthClient | None:
        return await oauth_repo.get_client(self.db, client_id)

    async def start(self, client_id: str, params: dict[str, Any]) -> str:
        """Hold an `/authorize` request for consent; the URL of the consent page."""
        now = datetime.now(UTC)
        await oauth_repo.delete_expired_requests(self.db, before=now)
        request = await oauth_repo.create_request(
            self.db, client_id=client_id, params=params, expires_at=now + REQUEST_LIFETIME
        )
        return f"{settings.FRONTEND_URL.rstrip('/')}{CONSENT_PATH}?request={request.id}"

    async def _pending(self, request_id: UUID) -> tuple[OAuthAuthorizationRequest, OAuthClient]:
        request = await oauth_repo.get_request(self.db, request_id)
        client = await oauth_repo.get_client(self.db, request.client_id) if request else None
        if request is None or client is None or request.expires_at <= datetime.now(UTC):
            raise NotFoundError(
                message="This authorization request has expired. Start the connection again.",
                details={"request_id": request_id},
            )
        return request, client

    @staticmethod
    def _refuse_impersonation() -> None:
        # Consenting hands an application the person's authority; an administrator
        # acting as somebody must not be able to do that on their behalf (#1438).
        if current_impersonator() is not None:
            raise AuthorizationError(
                message="An application cannot be authorized while impersonating"
            )

    async def describe(self, ctx: AuthContext, request_id: UUID) -> OAuthConsentRead:
        """What the consent page shows, for the person and organization signed in."""
        self._refuse_impersonation()
        request, client = await self._pending(request_id)
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        return OAuthConsentRead(
            request_id=request.id,
            client_name=client_name(client),
            client_uri=client.info.get("client_uri"),
            redirect_host=urlparse(str(request.params["redirect_uri"])).netloc
            or str(request.params["redirect_uri"]),
            organization_id=ctx.organization_id,
            organization_name=organization.name if organization else "",
            catalog=ApiKeyService(self.db).scope_catalog(ctx),
        )

    async def approve(
        self, ctx: AuthContext, request_id: UUID, scopes: list[Perm]
    ) -> OAuthConsentAnswer:
        """Grant the client the chosen permissions, as the caller, in their organization.

        Raises:
            BadRequestError: A permission the caller does not hold, named on the field.
        """
        self._refuse_impersonation()
        request, client = await self._pending(request_id)
        grantable = set(ApiKeyService(self.db).scope_catalog(ctx).scopes)
        refused = sorted(scope.value for scope in scopes if scope.value not in grantable)
        if refused:
            raise refused_field(
                "scopes", f"You cannot grant what you do not hold: {', '.join(refused)}"
            )
        now = datetime.now(UTC)
        grant = await oauth_repo.create_grant(
            self.db,
            client_id=client.client_id,
            user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            scopes=sorted({scope.value for scope in scopes}),
        )
        code = secrets.token_urlsafe(32)
        params = request.params
        await oauth_repo.create_code(
            self.db,
            code_hash=digest(code),
            grant_id=grant.id,
            code_challenge=str(params["code_challenge"]),
            redirect_uri=str(params["redirect_uri"]),
            redirect_uri_provided_explicitly=bool(params["redirect_uri_provided_explicitly"]),
            resource=params.get("resource"),
            expires_at=now + CODE_LIFETIME,
        )
        await oauth_repo.delete_request(self.db, request)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="oauth.grant_created",
            target_type="oauth_grant",
            target_id=str(grant.id),
            details={
                "client_id": client.client_id,
                "client_name": client_name(client),
                "scopes": grant.scopes,
            },
        )
        return OAuthConsentAnswer(
            redirect_to=_with_query(
                str(params["redirect_uri"]), code=code, state=params.get("state")
            )
        )

    async def deny(self, request_id: UUID) -> OAuthConsentAnswer:
        """Turn the client away; it is told `access_denied`."""
        request, _client = await self._pending(request_id)
        params = request.params
        await oauth_repo.delete_request(self.db, request)
        return OAuthConsentAnswer(
            redirect_to=_with_query(
                str(params["redirect_uri"]), error="access_denied", state=params.get("state")
            )
        )

    async def _live_grant(self, grant_id: UUID) -> OAuthGrant | None:
        grant = await oauth_repo.get_grant(self.db, grant_id)
        return grant if grant is not None and grant.revoked_at is None else None

    async def _revoke(self, grant: OAuthGrant, *, reason: str) -> None:
        await oauth_repo.revoke_grant(self.db, grant, at=datetime.now(UTC))
        await record_audit(
            self.db,
            actor_user_id=None,
            organization_id=grant.organization_id,
            action="oauth.grant_revoked",
            target_type="oauth_grant",
            target_id=str(grant.id),
            details={"client_id": grant.client_id, "reason": reason},
        )

    async def code(self, client_id: str, code: str) -> CodeGrant | None:
        """The grant a code stands for - or `None`, revoking the grant if it was spent."""
        found = await oauth_repo.get_code(self.db, digest(code))
        if found is None:
            return None
        row, grant = found
        if grant.revoked_at is not None or grant.client_id != client_id:
            return None
        if row.used_at is not None:
            await self._revoke(grant, reason="authorization code reused")
            return None
        return CodeGrant(
            grant=grant,
            code_challenge=row.code_challenge,
            redirect_uri=row.redirect_uri,
            redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
            resource=row.resource,
            expires_at=row.expires_at,
        )

    async def exchange_code(self, client: OAuthClient, code: str) -> IssuedTokens:
        """Spend a code; the first access and refresh tokens of its grant."""
        found = await oauth_repo.get_code(self.db, digest(code))
        if found is None:
            raise NotFoundError(message="Unknown authorization code")
        row, grant = found
        await self._spend(client, row, grant, what="authorization code")
        return await self._issue(client, grant, list(grant.scopes))

    async def refresh(self, client_id: str, token: str) -> RefreshGrant | None:
        """What a refresh token may renew - or `None`, revoking the grant if it was spent."""
        found = await oauth_repo.get_refresh_token(self.db, digest(token))
        if found is None:
            return None
        row, grant = found
        if grant.revoked_at is not None or grant.client_id != client_id:
            return None
        if row.used_at is not None:
            await self._revoke(grant, reason="refresh token reused")
            return None
        return RefreshGrant(grant=grant, scopes=list(row.scopes), expires_at=row.expires_at)

    async def exchange_refresh(
        self, client: OAuthClient, token: str, scopes: list[str]
    ) -> IssuedTokens:
        """Rotate a refresh token: spend it, issue a new pair, at most its scopes."""
        found = await oauth_repo.get_refresh_token(self.db, digest(token))
        if found is None:
            raise NotFoundError(message="Unknown refresh token")
        row, grant = found
        await self._spend(client, row, grant, what="refresh token")
        return await self._issue(client, grant, [scope for scope in scopes if scope in row.scopes])

    async def _spend(
        self,
        client: OAuthClient,
        row: OAuthAuthorizationCode | OAuthRefreshToken,
        grant: OAuthGrant,
        *,
        what: str,
    ) -> None:
        """Check the token is still good and spend it, in the exchange that issues.

        FastMCP loads a token before exchanging it, and anything can happen
        between the two - a disconnect revokes the grant, a second request
        presents the same token - so the checks are made again here and the
        spend is atomic. Losing the race is a reuse, answered like one: the grant
        and every token it issued are revoked.

        Raises:
            BadRequestError: Revoked, another client's, expired, or already spent.
        """
        now = datetime.now(UTC)
        if (
            grant.revoked_at is not None
            or grant.client_id != client.client_id
            or row.expires_at <= now
        ):
            raise BadRequestError(message=f"This {what} is no longer valid")
        spent = (
            await oauth_repo.consume_code(self.db, row, now)
            if isinstance(row, OAuthAuthorizationCode)
            else await oauth_repo.consume_refresh_token(self.db, row, now)
        )
        if not spent:
            await self._revoke(grant, reason=f"{what} reused")
            raise BadRequestError(message=f"This {what} was already used")

    async def _issue(
        self, client: OAuthClient, grant: OAuthGrant, scopes: list[str]
    ) -> IssuedTokens:
        now = datetime.now(UTC)
        access = await ApiKeyService(self.db).issue_for_grant(
            grant_id=grant.id,
            organization_id=grant.organization_id,
            user_id=grant.user_id,
            client_name=client_name(client),
            scopes=scopes,
            expires_at=now + ACCESS_TOKEN_LIFETIME,
        )
        refresh = secrets.token_urlsafe(32)
        await oauth_repo.create_refresh_token(
            self.db,
            token_hash=digest(refresh),
            grant_id=grant.id,
            scopes=scopes,
            expires_at=now + REFRESH_TOKEN_LIFETIME,
        )
        return IssuedTokens(access_token=access, refresh_token=refresh, scopes=scopes)

    async def revoke_token(self, grant_id: UUID) -> None:
        """RFC 7009: revoking either token of a grant revokes the grant."""
        grant = await self._live_grant(grant_id)
        if grant is not None:
            await self._revoke(grant, reason="revoked by the client")

    async def list_grants(self, ctx: AuthContext) -> OAuthGrantList:
        """Applications connected in this organization: everybody's with
        `api_keys:manage`, otherwise the caller's own."""
        mine_only = None if ctx.has(Perm.API_KEYS_MANAGE) else ctx.subject_id
        rows = await oauth_repo.list_grants(
            self.db, organization_id=ctx.organization_id, user_id=mine_only
        )
        items = [
            OAuthGrantRead(
                id=grant.id,
                client_name=client_name(client),
                client_uri=client.info.get("client_uri"),
                user_id=grant.user_id,
                user_email=email,
                scopes=list(grant.scopes),
                created_at=grant.created_at,
            )
            for grant, client, email in rows
        ]
        return OAuthGrantList(items=items, total=len(items))

    async def disconnect(self, ctx: AuthContext, grant_id: UUID) -> None:
        """Revoke an application's access - one's own, or anybody's with `api_keys:manage`.

        Raises:
            NotFoundError: Not this organization's, or somebody else's without the
                permission - the same answer.
        """
        grant = await oauth_repo.get_grant_in_org(
            self.db, grant_id, organization_id=ctx.organization_id
        )
        if (
            grant is None
            or grant.revoked_at is not None
            or (grant.user_id != ctx.subject_id and not ctx.has(Perm.API_KEYS_MANAGE))
        ):
            raise NotFoundError(
                message="Connected application not found", details={"grant_id": grant_id}
            )
        await oauth_repo.revoke_grant(self.db, grant, at=datetime.now(UTC))
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="oauth.grant_revoked",
            target_type="oauth_grant",
            target_id=str(grant.id),
            details={"client_id": grant.client_id, "reason": "disconnected"},
        )
