"""Workflow registry - a graph an organization composes, and its published versions.

Shaped after `app.db.models.agent`, not after `virtual_table`: `Workflow` is the
thing people talk about (name, owner, sharing state, the draft being edited) and
`WorkflowVersion` is one frozen graph, published and immutable. Editing writes the
draft; publishing snapshots it into a version and points the workflow at it.

`draft_revision` is a field `Agent.draft_spec` has no equivalent of, because
autosave (a later issue) writes a workflow's draft far more often than the
Builder's occasional agent edit - see `docs/virtual-tables.md`'s
`expected_revision` pattern, reused here rather than reinvented.
"""

import enum
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.resource_grant import Visibility


class WorkflowStatus(enum.StrEnum):
    """Whether a workflow is runnable.

    Mirrors `AgentStatus`: `DRAFT` has never been published, `PUBLISHED` has a
    current version, `ARCHIVED` keeps its history and its runs but refuses new
    ones - the same "stop it, keep the trail" shape `Agent`'s archive gives.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Workflow(Base, TimestampMixin):
    """A configured workflow, owned by an organization."""

    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Owner and visibility make this a shareable resource; see app.services.access.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Visibility.PRIVATE.value
    )

    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=WorkflowStatus.DRAFT.value, index=True
    )

    # The graph being edited. Always present; equals the published version's
    # graph right after a publish, and diverges as soon as someone edits.
    # `WorkflowGraph.model_dump(mode="json")`, validated by the service on the
    # way in and out - never by a database constraint, the same division of
    # labor `Agent.draft_spec` has with `AgentSpec`.
    draft_graph: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Bumped by one per accepted draft write, never on publish. Starts at 0, so
    # a workflow nobody has edited yet has a well-defined `expected_revision`
    # to send on the first `PATCH .../draft` without having read one back first.
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # What runs. Null until first publish.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        # No FK, for the same reason Agent.current_version_id has none:
        # workflow_versions references workflows, and a mutual constraint would
        # need deferred constraints on both inserts and deletes for no benefit.
        nullable=True,
    )

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_workflow_org_slug"),
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_workflow_status"),
        CheckConstraint("visibility IN ('private', 'team', 'org')", name="ck_workflow_visibility"),
        CheckConstraint("draft_revision >= 0", name="ck_workflow_draft_revision"),
    )

    def __repr__(self) -> str:
        return f"<Workflow(org={self.organization_id}, slug={self.slug}, status={self.status})>"


class WorkflowVersion(Base, TimestampMixin):
    """One published graph, frozen.

    Immutable by convention, like `AgentVersion`: nothing updates a version
    after insert. `repositories/workflow.py` exposes `create_version` and reads
    only - no `update_version` - which is what makes "published definitions
    remain unchanged after draft edits" structural rather than a convention to
    remember.
    """

    __tablename__ = "workflow_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # `WorkflowGraph.model_dump(mode="json")`, frozen at publish time.
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Why this version exists - a commit message for workflows.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The pinned budget cap a run of this version starts with -
    # `WorkflowRun.budget_limit` (a later issue) copies this at run start.
    # `None` means no workflow-level cap, only whatever each `agent.run` node's
    # own pinned agent enforces. Pinned per version like everything else here:
    # republishing to change the cap is the only way to change it.
    budget_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)

    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_version_number"),
        CheckConstraint("version >= 1", name="ck_workflow_version_number"),
    )

    def __repr__(self) -> str:
        return f"<WorkflowVersion(workflow={self.workflow_id}, v{self.version})>"
