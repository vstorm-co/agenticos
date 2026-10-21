"""The authoring assistant's shapes: what the improver answers, and what the API returns.

The improver's answers are plain models, not `BaseSchema`: whitespace in a
passage it quotes or replaces is part of the text, and stripping it would anchor
a change somewhere it was not meant to go.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.base import BaseSchema

MAX_QUOTE_CHARS = 600
"""The longest quote that stays in a proposal's evidence."""

MAX_EVIDENCE_ITEMS = 12
"""How many evidence items one change keeps."""


class EvidenceQuote(BaseModel):
    """A passage of one run the improver read, quoted as support for a change."""

    run_id: UUID = Field(description="The id of the run the quote is from, as given.")
    quote: str = Field(
        description=(
            "Words copied exactly from that run's prompt, answer, tool calls, error or "
            f"a reader's comment - at most {MAX_QUOTE_CHARS} characters."
        )
    )


class Finding(BaseModel):
    observation: str = Field(description="One problem or pattern the runs show.")
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class RunFindings(BaseModel):
    """What one group of runs shows, read before the proposal is written."""

    findings: list[Finding] = Field(default_factory=list)


class InstructionChange(BaseModel):
    old_text: str = Field(
        description=(
            "The exact passage of the current instructions to replace, copied verbatim and "
            "long enough to occur only once. Empty to insert new text."
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


class ToolChange(BaseModel):
    capability_id: str = Field(description="The capability the tool belongs to, as listed.")
    tool_id: str = Field(description="The tool's stable id, as listed - not its name.")
    name: str | None = Field(
        default=None, description="A new name of at most 64 characters, or null to keep it."
    )
    description: str | None = Field(
        default=None,
        description="A new description of at most 1024 characters, or null to keep it.",
    )
    rationale: str
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class ImprovementProposal(BaseModel):
    """What the improver proposes for one agent."""

    summary: str = Field(description="Two sentences: what the evidence shows.")
    expected_effect: str = Field(
        description=(
            "What should behave differently once the changes are made, and which of the "
            "runs you read should have gone otherwise."
        )
    )
    instructions: list[InstructionChange] = Field(default_factory=list)
    tools: list[ToolChange] = Field(default_factory=list)


class SkillImprovement(BaseModel):
    """What the improver proposes for one skill: the whole new body."""

    summary: str
    expected_effect: str
    description: str = Field(description="The skill's one-line description, changed or not.")
    content: str = Field(description="The complete new body, not a diff.")
    rationale: str
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class VerifyFinding(BaseModel):
    verdict: Literal["supports", "risk", "removed"] = Field(
        description=(
            "`supports` when the evidence backs the edit, `risk` when it may bring back a "
            "problem the evidence shows, `removed` when the edit dropped something the "
            "evidence relied on."
        )
    )
    text: str
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class VerifyReport(BaseModel):
    """The improver's critique of a person's own edits."""

    findings: list[VerifyFinding] = Field(default_factory=list)
    instructions: list[InstructionChange] = Field(default_factory=list)
    tools: list[ToolChange] = Field(default_factory=list)


class AuthoringStart(BaseSchema):
    """What a person asks for, the same body estimating and starting.

    Attributes:
        kind: Improve from the evidence, or verify the draft's own edits.
        window_days: How far back the evidence reaches.
    """

    kind: Literal["improve", "verify"] = "improve"
    window_days: int = Field(default=30, ge=1, le=90)


class AuthoringEstimate(BaseSchema):
    """What an Improve or Verify would read and cost, before anybody consents.

    Attributes:
        runs: How many runs it would read.
        rated_down: Of those, how many were rated down.
        calls: How many improver runs it takes: one per group of runs, and one to propose.
        estimate_usd: What those runs are estimated to cost.
        affordable: Whether the improver's and the organization's budgets cover it.
        reason: Why it cannot start, when it cannot: `no_evidence`, `no_draft_change`.
    """

    runs: int
    rated_down: int
    calls: int
    estimate_usd: Decimal
    affordable: bool
    reason: str | None = None


class AuthoringRequestRead(BaseSchema):
    id: UUID
    kind: str
    target: str
    agent_id: UUID | None
    skill_id: UUID | None
    status: str
    error: str | None
    estimate_usd: Decimal
    cost_usd: Decimal
    run_ids: list[UUID]
    window_days: int
    evidence: dict[str, object]
    report: dict[str, object] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class EvidenceItemRead(BaseSchema):
    """One checked piece of evidence. `quote` is absent for a reader without `runs:view`."""

    run_id: UUID
    quote: str | None = None


class HunkRead(BaseSchema):
    """One proposed change, and whether it still applies to the draft.

    Attributes:
        state: `pending`, `accepted` or `dismissed`, as decided.
        applies: For a pending hunk, whether its anchor still resolves in the
            draft; for an accepted one, whether Undo still can.
    """

    id: UUID
    kind: str
    origin: str
    status: str
    old_text: str
    new_text: str
    accepted_text: str | None
    context_before: str
    context_after: str
    capability_id: str | None
    tool_id: str | None
    base_name: str | None
    base_description: str | None
    new_name: str | None
    new_description: str | None
    rationale: str
    evidence: list[EvidenceItemRead]
    evidence_dropped: int
    applies: bool
    decided_at: datetime | None


class BatchRead(BaseSchema):
    id: UUID
    agent_id: UUID
    status: str
    expected_effect: str
    request_id: UUID | None = Field(description="The Improve or Verify that opened it")
    hunks: list[HunkRead]
    check_eval_run_ids: list[UUID]
    created_at: datetime


class AgentAuthoringRead(BaseSchema):
    """Everything the Builder's assistant strip shows for one agent.

    Attributes:
        batch: The open batch, or the latest closed one when there is no open one.
        latest: The newest request, finished or not - the strip's spinner and errors.
        verify: The newest finished Verify, whose findings the verify card shows.
    """

    batch: BatchRead | None
    latest: AuthoringRequestRead | None
    verify: AuthoringRequestRead | None


class DecisionRead(BaseSchema):
    """What a decision left: the strip as it now stands, and the draft it wrote."""

    authoring: AgentAuthoringRead
    draft_spec: dict[str, object]


class HunkDecision(BaseSchema):
    """Accept, dismiss or undo one hunk.

    Attributes:
        text: Accept this instead of the proposed text - the person's edit of it.
    """

    action: Literal["accept", "dismiss", "undo"]
    text: str | None = Field(default=None, max_length=20000)


class ProposalCheck(BaseSchema):
    """Run a dataset against the draft as it would be with the pending changes."""

    dataset_id: UUID
    dataset_version: int | None = Field(default=None, ge=1)
    environment_id: UUID | None = None
    agent_id: UUID | None = Field(
        default=None,
        description="For a skill change: the agent, bound to the skill, the dataset runs on.",
    )
    proposal_id: UUID | None = Field(
        default=None, description="For a skill change: the pending change to check."
    )


class AgentWaiting(BaseSchema):
    """One agent with suggestions waiting, by kind."""

    agent_id: UUID
    name: str
    instructions: int
    tools: int


class AuthoringWaiting(BaseSchema):
    """What the assistant proposed that the caller may decide and nobody has.

    Attributes:
        agents: Agents the caller may edit whose open batch has pending suggestions.
        skills: Pending skill changes the assistant proposed, for a caller holding
            `skills:edit`; zero otherwise.
    """

    agents: list[AgentWaiting]
    skills: int
