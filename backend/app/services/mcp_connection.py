"""Business logic for MCP server connections, personal and organization-wide.

A connection is a row pointing at a remote MCP server (streamable HTTP or SSE,
inferred from the URL). Two kinds share this service because they share almost
everything - URL validation, the probe, toolset building - and differ in exactly
two places, both of which are the point:

*Who owns it.* A personal connection (Settings → Your connections) is scoped to
one member and reached only by their own assistant. An organization connection
is scoped to the organization, gated on `connections:manage`, and is the only
kind an agent spec may bind - a published agent that answered differently
depending on whose session ran it could not be reviewed or reasoned about.

*Who its credential is sealed for.* Both go through :mod:`app.core.vault`; what
differs is the scope the envelope is bound to. An organization token is bound to
the organization, so a ciphertext lifted into another tenant's row fails to
unwrap. A personal one is bound to the *member* - not to an organization,
because a personal connection has none and its owner may belong to several, so
binding it to whichever was active when they added it would make the token
unreadable the moment they switched. Neither is encrypted with a deployment-wide
key any more; that gave a ciphertext no owner at all.

The service also owns SSRF validation of submitted URLs (same policy as
webhooks), the connectivity test that discovers a server's tools, and building
per-turn agent toolsets - either from the user's own enabled connections (the
general assistant) or from the organization-scoped ones a published agent's
spec names.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from mcp.shared.auth import OAuthToken
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import mcp_oauth
from app.agents.mcp import (
    McpServerSpec,
    McpToolInfo,
    build_mcp_toolsets,
    probe_error_message,
    probe_mcp_server,
    validate_mcp_url,
)
from app.agents.mcp_oauth import McpOAuthPayload, OAuthError
from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.core.sanitize import UrlRefusedError
from app.core.vault import SealedSecret, VaultScope, seal, unseal
from app.db.models.mcp_connection import McpConnection
from app.db.updates import writable
from app.repositories import mcp_connection_repo
from app.schemas.mcp_connection import (
    McpConnectionCreate,
    McpConnectionUpdate,
    OrgMcpConnectionCreate,
    OrgMcpConnectionUpdate,
)
from app.services.mcp_catalog import get_entry

logger = logging.getLogger(__name__)


def _oauth_redirect_uri() -> str:
    """Where the provider sends the user back - a Next route that forwards the
    code + state to our (state-authenticated) callback endpoint."""
    return f"{settings.FRONTEND_URL.rstrip('/')}/api/me/mcp-connections/oauth/callback"


def _now_epoch() -> float:
    return datetime.now(UTC).timestamp()


async def _checked_url(url: str) -> str:
    """SSRF-check a submitted URL, refusing it as a 400 rather than a crash.

    `validate_mcp_url` raises `SSRFBlockedError`, which subclasses `ValueError`
    and which no handler in `app/api/exception_handlers.py` maps - so pasting a
    `localhost` server URL into the connection dialog answered 500 "An
    unexpected error occurred" with `details: null`, and left a traceback in the
    log, for a guard doing exactly what it is there for. The operator who could
    have fixed it in five seconds was told the platform had broken (#861).

    `details` names the field rather than repeating the address, and the reason
    is the validator's own message, which names a host and never a URL - a URL
    carries a key in its query string (#840).

    Which is why this catches `UrlRefusedError` and not `ValueError`. Only the
    narrower type is a refusal *written here* and so safe to quote; a bare
    `ValueError` escaping the validator is the standard library talking about
    the caller's own text - `Port could not be cast to integer value as
    'client_secret=...'` - and quoting that would put a query-string secret in
    the response body. Nothing below the validator can raise one today, so there
    is no second branch to answer with a controlled sentence: if that changes,
    it is a bug and the generic 500 is the honest answer, since the traceback
    goes to the log and the body stays empty. `tests/test_ssrf.py` fails on a
    refusal that is not a `UrlRefusedError`.

    Raises:
        BadRequestError: If the URL is malformed or points inside the
            deployment's network.
    """
    try:
        return await validate_mcp_url(url)
    except UrlRefusedError as exc:
        # Ours to quote, in the log as much as in the body - see the docstring.
        logger.warning("MCP server URL refused: %s", exc)
        raise refused_field("url", f"This MCP server URL cannot be used: {exc}") from exc


def _apply_token(payload: McpOAuthPayload, token: OAuthToken) -> McpOAuthPayload:
    """Fold a fresh token grant/refresh into the stored payload."""
    return payload.model_copy(
        update={
            "access_token": token.access_token,
            # A refresh response may omit refresh_token - keep the existing one.
            "refresh_token": token.refresh_token or payload.refresh_token,
            "expires_at": (_now_epoch() + token.expires_in) if token.expires_in else None,
            "scope": token.scope or payload.scope,
            "code_verifier": None,
        }
    )


def connection_scope(connection: McpConnection) -> VaultScope:
    """Whose envelope this connection's secrets are sealed under.

    Raises:
        BadRequestError: If the row has no owner for its scope. Both cases are
            forbidden by a check constraint and impossible through the API, so
            the only way to reach either is corrupted data - which must fail
            rather than quietly fall through to the other scope and report
            "wrong master key" about a row that was never sealed with it.
    """
    if connection.scope == "org":
        if connection.organization_id is None:
            raise BadRequestError(message="Organization-scoped connection has no organization")
        return VaultScope.organization(connection.organization_id)
    if connection.user_id is None:
        raise BadRequestError(message="Personal connection has no owner")
    return VaultScope.user(connection.user_id)


def _seal_for(connection: McpConnection, plaintext: str) -> SealedSecret:
    return seal(
        plaintext, scope=connection_scope(connection), key_version=connection.secret_key_version
    )


def _decode_payload(connection: McpConnection, encrypted: str | None) -> McpOAuthPayload | None:
    """Open a stored OAuth payload, or None if it can't be read.

    An unreadable payload means the master key was rotated (or the row was
    tampered with). That's a dead connection the user has to re-authorize, not
    a reason to fail the chat turn.
    """
    if not encrypted:
        return None
    try:
        return McpOAuthPayload.model_validate_json(
            unseal(
                encrypted,
                scope=connection_scope(connection),
                key_version=connection.secret_key_version,
            )
        )
    except Exception:
        logger.warning("Cannot decrypt OAuth payload for MCP connection %r", connection.name)
        return None


def _token_is_fresh(payload: McpOAuthPayload) -> bool:
    """True when the stored access token is good for at least the skew window."""
    return (
        payload.expires_at is None
        or _now_epoch() < payload.expires_at - mcp_oauth.TOKEN_EXPIRY_SKEW_SECS
    )


async def _refresh_under_lock(db: AsyncSession, connection: McpConnection) -> str | None:
    """Spend the refresh token for *connection* while holding its row lock.

    Two chat turns for the same user can reach an expired token at the same
    moment. Providers that rotate refresh tokens invalidate whichever copy is
    redeemed second, and the connection then stops working with no visible
    cause. The lock makes the loser wait, re-read the row, and find the token
    the winner already stored.

    A turn can end up holding several of these at once; they're always taken in
    `list_for_user` order (created_at ascending), so two turns can't deadlock
    by grabbing the same pair of rows in opposite orders.
    """
    locked = await mcp_connection_repo.get_by_id_for_update(db, connection.id)
    if locked is None:
        return None
    payload = _decode_payload(locked, locked.oauth_payload)
    if payload is None or not payload.access_token:
        return None
    if _token_is_fresh(payload):
        return payload.access_token  # another turn refreshed while we waited
    if not payload.refresh_token:
        return None
    try:
        token = await mcp_oauth.refresh_tokens(
            token_endpoint=payload.token_endpoint,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            refresh_token=payload.refresh_token,
            resource=payload.resource,
            scope=payload.scope,
        )
    except OAuthError as exc:
        logger.warning("OAuth token refresh failed for %r: %s", connection.name, exc)
        return None
    payload = _apply_token(payload, token)
    await mcp_connection_repo.update(
        db,
        db_connection=locked,
        update_data={"oauth_payload": _seal_for(locked, payload.model_dump_json()).ciphertext},
    )
    return payload.access_token


async def _oauth_access_token(db: AsyncSession, connection: McpConnection) -> str | None:
    """A currently-valid access token for an OAuth connection, refreshing and
    persisting if needed. None when the connection isn't authorized yet, its
    token expired with no refresh path, or the payload can't be decrypted."""
    payload = _decode_payload(connection, connection.oauth_payload)
    if payload is None or not payload.access_token:
        return None  # not authorized yet, or an unreadable payload
    if _token_is_fresh(payload):
        return payload.access_token
    if not payload.refresh_token:
        return None  # expired, no refresh token → user must re-authorize
    return await _refresh_under_lock(db, connection)


async def sweep_oauth_connections(db: AsyncSession) -> dict[str, int]:
    """Renew OAuth tokens that are about to expire, and mark the ones that cannot be.

    The lazy refresh in :func:`_oauth_access_token` is the load-bearing one and
    stays: it renews exactly when a token is needed, which no schedule can beat.
    What it cannot do is tell anybody *before* the fact. A refresh token that a
    provider has revoked - because the grant was withdrawn, or it sat unused
    past its own lifetime - is discovered by an agent, mid-run, in front of
    whoever asked the question.

    This is the sweep that finds it first. It touches only connections whose
    token is near expiry, so a fleet of healthy ones costs one query; and it
    writes `last_status` either way, so the UI can say "needs authorization"
    without waiting for somebody's run to fail.

    Returns a count per outcome, for the flow to log.
    """
    connections = await mcp_connection_repo.list_oauth_connections(db)
    counts = {"checked": 0, "refreshed": 0, "needs_authorization": 0, "skipped": 0}

    for connection in connections:
        payload = _decode_payload(connection, connection.oauth_payload)
        if payload is None or not payload.access_token:
            # Never authorized, or a payload this deployment cannot decrypt.
            # Neither is something a refresh can fix, and neither is news.
            counts["skipped"] += 1
            continue

        counts["checked"] += 1
        if _token_is_fresh(payload):
            counts["skipped"] += 1
            continue

        token = await _refresh_under_lock(db, connection) if payload.refresh_token else None
        healthy = token is not None
        await mcp_connection_repo.update(
            db,
            db_connection=connection,
            update_data={
                "last_status": "ok" if healthy else "error",
                "last_error": None if healthy else "Authorization expired - reconnect this server",
                "last_checked_at": datetime.now(UTC),
            },
        )
        counts["refreshed" if healthy else "needs_authorization"] += 1

    return counts


async def _resolve_auth_headers(
    db: AsyncSession, connection: McpConnection
) -> dict[str, str] | None:
    """Auth headers to reach *connection*, or None if it can't be used right now
    (OAuth not authorized / expired, or an undecryptable bearer token)."""
    if connection.auth_type == "oauth":
        token = await _oauth_access_token(db, connection)
        return {"Authorization": f"Bearer {token}"} if token else None
    if connection.auth_token is None:
        return {}
    try:
        token = unseal(
            connection.auth_token,
            scope=connection_scope(connection),
            key_version=connection.secret_key_version,
        )
    except Exception:
        logger.warning("Cannot decrypt auth token for MCP connection %r", connection.name)
        return None
    return {"Authorization": f"Bearer {token}"}


class McpConnectionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_user(self, *, user_id: UUID) -> tuple[list[McpConnection], int]:
        return await mcp_connection_repo.list_for_user(self.db, user_id=user_id)

    async def create(self, *, user_id: UUID, data: McpConnectionCreate) -> McpConnection:
        url = await _checked_url(data.url)
        existing = await mcp_connection_repo.get_by_name(self.db, user_id=user_id, name=data.name)
        if existing is not None:
            raise AlreadyExistsError(
                message="MCP connection with this name already exists",
                details={"name": data.name},
            )
        token = data.auth_token.strip() if data.auth_token else None
        sealed = seal(token, scope=VaultScope.user(user_id)) if token else None
        try:
            return await mcp_connection_repo.create(
                self.db,
                user_id=user_id,
                name=data.name,
                url=url,
                auth_token=sealed.ciphertext if sealed else None,
                secret_key_version=sealed.key_version if sealed else 1,
                allowed_tools=data.allowed_tools,
                is_enabled=data.is_enabled,
            )
        except IntegrityError as exc:
            raise AlreadyExistsError(
                message="MCP connection with this name already exists",
                details={"name": data.name},
            ) from exc

    async def update(
        self, *, user_id: UUID, connection_id: UUID, data: McpConnectionUpdate
    ) -> McpConnection:
        db_connection = await self._get_owned(user_id=user_id, connection_id=connection_id)
        update_data: dict[str, Any] = writable(
            data, over=McpConnection, exclude={"clear_allowed_tools"}
        )

        if "url" in update_data:
            update_data["url"] = await _checked_url(update_data["url"])

        if "name" in update_data and update_data["name"] != db_connection.name:
            collision = await mcp_connection_repo.get_by_name(
                self.db, user_id=user_id, name=update_data["name"]
            )
            if collision is not None and collision.id != db_connection.id:
                raise AlreadyExistsError(
                    message="MCP connection with this name already exists",
                    details={"name": update_data["name"]},
                )

        if "auth_token" in update_data:
            token = (update_data["auth_token"] or "").strip()
            # "" clears the stored token; a non-empty value replaces it.
            sealed = seal(token, scope=VaultScope.user(user_id)) if token else None
            update_data["auth_token"] = sealed.ciphertext if sealed else None
            if sealed is not None:
                update_data["secret_key_version"] = sealed.key_version

        if data.clear_allowed_tools:
            update_data["allowed_tools"] = None

        # URL or credentials changed → the previous check result is stale.
        if "url" in update_data or "auth_token" in update_data:
            update_data.setdefault("last_status", None)
            update_data.setdefault("last_error", None)
            update_data.setdefault("last_checked_at", None)

        # OAuth tokens are bound to the resource they were issued for - never
        # carry them over to a different host. The user re-authorizes instead.
        moved = "url" in update_data and update_data["url"] != db_connection.url
        if moved and db_connection.auth_type == "oauth":
            update_data["oauth_payload"] = None
            update_data["oauth_pending_payload"] = None
            update_data["oauth_state"] = None

        if not update_data:
            return db_connection
        return await mcp_connection_repo.update(
            self.db, db_connection=db_connection, update_data=update_data
        )

    async def delete(self, *, user_id: UUID, connection_id: UUID) -> None:
        db_connection = await self._get_owned(user_id=user_id, connection_id=connection_id)
        await mcp_connection_repo.delete(self.db, db_connection=db_connection)

    async def test(
        self, *, user_id: UUID, connection_id: UUID
    ) -> tuple[McpConnection, list[McpToolInfo], str | None]:
        """Probe the server, persist the result, and return discovered tools."""
        db_connection = await self._get_owned(user_id=user_id, connection_id=connection_id)
        return await self._probe(db_connection)

    async def _probe(
        self, db_connection: McpConnection
    ) -> tuple[McpConnection, list[McpToolInfo], str | None]:
        """Talk to the server, record what happened, and report its tools."""
        tools: list[McpToolInfo] = []
        error: str | None = None
        headers = await _resolve_auth_headers(self.db, db_connection)
        if headers is None:
            error = "This plugin needs to be authorized before it can connect."
        else:
            try:
                tools = await probe_mcp_server(db_connection.url, headers)
            except Exception as exc:
                error = probe_error_message(exc)
        db_connection = await mcp_connection_repo.update(
            self.db,
            db_connection=db_connection,
            update_data={
                "last_status": "error" if error else "ok",
                "last_error": error,
                "last_checked_at": datetime.now(UTC),
            },
        )
        return db_connection, tools, error

    async def oauth_start_for_org(self, ctx: AuthContext, *, name: str, url: str) -> str:
        """Begin the OAuth flow for a server the *organization* will own.

        The grant is still one person's - somebody clicks consent, and the
        tokens that come back are theirs at the provider. What differs is who
        holds the connection afterwards: the organization, so every agent can
        reach it, which is what a shared service account is for.

        The cost is real and belongs in this docstring rather than in a refusal:
        when that person's access at the provider is revoked, the organization's
        connection stops working, and the fix is for somebody to authorize it
        again. An organization that wants this should consent with an account it
        controls, not with a member's personal one.
        """
        return await self._oauth_start(
            name=name,
            url=url,
            existing=await mcp_connection_repo.get_org_scoped_by_name(
                self.db, organization_id=ctx.organization_id, name=name
            ),
            vault_scope=VaultScope.organization(ctx.organization_id),
            create=lambda **kwargs: mcp_connection_repo.create_org_scoped(
                self.db,
                organization_id=ctx.organization_id,
                created_by_user_id=ctx.subject_id,
                allowed_tools=None,
                catalog_key=None,
                sealed_token=None,
                **kwargs,
            ),
        )

    async def oauth_start(self, *, user_id: UUID, name: str, url: str) -> str:
        """Begin the OAuth authorization-code flow for a server this person owns."""
        return await self._oauth_start(
            name=name,
            url=url,
            existing=await mcp_connection_repo.get_by_name(self.db, user_id=user_id, name=name),
            vault_scope=VaultScope.user(user_id),
            create=lambda **kwargs: mcp_connection_repo.create(
                self.db,
                user_id=user_id,
                auth_token=None,
                allowed_tools=None,
                **kwargs,
            ),
        )

    async def _oauth_start(
        self,
        *,
        name: str,
        url: str,
        existing: McpConnection | None,
        vault_scope: VaultScope,
        create: Callable[..., Awaitable[McpConnection]],
    ) -> str:
        """The flow both scopes share: discover, register, stage, and hand back a URL.

        Discovers the authorization server, dynamically registers this app,
        stores the flow state (endpoints, client creds, PKCE verifier) in
        `oauth_pending_payload`, and returns the provider consent URL.
        Starting again with the same name re-authorizes the existing OAuth
        connection: the live tokens in `oauth_payload` are left untouched
        until the callback succeeds, so abandoning the consent screen leaves a
        working connection working. The pending flow stops being redeemable
        after `mcp_oauth.FLOW_TTL_SECS`.

        What the two scopes differ in is only where the row lives and whose
        envelope seals it - so those are arguments, and the flow is written
        once. Two copies of an OAuth handshake is two places for a PKCE verifier
        to be dropped.
        """
        url = await _checked_url(url)
        server = await mcp_oauth.discover(url)  # raises OAuthError if unsupported
        redirect_uri = _oauth_redirect_uri()
        client_id, client_secret = await mcp_oauth.register_client(server, redirect_uri)
        pkce = mcp_oauth.new_pkce()
        state = secrets.token_urlsafe(32)
        payload = McpOAuthPayload(
            server_url=url,
            started_at=_now_epoch(),
            authorization_endpoint=server.authorization_endpoint,
            token_endpoint=server.token_endpoint,
            registration_endpoint=server.registration_endpoint,
            client_id=client_id,
            client_secret=client_secret,
            scope=server.scope,
            resource=server.resource,
            redirect_uri=redirect_uri,
            code_verifier=pkce.code_verifier,
        )
        if existing is not None:
            if existing.auth_type != "oauth":
                raise AlreadyExistsError(
                    message="A connection with this name already exists",
                    details={"name": name},
                )
            # Sealed at the row's own key version: one row, one version, so the
            # pending payload stays readable alongside a token sealed before a
            # rotation moved the row on.
            # Only the pending flow is written - the live tokens and the URL
            # they belong to move over in oauth_callback, once consent lands.
            await mcp_connection_repo.update(
                self.db,
                db_connection=existing,
                update_data={
                    "is_enabled": True,
                    "oauth_state": state,
                    "oauth_pending_payload": _seal_for(
                        existing, payload.model_dump_json()
                    ).ciphertext,
                },
            )
        else:
            sealed = seal(payload.model_dump_json(), scope=vault_scope)
            await create(
                name=name,
                url=url,
                secret_key_version=sealed.key_version,
                is_enabled=True,
                auth_type="oauth",
                oauth_state=state,
                oauth_pending_payload=sealed.ciphertext,
            )
        return mcp_oauth.authorization_url(
            server,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=pkce.code_challenge,
        )

    async def oauth_callback(self, *, state: str, code: str) -> McpConnection:
        """Complete the flow: exchange the code for tokens and store them.

        Authenticated by *state* (an unguessable CSRF token we issued), so this
        needs no user session - the provider redirect lands here without our
        cookies. The pending flow is promoted to the live payload only now, so
        a flow that is never completed leaves the previous tokens in place.
        """
        connection = await mcp_connection_repo.get_by_oauth_state(self.db, state)
        if connection is None or not connection.oauth_pending_payload:
            raise NotFoundError(message="OAuth session not found or already completed")
        payload = _decode_payload(connection, connection.oauth_pending_payload)
        if payload is None or not payload.code_verifier:
            raise OAuthError("This authorization session is no longer valid - start again.")
        if _now_epoch() - payload.started_at > mcp_oauth.FLOW_TTL_SECS:
            raise OAuthError("This authorization session has expired - start again.")
        token = await mcp_oauth.exchange_code(
            token_endpoint=payload.token_endpoint,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            code=code,
            code_verifier=payload.code_verifier,
            redirect_uri=payload.redirect_uri,
            resource=payload.resource,
        )
        payload = _apply_token(payload, token)
        return await mcp_connection_repo.update(
            self.db,
            db_connection=connection,
            update_data={
                # The URL moves together with the tokens issued for it.
                "url": payload.server_url,
                "oauth_payload": _seal_for(connection, payload.model_dump_json()).ciphertext,
                "oauth_pending_payload": None,
                "oauth_state": None,
                "last_status": "ok",
                "last_error": None,
                "last_checked_at": datetime.now(UTC),
            },
        )

    async def _get_owned(self, *, user_id: UUID, connection_id: UUID) -> McpConnection:
        db_connection = await mcp_connection_repo.get_by_id(self.db, connection_id)
        # The scope check is the load-bearing half. These routes authorize on
        # `user_id` alone and demand no organization permission, so without it
        # whoever created an organization connection could repoint a published
        # agent's server at a host of their choosing.
        if (
            db_connection is None
            or db_connection.scope != "user"
            or db_connection.user_id != user_id
        ):
            raise NotFoundError(
                message="MCP connection not found",
                details={"connection_id": str(connection_id)},
            )
        return db_connection

    async def list_for_org(self, ctx: AuthContext) -> tuple[list[McpConnection], int]:
        return await mcp_connection_repo.list_org_scoped(
            self.db, organization_id=ctx.organization_id
        )

    async def create_for_org(self, ctx: AuthContext, data: OrgMcpConnectionCreate) -> McpConnection:
        """Seal a credential for this organization and store the connection.

        Raises:
            BadRequestError: If `catalog_key` names no catalog entry. A key
                nothing recognises would show up in the Builder as a server with
                no name and no logo, which reads as a broken row rather than as
                the typo it is.
            AlreadyExistsError: If the name is taken inside this organization.
                The name becomes the agent's tool prefix, so two servers sharing
                one is two sets of tools nobody can tell apart.
        """
        if data.catalog_key is not None and get_entry(data.catalog_key) is None:
            raise BadRequestError(
                message=f"Unknown catalog server: {data.catalog_key}",
                details={"catalog_key": data.catalog_key},
            )
        url = await _checked_url(data.url)
        existing = await mcp_connection_repo.get_org_scoped_by_name(
            self.db, organization_id=ctx.organization_id, name=data.name
        )
        if existing is not None:
            raise AlreadyExistsError(
                message="This organization already has an MCP server with that name",
                details={"name": data.name},
            )
        token = data.auth_token.strip() if data.auth_token else None
        sealed = seal(token, scope=VaultScope.organization(ctx.organization_id)) if token else None
        try:
            connection = await mcp_connection_repo.create_org_scoped(
                self.db,
                organization_id=ctx.organization_id,
                created_by_user_id=ctx.subject_id,
                name=data.name,
                url=url,
                sealed_token=sealed.ciphertext if sealed else None,
                secret_key_version=sealed.key_version if sealed else 1,
                allowed_tools=data.allowed_tools,
                catalog_key=data.catalog_key,
                is_enabled=data.is_enabled,
            )
        except IntegrityError as exc:
            raise AlreadyExistsError(
                message="This organization already has an MCP server with that name",
                details={"name": data.name},
            ) from exc
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="mcp_connection.created",
            target_type="mcp_connection",
            target_id=str(connection.id),
            # The token never reaches the audit log. What identifies the row is
            # the name and where it points, both of which are already public.
            details={"name": data.name, "url": url, "catalog_key": data.catalog_key},
        )
        return connection

    async def update_for_org(
        self, ctx: AuthContext, *, connection_id: UUID, data: OrgMcpConnectionUpdate
    ) -> McpConnection:
        db_connection = await self._get_org(ctx, connection_id)
        update_data: dict[str, Any] = writable(
            data, over=McpConnection, exclude={"clear_allowed_tools"}
        )

        if "url" in update_data:
            update_data["url"] = await _checked_url(update_data["url"])

        if "name" in update_data and update_data["name"] != db_connection.name:
            collision = await mcp_connection_repo.get_org_scoped_by_name(
                self.db, organization_id=ctx.organization_id, name=update_data["name"]
            )
            if collision is not None:
                raise AlreadyExistsError(
                    message="This organization already has an MCP server with that name",
                    details={"name": update_data["name"]},
                )

        if "auth_token" in update_data:
            token = (update_data["auth_token"] or "").strip()
            # "" clears the stored token; a non-empty value replaces it.
            sealed = (
                seal(token, scope=VaultScope.organization(ctx.organization_id)) if token else None
            )
            update_data["auth_token"] = sealed.ciphertext if sealed else None
            if sealed is not None:
                update_data["secret_key_version"] = sealed.key_version

        if data.clear_allowed_tools:
            update_data["allowed_tools"] = None

        # URL or credentials changed → the previous check result is stale.
        if "url" in update_data or "auth_token" in update_data:
            update_data.setdefault("last_status", None)
            update_data.setdefault("last_error", None)
            update_data.setdefault("last_checked_at", None)

        if not update_data:
            return db_connection
        return await mcp_connection_repo.update(
            self.db, db_connection=db_connection, update_data=update_data
        )

    async def delete_for_org(self, ctx: AuthContext, *, connection_id: UUID) -> None:
        db_connection = await self._get_org(ctx, connection_id)
        await mcp_connection_repo.delete(self.db, db_connection=db_connection)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="mcp_connection.deleted",
            target_type="mcp_connection",
            target_id=str(connection_id),
            details={"name": db_connection.name},
        )

    async def test_for_org(
        self, ctx: AuthContext, *, connection_id: UUID
    ) -> tuple[McpConnection, list[McpToolInfo], str | None]:
        """Probe an organization server, persist the result, return its tools."""
        db_connection = await self._get_org(ctx, connection_id)
        return await self._probe(db_connection)

    async def _get_org(self, ctx: AuthContext, connection_id: UUID) -> McpConnection:
        """One organization connection, or a refusal that reveals nothing.

        Reported as "not found" rather than "forbidden" for the same reason as
        every other resource here: a distinguishable refusal turns an id into a
        probe for what another tenant owns.
        """
        db_connection = await mcp_connection_repo.get_org_scoped_by_id(
            self.db, connection_id=connection_id, organization_id=ctx.organization_id
        )
        if db_connection is None:
            raise NotFoundError(
                message="MCP connection not found",
                details={"connection_id": str(connection_id)},
            )
        return db_connection


async def build_toolsets_for_agent(
    db: AsyncSession, *, organization_id: UUID, connection_ids: list[UUID]
) -> list[Any]:
    """Agent toolsets for a published agent: exactly the servers its spec names.

    Deliberately never the servers the person running the turn has enabled:
    what an agent can reach is part of the agent, and one that answers
    differently depending on whose Slack account triggered it cannot be
    reasoned about or reviewed. Only organization-scoped rows resolve here, so
    a member's personal token can never end up inside a shared agent.

    Runs in the caller's session rather than opening its own: an OAuth refresh
    spent here has to be persisted by the same transaction that recorded the run.
    """
    specs: list[McpServerSpec] = []
    for connection_id in connection_ids:
        connection = await mcp_connection_repo.get_org_scoped_by_id(
            db, connection_id=connection_id, organization_id=organization_id
        )
        if connection is None or not connection.is_enabled:
            # Deleted, disabled or moved out of the organization since publish.
            # A binding that was already broken is refused at publish, where
            # somebody can still fix it; one that broke afterwards narrows the
            # agent instead of taking the conversation down with it.
            logger.warning(
                "Agent references MCP connection %s, which this organization (%s) no longer offers",
                connection_id,
                organization_id,
            )
            continue
        headers = await _resolve_auth_headers(db, connection)
        if headers is None:
            # OAuth not authorized / expired, or an undecryptable bearer token.
            # Warning rather than info: this server was bound on purpose, so
            # losing it is an operator's problem, not the routine attrition of
            # an ambient connection somebody enabled once in Settings.
            logger.warning(
                "Skipping MCP connection %r for this run: no usable credentials", connection.name
            )
            continue
        specs.append(
            McpServerSpec(
                name=connection.name,
                url=connection.url,
                headers=headers,
                allowed_tools=connection.allowed_tools,
            )
        )
    return await build_mcp_toolsets(specs)
