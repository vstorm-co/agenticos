"""Datasets - the questions an agent is tested on, kept as versioned cases.

A dataset is an owned, shareable resource like a skill or a context file: an
owner, a visibility and grants decide who reads, edits and runs it. What it
holds is cases - an input to answer, optionally a reference answer, the tool
calls the agent is expected to make and the checks to apply.

**Every change to the cases mints a version, and a version never changes.** An
eval run points at a version, so two runs over the same version saw the same
questions and their results compare. That is three tables rather than one:

- `dataset_cases` holds case *revisions*. A row's content is never updated;
  editing a case writes a new row with the same `case_id`, so the version that
  held the old one still reads it. The links to where a case came from are the
  one thing cleared later - when that conversation or its author is deleted.
- `dataset_versions` is one row per change, numbered from 1 within a dataset.
- `dataset_version_cases` says which revisions a version holds and in what order.
  A new version copies the previous membership and changes only what the edit
  touched, so a one-case edit costs a row of ids per case rather than a copy of
  every case's text.

The name, the description and the sharing are not versioned: they say what the
dataset is for and who reaches it, and neither changes what a run was asked.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.resource_grant import Visibility


class CaseSource(StrEnum):
    """Where a case came from."""

    MANUAL = "manual"
    """Written in the console."""

    IMPORT = "import"
    """A row of an imported CSV or JSONL file."""

    CONVERSATION = "conversation"
    """Taken from an answer somebody rated, with "Add to dataset"."""

    SYNTHETIC = "synthetic"
    """Drafted by the case generator and accepted by a person."""


class ToolOrderMode(StrEnum):
    """How the calls an agent made are matched against a case's expected ones."""

    ANY = "any"
    """Every expected call happened, in any order, other calls allowed."""

    IN_ORDER = "in_order"
    """The expected calls happened in the listed order, other calls allowed between them."""

    EXACT = "exact"
    """Exactly the expected calls, in the listed order, and nothing else."""


class DatasetChange(StrEnum):
    """What a version changed, so its history reads without a diff."""

    ADD = "add"
    EDIT = "edit"
    REMOVE = "remove"
    IMPORT = "import"


class Dataset(Base, TimestampMixin):
    """One set of test cases, and who may use it."""

    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Visibility.PRIVATE.value
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Kept in step with the newest version under the minting row lock, so a listing
    # needs no aggregate; 0 means no case was ever added.
    latest_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # How cases are scored (`app.schemas.scoring.DatasetScoring`). Not versioned
    # with the cases - how a team grades is not what it asks - so each score keeps
    # a copy of the configuration it was computed with.
    scoring: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_dataset_org_name"),
        CheckConstraint("visibility IN ('private', 'team', 'org')", name="ck_dataset_visibility"),
        CheckConstraint("latest_version >= 0", name="ck_dataset_latest_version"),
        CheckConstraint("case_count >= 0", name="ck_dataset_case_count"),
    )

    def __repr__(self) -> str:
        return f"<Dataset(org={self.organization_id}, name={self.name}, v={self.latest_version})>"


class DatasetVersion(Base):
    """One immutable state of a dataset's cases."""

    __tablename__ = "dataset_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    change: Mapped[str] = mapped_column(String(16), nullable=False)
    changed_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("dataset_id", "number", name="uq_dataset_version_number"),
        CheckConstraint("number >= 1", name="ck_dataset_version_number"),
        CheckConstraint("case_count >= 0", name="ck_dataset_version_case_count"),
        CheckConstraint("changed_cases >= 0", name="ck_dataset_version_changed_cases"),
        CheckConstraint(
            "change IN ('add', 'edit', 'remove', 'import')", name="ck_dataset_version_change"
        ),
    )

    def __repr__(self) -> str:
        return f"<DatasetVersion(dataset={self.dataset_id}, number={self.number})>"


class DatasetCase(Base):
    """One revision of one case. Its content is never updated after insert."""

    __tablename__ = "dataset_cases"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The case across its revisions: what an edit keeps, and what a comparison
    # of two eval runs matches results on.
    case_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    counter_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    order_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ToolOrderMode.ANY.value, server_default="any"
    )
    # Open objects named by `type`: scoring decides the vocabulary, and any validation
    # it adds must still accept the rows already stored here.
    checks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    # `SET NULL`: the question and answer were copied into this row, so a case
    # outlives the run, conversation and message it was taken from.
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('manual', 'import', 'conversation', 'synthetic')",
            name="ck_dataset_case_source",
        ),
        CheckConstraint(
            "order_mode IN ('any', 'in_order', 'exact')", name="ck_dataset_case_order_mode"
        ),
    )

    def __repr__(self) -> str:
        return f"<DatasetCase(dataset={self.dataset_id}, case={self.case_id}, rev={self.id})>"


class DatasetVersionCase(Base):
    """One case revision held by one version, at a position."""

    __tablename__ = "dataset_version_cases"

    version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    case_revision_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("dataset_cases.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_dataset_version_cases_order", "version_id", "position"),)

    def __repr__(self) -> str:
        return f"<DatasetVersionCase(version={self.version_id}, at={self.position})>"
