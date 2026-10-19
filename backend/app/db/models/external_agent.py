"""An agent from another vendor this organization can delegate to, over A2A (#2092).

Registered by the URL of its agent card, which is read and validated when it is
added and kept as a snapshot: what an author reviewed when they picked it as a
delegate is what the runner calls, until somebody refreshes it. A credential, when
the agent wants one, is a vault secret the row names - never a value on the row.
"""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ExternalAgent(Base, TimestampMixin):
    """One remote A2A agent, as its card described it."""

    __tablename__ = "external_agents"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_external_agent_org_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    """The name a delegating model calls it by, unique in the organization."""

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    card_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    """Where its JSON-RPC requests go: the card's `url`, checked like the card's own."""

    card: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """The card as it was read, for showing what it says it does."""

    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization_secrets.id", ondelete="CASCADE"),
        nullable=True,
        # The cascade from a deleted secret finds its registrations through this.
        index=True,
    )
    """The vault secret sent as its bearer token, if it asks for one.

    Deleting the secret deletes the registration. Left behind as `NULL` it would
    read as one that never had a key, and its next call would go out
    unauthenticated rather than failing - a run naming a removed registration
    fails loudly instead.
    """

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<ExternalAgent(id={self.id}, slug={self.slug})>"
