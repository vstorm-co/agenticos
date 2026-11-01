"""Starting an improvement session and reading its durable timeline."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.db.models.improvement import (
    DroppedHunk,
    ImprovementStage,
    ImprovementStatus,
    ImprovementVerdict,
    StopReason,
)
from app.schemas.base import BaseSchema
from app.schemas.knowledge_gap import CauseBranch
from app.schemas.scoring import ScorerKind, ScorerStatus


class ImprovementTarget(BaseSchema):
    improver_agent_id: UUID | None = None

    dataset_id: UUID | None = None
    suite_id: UUID | None = None
    window_days: int = Field(default=30, ge=1, le=90)
    max_iterations: int = Field(default=3, ge=1, le=3)

    @model_validator(mode="after")
    def _one_target(self) -> ImprovementTarget:
        if (self.dataset_id is None) == (self.suite_id is None):
            raise ValueError("Choose one dataset or one suite")
        return self


class ImprovementStart(ImprovementTarget):
    budget_usd: Decimal = Field(gt=0, max_digits=12, decimal_places=6)


class ImprovementEstimate(BaseSchema):
    proposal_usd: Decimal
    knowledge_usd: Decimal = Decimal(0)
    eval_usd: Decimal
    per_round_usd: Decimal = Field(
        description="About what one attempt costs - its proposal and its check - each priced "
        "again when a person takes it"
    )
    total_usd: Decimal = Field(
        description="What the session spends before it first waits for a person: sorting its "
        "examples. The spending limit caps everything after it"
    )
    max_iterations: int
    cases: int
    held_out: int | None = Field(
        default=None,
        description="How many questions the first attempt is measured on - kept aside, and "
        "no copy of its evidence - counted as its analysis will count them",
    )
    evidence_runs: int
    estimated_minutes: int = Field(
        description="About how long the session takes if every round runs; an estimate only"
    )
    affordable: bool
    reason: str | None = None


class ImprovementIterationRead(BaseSchema):
    id: UUID
    number: int
    authoring_request_id: UUID | None
    batch_id: UUID | None
    eval_run_ids: list[UUID]
    candidate_spec_hash: str | None
    included_hunk_ids: list[UUID] | None = None
    note: str | None = Field(
        default=None, description="What the person who asked for this attempt told its helper"
    )
    previous_eval_run_ids: list[UUID] = Field(default_factory=list)
    attribution_eval_run_ids: dict[UUID, UUID] = Field(default_factory=dict)
    dropped_hunk_ids: list[UUID]
    dropped: list[DroppedHunk] = Field(default_factory=list)
    verdict: ImprovementVerdict | None
    verdict_detail: dict[str, int | float | str | None] | None
    held_out: int | None = Field(
        default=None,
        description="How many questions the attempt is measured on - kept aside, and no copy "
        "of its evidence: counted by its check once it ran, before that by the analysis or "
        "its draw; null until known",
    )
    cost_usd: Decimal
    started_at: datetime
    ended_at: datetime | None


class ImprovementEvent(BaseSchema):
    action: str
    at: datetime
    stage: str | None = None
    status: str | None = None
    reason: str | None = None
    actor_user_id: UUID | None = Field(
        default=None,
        description="The person whose action this was; absent for the session's own steps",
    )
    actor_name: str | None = Field(
        default=None,
        description="That person's display name, for a reader who may see the member directory",
    )


class CheckAnswers(BaseSchema):
    """How far one side of a check has answered its questions."""

    answered: int = Field(description="First answers finished, failed ones included")
    total: int = Field(description="First answers asked")
    reused: bool = Field(
        default=False,
        description="Answered in an earlier run, so this check asked nothing new on this side",
    )


class NoisyAttempt(BaseSchema):
    """One attempt's answers to a question, first answer then each re-ask."""

    number: int
    baseline: list[bool | None]
    candidate: list[bool | None]


class NoisyQuestion(BaseSchema):
    """A held-out question whose grade changed without the agent changing."""

    case_id: UUID
    input: str = Field(description="The question the case asks")
    attempts: list[NoisyAttempt]


class AttemptNoise(BaseSchema):
    number: int
    baseline_unstable: int = Field(
        description="Held-out questions today's version answered both well and badly on re-asking"
    )
    candidate_unstable: int = Field(description="The same for the attempt's changed version")


