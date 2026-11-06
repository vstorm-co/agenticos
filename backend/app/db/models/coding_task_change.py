"""What one coding-agent task changed in its sandbox (#2480)."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class CodingTaskChange(Base, TimestampMixin):
    """The change set of one `run_coding_agent` task, read by the panel that shows the task.

    Its own row rather than a field of the tool call's result: the result is what
    the model reads back, and a patch of hundreds of kilobytes there would be paid
    for on every later turn. The result names this row's id instead.

    Bound to the conversation the task ran in, and read with exactly the access
    that reads that conversation's transcript; deleting the conversation deletes
    it. `files` is the `ChangeSet` file list, each entry carrying its part of the
    patch, already bounded where it was captured.
    """

    __tablename__ = "coding_task_changes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    harness: Mapped[str] = mapped_column(String(20), nullable=False)
    files: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)
    omitted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<CodingTaskChange(id={self.id}, conversation_id={self.conversation_id})>"
