"""One server the public MCP registry knows, as a row this deployment holds."""

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class McpRegistryServer(Base, TimestampMixin):
    """A mirrored registry entry, searchable in SQL and paged like any listing.

    **Deployment-wide, with no `organization_id`**, which is the whole reason this
    is a table rather than seventy thousand rows. The skill gallery settled the
    other case and settled it the other way: seventy industry skills seeded per
    tenant would be seventy rows nobody asked for in every organization on the
    next deploy, so that one is opt-in and never seeded. A *catalog* is not
    tenant data - it is the same list for everybody on the box - so one global
    table of it is one table, not one per tenant, and nothing an organization did
    or did not ask for changes.

    Held here rather than read out of the JSON on every request because the JSON
    cannot be paged. 5,703 entries in memory can answer "servers matching
    'linear'" and cannot answer "the fourth page of all of them" without loading
    the lot and slicing it - which is what made the console show a hundred and
    hide the rest behind a query.

    Seeded from `app/core/catalog/mcp_registry.json` and refreshed by
    `agenticos cmd mcp-registry-sync`, which is also what makes this different
    from the curated catalog: that one changes when somebody edits a file and
    redeploys, and this one can change without a deploy because it is a mirror of
    somebody else's list.

    Nothing here is reviewed. The description is the publisher's, and there is no
    token hint because the registry has no such field - which is why the console
    badges these rows rather than presenting them as catalog entries.
    """

    __tablename__ = "mcp_registry_servers"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    """The registry's own reverse-DNS name, e.g. `com.example/server`.

    The primary key, because it is the identity the upstream registry assigns and
    the thing a refresh matches on. A surrogate uuid would need a unique index on
    this anyway, and then two keys for one identity.
    """

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    """The URL's hostname, stored rather than parsed per query.

    Somebody holding a URL and wanting the name searches on this, and a
    `LIKE` against a parsed-out substring of `url` could not use an index.
    """

    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    """When the sync that wrote this row ran.

    A row the current sync did not touch is one the upstream registry no longer
    lists, which is how a delisted server is removed rather than kept for ever.
    """

    __table_args__ = (
        # Name first because that is the band that decides the ranking: the server
        # *called* Linear has to come before the fourteen mentioning it.
        Index("mcp_registry_servers_name_idx", "name"),
        Index("mcp_registry_servers_host_idx", "host"),
        Index("mcp_registry_servers_synced_at_idx", "synced_at"),
    )

    def __repr__(self) -> str:
        return f"<McpRegistryServer(id={self.id}, host={self.host})>"
