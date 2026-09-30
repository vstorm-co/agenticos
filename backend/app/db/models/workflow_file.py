"""A file a workflow run produced - what a `FileRef` resolves to (#1791).

`FileRef` stays the thin reference the contracts define: an id, a declared type
and a size. The row is what gives the id meaning. It says which organization
the bytes belong to, which run made them and at which step, and where storage
keeps them. A handler never trusts a `FileRef` it is handed: it looks the row
up in its own organization and checks it belongs to its own run, or to one the
run was started with, so knowing an id grants nothing.

Every file is run-scoped. There is no organization-wide file here, which is
why a `FileRef` written into a graph must name one a run the author can see
produced.
"""

import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WorkflowFile(Base, TimestampMixin):
    """One stored file, owned by the run that produced it."""

    __tablename__ = "workflow_files"

    # The `FileRef.file_id` that names it.
    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Which step made it - lineage a run's history reads. SET NULL, like any
    # pointer at a step, so the file outlives nothing it should not.
    producing_node_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("node_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (CheckConstraint("byte_size >= 0", name="ck_workflow_file_byte_size"),)
