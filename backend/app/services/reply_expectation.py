"""Exact, authenticated reply matching and quota-accounted durable expectation state."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_run import NodeRun, WorkflowRun
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.reply_expectation import ReplyExpectation, ReplyExpectationOutput
from app.services.portals.reply_metadata import ReplyMessage
from app.services.workflow_execution import admission
from app.services.workflow_execution.exceptions import WorkflowInlineStorageLimitError
from app.workflows.contracts.payload import json_byte_size


def match_reply(
    expectation: ReplyExpectation,
    messages: tuple[ReplyMessage, ...],
    *,
    now: datetime,
) -> ReplyExpectationOutput | None:
    """Provider scope and exact sender are mandatory; RFC headers only narrow them."""
    candidates = [
        message
        for message in messages
        if (
            message.thread_id == expectation.thread_id
            and message.sender.casefold() == str(expectation.expected_sender).casefold()
            and expectation.not_before < message.received_at <= min(expectation.deadline, now)
            and not message.sent_or_draft
            and not message.automatic
            and (
                expectation.anchor_message_id is None
                or expectation.anchor_message_id == message.in_reply_to
                or expectation.anchor_message_id in message.references
            )
        )
    ]
    ignored = sum(not message.authenticated for message in candidates)
    reply = min(
        (message for message in candidates if message.authenticated),
        key=lambda message: (message.received_at, message.message_id),
        default=None,
    )
    if reply is not None:
        return ReplyExpectationOutput(
            branch="reply",
            checked_at=now,
            deadline=expectation.deadline,
            message_id=reply.message_id,
            received_at=reply.received_at,
            ignored_unverified=ignored,
        )
    if now >= expectation.deadline:
        return ReplyExpectationOutput(
            branch="deadline",
            checked_at=now,
            deadline=expectation.deadline,
            ignored_unverified=ignored,
        )
    return None


async def store_expectation(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    step: NodeRun,
    expectation: ReplyExpectation,
) -> None:
    """Caller holds organization storage locks, then the run and step, in that order."""
    payload = expectation.model_dump(mode="json")
    previous = (
        json_byte_size(step.resume_payload, limit=(1 << 63) - 1)
        if step.resume_payload is not None
        else 0
    )
    size = json_byte_size(payload, limit=(1 << 63) - 1)
    scope = await admission.inline_storage_scope(
        db,
        organization_id=run.organization_id,
        run_bytes=run.inline_result_bytes,
        requested=max(0, size - previous),
    )
    if scope is not None:
        raise WorkflowInlineStorageLimitError(scope=scope)
    await workflow_run_repo.update_run(
        db, run=run, update_data={"inline_result_bytes": run.inline_result_bytes + size - previous}
    )
    await workflow_run_repo.update_node_run(
        db, node_run=step, update_data={"resume_payload": payload}
    )
