"""Personal coding credentials, explicitly enabled in one organization."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class CodingAccount(Base, TimestampMixin):
    __tablename__ = "coding_accounts"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "harness"),
        CheckConstraint("harness IN ('claude_code', 'codex')", name="ck_coding_account_harness"),
        CheckConstraint(
            "secret_kind IN ('api_key', 'openai_codex')", name="ck_coding_account_kind"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    harness: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    secret_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    sealed_secret: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generation: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )

    def __repr__(self) -> str:
        return f"<CodingAccount(id={self.id}, user_id={self.user_id}, harness={self.harness})>"
