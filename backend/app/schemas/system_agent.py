"""System agents: protected configuration for platform-owned background work (#2575)."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

SystemRole = Literal["daily_briefing", "memory_maintenance"]


class SystemAgentRunRead(BaseSchema):
    """One execution of a role: when, on what model, at what cost, and how it ended."""

    id: UUID
    started_at: datetime
    status: str
    model_label: str | None = None
    cost_usd: Decimal
    error: str | None = None


class SystemAgentRead(BaseSchema):
    """A role as an operator sees it."""

    role: SystemRole
    enabled: bool
    model_profile_id: UUID | None = None
    model_label: str | None = None
    monthly_budget_usd: Decimal | None = None
    spent_this_month: Decimal
    unavailable: Literal["starter_agent"] | None = None
    """Why a role that is switched on would do nothing right now.

    Background model calls are recorded under the organization's published AgenticOS starter
    agent so each has a row, a cost and a trace. Renamed, unpublished or deleted, it leaves
    nothing to record them under, and the role silently skips its work - so it is said here.
    """

    managed_in: Literal["proactivity"] | None = None
    """Set where the role's model and limit live in another setting rather than here.

    The daily briefing *is* the organization's proactivity setting; showing it here
    without letting it be edited here keeps one model and one limit, not two that
    can disagree.
    """

    runs: list[SystemAgentRunRead] = Field(default_factory=list)


class SystemAgentList(BaseSchema):
    items: list[SystemAgentRead]


class SystemAgentUpdate(BaseSchema):
    """A role's switch, model and monthly budget, replaced together."""

    enabled: bool
    model_profile_id: UUID | None = None
    monthly_budget_usd: Decimal | None = Field(default=None, ge=0)
