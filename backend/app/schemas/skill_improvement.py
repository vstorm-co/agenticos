"""Skill improvement sessions as the API reads and starts them.

The shapes follow an agent's session (`app.schemas.improvement`) field for field, so
one wizard reads both: a field both have keeps its name and meaning, and what a
skill session lacks - an agent, a dataset, a draft to publish - is absent rather
than null. What only a skill has - its line, the agents that line serves, the
multi-agent check and the outcomes it allows - is added.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models.improvement import (
    DroppedHunk,
    ImprovementStage,
    ImprovementStatus,
    ImprovementVerdict,
    StopReason,
)
from app.db.models.skill_check import CheckMode, CheckOutcome
from app.db.models.skill_improvement import SkillImprovementOutcome, SkillImprovementPurpose
from app.schemas.authoring import EvidenceQuote
from app.schemas.base import BaseSchema
from app.schemas.improvement import (
    ContinuationConsent,
    ContinuationEstimate,
    ImprovementEvent,
    NextStepBlocked,
    TryAgainBlocked,
)
from app.schemas.skill_check import (
    AgentRef,
    SkillCheckApply,
    SkillCheckEstimate,
    SkillCheckFork,
    SkillCheckRead,
)
from app.schemas.skill_version import PersonRef, ReturnedToMain, SkillForkRead


class SkillLine(BaseSchema):
    """One line of a skill: its main line (`fork_id` null) or one fork."""

    fork_id: UUID | None
    name: str = Field(description="`main`, or the fork's name")


class SkillVersionRef(BaseSchema):
    id: UUID
    number: int


class SkillImprovementTarget(BaseSchema):
    """Which line a session improves, and how far back it reads - estimating and starting alike."""

    fork_id: UUID | None = Field(
        default=None, description="The fork to improve; null for the main line"
    )
    window_days: int = Field(default=30, ge=1, le=90)
    max_iterations: int = Field(default=3, ge=1, le=3)
    from_run: UUID | None = Field(
        default=None,
        description="An agent's improvement session that pointed at this skill: its "
        "problems are read beside the line's evidence, and its agent's line is the one "
        "improved. Read on the server; nothing else about it is taken from the request",
    )
    improver_agent_id: UUID | None = Field(
        default=None,
        description="The helper that groups the problems and proposes the edits; the "
        "organization's own when null",
    )


class SkillImprovementStart(SkillImprovementTarget):
    budget_usd: Decimal = Field(gt=0, max_digits=12, decimal_places=6)


type MergeOutcome = Literal["catch_up", "return_to_main"]
"""What a person may do with a merge session's result, beside a check's own outcomes:
take the merge into the fork, or move the fork's agents back to main."""

type MainAlone = Literal["off", "same", "checked"]
"""Whether a catch-up also checked main's newest version alone on the fork's agents: not
asked for, not needed because the merge is main, or checked."""


class SkillMergeStart(BaseSchema):
    budget_usd: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=6,
        description="The spending limit for the session; its check is priced at Changes",
    )


class SkillMergeEstimate(BaseSchema):
    """What a catch-up or a move to main would merge, and what it costs before Changes."""

    line: SkillLine = Field(description="The line the merge becomes a new version of")
    source_fork: SkillLine | None = Field(
        default=None, description="For a move to main, the fork whose changes it takes"
    )
    base_version: SkillVersionRef = Field(description="The line's newest version, as merged")
    conflicts: int = Field(
        description="Parts both lines changed differently; the assistant proposes a text "
        "for each, and a person may change it"
    )
    total_usd: Decimal = Field(
        description="Proposing the conflicts' texts, zero without conflicts; the check is "
        "priced at Changes"
    )
    agents: int
    hidden_agents: int
    affordable: bool


class SkillImprovementEstimate(BaseSchema):
    """What a session on a line would read and cost before it first waits for a person."""

    line: SkillLine
    base_version: SkillVersionRef
    proposal_usd: Decimal = Field(description="Grouping the problems, then one proposal")
    check_usd: Decimal = Field(
        description="At most what one quick check across the line's agents costs, priced on "
        "the line as it is"
    )
    per_round_usd: Decimal = Field(
        description="About what one attempt costs - its proposal and its check - each priced "
        "again when a person takes it"
    )
    total_usd: Decimal = Field(
        description="What the session spends before it first waits for a person: grouping "
        "the problems. The spending limit caps everything after it"
    )
    max_iterations: int
    evidence_runs: int
    usage_unknown: int = Field(
        description="Rated-down or failed runs from before skill use was recorded, which may "
        "have used the skill and are not read"
    )
    agents: int = Field(description="Agents the line serves that the caller may see")
    hidden_agents: int = Field(description="Agents the line serves that the caller may not see")
    estimated_minutes: int
    affordable: bool
    reason: Literal["no_evidence"] | None = None


