"""A file an agent generated: who it belongs to, how large it is, and where it came from.

The bytes live in the file store under the organization's `generated_<id>/`
directory (`app/services/generated_media.py`); this row is the bookkeeping that
gives them a bound and a lifetime (#2310). Without it nothing knew how much an
organization had generated, or which conversation a clip belonged to, so a
deleted conversation left its images, speech and video in storage for good.

The row is not what *serves* a file. The serving route still resolves a leaf
name inside the caller's own organization directory, so a file written before
this table existed - which has no row - is served exactly as before.
"""

import uuid

from sqlalchemy import BigInteger, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class GeneratedMedia(Base, TimestampMixin):
    """One stored generated file, counted against its organization's quota."""

    __tablename__ = "generated_media"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # `SET NULL`, not `CASCADE`: a conversation deleted by a path that does not
    # unlink its media first must leave the row behind, so the retention sweep can
    # still find the bytes. A cascade would delete the only record of them.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Unique within the organization, which is the scope a leaf is served in: the
    # serving route resolves a name inside the caller's own directory, so two
    # organizations holding the same leaf are two different files.
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "filename", name="uq_generated_media_org_filename"),
        # The retention sweep walks the table oldest first, across every organization.
        Index("ix_generated_media_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<GeneratedMedia(id={self.id}, filename={self.filename}, size={self.size_bytes})>"


class GeneratedMediaReservation(Base, TimestampMixin):
    """Quota held for one generation call in flight, until its file is recorded.

    The quota is asked before a paid call and the file is recorded only after it,
    minutes later for a clip. Without a claim in between, every call admitted
    under the limit at once could finish, together far past it. So admission,
    under a per-organization lock, writes one of these with the call's estimated
    size; `bytes_used` and these together are what the next admission is measured
    against. Recording the file replaces it with the real size; a call that makes
    nothing releases it; a call that died with its process leaves it to expire
    (`app/services/generated_media.py`).
    """

    __tablename__ = "generated_media_reservations"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # The sweep removes expired claims across every organization by age.
    __table_args__ = (Index("ix_generated_media_reservations_created", "created_at"),)

    def __repr__(self) -> str:
        return f"<GeneratedMediaReservation(id={self.id}, size={self.size_bytes})>"
