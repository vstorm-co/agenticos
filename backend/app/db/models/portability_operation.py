"""Private, expiring journals for resumable resource bundle transfers."""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PortabilityOperation(Base, TimestampMixin):
    __tablename__ = "portability_operations"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "request_id"),
        CheckConstraint("direction IN ('export', 'import')", name="direction"),
        CheckConstraint("phase IN ('prepare', 'apply')", name="phase"),
        CheckConstraint(
            "status IN ('awaiting_upload', 'queued', 'running', 'review', 'needs_bindings', 'ready', 'failed', 'expired')",
            name="status",
        ),
        CheckConstraint("revision >= 1 AND worker_attempt >= 0", name="revision"),
        CheckConstraint("source_bytes >= 0", name="source_bytes"),
        CheckConstraint(
            "jsonb_typeof(request) = 'object' "
            "AND (manifest IS NULL OR jsonb_typeof(manifest) = 'object') "
            "AND (choices IS NULL OR jsonb_typeof(choices) = 'object') "
            "AND (result IS NULL OR jsonb_typeof(result) = 'object')",
            name="payload_objects",
        ),
        CheckConstraint(
            "status NOT IN ('review', 'needs_bindings', 'ready') OR manifest IS NOT NULL",
            name="review_manifest",
        ),
        CheckConstraint(
            "status != 'ready' OR ((direction = 'export' AND output_path IS NOT NULL) OR (direction = 'import' AND result IS NOT NULL))",
            name="ready_result",
        ),
        CheckConstraint("completed_bytes >= 0 AND total_bytes >= completed_bytes", name="progress"),
        Index(
            "portability_operations_owner_created_idx",
            "organization_id",
            "user_id",
            "created_at",
            "id",
        ),
        Index("portability_operations_expiry_idx", "expires_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Retain a deleted key's identity: it must never become session authority.
    api_key_id: Mapped[UUID | None] = mapped_column()
    request_id: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(16))
    phase: Mapped[str] = mapped_column(String(16), default="prepare")
    status: Mapped[str] = mapped_column(String(24))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    worker_attempt: Mapped[int] = mapped_column(Integer, default=0)
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("background_jobs.id", ondelete="SET NULL")
    )
    request: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    manifest: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB(none_as_null=True))
    choices: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB(none_as_null=True))
    result: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB(none_as_null=True))
    source_path: Mapped[str | None] = mapped_column(String(1024))
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    source_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    output_path: Mapped[str | None] = mapped_column(String(1024))
    completed_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"PortabilityOperation(id={self.id}, direction={self.direction!r}, status={self.status!r})"
