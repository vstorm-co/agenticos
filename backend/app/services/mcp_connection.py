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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
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
from app.agents.spec import McpServerRef, PersonalMcpServerRef
from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.core.sanitize import UrlRefusedError
from app.core.secret_kinds import SecretKind
from app.core.vault import SealedSecret, VaultScope, current_key_version, seal, unseal
from app.db.locks import LockScope, hold_name
from app.db.models.mcp_connection import McpConnection
from app.db.updates import writable
from app.repositories import mcp_connection_repo, mcp_registry_server_repo
from app.schemas.mcp_connection import (
    McpConnectionCreate,
    McpConnectionUpdate,
    OrgMcpConnectionCreate,
    OrgMcpConnectionUpdate,
)
from app.services import portal_catalog, portals
from app.services.mcp_catalog import get_entry
from app.services.organization_secret import OrganizationSecretService
from app.services.portals import github_oauth, google_oauth

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


async def _complete_mcp_flow(
    payload: McpOAuthPayload, code: str
) -> tuple[McpOAuthPayload, list[str] | None]:
    """Exchange a code through the discovery flow and fold the tokens in.

    The PKCE `code_verifier` is what makes this an MCP-discovery payload; its
    absence is a pending flow that can no longer be completed (a rotated master
    key left the verifier unreadable), which the user restarts rather than 500s on.
    """
    if not payload.code_verifier:
        raise OAuthError("This authorization session is no longer valid - start again.")
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
    return payload, (payload.scope.split() if payload.scope else None)


async def _initial_poll_cursor(*, portal_key: str, access_token: str) -> dict[str, Any] | None:
    """Where a freshly consented polled grant starts reading, or None.

    The adapter's own no-cursor poll is the snapshot - "the mailbox as of now,
    nothing to emit" - taken at consent so mail arriving before the first
    heartbeat lands *after* the boundary instead of inside it. Best-effort: a
    provider that cannot answer leaves the cursor to the first poll, whose only
    cost is the pre-heartbeat window this exists to close.
    """
    adapter = portals.get_adapter(portal_key)
    if adapter is None:
        return None
    try:
        read = await adapter.poll(access_token=access_token, cursor=None)
    except portals.PortalError:
        logger.warning("portal_initial_cursor_failed", extra={"portal_key": portal_key})
        return None
    return read.cursor


async def _complete_google_flow(
    payload: McpOAuthPayload, code: str
) -> tuple[McpOAuthPayload, list[str] | None]:
    """Exchange a code through Google's OAuth flow and fold the token in.

    Unlike GitHub's, a Google access token *expires* - an hour - so the refresh
    token and the expiry are both carried, and the shared `_refresh_under_lock`
    spends them when a poll finds the token stale. That is the whole reason a
    portal grant lives in this table rather than a new one.

    The granted scopes come from Google's space-separated `scope` response, which
    is what the account actually consented to: consent is per scope and a person
    can withhold one, so the poller has to know what it got before it reads a
    mailbox it may not have been given.
    """
    try:
        token = await google_oauth.exchange_code(
            client_id=payload.client_id,
            client_secret=payload.client_secret or "",
            code=code,
            redirect_uri=payload.redirect_uri,
        )
    except google_oauth.GoogleOAuthError as exc:
        raise OAuthError(str(exc)) from exc
    payload = payload.model_copy(
        update={
            "access_token": token.access_token,
            # Kept where Google sent one. Without `access_type=offline` it does not,
            # and a grant with no refresh token stops working in an hour with
            # nothing to say why - which is why the consent URL asks for it. A
            # re-consent that omits one falls back to the live payload's, in the
            # callback, where that payload is in hand.
            "refresh_token": token.refresh_token,
            "expires_at": (
                None if token.expires_in is None else _now_epoch() + float(token.expires_in)
            ),
            "code_verifier": None,
        }
    )
    return payload, (token.granted_scopes or None)


async def _complete_github_flow(
    payload: McpOAuthPayload, code: str
) -> tuple[McpOAuthPayload, list[str] | None]:
    """Exchange a code through GitHub's OAuth App flow and fold the token in.

    A classic OAuth App token neither refreshes nor expires, so both fields are
    cleared rather than carried; the granted scopes come from GitHub's own
    comma-separated `scope`, which is what the account actually consented to. The
    provider-specific failure is re-raised as :class:`OAuthError` so the shared
    callback route reports it the same way as a discovery-flow failure.
    """
    try:
        token = await github_oauth.exchange_code(
            client_id=payload.client_id,
            client_secret=payload.client_secret or "",
            code=code,
            redirect_uri=payload.redirect_uri,
        )
    except github_oauth.GithubOAuthError as exc:
        raise OAuthError(str(exc)) from exc
    payload = payload.model_copy(
        update={
            "access_token": token.access_token,
            "refresh_token": None,
            "expires_at": None,
            "code_verifier": None,
        }
    )
    return payload, (token.granted_scopes or None)


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


# Where a polled portal's grant is spent. `mcp_connections.url` is not nullable
# and a portal row has no MCP server to name, so it carries the API the token is
# actually used against - which is the honest answer to "what does this connection
# point at". A portal added here needs a row; one absent from it cannot be polled,
# and `oauth_start_for_polled_portal` would raise a `KeyError` before writing
# anything, which is the loud failure a silent empty string would not be.
_POLLED_PORTAL_URL = {"google": "https://gmail.googleapis.com"}

