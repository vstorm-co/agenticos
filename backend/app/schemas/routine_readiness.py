"""Whether a routine's next activation would run, and what stops it."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

RoutineBlockerCode = Literal[
    "creator_inactive",
    "creator_cannot_run",
    "agent_unavailable",
    "ended",
    "sources_setup",
    "sources_review",
    "routine_changed",
    "platform_identity",
    "awaiting_approval",
    "awaiting_answer",
    "budget_exhausted",
    "actions_need_approval",
]


class RoutineBlocker(BaseSchema):
    code: RoutineBlockerCode
    severity: Literal["blocked", "attention"] = Field(
        description="`blocked`: the next activation will not start a run. "
        "`attention`: it starts, but stops before finishing until somebody acts."
    )
    run_id: UUID | None = Field(
        default=None, description="The parked run to open, for `awaiting_*` blockers."
    )
    count: int | None = Field(
        default=None,
        description="How many actions still need approval, for `actions_need_approval`.",
    )


class TriggerReadiness(BaseSchema):
    """The checks a fire makes before running, evaluated now as the routine's creator.

    Reported for a paused routine too: there it says whether resuming would work.
    Empty `blockers` means nothing known stops the next activation.
    """

    trigger_id: UUID
    blockers: list[RoutineBlocker] = Field(default_factory=list)


class TriggerReadinessRequest(BaseSchema):
    trigger_ids: list[UUID] = Field(
        min_length=1,
        max_length=100,
        description="The routines a screen shows, at most 100 per request.",
    )


class TriggerReadinessList(BaseSchema):
    """One answer per requested routine the caller can see; the rest are left out."""

    items: list[TriggerReadiness]
