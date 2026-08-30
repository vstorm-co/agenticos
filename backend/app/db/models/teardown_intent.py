"""What a deleted tenant left behind, recorded before the delete commits.

`OrganizationService.purge` removes an organization's rows and hands the
external side effects - unlinking stored uploads, dropping vector tables - to a
Prefect flow. #1274 made the *run* durable: it is recorded on the Prefect server
and retried by a worker, so a process that dies mid-cleanup no longer takes the
work with it.

What that leaves is the window between the commit and the dispatch. A crash
there loses the cleanup with nothing left to reconstruct it: the committed delete
has already removed the document paths and collection names a retry would need
to find (#1269). So the intent is committed *with* the delete, and the dispatch
becomes an optimisation rather than the only chance - a sweep re-dispatches any
row nothing has finished.

The row is the record and its absence is the completion: the flow deletes it once
the work is done, so an empty table means nothing is outstanding.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TeardownIntent(Base, TimestampMixin):
    """External state one purge released, and has not yet finished releasing."""

    __tablename__ = "teardown_intents"
    __table_args__ = (
        # What the sweep reads: the oldest unfinished intent first. Partial on
        # the dispatch time so a fleet with nothing outstanding scans an empty
        # index rather than the table.
        Index("ix_teardown_intents_sweep", "dispatched_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The organization this released, for a log line and for somebody reading the
    # table during an incident. Not a foreign key: the row it names is gone by
    # the time this is read, which is the whole point of recording it.
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="org_purge")
    storage_paths: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    collections: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # When the cleanup was last handed to a worker, or NULL for one that never
    # was - a crash between the commit and the dispatch. The sweep re-dispatches
    # both: a NULL, and a stamp old enough that the run it names is not coming
    # back.
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    def __repr__(self) -> str:
        return (
            f"<TeardownIntent(id={self.id}, organization_id={self.organization_id}, "
            f"paths={len(self.storage_paths)}, collections={len(self.collections)})>"
        )
