"""A visual an agent drew, as an index entry - never its content (#2171).

The drawing itself lives in the tool call that carried it, in the transcript,
and its pictures under the thread's media prefix. This row is what a listing
needs without reading transcripts: whose it is, what it is called, where it
was drawn, the app it was saved as, and where its thumbnail is kept. It goes
with its conversation.
"""

import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Visual(Base, TimestampMixin):
    """One drawing or revision, by the tool call that made it."""

    __tablename__ = "visuals"
    __table_args__ = (
        UniqueConstraint("conversation_id", "tool_call_id"),
        Index("visuals_owner_recent_idx", "organization_id", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    tool_call_id: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    # The person the run drew it for; null for a run that acted for nobody.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    revision_of: Mapped[str | None] = mapped_column(String(100), nullable=True)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True
    )
    thumbnail_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<Visual(id={self.id}, tool_call_id={self.tool_call_id}, kind={self.kind})>"
