"""Receipts serialize same-principal installations; no manifest or secret is retained."""

from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SolutionInstallation(Base, TimestampMixin):
    __tablename__ = "solution_installations"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", "installation_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    installation_key: Mapped[str] = mapped_column(String(48))
    manifest_hash: Mapped[str] = mapped_column(String(64))
    resources: Mapped[dict[str, dict[str, str]]] = mapped_column(JSONB)

    def __repr__(self) -> str:
        return f"SolutionInstallation(id={self.id}, installation_key={self.installation_key!r})"
