"""Improvement sessions - the Improve pipeline run in the background, step by step.

Two tables:

- `improvement_runs` is one session on one agent: who started it, the base,
  dataset and grading it is pinned to, the budget it may spend, where it is now
  and why it stopped. An agent has at most one queued or running session.
- `improvement_iterations` is one round of a session: the authoring request that
  proposed changes, the candidate batch they landed in, what the policy dropped,
  the eval runs that checked the candidate and the verdict. It holds counts and
  ids only, never the text of a question or an answer, which stays with the eval
  run and is masked there.

**Background steps never write an agent.** They end at `ready` with a candidate
batch. A person may then confirm acceptance and publication through the normal
services; background transitions leave the draft, versions and environments untouched.
"""

import uuid
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import NotRequired, TypedDict

from pydantic import JsonValue
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ImprovementStatus(StrEnum):
    """Where a session is: moving on its own, waiting for a person, or over."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    """Between two steps until a person takes the next one; `stage` is the step it finished."""

    READY = "ready"
    """A checked candidate waits for a person to accept, publish or reject it."""

    STOPPED = "stopped"
    """Ended without a candidate worth accepting - the reason is in `stop_reason`."""

    FAILED = "failed"
    """A step broke - `stop_reason` names it, `error` says how."""

    CANCELLED = "cancelled"
    STALE = "stale"
    """The draft, the published version, the grading or the agent changed under it."""

    ACCEPTED = "accepted"
    PUBLISHED = "published"
    REJECTED = "rejected"

    @property
    def active(self) -> bool:
        """Still moving on its own: one of these per agent at a time."""
        return self in {ImprovementStatus.QUEUED, ImprovementStatus.RUNNING}

    @property
    def deciding(self) -> bool:
        """A checked candidate waits for a person: to decide on it, or to publish what was accepted."""
        return self in {ImprovementStatus.READY, ImprovementStatus.ACCEPTED}

    @property
    def open(self) -> bool:
        """Not over yet: one of these per agent, so a new session needs this one ended first."""
        return self in {
            ImprovementStatus.QUEUED,
            ImprovementStatus.RUNNING,
            ImprovementStatus.WAITING,
            ImprovementStatus.READY,
            ImprovementStatus.STOPPED,
            ImprovementStatus.FAILED,
        }

    @property
    def closed(self) -> bool:
        """Over for good - decided, discarded, cancelled or outdated - so nothing may change it.

        Stopped and failed sessions are not: they can still be continued or retried.
        """
        return self in {
            ImprovementStatus.ACCEPTED,
            ImprovementStatus.PUBLISHED,
            ImprovementStatus.REJECTED,
            ImprovementStatus.CANCELLED,
            ImprovementStatus.STALE,
        }


class ImprovementStage(StrEnum):
    """The step a session is on, or was on when it stopped."""

    ANALYZING = "analyzing"
    CLASSIFYING = "classifying"
    """Sorting the bad answers into the agent's faults, missing knowledge and non-problems."""

    DRAFTING = "drafting"
    """Drafting the content the knowledge base is missing, for a person to add."""

    PROPOSING = "proposing"
    FILTERING = "filtering"
    EVALUATING = "evaluating"
    JUDGING = "judging"
    SEARCHING = "searching"
    """Trying many variants of the instructions on training questions, before Changes."""


class ImprovementMode(StrEnum):
    """How a session's attempt reaches its candidate."""

    STEPS = "steps"
    """One proposal per attempt, checked on held-out questions."""

    SEARCH = "search"
    """Many variants scored on training questions; the best one is then checked as usual."""


