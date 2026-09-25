"""Durable execution: one run of a published (or draft-tested) workflow graph.

Six tables, all `organization_id`-scoped like everything else in the schema.
`WorkflowRun` is the run itself; `NodeRun` is one node's position in it
(one per `(run, node instance, loop scope)`); `NodeAttempt` is append-only,
one row per try, never mutated after it reaches a terminal status - the same
reason `agent_runs` never overwrites a row: an overwritten attempt could not
answer "what did the failed try before this one cost". `DispatchOutbox` is a
transactional outbox - a row naming what is ready to run next, created in the
same transaction as the `NodeResult` that made it runnable, so "the result is
durable" and "the next step is scheduled" can never disagree. `WorkflowEvent`
is an append-only log with a per-run monotonic `seq`, what #1787's run-history
view and any live "watch this run" panel read. `ResourceRef` holds the
`FileRef`/`TableIORef` bindings a run resolved at start.

`app.services.workflow_execution` is the state machine these tables drive;
its dispatcher's module docstring explains the transaction split they serve.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import (
    DateTime as SADateTime,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WorkflowRunMode(enum.StrEnum):
    """Where this run's graph came from.

    `REAL` reads its graph from `WorkflowVersion.graph`, the published,
    frozen definition. `TEST` reads it from `WorkflowRun.draft_graph_snapshot`
    - a snapshot of the *draft* graph taken at start, for #1787's test-run
    feature, since a real `WorkflowVersion` row can only ever be published and
    inventing an unpublished one would break the immutable-once-created
    discipline `create_version` exists to guarantee.
    """

    REAL = "real"
    TEST = "test"


class WorkflowRunTrigger(enum.StrEnum):
    """What admitted this run - who or what asked for it to start."""

    API = "api"
    WEBSOCKET = "websocket"
    WEBHOOK = "webhook"
    CHAT = "chat"
    SCHEDULE = "schedule"
    TABLE_CREATED = "table_created"


class WorkflowRunStatus(enum.StrEnum):
    """Where a run is, coarser than any one node's status.

    Several `NodeRun`s can be `waiting` in different ways at once - notably
    inside a `foreach` body - so the run's status is the most severe of its
    live nodes', ranked `needs_attention` > `budget_exceeded` > `failed` >
    `waiting_approval` > `waiting_retry` > `running`.
    """

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_RETRY = "waiting_retry"
    NEEDS_ATTENTION = "needs_attention"
    BUDGET_EXCEEDED = "budget_exceeded"
    CANCELLED = "cancelled"
    FAILED = "failed"
    SUCCEEDED = "succeeded"

    @property
    def is_terminal(self) -> bool:
        """Whether nothing further will ever dispatch for this run.

        `BUDGET_EXCEEDED` is terminal: no path resumes a run whose cap is
        spent, so leaving it open would only strand it.
        """
        return self in (
            WorkflowRunStatus.BUDGET_EXCEEDED,
            WorkflowRunStatus.CANCELLED,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.SUCCEEDED,
        )


class WaitingReason(enum.StrEnum):
    """Why a `NodeRun` (or, derived from it, a `WorkflowRun`) is parked.

    Mirrors `app.workflows.contracts.results.Waiting.reason` - the same three
    values, persisted rather than held only in the return value that produced
    them.
    """

    APPROVAL = "approval"
    EXTERNAL_EVENT = "external_event"
    RETRY_BACKOFF = "retry_backoff"


class NodeRunStatus(enum.StrEnum):
    """Where one node's execution, in one run and one loop scope, stands."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    NEEDS_ATTENTION = "needs_attention"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class RetryGuarantee(enum.StrEnum):
    """Whether repeating a node's effect is safe, and who gets to say so.

    Mirrors `app.workflows.contracts.definition.NodeDefinition.retry_guarantee`.
    A `NodeAttempt` may override the node's own static value - a guarantee is
    sometimes a property of the *call*, not the node kind (`http.request`'s
    safety to retry depends on the method and whether an idempotency header
    was actually sent).
    """

    NONE = "none"
    IDEMPOTENT = "idempotent"
    AT_LEAST_ONCE = "at_least_once"