class SkillImprovementIterationRead(BaseSchema):
    id: UUID
    number: int
    authoring_request_id: UUID | None
    batch_id: UUID | None
    candidate_spec_hash: str | None = Field(
        default=None,
        validation_alias="candidate_hash",
        description="The hash of the candidate skill text - description and body - that "
        "was checked; named as an agent attempt's for one wizard",
    )
    included_hunk_ids: list[UUID] | None = None
    note: str | None = Field(
        default=None, description="What the person who asked for this attempt told its helper"
    )
    dropped_hunk_ids: list[UUID]
    dropped: list[DroppedHunk] = Field(default_factory=list)
    description_changed: bool = Field(
        description="The candidate changes the skill's description, so its check is thorough"
    )
    verdict: ImprovementVerdict | None
    verdict_detail: dict[str, int | float | str | None] | None = None
    held_out: int | None = None
    check_id: UUID | None = Field(
        default=None, validation_alias="skill_check_id", description="The attempt's skill check"
    )
    check_verdict: Literal["passed", "blocked", "no_better", "needs_ack", "failed"] | None = None
    cost_usd: Decimal
    started_at: datetime = Field(validation_alias="created_at")
    ended_at: datetime | None


class SkillImprovementRead(BaseSchema):
    """One session on a skill line, as its wizard reads it."""

    round_hint: Literal["no_change", "inconclusive"] | None = None
    next_step: Literal["propose", "check"] | None = Field(
        default=None,
        description="What a person's next step starts while the session waits: a proposal "
        "after Understand, or the check of the chosen changes after Changes",
    )
    next_step_blocked: NextStepBlocked | None = None
    try_again_blocked: TryAgainBlocked | None = None
    can_restart: bool = False
    can_discard: bool = False

    id: UUID
    skill_id: UUID
    fork_id: UUID | None
    purpose: SkillImprovementPurpose = SkillImprovementPurpose.IMPROVE
    improver_agent_id: UUID | None = Field(
        default=None, description="The helper the session's steps run on; null for the default"
    )
    source_fork_id: UUID | None = Field(
        default=None, description="For a move to main, the fork whose changes it takes"
    )
    merge_id: UUID | None = Field(
        default=None,
        description="For a catch-up or a move to main, the merge Changes shows and edits",
    )
    line_name: str = ""
    base_version: SkillVersionRef | None = None
    created_by_user_id: UUID | None
    created_by: PersonRef | None = Field(
        default=None,
        description="Who started it, for a caller who may read the member directory",
    )
    status: ImprovementStatus
    stage: ImprovementStage | None
    iteration: int
    max_iterations: int
    estimate_usd: Decimal
    budget_usd: Decimal
    spent_usd: Decimal = Decimal(0)
    best_iteration_id: UUID | None
    stop_reason: StopReason | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None = Field(
        default=None,
        description="When a session waiting for a person ends on its own; null while it works "
        "or once it is over",
    )
    outcome: SkillImprovementOutcome | None
    applied_version_id: UUID | None
    agents: int = 0
    hidden_agents: int = 0
    check: SkillCheckRead | None = Field(
        default=None,
        description="The current attempt's check across the line's agents, once it started",
    )
    stale: bool = Field(
        default=False,
        description="The line moved on since the session read it. At Changes, price the "
        "next step again: it measures the chosen changes on the line as it is now. At "
        "Result, Check again (`POST …/recheck`) does. A decision refused with 409 because "
        "the line's agents changed since the check means the same",
    )
    main_alone: MainAlone | None = Field(
        default=None,
        description="A catch-up's second check, of main's newest version alone; `off` and "
        "`same` say why Return to main is not offered",
    )
    main_alone_check: SkillCheckRead | None = None
    outcomes: list[CheckOutcome | MergeOutcome] = Field(
        default_factory=list,
        description="What a person may do with the result now: the check's outcomes while "
        "the session waits on it, Try again included as `improve_further`. A catch-up "
        "offers `catch_up` and, when main alone made nobody worse, `return_to_main`",
    )
    iterations: list[SkillImprovementIterationRead] = Field(default_factory=list)
    timeline: list[ImprovementEvent] = Field(default_factory=list)


class SkillImprovementAwaiting(BaseSchema):
    """A skill session waiting for a person, as "Waiting for you" lists it."""

    id: UUID
    skill_id: UUID
    skill_name: str
    fork_id: UUID | None
    line_name: str
    status: ImprovementStatus
    stage: ImprovementStage | None
    iteration: int
    max_iterations: int
    created_at: datetime
    next_step_blocked: NextStepBlocked | None = None


class ProblemAgent(BaseSchema):
    id: UUID
    name: str
    runs: int


class SkillProblemExample(BaseSchema):
    """A passage of one run that shows the problem, checked word for word against it."""

    run_id: UUID
    quote: str | None = Field(
        description="Null for a reader who may not read runs: the example is named, not quoted"
    )


class SkillProblemRead(BaseSchema):
    title: str
    summary: str
    runs: int
    agents: list[ProblemAgent]
    hidden_agents: int = Field(description="Agents with this problem the caller may not see")
    examples: list[SkillProblemExample] = Field(default_factory=list)
    hidden_examples: int = Field(
        default=0, description="Examples from agents the caller may not see, counted, not shown"
    )


