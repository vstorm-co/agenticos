"""Read schemas for the trigger-portals catalog.

What the picker needs to draw a portal and its presets, and nothing it does not:
the OAuth scopes a portal registers with are an implementation detail of the
create flow, never sent to the browser.
"""

from __future__ import annotations

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
    presets: list[PortalPresetRead]


class PortalCatalog(BaseSchema):
    items: list[PortalRead]
    total: int
