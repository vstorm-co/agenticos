"""Answering where a run was started from, once it ends (#1792).

Only one surface has a place a run may write back to on its own: the chat, whose
conversation is frozen on the run at admission (`reply_conversation_id`). An API
or WebSocket caller reads the run and its events; a webhook's sender and a
schedule have nobody to answer, and reaching anyone else takes an explicit
outbound node in the graph.

The answer is written in the transaction that ends the run, so it is written
exactly once: a retried dispatch finds the run already terminal and settles
nothing, and a reconnecting chat reads the message rather than asking again.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_run import WorkflowRun
from app.repositories import conversation as conversation_repo
from app.repositories import workflow as workflow_repo
from app.schemas.conversation import MessagePart


async def deliver_result(db: AsyncSession, *, run: WorkflowRun) -> None:
    """Write `run`'s answer into the conversation it was started from, if any.

    Called by every path that ends a run for good - success, failure, budget,
    cancellation - after the run's own status is written, so the part names
    the status the run ended with.
    """
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
