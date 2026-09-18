"""A system announcement an app admin sent (#1598).

The one action in this feature no organization-scoped role can reach - gated
on `CurrentAppAdmin` alone, never on a `Perm`, since every entry in the
permission catalog is resolved against one organization and none of them can
express "every organization" (`docs/design/notification-center-plan.md`,
Decision 5). Sending writes one row here, then fans out one
:class:`app.db.models.notification.Notification` row per resolved recipient
through the same write path and delivery pipeline every other event uses - an
announcement is not a second mechanism.

Deliberately outside Decision 8's retention sweep: purging the per-recipient
`notifications` rows a broadcast fanned out to is what that window is for, but
this row - what an app admin actually sent, and what `record_audit`'s
`announcement_id` points at - survives past it, so "what did an app admin
send, and when" stays answerable from the audit trail after ordinary
retention has cleared the individual deliveries.
"""

import uuid
from typing import Any

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Announcement(Base, TimestampMixin):
    """One system-wide message, sent by one app admin to an explicit audience."""

    __tablename__ = "announcements"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # No ForeignKey, deliberately - the same choice `AppAdminAuditLog` already
    # makes for `actor_user_id`. This row is audit-adjacent evidence of who
    # sent what and when; it must not become undeletable-by-cascade the moment
    # the sender's own account is later removed, and nothing here ever writes
    # through this column, only reads it for display.
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    audience_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # The human-readable rendering of `audience_spec` - "all organizations", or
    # "Acme, Globex - owners and admins" - computed once at send time so a
    # reader of the audit trail does not have to re-decode the JSON to know who
    # was addressed.
    audience_description: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"<Announcement(id={self.id}, actor_user_id={self.actor_user_id})>"
