"""`flow.wait`: hold the run here for a while, until a time, or until a call, then go on.

The moment is fixed when the step is first reached: a duration after its node run
was created, or the `until` bound to it. Until then the step is parked on a
`timer` and its dispatch row comes due at that moment, so the wait survives a
worker restart and costs nothing while it lasts. A moment already past goes on at
once. Other branches of the run carry on meanwhile.

Waiting for a call, the step parks the same way, its time the longest it waits:
calling the run's resume link (`flow.resume_link`) stores what it was sent on the
step and brings its dispatch row forward, and the step hands the body on. Its
time passing first, it goes on with `called` false.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.session import get_worker_db_context
from app.repositories import workflow_run as workflow_run_repo
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed, NodeResult, Waiting, WorkflowError

MAX_WAIT_SECONDS = 30 * 24 * 3600


class FlowWaitConfig(BaseModel):
    """How long to wait, when no time to wait until is bound, and whether for a call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seconds: int | None = Field(
        default=None,
        ge=1,
        le=MAX_WAIT_SECONDS,
        title="Wait for (seconds)",
        description="How long after the step is reached to go on; at most thirty days. "
        "Waiting for a call, the longest to wait for it",
    )
    until_called: bool = Field(
        default=False,
        title="Wait for a call to the run's resume link",
        description="Go on when the address a Resume link step gives is called, "
        "handing on what it was sent",
    )


class FlowWaitInput(BaseModel):
    """A time to wait until instead, bound from an earlier step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    until: datetime | None = None


class FlowWaitOutput(BaseModel):
    """When the wait ended, and what a call to the resume link sent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    waited_until: datetime
    called: bool = False
    body: dict[str, Any] | None = None


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Go on once the moment has come or the call has, or park until one does."""
    until = node_input.until if isinstance(node_input, FlowWaitInput) else None
    settings = config if isinstance(config, FlowWaitConfig) else FlowWaitConfig()
    if until is None and settings.seconds is None and not settings.until_called:
        return Failed(
            error=WorkflowError(
                code="WAIT_NOT_CONFIGURED",
                message="Wait for a number of seconds, bind a time to wait until, "
                "or wait for a call",
            )
        )
    current = context.current()
    async with get_worker_db_context() as db:
        node_run = await workflow_run_repo.get_node_run_by_id(db, current.node_run_id)
    now = datetime.now(UTC)
    if settings.until_called and node_run is not None and node_run.resume_payload is not None:
        return Completed[FlowWaitOutput](
            output=FlowWaitOutput(waited_until=now, called=True, body=node_run.resume_payload)
        )
    if until is None:
        reached = node_run.created_at if node_run is not None else now
        # Waiting for a call with no time of its own waits the longest a wait may.
        seconds = settings.seconds if settings.seconds is not None else MAX_WAIT_SECONDS
        until = reached + timedelta(seconds=seconds)
    until = until if until.tzinfo is not None else until.replace(tzinfo=UTC)
    if now >= until:
        return Completed[FlowWaitOutput](output=FlowWaitOutput(waited_until=until))
    return Waiting(reason="timer", resume_token=str(current.node_run_id), resume_at=until)
