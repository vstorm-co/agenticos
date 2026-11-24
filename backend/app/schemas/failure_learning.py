"""The failure-learning loop's wire shapes: patterns, ledger, cases, tries.

Patterns are mined live, so they carry no `id` - a pattern is a grouping of
real runs, and the ledger entry a human curates from it is the row that
keeps. Eval tries mirror the workflow-eval shapes: a try stores per-case
snapshots + run ids, and the verdict is judged when the try is read.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.eval_judging import EvalExpectation

MAX_EVAL_CASES = 50
"""The most cases one agent holds: a try starts test runs for each, per side."""

MAX_SAMPLES = 5
"""The most samples per case in a try: Theo fails a case when half or more fail."""

MAX_AGENT_RUNS_PER_TRY = 10
"""Each case sample starts one agent run for old and new content."""

MAX_HISTORY_TURNS = 10
"""Prior turns a case carries, truncated - the failing part is the message."""

LedgerScope = Literal["agent", "model"]
LedgerStatus = Literal["draft", "open", "dismissed", "resolved"]


class FailurePattern(BaseSchema):
    """One recurring failure, counted live over real runs in a window."""

    agent_id: UUID | None = Field(
        default=None, description="The agent, or null for a model-scoped pattern"
    )
    agent_name: str | None = Field(default=None)
    model: str | None = Field(
        default=None,
        description="Primary `model_label`; approximate where a fallback may have served",
    )
    status: str = Field(description="The run status the pattern counts")
    error_class: str = Field(
        description="Parsed from the stored failure sentence, e.g. `ModelHTTPError:400`"
    )
    pattern_key: str = Field(
        description="Machine key for the pattern, e.g. `failed:ModelHTTPError:400`"
    )
    count: int
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    sample_run_ids: list[UUID] = Field(default_factory=list)
    sample_message_ids: list[UUID] = Field(
        default_factory=list,
        description="Down-rated answers only: ratings attach to messages, not runs",
    )
    already_tracked: bool = Field(
        default=False, description="An open ledger entry already covers this pattern"
    )


class FailurePatternList(BaseSchema):
    """Mined patterns, and what the mining cannot see."""

    items: list[FailurePattern]
    total: int
    notes: list[str] = Field(
        default_factory=list,
        description="What the counts do not claim - hangs with a fresh heartbeat "
        "are not detectable, per-model attribution is approximate",
    )


class LedgerEntryCreate(BaseSchema):
    """A pattern, accepted as real and worth a rule."""

    scope: LedgerScope
    model: str | None = Field(default=None, max_length=128)
    pattern_key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1)
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Snapshot at curation: run ids, count, window, error class, "
        "first and last seen",
    )


class LedgerEntryUpdate(BaseSchema):
    """Curate an entry: accept it, dismiss it, mark it resolved, rewrite why."""

    status: LedgerStatus | None = None
    summary: str | None = Field(default=None, min_length=1)


class LedgerEntryRead(BaseSchema, TimestampSchema):
    id: UUID
    organization_id: UUID
    agent_id: UUID | None = None
    scope: LedgerScope
    model: str | None = None
    pattern_key: str
    title: str
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: LedgerStatus
    created_by_user_id: UUID | None = None
    eval_case_count: int = 0
    proposal_count: int = 0
    open_since: datetime | None = Field(default=None, description="When the entry was opened")


class LedgerEntryList(BaseSchema):
    items: list[LedgerEntryRead]
    total: int


class EvalCaseHistoryTurn(BaseSchema):
    """One prior turn, as the case replays it to the model."""

    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=20000)


class EvalCaseInput(BaseSchema):
    """The user message that triggered the failure, and what came before it."""

    message: str = Field(min_length=1, max_length=20000)
    history: list[EvalCaseHistoryTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)


class EvalCaseCreate(BaseSchema):
    """A case: an input the agent should handle, and what its answer should say."""

    ledger_entry_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    input: EvalCaseInput
    expectation: EvalExpectation
    model_profile_id: UUID | None = None
    source_run_id: UUID | None = None


class EvalCaseLatestTry(BaseSchema):
    """How the agent's latest try went for this one case, or null when untried."""

    try_id: UUID
    old_passed: bool | None = None
    new_passed: bool | None = None
    gate_passed: bool | None = None
    status: str = Field(description="passed, failed or pending")


class EvalCaseRead(BaseSchema, TimestampSchema):
    id: UUID
    agent_id: UUID
    ledger_entry_id: UUID | None = None
    name: str
    position: int
    input: EvalCaseInput
    expectation: EvalExpectation
    model_profile_id: UUID | None = None
    source_run_id: UUID | None = None
    created_by_user_id: UUID | None = None
    latest_try: EvalCaseLatestTry | None = None