class MeasurementNoise(BaseSchema):
    """Whether the session's test can tell a better version from a worse one.

    Read from the attempts' stored checks. Each attempt is measured on its own draw
    of held-out questions, so re-asks within an attempt and today's version on the
    questions two attempts share are what compare.
    """

    noisy: bool
    held_out: int = Field(
        description="Distinct held-out questions the attempts measured, across all of them; "
        "one attempt's own count is its iteration's held_out"
    )
    within: int = Field(
        default=0, description="Held-out questions graded both ways when asked again in one attempt"
    )
    shared: int = Field(default=0, description="Held-out questions two or more attempts measured")
    between: int | None = Field(
        default=None,
        description="Shared questions today's version was graded differently on in two "
        "attempts; null when too few are shared to tell",
    )
    too_few_shared: bool = Field(
        default=True, description="Fewer shared questions than it takes to compare attempts"
    )
    baseline_low: float | None = Field(
        description="Today's version's lowest pass rate on the shared questions across attempts"
    )
    baseline_high: float | None = Field(description="And its highest")
    baseline_spread: int | None = Field(
        description="Shared questions between today's version's lowest and highest score"
    )
    unstable: int = Field(
        description="Distinct held-out questions graded both ways when asked again, or "
        "differently for today's version on a shared question"
    )
    by_attempt: list[AttemptNoise] = Field(default_factory=list)
    examples: list[NoisyQuestion] = Field(default_factory=list)


class TryAgainBlocked(BaseSchema):
    """Why Try again would be refused, said before anyone presses it."""

    reason: Literal["nothing_to_learn", "missing_holdout"] = Field(
        description="nothing_to_learn: no answer the next attempt would read still fails. "
        "missing_holdout: another attempt would keep aside too few gradable questions to be "
        "measured, and the session's questions are fixed"
    )
    needed: int | None = Field(
        default=None,
        ge=1,
        description="With missing_holdout, how many more such questions another attempt needs",
    )


class NextStepBlocked(BaseSchema):
    """Why a waiting session's next step cannot be taken."""

    reason: Literal["missing_holdout"] = Field(
        description="missing_holdout: the attempt keeps aside too few gradable questions "
        "to measure its check, and the session's questions are fixed"
    )
    needed: int = Field(ge=1, description="How many more such questions the check needs")


class ImprovementRead(BaseSchema):
    round_hint: Literal["no_change", "inconclusive"] | None = Field(
        default=None,
        description="When the last two attempts changed nothing, or could not tell, another "
        "one is unlikely to help; only a hint, Try again stays available",
    )
    next_step: Literal["propose", "check"] | None = Field(
        default=None,
        description="What a person's next step starts while the session waits: a proposal "
        "after Understand, or the check of the chosen changes after Changes",
    )
    next_step_blocked: NextStepBlocked | None = Field(
        default=None,
        description="Why the next step cannot be taken at this stop; null when it can",
    )
    try_again_blocked: TryAgainBlocked | None = Field(
        default=None,
        description="Why Try again would be refused, for a caller who may continue the "
        "session; null when it would go on or is not offered",
    )
    published_version_id: UUID | None = None
    published_version: int | None = None
    next_version: int | None = None
    offer_automatic_check: bool = False
    can_restart: bool = False
    can_discard: bool = False
    improver_agent_id: UUID | None = None

    id: UUID
    agent_id: UUID
    created_by_user_id: UUID | None
    status: ImprovementStatus
    stage: ImprovementStage | None
    iteration: int
    max_iterations: int
    base_version_id: UUID | None
    dataset_id: UUID
    dataset_version: int
    suite_id: UUID | None
    estimate_usd: Decimal
    budget_usd: Decimal
    spent_usd: Decimal
    best_iteration_id: UUID | None
    stop_reason: StopReason | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    iterations: list[ImprovementIterationRead] = Field(default_factory=list)
    timeline: list[ImprovementEvent] = Field(default_factory=list)
    knowledge_eval_run_ids: list[UUID] = Field(default_factory=list)
    deferred_topic_ids: list[UUID] = Field(
        default_factory=list,
        description="Knowledge documents set aside with Not now in this session",
    )
    baseline_answers: CheckAnswers | None = Field(
        default=None,
        description="How far the first attempt's check has asked the agent as it is today; "
        "none before that check starts",
    )
    candidate_answers: CheckAnswers | None = Field(
        default=None,
        description="How far the current attempt's check has asked the changed agent; "
        "none before that check starts",
    )
    measurement_noise: MeasurementNoise | None = Field(
        default=None,
        description="Whether the test told the versions apart; none while the session works, "
        "before an attempt is measured, for a reader without runs:view, or in a list of "
        "sessions - read the session for it",
    )


class ImprovementAwaiting(BaseSchema):
    """A session waiting for a person, as a list of them shows it."""

    id: UUID
    agent_id: UUID
    agent_name: str
    status: ImprovementStatus
    stage: ImprovementStage | None
    iteration: int
    max_iterations: int
    created_at: datetime
    next_step_blocked: NextStepBlocked | None = Field(
        default=None,
        description="Why the next step cannot be taken at this stop; null when it can",
    )


