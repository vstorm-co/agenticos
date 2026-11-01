"""`flow.resume_link`: the address that resumes this run, for a step before its Wait.

A Wait step waiting for a call goes on when the run's resume link is called; this
step hands that link on, so an earlier message or request can carry it to
whoever answers - an approver's email, a partner's callback URL. The link is the
run's own (`app.services.workflow_execution.resume_link`): the same from every
Resume link step of a run, and no use for any other.
"""

from pydantic import BaseModel, ConfigDict

from app.services.workflow_execution import context
from app.services.workflow_execution.resume_link import resume_url
from app.workflows.contracts.results import Completed, NodeResult


class ResumeLinkOutput(BaseModel):
    """The run's resume link."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """This run's resume link."""
    return Completed[ResumeLinkOutput](
        output=ResumeLinkOutput(url=resume_url(context.current().workflow_run_id))
    )
