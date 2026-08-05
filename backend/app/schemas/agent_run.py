"""Schemas for run history, approvals and the cost dashboard."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


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
        default=None, description="Deep-link into the full trace; spans are not duplicated here"
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
            "chat and a row in run history can be shown to be the same thing."
        ),
    )


class AgentRunList(BaseSchema):
    items: list[AgentRunRead]
    total: int


class ApprovalRead(BaseSchema):
    """A parked tool call awaiting a decision."""

    id: UUID
    run_id: UUID
    agent_id: UUID
    tool_id: str
    tool_args: dict[str, Any]
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
    agent_id: UUID
    model_label: str | None = None
    cost_usd: Decimal
    run_count: int


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

    period_days: int
    month_to_date_usd: Decimal
    by_agent: list[CostByAgent]
    by_provider: list[CostByProvider]
    by_key: list[CostByKey]