class TopicDeferral(BaseSchema):
    """Set a knowledge document aside for this session, or bring it back."""

    later: bool


class ImprovementContinue(BaseSchema):
    budget_usd: Decimal = Field(gt=0, max_digits=12, decimal_places=6)


class ContinuationEstimate(BaseSchema):
    mode: Literal["next_step", "next_round", "resume", "retry"]
    number: int
    total_usd: Decimal = Field(description="The most the step may cost; consent is given to it")
    expected_usd: Decimal = Field(
        description="What the step most likely costs: a check without the repeat an "
        "inconclusive result gets, or asking again the answers whose result changed"
    )
    budget_usd: Decimal
    affordable: bool
    candidate_hash: str


class ContinuationConsent(ImprovementContinue):
    confirmed: Literal[True]
    estimate_usd: Decimal = Field(ge=0, max_digits=12, decimal_places=6)
    candidate_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    note: str | None = Field(
        default=None,
        max_length=2000,
        description="With Try again only: what the attempt's helper should keep in mind, "
        "read beside its evidence",
    )


class ImprovementDiscard(BaseSchema):
    confirmed: Literal[True]


class AttributionEstimate(BaseSchema):
    changes: int
    total_usd: Decimal
    affordable: bool
    already_started: bool


class AttributionConsent(BaseSchema):
    confirmed: Literal[True]
    estimate_usd: Decimal = Field(ge=0, max_digits=12, decimal_places=6)


class ImprovementFinish(BaseSchema):
    confirmed: Literal[True]
    publish: bool = False
    automatic_check: bool = False


class ImprovementFinished(BaseSchema):
    session: ImprovementRead
    version_id: UUID | None = None
    version: int | None = None


class KnowledgeCheckTarget(BaseSchema):
    topic_id: UUID
    mode: Literal["context", "retrieval"] = "context"
    round: int = Field(ge=1, le=3)
    case_ids: list[UUID] = Field(min_length=1, max_length=1000)


class KnowledgeCheckEstimate(BaseSchema):
    total_usd: Decimal
    affordable: bool
    can_measure: bool
    cases: int
    excluded: int
    supported: bool
    draft_hash: str
    reason: str | None = None


class KnowledgeCheckConsent(KnowledgeCheckTarget):
    confirmed: Literal[True]
    estimate_usd: Decimal = Field(ge=0, max_digits=12, decimal_places=6)
    draft_hash: str = Field(min_length=64, max_length=64)


class KnowledgeAdded(BaseSchema):
    """The document since added to cover what an answer was missing."""

    document_id: UUID
    filename: str
    knowledge_base_id: UUID
    added_at: datetime | None = Field(description="When the document covered the topic")


class EvidenceGrade(BaseSchema):
    """How one check or judge criterion graded a test answer."""

    scorer: ScorerKind
    name: str
    status: ScorerStatus
    reason: str


class ImprovementEvidenceItem(BaseSchema):
    run_id: UUID
    conversation_id: UUID | None
    kind: Literal["chat", "train_eval"]
    status: str
    rating: int
    question: str | None
    answer: str | None
    comments: list[str]
    grades: list[EvidenceGrade] = Field(
        default_factory=list, description="How a test question's answer was graded"
    )
    branch: CauseBranch = Field(description="The column the classifier put it in")
    reason: str | None = None
    topic_id: UUID | None = Field(
        default=None,
        description="The knowledge gap topic its miss joined, when one did; examples sharing one "
        "are one problem",
    )
    knowledge_added: KnowledgeAdded | None = Field(
        default=None,
        description="For an answer missing knowledge, the document added since to its topic: "
        "nothing is left to draft for it",
    )


class ImprovementEvidence(BaseSchema):
    items: list[ImprovementEvidenceItem]
    sample_limit: int
    training_failures: int


class ImprovementSelection(BaseSchema):
    hunk_ids: list[UUID] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _distinct(self) -> ImprovementSelection:
        if len(set(self.hunk_ids)) != len(self.hunk_ids):
            raise ValueError("Choose each change once")
        return self


class ChangeEdit(BaseSchema):
    """A person's edit of one proposed change's text while the session waits at Changes;
    null puts back the text that was proposed."""

    edited_text: str | None = Field(max_length=20000)


class SelectionEstimate(BaseSchema):
    suggestions: int
    total_usd: Decimal
    affordable: bool
    candidate_hash: str


class SelectionConsent(ImprovementSelection):
    confirmed: Literal[True]
    estimate_usd: Decimal = Field(ge=0, max_digits=12, decimal_places=6)
    candidate_hash: str = Field(min_length=64, max_length=64)
