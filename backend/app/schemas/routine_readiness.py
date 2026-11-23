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
