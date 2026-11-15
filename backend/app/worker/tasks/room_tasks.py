"""Execute explicitly requested room answers once, in accepted room order."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import start_deferred
from app.core.exceptions import AlreadyExistsError, AppException
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.room_submission import RoomSubmission
from app.db.session import get_worker_db_context
from app.repositories import conversation as conversation_repo
from app.repositories import room_submission as room_repo
from app.schemas.conversation import MessageRead
from app.services import chat_room, live_turn
from app.services.agent_runner import AgentRunnerService, RunSegment
from app.services.conversation import ConversationService
from app.services.conversation_turns import claim
from app.services.room_submission import TERMINAL, RoomSubmissionService, announce_request
from app.services.run_stream import RunFrames
from app.worker.jobs import RoomRequestJob


@asynccontextmanager
async def _live(submission: RoomSubmission, message: MessageRead) -> AsyncGenerator[RunFrames]:
    conversation_id = str(submission.conversation_id)
    trace = await live_turn.begin(conversation_id)

    async def emit(kind: str, payload: dict[str, object]) -> None:
        if trace is not None:
            await live_turn.publish(trace, kind, payload)

    try:
        await emit(
            "turn_prompt",
            {
                "conversation_id": conversation_id,
                "message_id": str(message.id),
                "client_message_id": message.client_message_id,
                "content": message.content,
                "sender": None
                if message.sender is None
                else message.sender.model_dump(mode="json"),
                "reply_to": None
                if message.reply_to is None
                else message.reply_to.model_dump(mode="json"),
                "agent_id": str(submission.agent_id),
                "file_source": None,
            },
        )
        await chat_room.turn_begun(conversation_id, submission.requester_id)
        yield RunFrames(emit=emit)
    finally:
        await emit("complete", {"conversation_id": conversation_id})
        if trace is not None:
            await live_turn.end(trace)


async def _emit_saved(frames: RunFrames, segment: RunSegment | None) -> None:
    """Associate the streamed bubble only with a separately visible committed row."""
    if segment is None or segment.message_id is None:
        return
    async with get_worker_db_context() as fresh:
        message = await conversation_repo.get_message_by_id(fresh, segment.message_id)
        if message is None or message.run_id != segment.run.id:
            return
    await frames.emit(
        "message_saved",
        {
            "conversation_id": str(message.conversation_id),
            "message_id": str(message.id),
            "run_id": str(segment.run.id),
            "run_status": segment.run.status,
        },
    )


async def _settle(db: AsyncSession, request_id: UUID, run: AgentRun) -> None:
    current = await room_repo.get(db, request_id, organization_id=run.organization_id, lock=True)
    if current is None or current.status in TERMINAL or current.run_id != run.id:
        return
    current.status = (
        run.status
        if run.status
        in {"running", "completed", "cancelled", "awaiting_approval", "awaiting_answer"}
        else "failed"
    )
    current.error = (
        "The agent could not complete this request. Check its saved run."
        if current.status == "failed"
        else None
    )
    await room_repo.save(db, current)
    announce_request(db, current)


async def run_request(job: RoomRequestJob) -> None:
    async with get_worker_db_context() as db:
        submission = await room_repo.get(db, job.request_id, organization_id=job.organization_id)
        if submission is None or submission.status != "queued":
            # This durable guard also refuses manual retries of a dead job:
            # unknown external side effects are never replayed automatically.
            return
        conversation_id = submission.conversation_id
    async with claim(conversation_id, background=True, room_request_id=job.request_id) as admitted:
        if not admitted:
            # The reconciler queues the oldest eligible head after the existing
            # foreground turn, approval or answer is finished. No worker waits.
            return
        async with get_worker_db_context() as db:
            service = RoomSubmissionService(db)
            submission = await room_repo.get(
                db, job.request_id, organization_id=job.organization_id, lock=True
            )
            if submission is None or submission.status != "queued":
                return
            first = await room_repo.head(db, conversation_id)
            if first is None or first.id != submission.id:
                return
            try:
                ctx, conversation, message = await service.authority(submission)
            except AppException:
                submission.status = "failed"
                submission.error = (
                    "Access or the original message changed before this request could run."
                )
                await room_repo.save(db, submission)
                announce_request(db, submission)
                return
            agent_id, version_id = submission.agent_id, submission.version_id
            assert agent_id is not None and version_id is not None, (
                "authority checked the pinned agent"
            )
            history = await ConversationService(db).model_history(
                conversation_id, limit=60, room_request_message_id=message.id
            )
            prompt = await service.conversations.model_text(message, conversation)
            people = await conversation_repo.users_by_id(db, {submission.requester_id})
            sender = people.get(submission.requester_id)
            if sender is None:
                submission.status = "failed"
                submission.error = "The member who requested this answer is unavailable."
                await room_repo.save(db, submission)
                announce_request(db, submission)
                return
            prompt_read = await service.read_message(message, sender)
            submission.status = "running"
            await room_repo.save(db, submission)
            announce_request(db, submission)
            await db.commit()
            start_deferred(db)

            async def opened(run: AgentRun) -> None:
                current = await room_repo.get(
                    db, job.request_id, organization_id=job.organization_id, lock=True
                )
                if current is None or current.status != "running" or current.run_id is not None:
                    raise AlreadyExistsError(message="This room request no longer owns its run")
                current.run_id = run.id
                await conversation_repo.link_message_to_run(
                    db,
                    message_id=current.message_id,
                    run_id=run.id,
                    conversation_id=current.conversation_id,
                )
                await room_repo.save(db, current)
                announce_request(db, current)

            async def check_model_request(fresh: AsyncSession) -> None:
                current = await room_repo.get(
                    fresh, job.request_id, organization_id=job.organization_id
                )
                if current is None or current.status != "running":
                    raise AlreadyExistsError(message="This room request no longer owns its run")
                await RoomSubmissionService(fresh).authority(current)

            saved_segment: RunSegment | None = None

            async def settled(segment: RunSegment) -> None:
                nonlocal saved_segment
                await _settle(db, job.request_id, segment.run)
                saved_segment = segment

            try:
                async with _live(submission, prompt_read) as frames:
                    try:
                        _, run = await AgentRunnerService(db).execute(
                            ctx,
                            agent_id,
                            prompt,
                            said="",
                            surface=RunSurface.WEB,
                            conversation_id=conversation_id,
                            version_id=version_id,
                            memory_room_key=f"room:project:{conversation_id}",
                            message_history=history,
                            acts_for_sender=True,
                            parks_questions=True,
                            on_run_open=opened,
                            check_model_request=check_model_request,
                            on_segment=settled,
                            stream=frames.drive,
                        )
                    finally:
                        await _emit_saved(frames, saved_segment)
                await _settle(db, job.request_id, run)
            except AppException:
                current = await room_repo.get(
                    db, job.request_id, organization_id=job.organization_id, lock=True
                )
                if current is not None and current.status not in TERMINAL:
                    current.status = "failed"
                    current.error = (
                        "The agent could not complete this request. Check its saved run."
                    )
                    await room_repo.save(db, current)
                    announce_request(db, current)


async def settle_lost_request(job: RoomRequestJob, _why: str) -> None:
    async with get_worker_db_context() as db:
        current = await room_repo.get(
            db, job.request_id, organization_id=job.organization_id, lock=True
        )
        if current is None or current.status in TERMINAL or current.status == "posted":
            return
        # A successfully parked run has completed its dispatch. Losing a later
        # duplicate job must not convert that resumable decision into a restart.
        if current.status in {"awaiting_approval", "awaiting_answer"}:
            return
        current.status = "interrupted"
        current.error = (
            "The worker stopped. This request may have changed external state; "
            "it was not restarted automatically."
        )
        await room_repo.save(db, current)
        announce_request(db, current)


async def reconcile_requests() -> int:
    async with get_worker_db_context() as db:
        unsettled = await room_repo.unsettled_runs(db)
        for submission, run in unsettled:
            await _settle(db, submission.id, run)
        ready = await room_repo.ready(db)
        service = RoomSubmissionService(db)
        for submission in ready:
            await service.queue(submission)
        return len(unsettled) + len(ready)
