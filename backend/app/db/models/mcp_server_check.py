"""What the last catalog check found when it called one listed MCP server (#2103)."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class CheckOutcome(StrEnum):
    """What calling a listed server found. `app.services.mcp_audit` says how."""

    OPEN = "open"
    SIGN_IN = "sign_in"
    TOKEN = "token"
    UNREACHABLE = "unreachable"
    BROKEN = "broken"
    REFUSED = "refused"
    DUPLICATE = "duplicate"
    SELF_HOSTED = "self_hosted"


NOT_OFFERED: frozenset[str] = frozenset(
    {CheckOutcome.UNREACHABLE, CheckOutcome.BROKEN, CheckOutcome.REFUSED, CheckOutcome.DUPLICATE}
)
"""Outcomes that take a *mirrored* listing off the console's list.

A curated entry is never hidden by a check: somebody chose it, so a failed
check is a finding for whoever keeps the catalog, not a reason to make the
entry vanish from under the organizations already using it."""


class McpServerCheck(Base, TimestampMixin):
    """One listing's last check: did it answer, and what did it ask for.

    Keyed on the listing rather than on a URL, because the question the console
    asks is about a row it shows - a curated entry by its catalog key, a mirrored
    one by its registry name - and two listings at one URL are exactly what the
    check exists to find. No foreign key to `mcp_registry_servers`: the curated
    catalog is a file, not a table, and a check outliving a pruned registry row
    is harmless (`agenticos cmd mcp-catalog-check` prunes it on its next full
    run).

    Deployment-wide like the two catalogs it describes, and written only by that
    command and by the bundled snapshot seeded beside the registry mirror.
    """

    __tablename__ = "mcp_server_checks"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    """`catalog` or `registry` - which list the key belongs to."""

    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    """A `CheckOutcome` from `app.services.mcp_audit`."""

    auth: Mapped[str | None] = mapped_column(String(8), nullable=True)
    """What the server asked for - `none`, `token` or `oauth` - when it answered."""

    tools: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """How many tools `tools/list` returned without a credential; null where the
    check could not get that far. Counts rather than the list: the console shows
    how many and how many only read, and the operator's report keeps the names."""

    read_only_tools: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """How many of those the server marks `readOnlyHint`."""

    duplicate_of: Mapped[str | None] = mapped_column(String(255), nullable=True)
    """The listing kept in this one's place, when two listings are one server."""

    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("mcp_server_checks_outcome_idx", "outcome"),)

    def __repr__(self) -> str:
        return f"<McpServerCheck(key={self.key}, outcome={self.outcome})>"
