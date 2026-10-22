"""The authoring assistant's shapes: what the improver answers, and what the API returns.

The improver's answers are plain models, not `BaseSchema`: whitespace in a
passage it quotes or replaces is part of the text, and stripping it would anchor
a change somewhere it was not meant to go.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, model_validator

from app.schemas.base import BaseSchema

MAX_QUOTE_CHARS = 600
"""The longest quote that stays in a proposal's evidence."""

MAX_EVIDENCE_ITEMS = 12
"""How many evidence items one change keeps."""

MAX_REJECTED = 20
"""How many of the changes the improver proposed and nothing recorded a report lists."""


class Rejection(StrEnum):
    """Why a change the improver proposed was not recorded - one wording everywhere.

    The report, the worker's log and the console all name a refusal by these values.
    """

    UNANCHORED = "unanchored"
    """The passage it replaces, or follows, is not in the instructions."""
    AMBIGUOUS_ANCHOR = "ambiguous_anchor"
    """The passage occurs more than once, so where it goes cannot be told."""
    NO_CHANGE = "no_change"
    """It changes nothing."""
    UNKNOWN_TOOL = "unknown_tool"
    """It names a tool the agent does not have."""
    INVALID_TOOL_CHANGE = "invalid_tool_change"
    """A tool name or description a binding may not take."""
    # What `authoring_fields.stage` refuses, by the names it gives.
    NOT_A_TARGET = "not_a_target"
    OPERATION = "operation"
    LOOSENS_APPROVAL = "loosens_approval"
    WEAKENS_PROTECTION = "weakens_protection"
    UNKNOWN_CAPABILITY = "unknown_capability"
    INVALID_CONFIG = "invalid_config"
    DOES_NOT_APPLY = "does_not_apply"
    NOT_GRANTABLE = "not_grantable"
    """It adds something the person who asked may not grant."""
    DISMISSED_BEFORE = "dismissed_before"
    """Somebody dismissed the same change in the batch it replaces."""
    UNSUPPORTED = "unsupported"
    """A finding that an edit is supported, left with no evidence that could be checked."""
    EDIT_NOT_IN_DIFF = "edit_not_in_diff"
    """The line a finding names is not part of the edit; the finding is shown without it."""
    SUPERSEDED = "superseded"
    """A request started later had already replaced the suggestions."""


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


class FieldChange(BaseModel):
    """A change to one field of the agent's configuration, at a path the prompt lists."""

    path: str = Field(
        description=(
            "Where the change goes, exactly as one of the paths listed, with its names "
            "filled in - for example `model_settings/temperature` or "
            "`capabilities/knowledge/config`."
        )
    )
    op: Literal["set", "add", "remove"] = Field(
        description=(
            "`set` replaces the value; `add` and `remove` add or remove one item of a "
            "list - a capability binding, a collection id, a context file id."
        )
    )
    value: JsonValue = Field(
        description=(
            "For `set`, the new value; for `add`, the item to add - a capability binding "
            "is `{id, config}`; for `remove`, the item to remove - a capability by its id."
        )
    )
    rationale: str = Field(description="One paragraph: why, in terms of the evidence.")
    expected_effect: str = Field(
        description="What this change should do to quality and to cost, which you predict now."
    )
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
    fields: list[FieldChange] = Field(default_factory=list)


class SkillImprovement(BaseModel):
    """What the improver proposes for one skill: the whole new body."""

    summary: str
    expected_effect: str
    description: str = Field(description="The skill's one-line description, changed or not.")
    content: str = Field(description="The complete new body, not a diff.")
    rationale: str
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class ContextImprovement(BaseModel):
    """What the improver proposes for one context file: the whole new body."""

    summary: str
    expected_effect: str
    description: str = Field(description="The file's one-line description, changed or not.")
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
    edit: str = Field(
        default="",
        description=(
            "The line of the edit this finding is about, copied from the edit above - an "
            "added or removed line of the instructions, or a line of the tool or configuration "
            "edit. Empty when it is about no single line."
        ),
    )
    evidence: list[EvidenceQuote] = Field(
        default_factory=list,
        description=(
            "Quotes that show this very edit at work - a run where that line mattered. None "
            "when no run shows it; a quote about something else does not support the edit."
        ),
    )


class VerifyReport(BaseModel):
    """The improver's critique of a person's own edits."""

    findings: list[VerifyFinding] = Field(default_factory=list)
    instructions: list[InstructionChange] = Field(default_factory=list)
    tools: list[ToolChange] = Field(default_factory=list)
    fields: list[FieldChange] = Field(default_factory=list)


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
    context_id: UUID | None = None
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
    path: str | None = None
    op: str | None = None
    base_value: JsonValue = None
    new_value: JsonValue = None
    accepted_value: JsonValue = None
    effect: dict[str, JsonValue] | None = Field(
        default=None,
        description=(
            "What a field change is expected to do to cost or limits, measured on recent "
            "runs: for a model, `cost_per_run_before`, `cost_per_run_after` and `runs`"
        ),
    )
    names: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Names of the models, collections, context files and MCP servers a field "
            "change refers to, by id - only those the reader may see"
        ),
    )
    writes: list[str] = Field(
        default_factory=list,
        description=(
            "Tools a field change makes reachable that change something outside the run; "
            "an eval holds them back, so a check does not measure what they do"
        ),
    )
    blocked: str | None = Field(
        default=None,
        description=(
            "Why Accept is refused for now, when it is: `check_first` - a model change "
            "is accepted only after a check with no confirmed regression; "
            "`check_outdated` - the checks of this model measured another combination "
            "of the draft and its suggestions; `inconclusive`; `regression`"
        ),
    )
    rationale: str
    expected_effect: str = ""
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
        value: Accept this instead of a field change's proposed value, for a field
            whose value is a single setting or a text.
    """

    action: Literal["accept", "dismiss", "undo"]
    text: str | None = Field(default=None, max_length=20000)
    value: JsonValue = None


class ProposalCheck(BaseSchema):
    """Run a dataset - or an eval suite's - against the draft as it would be with the pending changes."""

    dataset_id: UUID | None = None
    suite_id: UUID | None = Field(
        default=None,
        description=(
            "An eval suite of the agent the check runs on: its dataset and environment are "
            "used in place of `dataset_id` and `environment_id`."
        ),
    )
    dataset_version: int | None = Field(default=None, ge=1)
    environment_id: UUID | None = None
    agent_id: UUID | None = Field(
        default=None,
        description=(
            "For a skill or context file change: the agent, bound to it, the dataset runs on."
        ),
    )
    proposal_id: UUID | None = Field(
        default=None, description="For a skill or context file change: the pending change."
    )

    @model_validator(mode="after")
    def _one_source(self) -> ProposalCheck:
        if (self.dataset_id is None) == (self.suite_id is None):
            raise ValueError("Name a dataset or an eval suite to check against, not both")
        return self


class AgentWaiting(BaseSchema):
    """One agent with suggestions waiting, by kind."""

    agent_id: UUID
    name: str
    instructions: int
    tools: int
    fields: int = 0


class AuthoringWaiting(BaseSchema):
    """What the assistant proposed that the caller may decide and nobody has.

    Attributes:
        agents: Agents the caller may edit whose open batch has pending suggestions.
        skills: Pending skill changes the assistant proposed, for a caller holding
            `skills:edit`; zero otherwise.
        contexts: Pending context file changes the assistant proposed, for a caller
            holding `context:edit`; zero otherwise.
    """

    agents: list[AgentWaiting]
    skills: int
    contexts: int = 0