class EvalCaseList(BaseSchema):
    items: list[EvalCaseRead]
    total: int


class EvalTryCreate(BaseSchema):
    """Start a try: which cases, what new text, how many samples of each."""

    case_ids: list[UUID] = Field(min_length=1)
    # A try naming a proposal tries that proposal's new text, so the try
    # can evidence the proposal it would gate.
    proposal_id: UUID | None = None
    instructions_override: str | None = Field(default=None, min_length=1)
    samples: int = Field(default=1, ge=1, le=MAX_SAMPLES)

    @model_validator(mode="after")
    def bound_agent_runs(self) -> EvalTryCreate:
        if len(self.case_ids) * self.samples * 2 > MAX_AGENT_RUNS_PER_TRY:
            raise ValueError(f"A try can start at most {MAX_AGENT_RUNS_PER_TRY} agent runs")
        return self


class EvalTryCaseRead(BaseSchema):
    """One case as its runs stand now: still going, answered, or failed."""

    eval_id: UUID
    name: str
    expectation: EvalExpectation
    old_run_ids: list[UUID] = Field(default_factory=list)
    new_run_ids: list[UUID] = Field(default_factory=list)
    old_passed: bool | None = Field(
        default=None, description="Whether the old text passed; null while running"
    )
    new_passed: bool | None = Field(default=None)
    gate_passed: bool | None = Field(
        default=None, description="Old fails and new passes; null while running"
    )
    status: str = Field(description="passed, failed or pending")
    reason: str | None = Field(
        default=None,
        description="Why it failed without a verdict - a refusal, or that the "
        "case does not reproduce the failure",
    )


class EvalTryRead(BaseSchema):
    """One try of a set of cases, judged as its runs stand now."""

    id: UUID
    agent_id: UUID
    proposal_id: UUID | None = None
    target_skill_id: UUID | None = None
    tested_content_sha256: str | None = None
    created_at: datetime | None = None
    cases: list[EvalTryCaseRead]
    passed: int
    failed: int
    pending: int
    gate_passed: bool | None = Field(
        default=None,
        description="True when every case gate-passes, false when any fails, "
        "null while any is still going",
    )


ProposalTargetType = Literal["instructions", "skill"]
ProposalStatus = Literal["draft", "applied", "rejected"]


class ProposalTarget(BaseSchema):
    """What a proposal would change: the agent's instructions, or one skill."""

    type: ProposalTargetType
    skill_id: UUID | None = Field(default=None, description="Set iff the target is a skill")


class ProposalCreate(BaseSchema):
    """Propose a change: what it replaces, what replaces it, and why.

    `base_agent_version_id` defaults to the agent's current published
    version; `base_content_sha256` is never sent - it is the hash of the
    skill's content when a skill-targeted proposal is written.
    """

    ledger_entry_id: UUID | None = None
    eval_try_id: UUID | None = None
    target: ProposalTarget
    old_text: str = Field(min_length=1)
    new_text: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    base_agent_version_id: UUID | None = None


class ProposalReject(BaseSchema):
    """Reject a proposal, with the reason - recorded in the audit trail."""

    reason: str = Field(min_length=1)


class AppliedVersionRead(BaseSchema):
    """The version an apply published: its id and its number, the rollback handle."""

    id: UUID
    number: int


class ProposalRead(BaseSchema, TimestampSchema):
    """One proposal, its eval evidence, and its apply record if applied."""

    id: UUID
    organization_id: UUID
    agent_id: UUID
    ledger_entry_id: UUID | None = None
    eval_try_id: UUID | None = None
    target_type: ProposalTargetType
    skill_id: UUID | None = None
    old_text: str
    new_text: str
    rationale: str
    base_agent_version_id: UUID | None = None
    base_content_sha256: str | None = None
    applied_content_sha256: str | None = None
    reverted_at: datetime | None = None
    rollback_available: bool = False
    status: ProposalStatus
    applied_version_id: UUID | None = None
    created_by_user_id: UUID | None = None
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    eval_evidence: EvalTryRead | None = Field(
        default=None,
        description="The linked try, judged as its runs stand now - or null when no try is linked",
    )
    applied_version: AppliedVersionRead | None = Field(
        default=None, description="The version the apply published, or null"
    )
    eval_gated: bool = Field(
        description="Whether an eval gate evidences this proposal. "
        "Instruction targets only: skill targets are human-reviewed, never "
        "eval-gated, and are flagged as ungated wherever they are shown."
    )


class ProposalList(BaseSchema):
    items: list[ProposalRead]
    total: int