class StopReason(StrEnum):
    """Why a session ended where it did."""

    NO_DATA = "no_data"
    NO_PROPOSAL = "no_proposal"
    BUDGET = "budget"
    INCONCLUSIVE = "inconclusive"
    REGRESSION = "regression"
    NO_CHANGE = "no_change"
    MAX_ITERATIONS = "max_iterations"
    REPEAT_CANDIDATE = "repeat_candidate"
    PERMISSION = "permission"
    STALE = "stale"
    STALLED = "stalled"
    PROPOSAL = "proposal"
    """The authoring request failed or went stale."""

    EVAL = "eval"
    """The eval run failed or was cancelled by someone else."""

    SUPERSEDED = "superseded"
    """A newer candidate or a person's own Improve replaced this one."""

    KNOWLEDGE_ONLY = "knowledge_only"
    """Every bad answer was missing knowledge: its topics wait for a person to draft them."""

    DRAFT = "draft"
    """A session's own drafting step failed; stored on sessions from when a session drafted."""

    EXPIRED = "expired"
    """Nobody took the next step or decided for seven days."""

    CRITERIA_WORSE = "criteria_worse"
    """No question broke, but a criterion the check confirmed got worse."""

    NO_VARIANT = "no_variant"
    """A search found no variant that did better than the instructions on training questions."""


class ImprovementVerdict(StrEnum):
    """How a round's candidate compared with the base on the pinned dataset."""

    BETTER = "better"
    CRITERIA_BETTER = "criteria_better"
    """No question flipped, and criteria the check confirmed got better while none got worse."""

    NO_CHANGE = "no_change"
    CRITERIA_WORSE = "criteria_worse"
    """No question broke, and a criterion the check confirmed got worse."""

    REGRESSION = "regression"
    INCONCLUSIVE = "inconclusive"


