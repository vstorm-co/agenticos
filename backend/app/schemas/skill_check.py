"""A skill change checked on every agent of its line: what to start, and what came back."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.db.models.skill_check import (
    AgentState,
    CheckMode,
    CheckOutcome,
    CheckSource,
    CheckStatus,
    CheckVerdict,
    SampleKind,
    UnknownReason,
)
from app.schemas.base import BaseSchema
from app.schemas.skill_version import SkillForkRead, SkillVersionRead, VersionRef


class CandidateText(BaseSchema):
    """The text a change would leave the skill with."""

    description: str = Field(min_length=1, max_length=500)
    content: str


class SkillCheckStart(BaseSchema):
    """What to check: a text, or a pending proposal, on main or one fork."""

    fork_id: UUID | None = Field(default=None, description="The fork to change; null for main")
    candidate: CandidateText | None = None
    proposal_id: UUID | None = Field(
        default=None, description="A pending change to the skill, checked as it was proposed"
    )
    base_version_id: UUID | None = Field(
        default=None,
        description=(
            "The version of the line the text was written against. A check is refused once "
            "the line has moved past it, so a save made meanwhile is never written over"
        ),
    )
    mode: CheckMode = Field(
        default=CheckMode.QUICK,
        description=(
            "`quick` asks the skill's test questions and at most four of each agent's own "
            "that loaded the skill; `thorough` each agent's whole dataset. A change to the "
            "description is always thorough"
        ),
    )

    @model_validator(mode="after")
    def _one_candidate(self) -> Self:
        if (self.candidate is None) == (self.proposal_id is None):
            raise ValueError("Name a candidate text or a proposal, not both")
        return self


class SkillCheckRequest(SkillCheckStart):
    """A check as a caller asks for it: a text names the version it was written against,
    so a save made meanwhile is refused rather than written over."""

    @model_validator(mode="after")
    def _text_names_its_base(self) -> Self:
        if self.candidate is not None and self.base_version_id is None:
            raise ValueError("Name the version the text was written against")
        return self


class SkillUpdateCheck(BaseSchema):
    """How thoroughly to check main's newest version on one pinned agent."""

    mode: CheckMode = Field(
        default=CheckMode.QUICK,
        description="As for a change; a newer description is always checked thoroughly",
    )


class AgentRef(BaseSchema):
    id: UUID
    name: str


StageKind = Literal["skill_set", "dataset_sample", "dataset"]


class StageCounts(BaseSchema):
    """One stage's held-out questions, candidate against baseline."""

    compared: int = Field(
        description="Answered and graded on both sides: fixed, broken or unchanged"
    )
    fixed: int = Field(description="Failed before and pass with the change, re-asks or not")
    broken: int = Field(description="Passed before and fail with the change, re-asks or not")
    unchanged: int = Field(description="Compared, and answered the same way on both sides")
    unknown: int = Field(
        description=(
            "Held out but not compared: unanswered or ungraded on a side, asked on one side "
            "only, or changed in between"
        )
    )


class CheckStage(BaseSchema):
    kind: StageKind
    dataset_id: UUID
    dataset_name: str | None = Field(description="Null for a dataset the reader may not see")
    cases: int = Field(
        description=(
            "The questions the stage asks, without those taken from the conversations the "
            "change learned from"
        )
    )
    eval_run_id: UUID | None = Field(
        default=None, description="The eval run that asked them, once the stage started"
    )
    counts: StageCounts | None = Field(
        default=None,
        description=(
            "Null until the agent is judged, for a check judged before counts were kept, "
            "and for a dataset the reader may not see"
        ),
    )


class SkillCheckAgentRead(BaseSchema):
    agent: AgentRef
    via_specialist: str | None = None
    agent_version: int | None = None
    state: AgentState
    unknown_reason: UnknownReason | None = None
    sample: SampleKind | None = Field(
        default=None,
        description=(
            "In a quick check, whether the agent's own questions were asked; the skill's "
            "test questions alone, with none that loaded the skill or could be graded; or "
            "`own_not_asked`, picked and left unasked once the skill's made it worse"
        ),
    )
    stages: list[CheckStage]
    fixed: int = 0
    broken: int = 0
    held_out: int = Field(default=0, description="Questions compared, both stages together")
    fixed_confirmed: int = 0
    regressions_confirmed: int = 0
    noisy: bool = False
    expected_usd: Decimal
    at_most_usd: Decimal


