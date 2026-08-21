"""Read schemas for the trigger-portals catalog.

What the picker needs to draw a portal and its presets, and nothing it does not:
the OAuth scopes a portal registers with are an implementation detail of the
create flow, never sent to the browser.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class PortalPresetRead(BaseSchema):
    """One ready-made event a portal can fire on."""

    key: str
    label: str
    description: str
    target_required: bool = Field(
        description="Whether this preset needs a target (which repository) before it can be set up",
    )


class PortalRead(BaseSchema):
    """One connectable service and the events it fires an agent on."""

    key: str
    name: str
    description: str
    category: str
    icon: str | None = None
    event_source: str
    delivery: str = Field(
        description="auto_webhook (platform registers the webhook), manual (paste a URL), or polling",
    )
    target_kind: str | None = Field(
        default=None, description="What a preset's target names - 'repo', 'channel' - or null"
    )
    connection_catalog_key: str | None = Field(
        default=None,
        description="The mcp_servers.json key this portal shares a connection with, for joining connection state",
    )
    webhook_admin_scopes: list[str] = Field(
        default_factory=list,
        description="OAuth scopes the account must carry to auto-register the webhook; the picker checks these against a connection's granted_scopes to decide whether to offer re-authorization",
    )
    connection_id: UUID | None = Field(
        default=None,
        description=(
            "The organization's connection for this portal's catalog entry, or null "
            "when nobody has connected it. Carried on the catalog so a caller who "
            "may create a trigger (agents:run, per agent) sees the connected state "
            "without the mcp:manage-gated connection listing - a Member who cannot "
            "manage connections still needs to know the account is there to use"
        ),
    )
    connection_state: Literal["connected", "needs_authorization", "disabled", "error"] | None = (
        Field(
            default=None,
            description=(
                "How usable that connection is, resolved server-side: authorized and "
                "enabled with no failing check is connected; an OAuth row whose "
                "consent never landed needs authorization; the rest name themselves. "
                "Null exactly when connection_id is null"
            ),
        )
    )
    connect_blocked_by: Literal["oauth_app_secret", "ambiguous_oauth_app_secret"] | None = Field(
        default=None,
        description=(
            "Why connecting this portal cannot start yet, or null when it can. "
            "GitHub's flow spends the organization's own OAuth App credentials, so "
            "with none stored - or with two org-visible ones and no way to know "
            "which was meant - pressing Connect can only fail. Answered on the "
            "catalog so the card says the prerequisite before the click instead of "
            "after it, as a red toast"
        ),
    )
    connection_covers_webhook_scopes: bool = Field(
        default=False,
        description=(
            "Whether the connection's granted scopes include every webhook_admin_scope "
            "this portal registers with - the create-vs-reauthorize decision, answered "
            "without exposing what was granted"
        ),
    )
    presets: list[PortalPresetRead]


class PortalCatalog(BaseSchema):
    items: list[PortalRead]
    total: int


class PortalTargetRead(BaseSchema):
    """One place a preset can point at - a repository, a channel."""

    id: str
    label: str


class PortalTargetList(BaseSchema):
    items: list[PortalTargetRead]
    total: int
