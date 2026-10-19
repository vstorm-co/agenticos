"""A person's saved sign-in to one site, for the web browser (#2129).

One row per (organization, person, site). The state - cookies and the origin's
`localStorage` - is sealed in `sealed_state` through :mod:`app.core.vault` under
the person's own scope, because it is their session on somebody else's site and
nobody else's to read. `secret_key_version` records which master key sealed it,
as on every sealed row, so the vault rotation sweeps it.

Kept per organization as well as per person: the browser a sign-in is handed to
is the organization's, so a sign-in kept through one organization's browser is
not given to another's.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BrowserSignIn(Base, TimestampMixin):
    """One person's sign-in to one site, saved when they handed the browser back."""

    __tablename__ = "browser_sign_ins"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", "site"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site: Mapped[str] = mapped_column(String(253), nullable=False)
    sealed_state: Mapped[str] = mapped_column(Text, nullable=False)
    secret_key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<BrowserSignIn(id={self.id}, user_id={self.user_id}, site={self.site})>"
