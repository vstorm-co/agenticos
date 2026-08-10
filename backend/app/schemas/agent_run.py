"""Schemas for run history, approvals and the cost dashboard."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.base import BaseSchema
from app.schemas.conversation import MessageRead


class AgentRunRead(BaseSchema):
    """One execution, as run history lists it."""

    id: UUID
    agent_id: UUID
    agent_version_id: UUID | None = None
    user_id: UUID | None = None
    surface: str
    status: str
    model_label: str | None = None
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    cost_is_partial: bool = Field(
        description="True when a model in this run had no price - the cost is a floor"
    )
    logfire_trace_id: str | None = Field(
        default=None,
        description=(
            "The trace this run executed inside, as Logfire spells it. Useful to "
            "anybody with Logfire access on its own; `logfire_url` is the link, "
            "when there is somewhere to link to. Null when nothing was tracing - "
            "a deployment with no `LOGFIRE_TOKEN`"
        ),
    )
    logfire_url: str | None = Field(
        default=None,
        description=(
            "Where this run's trace can be read. Sent on the single-run read only: "
            "resolving it needs the version's stored spec, because an agent may "
            "redirect its traces to a client's own project, and a list of fifty "
            "runs has no use for fifty trace links. Null when no organization and "
            "project slug are configured - a `LOGFIRE_TOKEN` is a write credential "
            "and carries neither, so the absence is a configuration fact rather "
            "than a promise this schema is failing to keep"
        ),
    )
    error: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    parent_run_id: UUID | None = Field(
        default=None,
        description=(
            "The run this one was delegated from, or null for a run somebody "
            "started. Sent because otherwise nothing outside the database can "
            "tell a delegated run from a top-level one, and the two must not be "
            "read the same way: a parent's cost already contains its children's, "
            "so a surface that sums a page of rows double-counts every delegation."
        ),
    )
    subagent_task_id: str | None = Field(
        default=None,
        description=(
            "Which delegation produced this run, matching the task id the "
            "streamed `subagent_*` frames carry - so a delegation panel in a "
            "chat and a row in run history can be shown to be the same thing. "
            "Null whenever `parent_run_id` is, because a handle with no "
            "delegation left to reach is worse than no handle."
        ),
    )

    @model_validator(mode="after")
    def _no_delegation_handle_without_a_delegation(self) -> "AgentRunRead":
        """Withhold the task id of a delegation that no longer has a parent.

        `agent_runs.parent_run_id` is `ON DELETE SET NULL`, which is the right
        arithmetic - deleting the parent removes the row that contained this
        cost, so the orphan *should* start counting toward the organization's
        bill - but the database nulls one column and leaves the other, so the
        row becomes a top-level run still carrying a delegation handle. The
        transcript that handle named went with the parent.

        Dropped here rather than in the database, and rather than in each
        reader. A trigger would be the only way to null the second column: the
        parent is usually deleted by a cascade from its agent, with no
        application code in the transaction to do it - and a trigger on every
        insert into the hottest table in the schema is a permanent cost for a
        case that happens when somebody deletes an agent. Every surface reads
        this schema, so nulling it once here is the same guarantee for a tenth
        of the weight. The stored value stays wrong and unread.
        """
        if self.parent_run_id is None:
            self.subagent_task_id = None
        return self


class AgentRunList(BaseSchema):
    items: list[AgentRunRead]
    total: int


class RunTranscript(BaseSchema):
    """One run's turns, in the order they happened, as the run detail view reads them.

    The messages are the same rows `GET /conversations/{id}/messages` returns, but
    narrowed to a single run by `messages.run_id` and reached under a different
    authorization: reading a run is the organization's right, not its owner's, so a
    colleague holding `runs:view` reads a run somebody else started - which the
    conversation route deliberately refuses.

    Attributes:
        run_id: The run these turns belong to.
        conversation_id: The thread the run ran inside, or `None` when it ran
            with no conversation - an API call that passed no `conversation_id`.
            A null here is the answer "this run has no transcript", which a client
            must tell apart from an empty `items` for a run that *had* a thread and
            simply produced nothing: the runner never writes a turn for a run with
            no conversation, so an empty list under a null id is a certainty rather
            than a coincidence, and reads as "there is nothing to show" rather than
            "it did nothing".
        items: The run's messages, oldest first.
        total: How many turns the run produced, so a paged read still knows the
            size of what it is paging through.
    """

    run_id: UUID
    conversation_id: UUID | None = Field(
        default=None,
        description=(
            "The conversation this run ran inside, or null when it ran with none - "
            "which is how a client says 'this run has no transcript' rather than "
            "drawing an empty list that reads as 'it did nothing'."
        ),
    )
    items: list[MessageRead]
    total: int


class ApprovalRead(BaseSchema):
    """A parked tool call awaiting a decision."""

    id: UUID
    run_id: UUID
    agent_id: UUID
    agent_name: str | None = Field(
        default=None,
        description=(
            "Whose run this is, as something readable. A UUID names nothing to an "
            "approver, and a queue of tool ids with no agent beside them is one "
            "people approve blind. Absent on the row a decision returns, which "
            "carries the approval itself rather than the queue's projection of it"
        ),
    )
    tool_id: str
    tool_args: dict[str, Any]
    triggered_by_user_id: UUID | None = Field(
        default=None,
        description=(
            "Who started the run this call belongs to. Not on the approval itself: "
            "an approval belongs to a run and a run belongs to a person. Null for "
            "a run nobody started as themselves - an embedded widget's visitor is "
            "anonymous - and for one whose user has since been deleted"
        ),
    )
    triggered_by_email: str | None = Field(
        default=None, description="That person, for a queue somebody has to read"
    )
    decided_by_email: str | None = Field(
        default=None,
        description=(
            "Who decided, for the record view. The decided list is an "
            "accountability trail and a bare UUID is not one"
        ),
    )
    subagent_name: str | None = Field(
        default=None,
        description=(
            "Which delegate is asking, when the call came from inside a delegation. "
            "Null means the agent whose run this is asked directly - `agent_id` "
            "answers whose run, never who is acting. A queue that shows a tool name "
            "with no actor is a queue people approve blind"
        ),
    )
    subagent_agent_id: UUID | None = Field(
        default=None,
        description=(
            "That delegate's own agent, for a link to it. Null for an inline "
            "specialist, which is defined inside its parent's spec and has no agent "
            "of its own"
        ),
    )
    status: str
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    note: str | None = None
    created_at: datetime | None = None


class ApprovalList(BaseSchema):
    items: list[ApprovalRead]
    total: int


class ApprovalDecision(BaseSchema):
    approved: bool
    note: str | None = Field(default=None, max_length=500)


class CostByAgent(BaseSchema):
    """One agent's line on the Spend tab.

    Two cost figures with two different names, which is the rule this page
    follows throughout: a number needing a different denominator needs a
    different word, never the same word with different arithmetic.
    """

    agent_id: UUID
    agent_name: str | None = Field(
        default=None,
        description=(
            "The agent's name. Absent from the usage email's breakdown, which "
            "groups by agent *and model* and carries `model_label` instead"
        ),
    )
    model_label: str | None = Field(
        default=None,
        description=(
            "The model, on the email's per-model rows only. Null on the Spend "
            "tab, which is one row per agent - listing a model label where a "
            "reader expects an agent is what this row's `agent_name` fixed"
        ),
    )
    cost_usd: Decimal = Field(
        description=(
            "This agent's share of the window, top-level runs only, so the "
            "column sums to the total printed above it"
        )
    )
    run_count: int
    partial_run_count: int = Field(
        default=0,
        description=(
            "How many of those runs had a model with no price. The cost is a "
            "floor by exactly that much, and '3 of 40 runs could not be priced' "
            "is the difference between a figure a reader can act on and one "
            "they have to take on trust"
        ),
    )
    month_to_date_usd: Decimal | None = Field(
        default=None,
        description=(
            "This agent's own calendar month, delegated runs **included** - "
            "that is the spend its cap is a cap on, and a delegate's rows are "
            "the only record of what it itself did. It does not sum to the "
            "organization's month and must not be drawn as if it did"
        ),
    )
    monthly_cap_usd: Decimal | None = Field(
        default=None,
        description=(
            "The cap in the published spec, or null for an agent that sets "
            "none. Always the calendar month, whatever window the tab is "
            "showing: a rolling seven days measured against a monthly ceiling "
            "reads as 20% used on the day the cap was actually reached"
        ),
    )


class CostByProvider(BaseSchema):
    """One model provider's share of the bill.

    `provider` is null for runs recorded before this was tracked. Rendered as
    "not recorded" rather than folded into another provider, because a total
    that quietly attributes spend to the wrong vendor is worse than one that
    admits a gap.
    """

    provider: str | None
    cost_usd: Decimal
    run_count: int


class CostByKey(BaseSchema):
    """One stored key's share of the bill.

    `label` is null when the key has since been deleted. The spend still
    happened, so the row stays.
    """

    secret_id: UUID | None
    label: str | None
    cost_usd: Decimal
    run_count: int


class CostSummary(BaseSchema):
    """What the cost dashboard renders."""

    period_days: int | None = Field(
        default=None,
        description=(
            "The rolling window, when one was asked for that way. Null for an "
            "explicit `from`/`to` range, which is not a number of days"
        ),
    )
    from_date: datetime | None = Field(
        default=None, description="Start of the window these figures cover"
    )
    to_date: datetime | None = Field(default=None, description="End of it, or null for 'up to now'")
    month_to_date_usd: Decimal
    partial_run_count: int = Field(
        default=0,
        description=(
            "Runs in the window whose cost is a floor because some model in "
            "them had no price. How much of everything below is a fact"
        ),
    )
    by_agent: list[CostByAgent]
    by_provider: list[CostByProvider]
    by_key: list[CostByKey]
