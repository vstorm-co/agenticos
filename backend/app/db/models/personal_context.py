"""Rebuildable, private work-index checkpoints owned by an organization membership."""

from uuid import UUID

from sqlalchemy import ForeignKeyConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PersonalContextCache(Base, TimestampMixin):
    __tablename__ = "personal_context_cache"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            ondelete="CASCADE",
            name="fk_personal_context_member",
        ),
    )
    organization_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    def __repr__(self) -> str:
        return f"<PersonalContextCache(user={self.user_id}, key={self.source_key})>"
