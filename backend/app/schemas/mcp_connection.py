"""Schemas for user-configured MCP server connections."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.db.models.mcp_connection import McpConnection
from app.schemas.base import BaseSchema, TimestampSchema

# Slug-style names: lowercase letters, digits, hyphens. The name doubles as
# the tool prefix in the agent (sanitized to snake_case), so keep it tight.
NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"

MAX_ALLOWED_TOOLS = 100


class McpToolRead(BaseSchema):
    name: str
    description: str


class McpConnectionCreate(BaseSchema):
    name: str = Field(..., min_length=1, max_length=32, pattern=NAME_PATTERN)
    url: str = Field(..., min_length=1, max_length=2048)
    # Sent as "Authorization: Bearer <token>" to the MCP server.
    auth_token: str | None = Field(default=None, max_length=4096)
    # None = expose every tool the server offers.
    allowed_tools: list[str] | None = Field(default=None, max_length=MAX_ALLOWED_TOOLS)
    is_enabled: bool = True
    label: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "What a person reads. `name` is the tool prefix and is constrained "
            "to what a tool name can carry, which makes it a poor label for two "
            "accounts on one service. Optional; the slug is shown when it is absent."
        ),
    )


class McpConnectionUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=32, pattern=NAME_PATTERN)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    # None = leave unchanged; "" = clear the stored token.
    auth_token: str | None = Field(default=None, max_length=4096)
    allowed_tools: list[str] | None = Field(default=None, max_length=MAX_ALLOWED_TOOLS)
    # Explicit marker to reset allowed_tools back to "all tools" (since None
    # in a PATCH body is indistinguishable from "not provided").
    clear_allowed_tools: bool = False
    is_enabled: bool | None = None
    label: str | None = Field(
        default=None,
        max_length=64,
        description=(
            'What a person reads, beside the slug the model does. `""` clears '
            "it, which is how a connection goes back to showing its name; `null` "
            "leaves it unchanged, as everywhere in a PATCH body."
        ),
    )
    is_default: bool | None = Field(
        default=None,
        description=(
            "Speak as this account, where an agent binding asked for the "
            "member's own and they hold several on this service. Setting it "
            "clears the flag on the others (#1342)."
        ),
    )


class McpConnectionRead(TimestampSchema, BaseSchema):
    id: UUID
    name: str
    url: str
    # The token itself never leaves the backend.
    has_auth_token: bool
    allowed_tools: list[str] | None
    is_enabled: bool
    # "bearer" or "oauth".
    auth_type: str
    # OAuth connection that has completed the consent flow (has usable tokens).
    # False for a bearer connection or an OAuth connection still awaiting consent.
    oauth_authorized: bool
    # The OAuth scopes the account consented to, so a caller can tell whether a
    # connection carries a scope a feature needs (a trigger portal's webhook-admin
    # scope). Scope names describe breadth, not a credential, so they are safe to
    # show; null on a bearer connection or one not yet authorized.
    granted_scopes: list[str] | None = None
    last_status: str | None
    last_error: str | None
    last_checked_at: datetime | None
    # Which catalog entry this points at, where it was connected from one. On
    # the personal read as well as the organization's, because it is what says a
    # member's Notion and the organization's are the same service - the join the
    # substitution is made on.
    catalog_key: str | None = None
    # What a person reads, where somebody set one. Null is not a gap to fill in:
    # the slug is what the connection was always shown as.
    label: str | None = None
    # Every tool the server offered when it was last reached, so a Builder can
    # list them without holding the permission the probe needs. Null means
    # nothing has asked yet, which is not the same as "offers none".
    last_tools: list[McpToolRead] | None = None
    # Whether an agent speaking as this member uses this account. Only ever true
    # for one of their connections per service.
    is_default: bool = False

    @classmethod
    def from_model(cls, connection: McpConnection) -> McpConnectionRead:
        # Authorized once the live payload is written, which happens only after
        # a successful token exchange - this avoids decrypting it just to render
        # the list. A pending re-authorization lives in oauth_pending_payload
        # and must not flip a working connection back to "not connected".
        oauth_authorized = connection.auth_type == "oauth" and connection.oauth_payload is not None
        return cls(
            id=connection.id,
            name=connection.name,
            url=connection.url,
            has_auth_token=connection.auth_token is not None,
            allowed_tools=connection.allowed_tools,
            is_enabled=connection.is_enabled,
            auth_type=connection.auth_type,
            oauth_authorized=oauth_authorized,
            granted_scopes=connection.granted_scopes,
            last_status=connection.last_status,
            last_error=connection.last_error,
            last_checked_at=connection.last_checked_at,
            catalog_key=connection.catalog_key,
            label=connection.label,
            last_tools=(
                None
                if connection.last_tools is None
                else [McpToolRead(**tool) for tool in connection.last_tools]
            ),
            is_default=connection.is_default,
            created_at=connection.created_at,
            updated_at=connection.updated_at,
        )


class McpConnectionList(BaseSchema):
    items: list[McpConnectionRead]
    total: int


class OrgMcpConnectionCreate(BaseSchema):
    """A server the whole organization connects, not one person.

    No OAuth field, and that is deliberate rather than unfinished: an OAuth
    grant is obtained by one human at a consent screen, and storing it as the
    organization's would attribute one member's access to everybody and revoke
    every agent's reach the day that member's account is closed. Organization
    connections take a service credential, which is a thing an organization can
    actually own.
    """

    name: str = Field(..., min_length=1, max_length=32, pattern=NAME_PATTERN)
    url: str = Field(..., min_length=1, max_length=2048)
    # Sealed for this organization before it is stored, and never read back.
    auth_token: str | None = Field(default=None, max_length=4096)
    allowed_tools: list[str] | None = Field(default=None, max_length=MAX_ALLOWED_TOOLS)
    is_enabled: bool = True
    label: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "What a person reads. `name` is the tool prefix and is constrained "
            "to what a tool name can carry, which makes it a poor label for two "
            "accounts on one service. Optional; the slug is shown when it is absent."
        ),
    )
    # Which catalog entry this came from, when it did not come from a raw URL.
    catalog_key: str | None = Field(default=None, max_length=64)


class OrgMcpConnectionUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=32, pattern=NAME_PATTERN)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    # None = leave unchanged; "" = clear the stored token.
    auth_token: str | None = Field(default=None, max_length=4096)
    allowed_tools: list[str] | None = Field(default=None, max_length=MAX_ALLOWED_TOOLS)
    clear_allowed_tools: bool = False
    is_enabled: bool | None = None
    label: str | None = Field(
        default=None,
        max_length=64,
        description=(
            'What a person reads, beside the slug the model does. `""` clears '
            "it, which is how a connection goes back to showing its name; `null` "
            "leaves it unchanged, as everywhere in a PATCH body."
        ),
    )


class OrgMcpConnectionList(BaseSchema):
    """An organization's connections.

    Its own list rather than `McpConnectionList` because the two are different
    collections behind different permissions; the *rows* are the same shape, and
    were only ever a subclass to add `catalog_key` - which every connection has
    now that the substitution joins a member's account to the organization's on
    it (#1342).
    """

    items: list[McpConnectionRead]
    total: int


class McpConnectionTestResult(BaseSchema):
    ok: bool
    error: str | None = None
    tools: list[McpToolRead] = []


class McpOAuthStart(BaseSchema):
    """Begin the OAuth flow for a server (catalog or custom)."""

    name: str = Field(..., min_length=1, max_length=32, pattern=NAME_PATTERN)
    url: str = Field(..., min_length=1, max_length=2048)


class GithubOAuthStart(BaseSchema):
    """Begin the GitHub OAuth App flow for a trigger portal.

    Carries the portal key, not a URL or a name: the endpoints are GitHub's fixed
    ones, the client credentials come from the organization's stored
    `github_oauth_app` secret, and the connection is named after the portal's MCP
    catalog entry - so nothing about the server is the caller's to choose.
    """

    portal_key: str = Field(..., min_length=1, max_length=64)


class McpOAuthStartResult(BaseSchema):
    # The provider consent URL the browser should be redirected to.
    authorization_url: str


class McpOAuthCallback(BaseSchema):
    """Payload the frontend callback route forwards from the provider redirect."""

    state: str = Field(..., min_length=1, max_length=128)
    code: str = Field(..., min_length=1, max_length=4096)


class McpOAuthCallbackResult(BaseSchema):
    ok: bool
    connection_name: str | None = None
    error: str | None = None
