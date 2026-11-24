"""A secret an agent asked its person for, mid-run.

The request is the durable record of the ask - which secret, what it is
for, who was asked, and what happened to it - while the value itself is
never stored here. On fulfil the value is sealed straight into
`organization_secrets` by `OrganizationSecretService.create`, and this row
keeps only the created secret's id, name and hint. A row that held the value
would put it in the run's read path, the audit trail and every listing that
touches it; a reference cannot leak what it does not hold.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SecretRequestStatus:
    """What happened to a secret request."""

    PENDING = "pending"
    FULFILLED = "fulfilled"
    DECLINED = "declined"
    EXPIRED = "expired"


class SecretRequest(Base, TimestampMixin):
    """One ask for a secret, from the agent that raised it to the person who answers it."""

    __tablename__ = "secret_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The tool call that raised the request, so the fulfil can resume it and
    # the card can match the request to the step that asked.
    tool_call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # The name the secret is stored under, and the shape the vault seals it
    # as - both copied from the tool call, so the card reads them without
    # re-parsing the run's parked messages.
    secret_name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="api_key")
    # What the secret is for, in the agent's own words, as the card shows it.
    what_for: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SecretRequestStatus.PENDING, index=True
    )
    # The secret the fulfil created, once there is one. `SET NULL` rather
    # than cascade: deleting the secret must not delete the record that
    # somebody supplied it.
    fulfilled_secret_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization_secrets.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The hint of the stored secret - its last four characters - so the card
    # can show which secret was provided without ever holding the value.
    fulfilled_hint: Mapped[str | None] = mapped_column(String(8), nullable=True)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