def _values(members: Iterable[StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in members)


ACTIVE_STATUSES = tuple(status for status in ImprovementStatus if status.active)
DECIDING_STATUSES = tuple(status for status in ImprovementStatus if status.deciding)
OPEN_STATUSES = tuple(status for status in ImprovementStatus if status.open)
UNSETTLED_STATUSES = tuple(status for status in ImprovementStatus if status.open or status.deciding)


class DroppedHunk(TypedDict):
    """A hunk the policy left out of a round's candidate, and why."""

    hunk_id: str
    reason: str


class CriterionDetail(TypedDict):
    """One criterion's counts on a round's held-out questions, and who it was put down to."""

    scorer: str
    name: str
    graded: int
    before: int
    after: int
    fixed: int
    broken: int
    skill: NotRequired[str]
    skill_id: NotRequired[str]
    """The skill the session's improver put a criterion that still fails down to."""


class FamilyDetail(TypedDict):
    """One family of criteria's counts on a round's held-out questions.

    `fixed` and `broken` count the cases that hold: every flipped one when the
    family is settled by its own spread, else those the re-asks confirmed.
    """

    family: str
    criteria: int
    cases: int
    before: int
    after: int
    fixed: int
    broken: int
    settled: bool
    better: bool
    worse: bool
    skill: NotRequired[str]
    skill_id: NotRequired[str]
    """The skill the session's improver put the family down to."""


class VerdictDetail(TypedDict, total=False):
    """The counts behind a round's verdict - never a question's or an answer's text."""

    fixed: int | None
    criterion_change: float
    crashed: int
    gradable_holdout: int
    held_out: int | None
    minimum_holdout: int
    missing_holdout: int
    broken: int | None
    incomplete: int
    ungraded: int
    candidate_pass_rate: float | None
    baseline_pass_rate: float | None
    suite: str | None
    reason: str | None
    criteria: list[CriterionDetail]
    families: list[FamilyDetail]


class SearchSettings(TypedDict):
    """What a search attempt may spend and try, frozen when the session starts."""

    budget_usd: str
    grading_model_profile_id: str | None
    max_variants: int
    per_generation: int
    minibatch: int
    patience: int


class SearchProgress(TypedDict, total=False):
    """Where a search attempt is: its settings, what it spent and what it found.

    `spent_before_usd` is the session's spend when the search began, so the
    search's own cost is the session's spend now less it. `best_before` is the
    best score a round of proposals started from, and `stale_generations` counts
    the rounds in a row that found nothing better.
    """

    settings: SearchSettings
    case_ids: list[str]
    """The training questions every variant is scored on, so their scores compare."""

    spent_before_usd: str
    generation: int
    closed_generation: int
    stale_generations: int
    seed_score: float | None
    best_before: float | None
    cost_usd: str
    stop_reason: str | None
    chosen_variant_id: str | None


class ImprovementRun(Base):
    """One improvement session on one agent, from start to a person's decision."""

    __tablename__ = "improvement_runs"

    helper_settings: Mapped[dict[str, JsonValue]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    improver_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

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
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # No foreign key, as on `eval_runs`: keys are hard-deleted, and a reference set
    # to null would let the run fall back to the issuer's full role.
    created_by_api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    # Whoever took the latest step a person starts; the steps after it run as them,
    # with the credential they acted with. Unset, the session runs as its creator.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_api_key_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ImprovementStatus.QUEUED.value
    )
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ImprovementMode.STEPS.value,
        server_default=ImprovementMode.STEPS.value,
    )
    stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # Pinned at start and kept without a foreign key, so deleting the version, the
    # dataset or the suite leaves the pin to compare with and the session goes stale.
    base_version_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    # Publication made by this session; kept as a historical pin if removed later.
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_draft_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    dataset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    suite_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    scoring_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chat_evidence_run_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    pinned_scoring: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    # Knowledge documents a person set aside with "Not now"; the topic keeps its draft.
    deferred_topic_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    judge_version_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    # A suite is edited in place, so its id alone would let a session be judged
    # against a bar other than the one it started with.
    suite_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    estimate_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    budget_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    archived_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal(0), server_default="0"
    )
    """Cost of paid root runs already removed by activity retention; no evidence text."""
    best_iteration_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("improvement_iterations.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    stop_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    stage_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_improvement_runs_tenant"),
        CheckConstraint(
            f"status IN ({_values(ImprovementStatus)})", name="ck_improvement_run_status"
        ),
        CheckConstraint(
            f"stage IS NULL OR stage IN ({_values(ImprovementStage)})",
            name="ck_improvement_run_stage",
        ),
        CheckConstraint(f"mode IN ({_values(ImprovementMode)})", name="ck_improvement_run_mode"),
        CheckConstraint(
            f"stop_reason IS NULL OR stop_reason IN ({_values(StopReason)})",
            name="ck_improvement_run_stop_reason",
        ),
        CheckConstraint(
            "max_iterations BETWEEN 1 AND 10 AND iteration BETWEEN 1 AND max_iterations",
            name="ck_improvement_run_iterations",
        ),
        CheckConstraint(
            "estimate_usd >= 0 AND budget_usd >= 0 AND spent_usd >= 0",
            name="ck_improvement_run_money",
        ),
        CheckConstraint("archived_cost_usd >= 0", name="ck_improvement_run_archived_cost"),
        CheckConstraint(
            "(suite_id IS NULL) = (suite_hash IS NULL)", name="ck_improvement_run_suite_pin"
        ),
        # One open session per agent, held where two concurrent starts cannot
        # both slip past it.
        Index(
            "uq_improvement_runs_open",
            "agent_id",
            unique=True,
            postgresql_where=text(f"status IN ({_values(OPEN_STATUSES)})"),
        ),
        Index("ix_improvement_runs_agent", "organization_id", "agent_id", "created_at"),
        Index(
            "ix_improvement_runs_unsettled",
            "status",
            postgresql_where=text(f"status IN ({_values(UNSETTLED_STATUSES)})"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ImprovementRun(id={self.id}, agent={self.agent_id}, status={self.status}, "
            f"stage={self.stage})>"
        )


class ImprovementIteration(Base):
    """One round of a session: a proposal, its candidate and the check of it."""

    __tablename__ = "improvement_iterations"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    authoring_request_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("authoring_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("spec_proposal_batches.id", ondelete="SET NULL"),
        nullable=True,
    )
    candidate_spec_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Freeze exactly what was measured; later Verify suggestions remain excluded.
    # Null preserves legacy rounds created before selections were recorded.
    included_hunk_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    previous_eval_run_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    dropped_hunk_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    dropped: Mapped[list[DroppedHunk]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # Every eval run that checked this round's candidate, oldest first; the last
    # one is the one the verdict reads. An inconclusive check is run once more.
    eval_run_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    attribution_eval_run_ids: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # What the person who asked for this attempt told its helper.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The attempt's own draw of which questions it learns from and which it is
    # measured on, frozen when the attempt is made: its proposal never reads its
    # measured questions and a rerun cannot redraw them. Unset, the dataset's
    # stored partition applies.
    split_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    train_case_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    holdout_case_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    verdict_detail: Mapped[VerdictDetail | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    # SET NULL: a job retention removed reads as one that ended long ago.
    classify_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("background_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    draft_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("background_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    search: Mapped[SearchProgress | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_improvement_iterations_tenant"),
        # A round belongs to its session's organization, held by the schema rather
        # than by every writer passing the matching pair.
        ForeignKeyConstraint(
            ["run_id", "organization_id"],
            ["improvement_runs.id", "improvement_runs.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("run_id", "number", name="uq_improvement_iterations_number"),
        CheckConstraint(
            f"verdict IS NULL OR verdict IN ({_values(ImprovementVerdict)})",
            name="ck_improvement_iteration_verdict",
        ),
        CheckConstraint("number >= 1", name="ck_improvement_iteration_number"),
        CheckConstraint("cost_usd >= 0", name="ck_improvement_iteration_cost"),
    )

    def __repr__(self) -> str:
        return (
            f"<ImprovementIteration(id={self.id}, run={self.run_id}, number={self.number}, "
            f"verdict={self.verdict})>"
        )


class VariantFailure(TypedDict):
    """A training question a variant's answer failed, and the criteria it failed on."""

    case_id: str
    failed: list[str]


class SearchVariantStatus(StrEnum):
    """Where one variant of a search is."""

    PENDING = "pending"
    SCORED = "scored"
    FAILED = "failed"
    """Its answers could not be graded; it takes no part in the ranking."""


class ImprovementSearchVariant(Base):
    """One variant of an agent's instructions a search attempt tried on training questions.

    Holds the variant's text and its score - the share of required checks its
    answers passed - never a question's or an answer's text.
    """

    __tablename__ = "improvement_search_variants"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    iteration_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("improvement_search_variants.id", ondelete="SET NULL"),
        nullable=True,
    )
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SearchVariantStatus.PENDING.value
    )
    train_score: Mapped[float | None] = mapped_column(Numeric(6, 5, asdecimal=False), nullable=True)
    cases_scored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cases_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failures: Mapped[list[VariantFailure]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    """How often scoring this variant began; one that never finishes is given up on."""
    estimate_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal(0)
    )
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["iteration_id", "organization_id"],
            ["improvement_iterations.id", "improvement_iterations.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("iteration_id", "text_hash", name="uq_improvement_search_variant_text"),
        CheckConstraint(
            f"status IN ({_values(SearchVariantStatus)})", name="ck_search_variant_status"
        ),
        CheckConstraint(
            "train_score IS NULL OR train_score BETWEEN 0 AND 1",
            name="ck_search_variant_score",
        ),
        CheckConstraint(
            "generation >= 0 AND cases_scored >= 0 AND cases_passed BETWEEN 0 AND cases_scored "
            "AND attempts >= 0 AND estimate_usd >= 0 AND cost_usd >= 0",
            name="ck_search_variant_counts",
        ),
        Index("ix_improvement_search_variants_rank", "iteration_id", "status", "train_score"),
    )

    def __repr__(self) -> str:
        return (
            f"<ImprovementSearchVariant(id={self.id}, iteration={self.iteration_id}, "
            f"generation={self.generation}, status={self.status}, score={self.train_score})>"
        )
