"""One vault-backed identity per database, shared by API and worker replicas."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DiagnosticsIdentity(Base, TimestampMixin):
    __tablename__ = "diagnostics_identity"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    sealed_seed: Mapped[str] = mapped_column(Text, nullable=False)
    secret_key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    last_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(16))

    def __repr__(self) -> str:
        return "<DiagnosticsIdentity(singleton)>"