class NodeAttemptStatus(enum.StrEnum):
    """Where one try at a node's effect stands.

    `IN_FLIGHT` is written, and committed, *before* the handler is called -
    see `app.services.workflow_execution.dispatcher` - so a crash mid-call
    always leaves a row the reconciler can find. `UNCERTAIN` is what an
    orphaned `IN_FLIGHT` attempt becomes when its effect's outcome is unknown
    and unsafe to assume either way.
    """

    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class DispatchOutboxStatus(enum.StrEnum):
    """Where one queued unit of dispatch work stands."""

    PENDING = "pending"
    CLAIMED = "claimed"
    DONE = "done"
    CANCELLED = "cancelled"


class ResourceRefKind(enum.StrEnum):
    """Which `BindingSource` variant a `ResourceRef` was resolved from."""

    FILE = "file"
    TABLE = "table"


class WorkflowRun(Base, TimestampMixin):
    """One execution of one workflow graph."""

    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # No index of its own: `ix_workflow_run_org_status` leads with it.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Exactly one of this pair is set - a CHECK below enforces it. A `TEST`
    # mode run (#1787) has no `WorkflowVersion` to point at, since a real one
    # can only ever be published; it carries its graph in the snapshot
    # instead. No `ondelete` on either FK: neither a published version nor a
    # run row is ever deleted by this codebase today, so there is nothing to
    # cascade or null out.
    workflow_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflow_versions.id"), nullable=True
    )
    # `none_as_null=True`: without it, assigning Python `None` to a JSONB
    # column stores the *JSON* value `null` (a real, non-NULL row value SQL
    # sees as present) rather than SQL `NULL` - which silently defeats the
    # `ck_workflow_run_graph_source_xor` CHECK below, since `draft_graph_snapshot
    # IS NULL` is then false for a row that looks unset from Python. Reading
    # a stored JSON `null` back still deserializes to Python `None` either
    # way, which is what made this invisible short of asking the database
    # directly whether the column holds SQL NULL.
    draft_graph_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    mode: Mapped[str] = mapped_column(String(8), nullable=False, default=WorkflowRunMode.REAL.value)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WorkflowRunStatus.QUEUED.value, index=True
    )
    triggered_by: Mapped[str] = mapped_column(String(16), nullable=False)
    # Pinned once, at admission, by whichever adapter created the run - never
    # re-resolved from a request afterward. SET NULL rather than a hard block
    # on user deletion, matching `agent_runs.user_id`: the run itself is not
    # what a deleted account takes with it.
    execution_principal_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    budget_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    spent_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    cost_is_partial: Mapped[bool] = mapped_column(nullable=False, default=False)
    deadline_at: Mapped[datetime | None] = mapped_column(SADateTime(timezone=True), nullable=True)
    # Incremented in the same transaction as each `WorkflowEvent` insert -
    # never a shared sequence, so a cursor for one run stays small, dense and
    # meaningless for another. See `app.services.workflow_execution.events`.
    next_event_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    paused_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # `none_as_null=True` for the same reason `draft_graph_snapshot` above
    # needs it: a truly absent error must be SQL NULL, not a stored JSON
    # `null`, for any future `error IS NULL` query to mean what it says.
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    # This run's own id if it is the root of its causal chain, else the
    # originating run's `root_run_id`. Always set - a root run points at
    # itself - which is what lets every consumer that needs "the run this
    # chain started from" read one column without branching on whether this
    # run happens to be the root.
    root_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False, index=True
    )
    # The run whose side effect (a node write, a trigger firing) admitted this
    # one. Null for a root run. #1785's cycle protection walks this chain;
    # #1788 only carries the column, so a later migration is not needed to
    # retrofit it.
    causation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    visited_trigger_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(SADateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(SADateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(workflow_version_id IS NULL) != (draft_graph_snapshot IS NULL)",
            name="ck_workflow_run_graph_source_xor",
        ),
        CheckConstraint("mode IN ('real', 'test')", name="ck_workflow_run_mode"),
        CheckConstraint(
            "status IN ('queued', 'running', 'waiting_approval', 'waiting_retry', "
            "'needs_attention', 'budget_exceeded', 'cancelled', 'failed', 'succeeded')",
            name="ck_workflow_run_status",
        ),
        CheckConstraint(
            "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created')",
            name="ck_workflow_run_triggered_by",
        ),
        CheckConstraint(
            "paused_reason IS NULL OR paused_reason IN "
            "('approval', 'external_event', 'retry_backoff')",
            name="ck_workflow_run_paused_reason",
        ),
        CheckConstraint("spent_cost >= 0", name="ck_workflow_run_spent_cost"),
        CheckConstraint("depth >= 0", name="ck_workflow_run_depth"),
        Index("ix_workflow_run_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<WorkflowRun(id={self.id}, workflow={self.workflow_id}, status={self.status})>"


class NodeRun(Base, TimestampMixin):
    """One node's execution, in one run and one loop scope."""

    __tablename__ = "node_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # No index of its own: `uq_node_run_identity` leads with it.
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # A `NodeInstance.id` from the run's own graph blob - not a foreign key,
    # since the graph it names is frozen JSONB, not a row.
    node_instance_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    # `[]` at top level; `[{"loop_node_id": ..., "index": ...}, ...]` inside a
    # `foreach` body. Part of this row's identity - see the unique constraint
    # below - because two loop iterations of the same node are two different
    # `NodeRun`s.
    scope_path: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=NodeRunStatus.PENDING.value, index=True
    )
    waiting_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Concretely this row's own id, stringified (the dispatcher's
    # `_settle_waiting` writes it). Stored rather than only derived so a
    # waiting `NodeRun` names the token it was issued with even before
    # anything reads it back.
    resume_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    waiting_agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(SADateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(SADateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id", "node_instance_id", "scope_path", name="uq_node_run_identity"
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'waiting', 'needs_attention', 'succeeded', "
            "'failed', 'skipped', 'cancelled')",
            name="ck_node_run_status",
        ),
        CheckConstraint(
            "waiting_reason IS NULL OR waiting_reason IN "
            "('approval', 'external_event', 'retry_backoff')",
            name="ck_node_run_waiting_reason",
        ),
    )

    def __repr__(self) -> str:
        return f"<NodeRun(id={self.id}, run={self.workflow_run_id}, status={self.status})>"


class NodeAttempt(Base, TimestampMixin):
    """One try at a node's effect. Append-only - its verdict is never changed once
    terminal; only a cost a late result reports is still added to it."""

    __tablename__ = "node_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # No index of its own: `uq_node_attempt_number` leads with it.
    node_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("node_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # Stable across attempts of the same logical operation, distinct across
    # loop iterations - see `dispatcher.py` for the exact format.
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    retry_guarantee: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # `none_as_null=True` for the same reason `WorkflowRun.draft_graph_snapshot`
    # needs it - an `in_flight` attempt has genuinely no result yet, and that
    # must be SQL NULL, not a stored JSON `null`.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    cost_is_partial: Mapped[bool] = mapped_column(nullable=False, default=False)
    started_at: Mapped[datetime] = mapped_column(SADateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(SADateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("node_run_id", "attempt_no", name="uq_node_attempt_number"),
        CheckConstraint("attempt_no >= 1", name="ck_node_attempt_number"),
        CheckConstraint(
            "retry_guarantee IS NULL OR retry_guarantee IN ('none', 'idempotent', 'at_least_once')",
            name="ck_node_attempt_retry_guarantee",
        ),
        CheckConstraint(
            "status IN ('in_flight', 'completed', 'failed', 'uncertain')",
            name="ck_node_attempt_status",
        ),
        CheckConstraint("cost >= 0", name="ck_node_attempt_cost"),
        # The reconciler's orphan scan and `take_stale_claims_for_resubmission`
        # both ask "is
        # anything in flight for this node run" on every tick.
        Index(
            "ix_node_attempt_in_flight",
            "node_run_id",
            postgresql_where=text("status = 'in_flight'"),
        ),
    )

    def __repr__(self) -> str:
        return f"<NodeAttempt(id={self.id}, node_run={self.node_run_id}, status={self.status})>"


class DispatchOutbox(Base, TimestampMixin):
    """What is ready to run next, and who currently owns it.

    A transactional outbox: a row is inserted in the same transaction that
    records the `NodeResult` which made the next node runnable.
    """

    __tablename__ = "dispatch_outbox"

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
    node_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("node_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(SADateTime(timezone=True), nullable=False)
    # A fencing token minted fresh per claim - not a Prefect flow-run identity
    # - so a hung flow and a reclaiming poller's flow can never both believe
    # they own the row: every status transition after a claim re-checks
    # `claimed_by` (booking a reported cost deliberately does not).
    claimed_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        SADateTime(timezone=True), nullable=True
    )
    # When this row was last handed to `workflow-dispatch-node`. The poll and
    # the stale-claim sweep submit only rows not submitted within a lease, and
    # stamp this in the same statement - without it every tick submitted every
    # due row again until a worker finally claimed it.
    submitted_at: Mapped[datetime | None] = mapped_column(SADateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DispatchOutboxStatus.PENDING.value
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'claimed', 'done', 'cancelled')",
            name="ck_dispatch_outbox_status",
        ),
        Index(
            "ix_dispatch_outbox_pending_claim",
            "available_at",
            postgresql_where=text("status = 'pending'"),
        ),
        # The reconciler's scans for claims whose lease has run out.
        Index(
            "ix_dispatch_outbox_claimed_lease",
            "lease_expires_at",
            postgresql_where=text("status = 'claimed'"),
        ),
        # Every dispatch reads a node run's latest row without a status
        # filter, which the partial indexes cannot serve; this also backs the
        # foreign key's cascade from `node_runs`.
        Index("ix_dispatch_outbox_node_run", "node_run_id"),
        # At most one live (pending/claimed) dispatch per `NodeRun` - what
        # closes the approval double-wake race: a reconciler backstop insert
        # racing a direct wake hits this constraint and is read back as
        # "already dispatched" rather than needing to remember to check first.
        Index(
            "uq_dispatch_outbox_live_node_run",
            "node_run_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'claimed')"),
        ),
    )

    def __repr__(self) -> str:
        return f"<DispatchOutbox(id={self.id}, node_run={self.node_run_id}, status={self.status})>"


