"""The failure-learning loop's own rows: curated patterns, eval cases, tries,
proposals.

Mining itself reads `agent_runs` and `message_ratings` live - there is no
snapshot table for failures. What lives here is what a human decided about
them: a ledger entry says a pattern is real and worth a rule, an eval case
reproduces one bad experience, an eval run records which test runs tried
which cases, and a proposal holds one rule-text change with its evidence
until a publisher applies it. Whether a case passed is read off its runs
when asked, never stored - the workflow-eval rule, so a run still going has
no verdict yet.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# An entry is live while a human still has to decide about it: drafted by
# mining or by hand, or accepted as real. A dismissed or resolved entry no
# longer blocks the same pattern being curated again.
OPEN_STATUSES = ("draft", "open")


class AgentFailureLedger(Base, TimestampMixin):
    """One recurring mistake, as a human curated it - not one occurrence.

    Occurrences stay where they are, on run rows; the entry snapshots the
    evidence at curation time (`evidence`: run ids, count, window,
    `error_class`, first and last seen). One open entry per
    (agent, pattern) or (model, pattern): the partial unique indexes enforce
    it, so the same pattern cannot be curated twice while open.
    """

    __tablename__ = "agent_failure_ledger"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Set for agent-scoped entries; NULL for model-scoped ones. A model entry
    # is a pattern record, not an applicable change; its proposals are
    # per-agent, and land in Phase 2.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    # The model label (e.g. `anthropic:claude-sonnet-4-5`) when the pattern is
    # model-specific. Approximate until the run row records which model
    # actually served a request - `model_label` is the primary, not the
    # serving model, when a fallback answered.
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Machine key for the pattern, e.g. `failed:ModelHTTPError:400`,
    # `downrated`, `stalled`, `approval_expired`, `loop_stopped`.
    pattern_key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    # What the agent keeps doing wrong, in one paragraph - the future rule's
    # rationale. A dismissal records its reason here too.
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The proposal whose apply resolved this entry. The foreign key lands
    # with the proposals table in Phase 2 (migration 0305).
    resolved_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_instruction_proposals.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint("scope IN ('agent', 'model')", name="ck_failure_ledger_scope_value"),
        CheckConstraint(
            "status IN ('draft', 'open', 'dismissed', 'resolved')", name="ck_failure_ledger_status"
        ),
        CheckConstraint(
            "(scope = 'agent' AND agent_id IS NOT NULL) OR "
            "(scope = 'model' AND agent_id IS NULL AND model IS NOT NULL)",
            name="ck_failure_ledger_scope",
        ),
        Index("ix_failure_ledger_org_agent_status", "organization_id", "agent_id", "status"),
        Index("ix_failure_ledger_org_model_status", "organization_id", "model", "status"),
        Index(
            "uq_failure_ledger_open_agent",
            "organization_id",
            "agent_id",
            "pattern_key",
            unique=True,
            postgresql_where=text("agent_id IS NOT NULL AND status IN ('draft', 'open')"),
        ),
        Index(
            "uq_failure_ledger_open_model",
            "organization_id",
            "model",
            "pattern_key",
            unique=True,
            postgresql_where=text("agent_id IS NULL AND status IN ('draft', 'open')"),
        ),
    )

    def __repr__(self) -> str:
        return f"<AgentFailureLedger(id={self.id}, scope={self.scope}, key={self.pattern_key})>"


class AgentEvalCase(Base, TimestampMixin):
    """One reproduction of a real bad experience, and what its answer should say.

    Mirrors `WorkflowStepEval`: a case outlives its ledger entry being
    deleted, and says so, rather than vanishing with work somebody wrote -
    so `ledger_entry_id` is nullable, SET NULL.
    """

    __tablename__ = "agent_eval_cases"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_failure_ledger.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Where the case sits among its agent's, in the order they were written.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # `{message: str, history?: [{role, text}]}` - the user message that
    # triggered the failure, plus up to 10 prior turns, truncated.
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # `{kind, field, value}` - see `app.schemas.eval_judging.EvalExpectation`.
    expectation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Pin the model for per-model cases; NULL = the agent's current profile.
    model_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The real run the case reproduces.
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (Index("ix_agent_eval_case_agent", "organization_id", "agent_id"),)

    def __repr__(self) -> str:
        return f"<AgentEvalCase(id={self.id}, agent={self.agent_id}, name={self.name})>"


class AgentEvalRun(Base):
    """One try of a set of cases: which test runs tried which case, as it stood.

    Mirrors `WorkflowEvalRun`: the try stores per-case snapshots + run ids;
    the verdict is judged when read, never stored. `cases` holds one entry
    per case: `{eval_id, name, expectation, old_run_ids, new_run_ids,
    samples, refused}` - the expectation as it was when tried, so editing a
    case later does not change what an earlier try was judged by.
    """

    __tablename__ = "agent_eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The proposal whose new text was tried, if any. The foreign key lands
    # with the proposals table in Phase 2 (migration 0305).
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_instruction_proposals.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_skill_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("skills.id", ondelete="SET NULL"), nullable=True
    )
    tested_content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    cases: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_agent_eval_run_agent", "organization_id", "agent_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AgentEvalRun(id={self.id}, agent={self.agent_id})>"


class AgentInstructionProposal(Base, TimestampMixin):
    """One proposed rule-text change, and the evidence for it.

    The change itself lives nowhere else until applied: `old_text` is the
    instructions (or skill content) being replaced, `new_text` the proposed
    replacement, `rationale` why in the proposer's words. An instruction
    target is eval-gated - apply refuses unless the linked try gate-passed
    (§5.4) - and optimistic concurrency on `base_agent_version_id` plus the
    draft guard keep it from overwriting a newer publish or in-progress
    edits. A skill target carries the hash of its base content, the exact
    content tried, and the previous content needed for a one-shot rollback.

    Applying is the approval: there is no separate approve step. A proposal
    is `draft` until it is applied or rejected; `applied_version_id` is the
    version the apply published (NULL for skill targets).
    """

    __tablename__ = "agent_instruction_proposals"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The agent the change would land on. Always set, even when the source
    # ledger entry is model-scoped: a model entry is a pattern record, and
    # the change always lands per agent.
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_failure_ledger.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The try that evidences this proposal. The gate must have passed before
    # an instruction target applies.
    eval_try_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_eval_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Set iff the target is a skill.
    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The text being replaced (instructions now, or skill content now).
    old_text: Mapped[str] = mapped_column(Text, nullable=False)
    new_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Why, in the proposer's words - the ledger entry's summary, refined.
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    # The published version the proposal was written against. Apply refuses
    # when the agent has been republished since.
    base_agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Skill-target equivalent: SHA-256 of the skill content at proposal time.
    base_content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prior_skill_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reverted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    # The version the apply published. The rollback handle; NULL for skill
    # targets, which have no versions.
    applied_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("target_type IN ('instructions', 'skill')", name="ck_proposal_target_type"),
        CheckConstraint("status IN ('draft', 'applied', 'rejected')", name="ck_proposal_status"),
        CheckConstraint(
            "(target_type = 'skill' AND skill_id IS NOT NULL) OR "
            "(target_type = 'instructions' AND skill_id IS NULL)",
            name="ck_proposal_skill_target",
        ),
        Index("ix_proposal_org_agent_status", "organization_id", "agent_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<AgentInstructionProposal(id={self.id}, target={self.target_type})>"