# How stale a grant's `polled_at` must be before a tick claims it again, and how
# many one tick takes. The interval matches the heartbeat's own minute; the batch
# bounds a tick's cost on a deployment with many connected mailboxes - the rest
# are claimed by the next tick, oldest first, so nothing starves.
_POLL_INTERVAL = timedelta(seconds=55)
_POLL_BATCH = 50


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
        """Store one member's own account on a server.

        Raises:
            BadRequestError: If `catalog_key` names neither a curated entry nor a
                mirrored registry row. The key is what a binding matches on to
                speak as this account, so a wrong one is a connection that
                silently never substitutes rather than an obvious mistake.
            AlreadyExistsError: If this member already has a connection by that
                name.
        """
        if data.catalog_key is not None and not await self._known_catalog_key(data.catalog_key):
            raise BadRequestError(
                message=f"Unknown catalog server: {data.catalog_key}",
                details={"catalog_key": data.catalog_key},
            )
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
                secret_key_version=sealed.key_version if sealed else current_key_version(),
                allowed_tools=data.allowed_tools,
                is_enabled=data.is_enabled,
                label=_stored_label(data.label),
                catalog_key=data.catalog_key,
            )
        except IntegrityError as exc:
            raise AlreadyExistsError(
                message="MCP connection with this name already exists",
                details={"name": data.name},
            ) from exc

    async def update(
        self, *, user_id: UUID, connection_id: UUID, data: McpConnectionUpdate
    ) -> McpConnection:
        # Locked from the read: the token below is sealed at the row's recorded
        # key version, and a rotation committing between an unlocked read and
        # this write would tag the new envelope with a version it was not
        # sealed under.
        db_connection = await self._get_owned(
            user_id=user_id, connection_id=connection_id, for_update=True
        )
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
            # "" clears the stored token; a non-empty value replaces it, sealed at
            # the row's version - one version column covers every envelope in the
            # row, so bumping it would orphan the OAuth siblings (#552).
            sealed = _seal_for(db_connection, token) if token else None
            update_data["auth_token"] = sealed.ciphertext if sealed else None

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

        # A different server offers different tools, and the Builder reads this
        # cache without probing - so leaving it presented the previous host's
        # tools as the new one's, and an allowlist saved from that list hides
        # every tool the replacement actually has. Cleared on a move only: a
        # failed probe against the same host says nothing about what it offers,
        # which is why `test` leaves the list alone on error.
        if moved:
            update_data.setdefault("last_tools", None)
        if moved and db_connection.auth_type == "oauth":
            update_data["oauth_payload"] = None
            update_data["oauth_pending_payload"] = None
            update_data["oauth_state"] = None

        if "label" in update_data:
            update_data["label"] = _stored_label(update_data["label"])

        if update_data.get("is_default"):
            if db_connection.catalog_key is None:
                # Nothing to nominate it against: the key is what says this
                # account and the organization's are the same service, so a
                # default on a connection made from a bare URL would never be
                # read (#1342).
                raise refused_field(
                    "is_default",
                    "This connection was made from a URL rather than from the catalog, "
                    "so nothing says which service it is. Reconnect it from the catalog "
                    "to speak as it.",
                )
            # Serialized per member and service before the clear, because the
            # clear is what makes room for the set. Two nominations racing on
            # one service each locked only their own row, each found no sibling
            # still marked, and both wrote `is_default` - so one hit
            # `uq_mcp_connections_user_default` and answered 500. The lock is
            # held for the rest of the transaction, which is exactly as long as
            # the index cares about.
            await hold_name(
                self.db, LockScope.MCP_DEFAULT_ACCOUNT, f"{user_id}:{db_connection.catalog_key}"
            )
            # Cleared on the siblings first, so the partial unique index is
            # never asked to hold two at once. One statement rather than a read
            # and a loop: the index is the constraint, and this is what keeps
            # the write inside it.
            await mcp_connection_repo.clear_default_for_catalog_key(
                self.db,
                user_id=user_id,
                catalog_key=db_connection.catalog_key,
                except_id=db_connection.id,
            )

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
                # Only on a probe that answered. A failed one says nothing about
                # what the server offers, and blanking the list would leave an
                # agent author with nothing to choose from because the server
                # was briefly unreachable.
                **({"last_tools": [asdict(tool) for tool in tools]} if error is None else {}),
            },
        )
        return db_connection, tools, error

    async def oauth_start_for_org(
        self, ctx: AuthContext, *, name: str, url: str, catalog_key: str | None = None
    ) -> str:
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
                catalog_key=catalog_key,
                sealed_token=None,
                **kwargs,
            ),
        )

    async def oauth_start(
        self, *, user_id: UUID, name: str, url: str, catalog_key: str | None = None
    ) -> str:
        """Begin the OAuth authorization-code flow for a server this person owns.

        `catalog_key` is stored on the row it creates, and that is the whole
        reason it is a parameter: a personal connection without one can never be
        substituted for the organization's, so an OAuth account authorised here
        would be invisible to every binding that asked to speak as its owner.
        """
        if catalog_key is not None and not await self._known_catalog_key(catalog_key):
            raise BadRequestError(
                message=f"Unknown catalog server: {catalog_key}",
                details={"catalog_key": catalog_key},
            )
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
                catalog_key=catalog_key,
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
        await self._stage_pending_oauth(
            name=name,
            url=url,
            existing=existing,
            vault_scope=vault_scope,
            create=create,
            payload=payload,
            state=state,
        )
        return mcp_oauth.authorization_url(
            server,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=pkce.code_challenge,
        )

    async def _stage_pending_oauth(
        self,
        *,
        name: str,
        url: str,
        existing: McpConnection | None,
        vault_scope: VaultScope,
        create: Callable[..., Awaitable[McpConnection]],
        payload: McpOAuthPayload,
        state: str,
        upgrade: bool = False,
    ) -> None:
        """Write a staged consent flow onto an existing row or a fresh one.

        Shared by the discovery-based MCP start and the GitHub-provider start: both
        seal a pending :class:`McpOAuthPayload` under `oauth_pending_payload`, keyed
        by `oauth_state`, and leave any live tokens in `oauth_payload` untouched
        until the callback lands. Abandoning the consent screen therefore leaves a
        working connection working, and re-authorizing never overwrites a URL or a
        token that still works - both move over in :meth:`oauth_callback`.

        `upgrade` lets the GitHub portal flow stage onto an existing *bearer* row:
        an organization that connected the GitHub catalog entry before the OAuth
        flow existed holds one, agents may already be bound to it, and refusing it
        would wedge the portal on Re-authorize until somebody deletes that row.
        The bearer token keeps working until the consent lands; the callback then
        promotes the row to OAuth. The discovery flow never passes it - there a
        name collision with a bearer row is a genuine conflict.
        """
        if existing is not None:
            if existing.auth_type != "oauth" and not upgrade:
                raise AlreadyExistsError(
                    message="A connection with this name already exists",
                    details={"name": name},
                )
            # Sealed at the row's own key version: one row, one version, so the
            # pending payload stays readable alongside a token sealed before a
            # rotation moved the row on.
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

    async def oauth_start_for_org_github(self, ctx: AuthContext, *, portal_key: str) -> str:
        """Begin the GitHub OAuth App flow for a trigger portal, using the org's creds.

        Unlike :meth:`oauth_start_for_org`, which discovers an authorization server
        and dynamically registers a client, GitHub OAuth Apps do neither: the
        endpoints are fixed and the client is one the organization registered by hand
        and stored in the vault (`github_oauth_app`). This reads those credentials,
        builds GitHub's consent URL for the portal's scopes, and stages the pending
        flow on the organization's connection.

        The connection is named and keyed after the portal's MCP catalog entry
        (`catalog_key`), so the trigger portal and the agent's MCP tools resolve to
        one connected account: the frontend joins a portal to its connection by that
        key. Re-running it re-authorizes the existing connection, keeping the live
        token until the new consent lands.

        Raises:
            BadRequestError: If `portal_key` names no portal, or one that does not
                connect through GitHub (no `mcp_catalog_key`).
            NotFoundError: If the organization has stored no `github_oauth_app`
                secret - a 4xx the connect UI shows, never a 500.
        """
        portal = portal_catalog.get_portal(portal_key)
        if portal is None or portal.mcp_catalog_key is None:
            raise BadRequestError(
                message="This portal does not connect through GitHub",
                details={"portal_key": portal_key},
            )
        entry = get_entry(portal.mcp_catalog_key)
        if entry is None:
            raise BadRequestError(
                message="This portal's connection catalog entry is missing",
                details={"portal_key": portal_key, "catalog_key": portal.mcp_catalog_key},
            )
        creds = await OrganizationSecretService(self.db).oauth_app(
            ctx, kind=SecretKind.GITHUB_OAUTH_APP
        )
        redirect_uri = _oauth_redirect_uri()
        state = secrets.token_urlsafe(32)
        scopes = [*portal.read_scopes, *portal.webhook_admin_scopes]
        catalog_key = portal.mcp_catalog_key
        payload = McpOAuthPayload(
            server_url=entry.url,
            started_at=_now_epoch(),
            authorization_endpoint=github_oauth.AUTHORIZE_ENDPOINT,
            token_endpoint=github_oauth.TOKEN_ENDPOINT,
            client_id=creds.client_id,
            client_secret=creds.client_secret.get_secret_value(),
            scope=" ".join(scopes),
            # GitHub uses no RFC 8707 resource indicator; the field is required, so
            # it carries the server the connection points at, like every payload.
            resource=entry.url,
            redirect_uri=redirect_uri,
            provider=github_oauth.PROVIDER,
        )
        # The organization's existing row for this catalog entry, whatever it is
        # named - the catalog key is how the frontend joins portal to connection,
        # so staging anywhere else would leave the portal reading a different row
        # than the one just authorized. A pre-OAuth bearer connection to the same
        # entry is upgraded in place rather than refused or duplicated: agents may
        # already be bound to it. Only a row that genuinely is this catalog entry
        # may be upgraded - a coincidentally like-named bearer row keeps the
        # refusal, since flipping it would hijack an unrelated connection.
        existing = await mcp_connection_repo.get_org_scoped_by_catalog_key(
            self.db, organization_id=ctx.organization_id, catalog_key=catalog_key
        ) or await mcp_connection_repo.get_org_scoped_by_name(
            self.db, organization_id=ctx.organization_id, name=catalog_key
        )
        await self._stage_pending_oauth(
            name=catalog_key,
            url=entry.url,
            existing=existing,
            upgrade=existing is not None and existing.catalog_key == catalog_key,
            vault_scope=VaultScope.organization(ctx.organization_id),
            create=lambda **kwargs: mcp_connection_repo.create_org_scoped(
                self.db,
                organization_id=ctx.organization_id,
                created_by_user_id=ctx.subject_id,
                allowed_tools=None,
                catalog_key=catalog_key,
                sealed_token=None,
                **kwargs,
            ),
            payload=payload,
            state=state,
        )
        return github_oauth.authorization_url(
            client_id=creds.client_id,
            redirect_uri=redirect_uri,
            scopes=scopes,
            state=state,
        )

    async def claim_grants_to_poll(self, *, portal_keys: list[str]) -> list[McpConnection]:
        """The portal grants this tick should read, claimed so no other tick does.

        No `AuthContext`: the poller is the deployment's own work, not a member's
        request, and it crosses organizations by design - one tick reads every
        connected mailbox. Every later step is scoped by the grant's own
        `organization_id`, which is what authorized reading that account.

        Claimed with `polled_at` advanced under the row lock, the protocol the
        trigger heartbeat already uses: a tick that outruns its minute cannot be
        double-claimed by the next, and a worker that dies mid-poll frees its lock
        without parking the mailbox - the next tick finds `polled_at` old again.
        """
        return await mcp_connection_repo.claim_portal_grants_to_poll(
            self.db,
            portal_keys=portal_keys,
            not_polled_since=datetime.now(UTC) - _POLL_INTERVAL,
            limit=_POLL_BATCH,
        )

    async def poll_grant(self, grant: McpConnection) -> portals.PolledEvents | None:
        """Read one connected account, or `None` when it cannot be read now.

        `None` rather than an exception for every recoverable case - no adapter, a
        token that will not refresh, a provider that is down - because a poll is a
        heartbeat's work: the tick moves on to the next mailbox and this one is
        tried again in a minute. The grant's own status records what happened, so a
        mailbox that has stopped working says so on the card rather than only in a
        log.

        A revoked grant is marked `error` and left enabled: re-consenting repairs
        it, and disabling it would take it out of the claim and out of the card's
        reach at the same time.
        """
        adapter = portals.get_adapter(grant.portal_key or "")
        if adapter is None:
            return None
        token = await _oauth_access_token(self.db, grant)
        if token is None:
            await self._record_poll_failure(grant, "The connected account could not be renewed")
            return None
        try:
            read = await adapter.poll(access_token=token, cursor=grant.poll_cursor)
        except portals.PortalError as exc:
            # The provider's own words are not carried: a portal's error body echoes
            # the request, and the request carries a bearer token (#423).
            logger.warning(
                "portal_poll_failed",
                extra={"portal_key": grant.portal_key, "error": exc.__class__.__name__},
            )
            await self._record_poll_failure(grant, "The provider refused or could not be reached")
            return None
        if grant.last_status != "ok":
            await mcp_connection_repo.update(
                self.db,
                db_connection=grant,
                update_data={"last_status": "ok", "last_error": None},
            )
        return read

    async def store_poll_cursor(self, grant: McpConnection, *, cursor: dict[str, Any]) -> None:
        """Advance where the reader has got to, after its fires were dispatched.

        Written last on purpose. In the other order a crash between the two loses
        every message the poll read - the cursor claims they were handled and
        nothing handled them. This way a crash re-reads them and the delivery-id
        claim dedups: at-least-once with the duplicate suppressed, rather than
        at-most-once with a silent hole.
        """
        await mcp_connection_repo.update(
            self.db,
            db_connection=grant,
            update_data={"poll_cursor": cursor, "last_checked_at": datetime.now(UTC)},
        )

    async def _record_poll_failure(self, grant: McpConnection, reason: str) -> None:
        """Say on the row why a mailbox could not be read.

        The reason is written here, not taken from the provider: `last_error` is
        rendered to everyone who can see the connection, and a provider's message
        carries the failing request URL - which carries a token (#423).
        """
        await mcp_connection_repo.update(
            self.db,
            db_connection=grant,
            update_data={
                "last_status": "error",
                "last_error": reason,
                "last_checked_at": datetime.now(UTC),
            },
        )

    async def oauth_start_for_polled_portal(self, ctx: AuthContext, *, portal_key: str) -> str:
        """Begin the consent flow for a portal this platform *reads* rather than
        registers a webhook at.

        Gmail is the case: the grant is spent by the heartbeat's poller, not by a
        provider posting to us, so there is nothing to register and the only thing
        the flow has to produce is a refreshable token with the portal's read
        scopes on it.

        **The client is the organization's, from the vault** - the same shape as
        GitHub's, and for the reason that outranks any argument about who owns a
        Google project: every secret at rest in this repository goes through
        `app/core/vault.py`, and there is no second mechanism. It is emphatically
        *not* the deployment's `GOOGLE_CLIENT_ID`, which is sign-in.

        The grant is staged on a `purpose = 'portal'` row, so it never appears
        among the organization's MCP servers: it has no tools and nobody should be
        offered it to bind an agent to. One row per portal per organization, so
        re-consenting replaces the grant rather than leaving two mailboxes with
        nothing to choose between them.

        Raises:
            BadRequestError: If `portal_key` names no portal, or one that is not
                polled - a webhook portal connects through its own flow.
            NotFoundError: If the organization has stored no org-visible
                `google_oauth_app` secret - a 4xx the card shows as a prerequisite,
                the same way a missing GitHub OAuth App is, never a 500.
            BadRequestError: If more than one is stored, or `portal_key` names no
                polled portal.
        """
        portal = portal_catalog.get_portal(portal_key)
        if portal is None or portal.delivery is not portal_catalog.DeliveryMode.POLLING:
            raise BadRequestError(
                message="This portal is not one the platform polls",
                details={"portal_key": portal_key},
            )
        creds = await OrganizationSecretService(self.db).oauth_app(
            ctx, kind=SecretKind.GOOGLE_OAUTH_APP
        )
        redirect_uri = _oauth_redirect_uri()
        state = secrets.token_urlsafe(32)
        scopes = list(portal.read_scopes)
        payload = McpOAuthPayload(
            # A portal grant points at the API it reads rather than at an MCP
            # server. The column is not nullable and the value is not a lie: it is
            # where the token is spent.
            server_url=_POLLED_PORTAL_URL[portal_key],
            started_at=_now_epoch(),
            authorization_endpoint=google_oauth.AUTHORIZE_ENDPOINT,
            token_endpoint=google_oauth.TOKEN_ENDPOINT,
            client_id=creds.client_id,
            client_secret=creds.client_secret.get_secret_value(),
            scope=" ".join(scopes),
            resource=_POLLED_PORTAL_URL[portal_key],
            redirect_uri=redirect_uri,
            provider=google_oauth.PROVIDER,
        )
        existing = await mcp_connection_repo.get_portal_grant(
            self.db, organization_id=ctx.organization_id, portal_key=portal_key
        )
        await self._stage_pending_oauth(
            name=portal.name,
            url=_POLLED_PORTAL_URL[portal_key],
            existing=existing,
            vault_scope=VaultScope.organization(ctx.organization_id),
            create=lambda **kwargs: mcp_connection_repo.create_org_scoped(
                self.db,
                organization_id=ctx.organization_id,
                created_by_user_id=ctx.subject_id,
                allowed_tools=None,
                catalog_key=None,
                sealed_token=None,
                purpose="portal",
                portal_key=portal_key,
                **kwargs,
            ),
            payload=payload,
            state=state,
        )
        return google_oauth.authorization_url(
            client_id=creds.client_id,
            redirect_uri=redirect_uri,
            scopes=scopes,
            state=state,
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
        if payload is None:
            raise OAuthError("This authorization session is no longer valid - start again.")
        if _now_epoch() - payload.started_at > mcp_oauth.FLOW_TTL_SECS:
            raise OAuthError("This authorization session has expired - start again.")
        if payload.provider == github_oauth.PROVIDER:
            payload, granted_scopes = await _complete_github_flow(payload, code)
        elif payload.provider == google_oauth.PROVIDER:
            payload, granted_scopes = await _complete_google_flow(payload, code)
            # Google may omit the refresh token on a re-consent for a grant it
            # already holds - the previous one stays valid, so it is carried
            # forward from the live payload rather than overwritten with None,
            # which would stop the mailbox's polling an hour later with nothing
            # to say why (`_apply_token` does the same for the shared MCP flow).
            if payload.refresh_token is None and connection.oauth_payload:
                live = _decode_payload(connection, connection.oauth_payload)
                if live is not None and live.refresh_token:
                    payload = payload.model_copy(update={"refresh_token": live.refresh_token})
        else:
            payload, granted_scopes = await _complete_mcp_flow(payload, code)
        # A polled grant's reading position starts *now*, at consent - not at the
        # first heartbeat up to a minute later. The first poll with no cursor
        # snapshots the mailbox and emits nothing, so mail arriving inside that
        # gap would be inside the snapshot and permanently skipped as if it
        # predated the connection. Best-effort: a provider that cannot answer
        # right now leaves the cursor to the first poll, which is the old window
        # rather than a broken flow.
        poll_cursor = connection.poll_cursor
        if (
            connection.purpose == "portal"
            and connection.portal_key is not None
            and poll_cursor is None
            and payload.access_token
        ):
            poll_cursor = await _initial_poll_cursor(
                portal_key=connection.portal_key, access_token=payload.access_token
            )
        return await mcp_connection_repo.update(
            self.db,
            db_connection=connection,
            update_data={
                "poll_cursor": poll_cursor,
                # The URL moves together with the tokens issued for it.
                "url": payload.server_url,
                # A row staged as an upgrade (a pre-OAuth bearer connection to a
                # catalog entry) is promoted only now, with the consent in hand:
                # the OAuth token takes over and the static one is dropped, so a
                # flow abandoned at the consent screen never broke the bearer.
                "auth_type": "oauth",
                "auth_token": None,
                "oauth_payload": _seal_for(connection, payload.model_dump_json()).ciphertext,
                "oauth_pending_payload": None,
                "oauth_state": None,
                # The scopes the provider actually granted, mirrored out of the
                # sealed payload into a plain column so the trigger-portal webhook
                # path can read them without unwrapping the token. Only that path
                # reads it; tool-calling is unaffected.
                "granted_scopes": granted_scopes,
                "last_status": "ok",
                "last_error": None,
                "last_checked_at": datetime.now(UTC),
            },
        )

    async def _get_owned(
        self, *, user_id: UUID, connection_id: UUID, for_update: bool = False
    ) -> McpConnection:
        fetch = (
            mcp_connection_repo.get_by_id_for_update
            if for_update
            else mcp_connection_repo.get_by_id
        )
        db_connection = await fetch(self.db, connection_id)
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

    async def _known_catalog_key(self, catalog_key: str) -> bool:
        """Whether a key names a server this deployment can identify.

        Two catalogs answer to this, and the second is the reason the check is
        not `get_entry` alone: the listing serves 99 curated entries beside
        5,703 mirrored from the public registry, and it hands back the registry
        row's own id as the key. Validating against the curated set alone
        refused every unreviewed server with `Unknown catalog server` - so the
        mirror was searchable and connectable personally, and unusable for the
        organization connections agents actually bind to.
        """
        if get_entry(catalog_key) is not None:
            return True
        return await mcp_registry_server_repo.get(self.db, catalog_key) is not None

    async def create_for_org(self, ctx: AuthContext, data: OrgMcpConnectionCreate) -> McpConnection:
        """Seal a credential for this organization and store the connection.

        Raises:
            BadRequestError: If `catalog_key` names neither a curated catalog
                entry nor a mirrored registry row. A key nothing recognises
                would show up in the Builder as a server with no name and no
                logo, which reads as a broken row rather than as the typo it is.
            AlreadyExistsError: If the name is taken inside this organization.
                The name becomes the agent's tool prefix, so two servers sharing
                one is two sets of tools nobody can tell apart.
        """
        if data.catalog_key is not None and not await self._known_catalog_key(data.catalog_key):
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
                secret_key_version=sealed.key_version if sealed else current_key_version(),
                allowed_tools=data.allowed_tools,
                catalog_key=data.catalog_key,
                is_enabled=data.is_enabled,
                label=_stored_label(data.label),
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
        # Locked from the read - same reason as `update` above.
        db_connection = await self._get_org(ctx, connection_id, for_update=True)
        update_data: dict[str, Any] = writable(
            data, over=McpConnection, exclude={"clear_allowed_tools"}
        )

        if "url" in update_data:
            update_data["url"] = await _checked_url(update_data["url"])

        if "label" in update_data:
            update_data["label"] = _stored_label(update_data["label"])

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
            # "" clears the stored token; a non-empty value replaces it, sealed at
            # the row's version - one version column covers every envelope in the
            # row, so bumping it would orphan the OAuth siblings (#552).
            sealed = _seal_for(db_connection, token) if token else None
            update_data["auth_token"] = sealed.ciphertext if sealed else None

        if data.clear_allowed_tools:
            update_data["allowed_tools"] = None

        # URL or credentials changed → the previous check result is stale.
        if "url" in update_data or "auth_token" in update_data:
            update_data.setdefault("last_status", None)
            update_data.setdefault("last_error", None)
            update_data.setdefault("last_checked_at", None)

        # OAuth tokens are bound to the resource they were issued for - never
        # carry them over to a different host. The same safeguard the personal
        # path has, and here it is also a boundary between administrators: an
        # org connection's GitHub token must not follow a repointed URL to a
        # host another `mcp:manage` holder chose. The mirrored scopes go with
        # the token they described; the organization re-authorizes instead.
        moved = "url" in update_data and update_data["url"] != db_connection.url
        if moved and db_connection.auth_type == "oauth":
            update_data["oauth_payload"] = None
            update_data["oauth_pending_payload"] = None
            update_data["oauth_state"] = None
            update_data["granted_scopes"] = None

        # The same reason as on the personal path, and it matters more here:
        # every agent bound to this connection reads the Builder's cached tool
        # list, so a repointed URL would offer the old host's tools to all of
        # them at once.
        if moved:
            update_data.setdefault("last_tools", None)

        if not update_data:
            return db_connection
        return await mcp_connection_repo.update(
            self.db, db_connection=db_connection, update_data=update_data
        )

    async def delete_for_org(self, ctx: AuthContext, *, connection_id: UUID) -> None:
        db_connection = await self._get_org(ctx, connection_id)
        # Any trigger webhook this account registered is deregistered first,
        # while its token still exists, and the trigger falls back to manual -
        # otherwise the trigger FK's SET NULL trips the shape CHECK (a registered
        # hook with no account to remove it by) and the delete fails at flush.
        # Imported locally: the trigger service imports this module at module scope.
        from app.services.agent_trigger import AgentTriggerService

        await AgentTriggerService(self.db).release_connection(ctx, connection_id)
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

    async def webhook_access_token(
        self, ctx: AuthContext, connection_id: UUID, *, required_scopes: Sequence[str]
    ) -> str | None:
        """A live token for an org connection that consented to `required_scopes`.

        For the trigger portals: registering a provider webhook needs a scope a
        plain tool connection never requested, so this hands back a token only
        when the account was re-authorized for it. `None` - the connection lacks
        the scope, or its token cannot be refreshed - is the signal to fall back
        to manual setup, never an error. A connection in another tenant is still
        a `NotFoundError`, because a bad id is a client mistake, not a fallback.
        """
        connection = await self._get_org(ctx, connection_id)
        # Disabled means disabled everywhere: the agent tool path already skips a
        # disabled row, and a caller who kept a trigger's connection_id must not
        # be able to keep enumerating repositories or registering hooks with a
        # credential an administrator switched off.
        if not connection.is_enabled:
            return None
        if not set(required_scopes).issubset(connection.granted_scopes or ()):
            return None
        return await _oauth_access_token(self.db, connection)

    async def get_org_portal_grant(self, ctx: AuthContext, portal_key: str) -> McpConnection | None:
        """The organization's grant for one polled portal, or `None`.

        What tells a portal card that its mailbox is connected. A polled portal has
        no entry in the MCP server catalog - there is no server, only an account we
        read - so the catalog listing cannot find its connection the way an
        `auto_webhook` portal's is found, by catalog key.
        """
        return await mcp_connection_repo.get_portal_grant(
            self.db, organization_id=ctx.organization_id, portal_key=portal_key
        )

    async def get_org_portal_connection(
        self, ctx: AuthContext, connection_id: UUID
    ) -> McpConnection:
        """One *portal grant* by id, resolved for the caller's tenant.

        The counterpart of :meth:`get_org_connection` for a polled portal, whose
        grant is not an MCP connection and is deliberately invisible to every
        MCP-facing read. A trigger being created against a connected mailbox proves
        the id is its own organization's through here.

        Raises:
            NotFoundError: If no grant with this id is visible to the caller's
                organization - the same unprobeable refusal every org-scoped
                connection lookup gives.
        """
        grant = await mcp_connection_repo.get_org_scoped_portal_by_id(
            self.db, connection_id=connection_id, organization_id=ctx.organization_id
        )
        if grant is None:
            raise NotFoundError(
                message="Connection not found", details={"connection_id": connection_id}
            )
        return grant

    async def get_org_connection(self, ctx: AuthContext, connection_id: UUID) -> McpConnection:
        """One organization connection by id, resolved for the caller's tenant.

        The public form of the org-scoped lookup, for a caller that only needs to
        prove a `connection_id` belongs to its organization before storing it - a
        trigger persisting the account whose token registers its webhook. A
        connection in another tenant, or a bogus id, is a `NotFoundError`, the same
        unprobeable refusal `_get_org` gives every other org-scoped path.

        Raises:
            NotFoundError: If no connection with this id is visible to the caller's
                organization.
        """
        return await self._get_org(ctx, connection_id)

    async def _get_org(
        self, ctx: AuthContext, connection_id: UUID, *, for_update: bool = False
    ) -> McpConnection:
        """One organization connection, or a refusal that reveals nothing.

        Reported as "not found" rather than "forbidden" for the same reason as
        every other resource here: a distinguishable refusal turns an id into a
        probe for what another tenant owns.
        """
        db_connection = await mcp_connection_repo.get_org_scoped_by_id(
            self.db,
            connection_id=connection_id,
            organization_id=ctx.organization_id,
            for_update=for_update,
        )
        if db_connection is None:
            raise NotFoundError(
                message="MCP connection not found",
                details={"connection_id": str(connection_id)},
            )
        return db_connection


def _stored_label(label: str | None) -> str | None:
    """A label as the column holds it: trimmed, and empty means none.

    `""` is how a PATCH says "clear this" - `None` is the sentinel for
    "unchanged" everywhere in an update body, so it cannot also mean "remove".
    Storing the empty string instead would make a connection whose label was
    cleared render as a blank line rather than as its slug.
    """
    trimmed = (label or "").strip()
    return trimmed or None


PersonalServiceGapKind = Literal["nobody_to_speak_as", "not_connected", "undecided", "unauthorized"]


@dataclass(frozen=True)
class UnavailablePersonalService:
    """A personal binding this turn could not honour, and why.

    Each gap is a different sentence to the person talking, which is why the
    reason is a value rather than a log line: nobody at the keyboard, no
    connection of their own to this service, several with none marked default
    (#1342), or one whose credential no longer opens the server.
    """

    catalog_key: str
    gap: PersonalServiceGapKind


@dataclass(frozen=True)
class ResolvedMcpToolsets:
    """What a spec's MCP bindings amount to for one turn.

    The toolsets that could be built, and the personal bindings that could not.
    Two lists rather than one because the second is not a failure: a personal
    binding with nobody to speak as is the designed outcome on an API key or a
    schedule, and the run proceeds - told, in its instructions, what is missing
    and where the person connects it.
    """

    toolsets: list[Any]
    unavailable: list[UnavailablePersonalService]


async def build_toolsets_for_agent(
    db: AsyncSession,
    *,
    organization_id: UUID,
    refs: Sequence[McpServerRef],
    sender_user_id: UUID | None = None,
) -> ResolvedMcpToolsets:
    """Agent toolsets for a published agent: exactly the servers its spec names.

    Deliberately never the servers the person running the turn has enabled:
    what an agent can reach is part of the agent, and one that answers
    differently depending on whose Slack account triggered it cannot be
    reasoned about or reviewed. An organization binding resolves only an
    organization-scoped row, so a member's personal token never ends up behind
    a shared agent by accident.

    A **personal** binding is the one place a member's own connection is
    reached, and it is reached on purpose: the spec says every person speaks to
    this service as themselves. `sender_user_id` is who is talking - the author
    of this message, never the thread's first speaker - and `None` where nobody
    is: an API key, the widget, a schedule, a channel sender with no linked
    account. The binding is then reported unavailable rather than quietly
    skipped, so the run can say so and say where the person connects one.

    A person holding two accounts to one service is left alone rather than
    guessed at: they nominate one in their own connections, and until they do
    the binding is unavailable to them (#1342).

    Runs in the caller's session rather than opening its own: an OAuth refresh
    spent here has to be persisted by the same transaction that recorded the run.
    """
    specs: list[McpServerSpec] = []
    unavailable: list[UnavailablePersonalService] = []
    for ref in refs:
        if isinstance(ref, PersonalMcpServerRef):
            spec, gap = await _personal_spec(db, ref, sender_user_id=sender_user_id)
            if spec is not None:
                specs.append(spec)
            if gap is not None:
                unavailable.append(UnavailablePersonalService(ref.catalog_key, gap))
            continue
        connection = await mcp_connection_repo.get_org_scoped_by_id(
            db, connection_id=ref.connection_id, organization_id=organization_id
        )
        if connection is None or not connection.is_enabled:
            # Deleted, disabled or moved out of the organization since publish.
            # A binding that was already broken is refused at publish, where
            # somebody can still fix it; one that broke afterwards narrows the
            # agent instead of taking the conversation down with it.
            logger.warning(
                "Agent references MCP connection %s, which this organization (%s) no longer offers",
                ref.connection_id,
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
                "Skipping MCP connection %r for this run: no usable credentials",
                connection.name,
            )
            continue
        specs.append(
            McpServerSpec(
                name=connection.name,
                url=connection.url,
                headers=headers,
                allowed_tools=_narrowed_tools(connection.allowed_tools, ref.allowed_tools),
            )
        )
    return ResolvedMcpToolsets(toolsets=await build_mcp_toolsets(specs), unavailable=unavailable)


async def _personal_spec(
    db: AsyncSession, ref: PersonalMcpServerRef, *, sender_user_id: UUID | None
) -> tuple[McpServerSpec | None, PersonalServiceGapKind | None]:
    """The sender's own connection to this service as a server spec, or why not.

    The tool prefix is the catalog key rather than the connection's name: the
    agent presents `notion_search` to everyone, whatever each person called
    their own Notion. The allowlist is the binding's ceiling intersected with
    the person's own - the same fold an organization binding makes, with the
    administrator's side coming from the spec because there is no connection
    row of the organization's to read it from.
    """
    if sender_user_id is None:
        return None, "nobody_to_speak_as"
    owned = await mcp_connection_repo.list_user_scoped_by_catalog_key(
        db, user_id=sender_user_id, catalog_key=ref.catalog_key
    )
    connection = _nominated(owned)
    if connection is None:
        return None, "undecided" if owned else "not_connected"
    headers = await _resolve_auth_headers(db, connection)
    if headers is None:
        logger.info(
            "Skipping the sender's own %r connection for this run: no usable credentials",
            ref.catalog_key,
        )
        return None, "unauthorized"
    return (
        McpServerSpec(
            name=ref.catalog_key,
            url=connection.url,
            headers=headers,
            allowed_tools=_narrowed_tools(ref.allowed_tools, connection.allowed_tools),
        ),
        None,
    )


def _narrowed_tools(connection: list[str] | None, binding: list[str] | None) -> list[str] | None:
    """The tools this binding may call: both allowlists, intersected.

    Null on either side means "no narrowing from here" - the connection's null is
    every tool the server offers, and the binding's is every tool the connection
    allows. So the answer is null only when neither narrows.

    Intersected rather than overridden, and that is the whole rule: the
    connection's list is an administrator's ceiling for everybody bound to it,
    and an agent published before a tool was excluded must not keep reaching it.
    A binding naming a tool the connection has since excluded loses that tool
    rather than the agent losing the server (#1341).
    """
    if connection is None:
        return binding
    if binding is None:
        return connection
    within = set(binding)
    return [tool for tool in connection if tool in within]


def _nominated(owned: list[McpConnection]) -> McpConnection | None:
    """Which of a member's accounts on one service to speak as, if any is clear.

    One account needs no nomination - there is nothing to choose between - so it
    answers whether or not it is marked. Several answer only the one marked
    default, which a partial unique index keeps to at most one; several with none
    marked answer nothing, because picking the older workspace silently is worse
    than telling the person to pick (#1342).
    """
    if len(owned) == 1:
        return owned[0]
    return next((account for account in owned if account.is_default), None)
