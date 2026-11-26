"""Reusable ChatGPT application registration, separate from rotating grants."""

from uuid import UUID, uuid4

from sqlalchemy import ForeignKeyConstraint, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ChatGPTRegistration(Base, TimestampMixin):
    __tablename__ = "chatgpt_registrations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            name="chatgpt_registrations_membership_fkey",
            ondelete="CASCADE",
        ),
    )
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, index=True)
    host_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid4)
    client_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    generation: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid4)

    def __repr__(self) -> str:
        return (
            f"<ChatGPTRegistration(organization_id={self.organization_id}, user_id={self.user_id})>"
        )
