"""Answering where a run was started from, once it ends (#1792, #1946).

Two surfaces have a place a run may write back to on its own: the chat, whose
conversation is frozen on the run at admission (`reply_conversation_id`), and a
`workflow.run` step of another run that called it (`parent_node_run_id`), which is
woken to hand on the answer. An API or WebSocket caller reads the run and its
events; a webhook's sender and a schedule have nobody to answer, and reaching
anyone else takes an explicit outbound node in the graph.

The answer is written in the transaction that ends the run, so it is written
exactly once: a retried dispatch finds the run already terminal and settles
nothing, and a reconnecting chat reads the message rather than asking again.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_run import NodeRunStatus, WaitingReason, WorkflowRun, WorkflowRunStatus
from app.repositories import conversation as conversation_repo
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.conversation import MessagePart

logger = logging.getLogger(__name__)


async def deliver_result(db: AsyncSession, *, run: WorkflowRun) -> None:
    """Write `run`'s answer into the conversation it was started from, if any.

    Called by every path that ends a run for good - success, failure, budget,
    cancellation - after the run's own status is written, so the part names
    the status the run ended with.
    """
    await wake_caller(db, run=run)
    if run.reply_conversation_id is None:
        return
    answer = (run.output or {}).get("text")
    text = answer if isinstance(answer, str) else ""
    workflow = await workflow_repo.get(db, run.workflow_id, organization_id=run.organization_id)
    # The card first - which workflow answered, and how its run ended - then its
    # words, stored the way every timeline entry is: the transcript is drawn
    # from these, so an answer only in `content` would vanish on reload.
    card = MessagePart(
        type="workflow_run",
        run_id=str(run.id),
        workflow_id=str(run.workflow_id),
        workflow_name=workflow.name if workflow is not None else None,
        status=run.status,
        error=(run.error or {}).get("message"),
    )
    parts = [card] + ([MessagePart(type="text", text=text)] if text else [])
    await conversation_repo.create_message(
        db,
        conversation_id=run.reply_conversation_id,
        role="assistant",
        content=text,
        parts=[part.model_dump(exclude_none=True) for part in parts],
    )


async def wake_caller(db: AsyncSession, *, run: WorkflowRun) -> None:
    """Dispatch the step that called `run` again, if it still waits on it.

    In the transaction that ends `run`, under the calling run's lock, so the wake
    is never lost: a step that parks after this finds `run` ended and wakes itself
    (`dispatcher._settle_waiting`), and one already parked is found here.
    """
    if run.parent_node_run_id is None:
        return
    step = await workflow_run_repo.get_node_run_by_id(db, run.parent_node_run_id)
    if step is None:
        return
    caller = await workflow_run_repo.get_run_by_id_for_update(db, step.workflow_run_id)
    step = await workflow_run_repo.get_node_run_by_id_for_update(db, step.id)
    if (
        caller is None
        or step is None
        or WorkflowRunStatus(caller.status).is_terminal
        or step.status != NodeRunStatus.WAITING.value
        or step.waiting_reason != WaitingReason.EXTERNAL_EVENT.value
    ):
        return
    try:
        async with db.begin_nested():
            await workflow_run_repo.create_outbox(
                db,
                organization_id=caller.organization_id,
                workflow_run_id=caller.id,
                node_run_id=step.id,
            )
    except IntegrityError:
        logger.info("workflow_caller_already_dispatched", extra={"node_run_id": str(step.id)})
