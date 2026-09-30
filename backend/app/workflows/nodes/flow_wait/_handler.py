"""`flow.wait`: hold the run here for a while, or until a time, then go on.

The moment is fixed when the step is first reached: a duration after its node run
was created, or the `until` bound to it. Until then the step is parked on a
`timer` and its dispatch row comes due at that moment, so the wait survives a
worker restart and costs nothing while it lasts. A moment already past goes on at
once. Other branches of the run carry on meanwhile.
"""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from app.db.session import get_worker_db_context
from app.repositories import workflow_run as workflow_run_repo
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed, NodeResult, Waiting, WorkflowError

MAX_WAIT_SECONDS = 30 * 24 * 3600


class FlowWaitConfig(BaseModel):
    """How long to wait, when no time to wait until is bound."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seconds: int | None = Field(
        default=None,
        ge=1,
        le=MAX_WAIT_SECONDS,
        title="Wait for (seconds)",
        description="How long after the step is reached to go on; at most thirty days",
    )


class FlowWaitInput(BaseModel):
    """A time to wait until instead, bound from an earlier step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    until: datetime | None = None


class FlowWaitOutput(BaseModel):
    """When the wait ended."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    waited_until: datetime


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Go on once the moment has come, or park until it does."""
    until = node_input.until if isinstance(node_input, FlowWaitInput) else None
    seconds = config.seconds if isinstance(config, FlowWaitConfig) else None
    if until is None and seconds is None:
        return Failed(
            error=WorkflowError(
                code="WAIT_NOT_CONFIGURED",
                message="Wait for a number of seconds, or bind a time to wait until",
            )
        )
    current = context.current()
    if until is None:
        async with get_worker_db_context() as db:
            node_run = await workflow_run_repo.get_node_run_by_id(db, current.node_run_id)
        reached = node_run.created_at if node_run is not None else datetime.now(UTC)
        until = reached + timedelta(seconds=seconds or 0)
    until = until if until.tzinfo is not None else until.replace(tzinfo=UTC)
    if datetime.now(UTC) >= until:
        return Completed[FlowWaitOutput](output=FlowWaitOutput(waited_until=until))
    return Waiting(reason="timer", resume_token=str(current.node_run_id), resume_at=until)
