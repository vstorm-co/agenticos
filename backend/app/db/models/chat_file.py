"""ChatFile database model - stores metadata for files uploaded in chat."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ChatFile(Base, TimestampMixin):
    """Tracks files uploaded by users in chat conversations."""

    __tablename__ = "chat_files"
    __table_args__ = (
        CheckConstraint(
            "message_id IS NULL OR queue_receipt_id IS NULL",
            name="ck_chat_file_message_or_queue",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    queue_receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "accepted_queued_messages.id", ondelete="SET NULL", name="fk_chat_files_queue_receipt"
        ),
        nullable=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    parsed_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ChatFile(id={self.id}, filename={self.filename}, type={self.file_type})>"
