"""One person's favourite app."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.artifact import Artifact
    from app.db.models.user import User


class ArtifactFavourite(Base, TimestampMixin):
    """A row per reader and artifact; a favourite belongs to the reader."""

    __tablename__ = "artifact_favourites"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    user: Mapped[User] = relationship("User", foreign_keys="ArtifactFavourite.user_id")
    artifact: Mapped[Artifact] = relationship(
        "Artifact", foreign_keys="ArtifactFavourite.artifact_id"
    )

    def __repr__(self) -> str:
        return f"<ArtifactFavourite(user_id={self.user_id}, artifact_id={self.artifact_id})>"
