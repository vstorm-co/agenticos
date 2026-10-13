"""Per-organization high-water mark of the audit hash chain (#1648)."""

import uuid

from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AppAdminAuditCheckpoint(Base, TimestampMixin):
    """The furthest each organization's audit chain has reached.

    A bare hash chain (`app_admin_audit_logs`, #1622) catches an edited, reordered,
    inserted or interior-deleted entry, because any of those diverges every hash
    after it. It cannot catch the two deletions that leave the survivors internally
    consistent: the newest entries dropped from a chain, and a whole chain deleted -
    which just vanishes from the walk. This row is the trusted high-water mark those
    two need. `record_audit` advances it under the same per-organization lock it
    appends the entry under, so it never lags or races; a database trigger forbids it
    moving backwards or being deleted; and `agenticos cmd audit-verify` flags a chain
    whose head is behind it, or an organization whose chain is gone.

    Detection against tampering through the application's own database access, which
    is the trail's threat model (an app admin's bypass). Not prevention against a
    Postgres superuser, who can drop the trigger and delete both this row and the
    entries - that needs a checkpoint kept outside this database, which #1648 tracks
    as the next step.

    Attributes:
        organization_id: The chain this checkpoints, or None for the deployment-wide
            chain. Unique with NULLs treated as equal, so the deployment chain has
            exactly one checkpoint and `record_audit`'s upsert can target it.
        max_seq: The largest `seq` this chain has held - a head now below it means
            the tail was truncated.
        entry_count: How many entries this chain has held - a count now below it
            means entries were deleted.
        head_entry_hash: The head entry's hash when the checkpoint was last advanced.
    """

    __tablename__ = "app_admin_audit_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            name="app_admin_audit_checkpoints_organization_id_key",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    max_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    head_entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    def __repr__(self) -> str:
        return f"<AppAdminAuditCheckpoint(org={self.organization_id}, max_seq={self.max_seq})>"
