"""What one run handed its model, kept beside the run rather than on it.

A table of its own, and that is the whole design decision. The document is large
- a system prompt, every tool's JSON schema, and the last request's messages -
and `agent_runs` is the most-listed table in the product: run history, the spend
tab, the dashboard figures and the CSV export all select rows from it fifty at a
time. A JSONB column there would be read by every one of those queries to answer
a question none of them asks.

So it is one row per run, written once when the run ends, read only by the run
detail. `ondelete="CASCADE"` from both sides: a deleted run takes its manifest,
and so does a deleted organization.

The payload is stored as it was recorded (`app/agents/manifest.py`) and is
deliberately not modelled column by column. What a provider is handed changes
with the library, and a schema that has to be migrated every time Pydantic AI
adds a field is a schema that stops being written to. `RunManifestRead` is what
gives it a shape on the way out.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base, TimestampMixin


class RunManifest(Base, TimestampMixin):
    """One run's record of what reached the model."""

    __tablename__ = "run_manifests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: Whether the messages were dropped to keep the row within its size ceiling.
    #: A reader must be able to tell a run that sent nothing from a run whose
    #: record was trimmed, which is the difference between a fact and an artefact.
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<RunManifest(run={self.run_id}, truncated={self.truncated})>"