class SkillImprovementProblems(BaseSchema):
    """Understand: what went wrong with the skill, grouped, and where."""

    problems: list[SkillProblemRead]
    not_the_skill: int = Field(
        description="Bad answers whose cause was the agent's own instructions or knowledge"
    )
    not_a_problem: int
    usage_unknown: int


class SkillContinue(BaseSchema):
    budget_usd: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=6,
        description="A spending limit to price the step against; the session's own when "
        "lower or not given, since a limit is only ever raised",
    )
    mode: CheckMode | None = Field(
        default=None,
        description="For a check: quick (the default) or thorough. A changed description "
        "is always checked thoroughly",
    )
    main_alone: bool = Field(
        default=True,
        description="For a catch-up's check: also check main's newest version alone, so "
        "the result can offer returning the fork's agents to main",
    )


class SkillContinuationEstimate(ContinuationEstimate):
    """The next step's price; for a check, what it costs across the line's agents."""

    check_estimate: SkillCheckEstimate | None = Field(
        default=None,
        description="For the check: each agent it runs, and the ones it cannot, before it starts",
    )
    main_alone_usd: Decimal | None = Field(
        default=None,
        description="For a catch-up: what checking main alone adds, included in `total_usd`",
    )
    main_alone_estimate: SkillCheckEstimate | None = None


class SkillContinuationConsent(ContinuationConsent):
    mode: CheckMode | None = Field(
        default=None,
        description="For a check: quick (the default) or thorough. A changed description "
        "is always checked thoroughly",
    )
    main_alone: bool = True


class SkillImprovementApply(SkillCheckApply):
    confirmed: Literal[True]


class SkillImprovementReturn(BaseSchema):
    confirmed: Literal[True]
    acknowledge_unknown: bool = Field(
        default=False,
        description="Return the fork's agents although main alone could not be checked on "
        "some of them",
    )


class SkillImprovementFork(SkillCheckFork):
    confirmed: Literal[True]


class SkillImprovementApplied(BaseSchema):
    """What applying made: the line's new version, and the agents kept where they were."""

    session: SkillImprovementRead
    version_id: UUID
    version: int
    pinned: list[AgentRef]


class SkillImprovementReturned(BaseSchema):
    """What returning a fork's agents to main did; the session is accepted with it."""

    session: SkillImprovementRead
    returned: ReturnedToMain


class SkillImprovementForked(BaseSchema):
    """The fork the change became, and the agents that moved onto it."""

    session: SkillImprovementRead
    fork: SkillForkRead
    moved: list[AgentRef]
    draft_only: list[AgentRef]


class SkillProblem(BaseModel):
    """One problem the bad answers show, as the analyst writes it."""

    title: str = Field(description="A few words naming the problem.")
    summary: str = Field(description="One or two sentences: what goes wrong, and when.")
    cause: Literal["skill", "not_the_skill", "not_a_problem"] = Field(
        description=(
            "skill: the skill's text leads to it. not_the_skill: the agent's own "
            "instructions or knowledge do. not_a_problem: the answer was fine."
        )
    )
    run_ids: list[UUID] = Field(description="The runs that show it, by the ids given.")
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class SkillProblems(BaseModel):
    """The analyst's grouping of a skill's bad answers."""

    problems: list[SkillProblem] = Field(default_factory=list)


class SkillBodyEdit(BaseModel):
    """One passage of the skill's body to change."""

    old_text: str = Field(
        description=(
            "The exact passage of the current body to replace, copied verbatim and long "
            "enough to occur only once. Empty to insert new text."
        )
    )
    new_text: str = Field(description="What replaces it. Empty to delete the passage.")
    after: str = Field(
        default="",
        description=(
            "For an insertion only: the exact passage the new text follows. Empty appends "
            "it at the end."
        ),
    )
    rationale: str = Field(description="One paragraph: why, in terms of the evidence.")
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class SkillEdits(BaseModel):
    """What the improver proposes for one skill line: edits to passages, not a new body."""

    summary: str
    expected_effect: str
    edits: list[SkillBodyEdit] = Field(default_factory=list)
    description: str | None = Field(
        default=None,
        description=(
            "A new one-line description, only when the evidence shows agents opening the "
            "skill when they should not, or not opening it when they should. Null keeps it."
        ),
    )
    description_rationale: str = ""


MERGE_ASK = (
    "Two lines of a skill changed the same passages differently. For each numbered "
    "conflict below, write the passage as it should read with both changes kept - the "
    "fork's and main's - or, where they cannot both stand, the one that keeps the skill "
    "correct. Answer with one text per conflict, in order, keeping each passage's line "
    "breaks. A description stays one line of at most 500 characters.\n\n"
)
"""What the improver is asked before a merge's numbered conflicts."""


class MergeTexts(BaseModel):
    """The improver's combined text for each conflict of a merge, in the order asked."""

    texts: list[str] = Field(
        description="One text per numbered conflict, in order: the passage as it should "
        "read with both sides' changes kept"
    )
