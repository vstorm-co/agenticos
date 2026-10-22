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

from sqlalchemy import BigInteger, ForeignKey, Index, String
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
    filename: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # The retention sweep walks the table oldest first, across every organization.
    __table_args__ = (Index("ix_generated_media_created", "created_at"),)

    def __repr__(self) -> str:
        return f"<GeneratedMedia(id={self.id}, filename={self.filename}, size={self.size_bytes})>"