class WorkflowEvent(Base, TimestampMixin):
    """One append-only entry in a run's event stream - what #1787 tails."""

    __tablename__ = "workflow_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # No index of its own: `uq_workflow_event_seq` leads with it.
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # From `WorkflowRun.next_event_seq`, incremented in the same transaction
    # as this insert - a per-run monotonic counter, never a shared sequence.
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    # Indexed for the cascade from `node_runs`: deleting a workflow or an
    # organization checks this table once per deleted node run.
    node_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("node_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (UniqueConstraint("workflow_run_id", "seq", name="uq_workflow_event_seq"),)

    def __repr__(self) -> str:
        return f"<WorkflowEvent(run={self.workflow_run_id}, seq={self.seq}, kind={self.kind})>"


class ResourceRef(Base, TimestampMixin):
    """A `FileRef`/`TableIORef` binding, resolved once at run start."""

    __tablename__ = "resource_refs"

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
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # `FileRef`/`TableIORef.model_dump(mode="json")` - thin and unopinionated,
    # like the reference types themselves (`app.workflows.contracts.io`).
    ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (CheckConstraint("kind IN ('file', 'table')", name="ck_resource_ref_kind"),)

    def __repr__(self) -> str:
        return f"<ResourceRef(id={self.id}, run={self.workflow_run_id}, kind={self.kind})>"