class LineRef(BaseSchema):
    fork_id: UUID | None
    name: str = Field(description="`main`, or the fork's name")


class SkillCheckEstimate(BaseSchema):
    line: LineRef
    base_version: VersionRef
    mode: CheckMode
    description_changed: bool
    agents: list[SkillCheckAgentRead] = Field(
        description="The agents of the line the caller may see"
    )
    hidden: int = Field(description="Agents of the line the caller may not see, counted")
    hidden_unknown: int = Field(
        default=0, description="Of those, the ones that could not be checked"
    )
    expected_usd: Decimal = Field(description="The most likely price")
    at_most_usd: Decimal = Field(description="The price if every question flips and is asked again")
    org_remaining_usd: Decimal | None
    affordable: bool


class SkillCheckRead(SkillCheckEstimate):
    id: UUID
    skill_id: UUID
    source: CheckSource = Field(
        description="`catch_up` for a pinned agent's update, which is accepted by moving the "
        "agent with `PUT .../agents/{agent_id}/binding`, never by applying it"
    )
    agent_id: UUID | None = Field(
        default=None, description="The pinned agent an update is checked on"
    )
    candidate_version_id: UUID | None = Field(
        default=None, description="The main version that update would move it to"
    )
    candidate: CandidateText = Field(
        description="The text checked, so a person can go back to editing it"
    )
    status: CheckStatus
    verdict: CheckVerdict | None = None
    warnings: list[Literal["within_noise"]] = Field(default_factory=list)
    outcomes: list[CheckOutcome] = Field(
        default_factory=list, description="What may be done with it now; empty while it runs"
    )
    outcome: CheckOutcome | None = None
    proposal_id: UUID | None = None
    session_id: UUID | None = Field(
        default=None,
        description="The improvement session that started this check; it is decided there, "
        "and the check's own decisions answer 409 DECIDE_IN_SESSION",
    )
    applied_version_id: UUID | None = None
    no_readers: bool = Field(
        default=False,
        description=(
            "No agent read the line, so the change reached nobody and nothing was asked; "
            "the check passed with nothing to measure"
        ),
    )
    created_at: datetime
    finished_at: datetime | None = None


class SkillCheckAwaiting(BaseSchema):
    """A check of a skill change a person has to come back to, as "Waiting for you" lists it."""

    id: UUID
    skill_id: UUID
    skill_name: str
    line: LineRef
    status: CheckStatus = Field(description="`running`, or `done` and waiting for a decision")
    verdict: CheckVerdict | None = None
    proposal_id: UUID | None = Field(
        default=None, description="The proposed change it checks; null for a text checked by hand"
    )
    agents: int = Field(
        description="The agents it checks, counting the ones the caller may not see"
    )
    created_at: datetime


class SkillCheckList(BaseSchema):
    items: list[SkillCheckRead]
    total: int


class SkillCheckApply(BaseSchema):
    acknowledge_unknown: bool = Field(
        default=False, description="Required when agents could not be checked"
    )
    pin_worse: bool = Field(
        default=False,
        description="Keep the agents the change made worse on the version they use now",
    )
    note: str | None = Field(default=None, max_length=500)


class SkillCheckApplied(BaseSchema):
    version: SkillVersionRead
    pinned: list[AgentRef]


class SkillCheckFork(BaseSchema):
    name: str = Field(min_length=1, max_length=64)
    acknowledge_unknown: bool = False
    agent_ids: list[UUID] | None = Field(
        default=None,
        description=(
            "The check's agents to move onto the fork. Left out, the agents it helped move; "
            "an empty list moves none"
        ),
    )


class SkillCheckForked(BaseSchema):
    fork: SkillForkRead
    moved: list[AgentRef] = Field(description="Agents whose published version now uses the fork")
    draft_only: list[AgentRef] = Field(
        description="Agents whose draft uses it; publishing is somebody else's to do"
    )


class SkillTestSetStart(BaseSchema):
    from_evidence: bool = Field(
        default=False,
        description="Add the questions of recent answers that loaded the skill, rated or failed",
    )
    window_days: int = Field(default=30, ge=1, le=90)
