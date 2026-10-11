"""A run's resume link: the address a Wait step waiting for a call goes on from (#1947).

Every run has one, derived from its id under the deployment's secret, so a
**Resume link** step can hand it to an earlier message or request and nothing
has to be stored for it. Calling it hands its JSON body to every Wait step of
the run waiting for a call: each takes the body as its output and the run goes
on. The link is the credential - whoever holds it may resume that run - which
is why it is a MAC nobody can derive without the secret, compared in constant
time, and why a wrong one answers as if the run did not exist.
"""

from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.workflow_run import NodeRunStatus, WorkflowRunStatus
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow_run import WorkflowResumed
from app.services.workflow_execution.dispatcher import resolve_graph
from app.services.workflow_execution.exceptions import (
    WorkflowNotWaitingError,
    WorkflowRunInputTooLargeError,
    WorkflowRunNotFoundError,
)
from app.services.workflow_execution.resume_link import resume_token
from app.services.workflow_exposure import parse_webhook_body

WAIT = "flow.wait"


class WorkflowResumeService:
    """Resumes a run from its link. No caller identity: the link is the credential."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resume(self, run_id: UUID, token: str, *, body: bytes) -> WorkflowResumed:
        """Hand `body` to every Wait step of the run waiting for a call, and wake them.

        Raises:
            WorkflowRunNotFoundError: The token is not this run's, or there is no
                such run - one answer for both, so a guess learns nothing.
            BadRequestError: The body is not a JSON object.
            WorkflowRunInputTooLargeError: The body is over the run input limit.
            WorkflowNotWaitingError: The run has ended, or nothing in it waits
                for a call now - one already woken by an earlier call included.
        """
        if not secrets.compare_digest(token, resume_token(run_id)):
            raise WorkflowRunNotFoundError(run_id=run_id)
        if len(body) > settings.WORKFLOW_RUN_MAX_INPUT_BYTES:
            raise WorkflowRunInputTooLargeError(
                limit=settings.WORKFLOW_RUN_MAX_INPUT_BYTES, size=len(body)
            )
        payload: dict[str, Any] = parse_webhook_body(body) if body else {}
        run = await workflow_run_repo.get_run_by_id_for_update(self.db, run_id)
        if run is None:
            raise WorkflowRunNotFoundError(run_id=run_id)
        if WorkflowRunStatus(run.status).is_terminal:
            raise WorkflowNotWaitingError(run_id=run_id)
        graph = await resolve_graph(self.db, run)
        waits = [
            node.id
            for node in graph.nodes
            if node.definition_id == WAIT and node.config.get("until_called") is True
        ]
        steps = [
            step
            for step in await workflow_run_repo.list_node_runs_of(
                self.db, workflow_run_id=run.id, node_instance_ids=waits
            )
            if step.status == NodeRunStatus.WAITING.value and step.resume_payload is None
        ]
        if not steps:
            raise WorkflowNotWaitingError(run_id=run_id)
        from app.worker.tasks.workflow_tasks import trigger_dispatch

        for step in steps:
            await workflow_run_repo.update_node_run(
                self.db, node_run=step, update_data={"resume_payload": payload}
            )
            # Its dispatch row waits for the step's time limit; brought forward, it
            # is due now, and the step reads what it was sent.
            await workflow_run_repo.bring_forward_outbox(self.db, node_run_id=step.id)
            trigger_dispatch(self.db, workflow_run_id=run.id, node_run_id=step.id)
        return WorkflowResumed(run_id=run.id, resumed=len(steps))


__all__ = ["WorkflowResumeService"]
