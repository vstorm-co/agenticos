"""Real database coverage for uploads shared by queued room responders."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.background import discard_deferred
from app.core.exceptions import AlreadyExistsError, BadRequestError
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Message
from app.db.models.user import User
from app.repositories import agent_run as run_repo
from app.repositories import conversation as conversation_repo
from app.repositories import room_submission as room_repo
from app.schemas.room_participant import RoomParticipantRef
from app.schemas.room_submission import RoomMessageCreate
from app.services.room_submission import RoomSubmissionService
from tests.integration.test_room_submissions import seed, seed_multiplayer

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_captionless_upload_links_once_and_missing_files_stop_queued_answers(db):
    room = await seed(db)
    upload = ChatFile(
        id=uuid4(),
        user_id=room.user.id,
        filename="diagram.png",
        mime_type="image/png",
        file_type="image",
        size=10,
        storage_path="room-test/diagram.png",
    )
    db.add(upload)
    await db.flush()
    service = RoomSubmissionService(db)
    request = RoomMessageCreate(
        client_message_id="files-only",
        content="",
        file_ids=[upload.id],
        agent_id=room.agent.id,
    )
    first = await service.post(room.ctx, room.conversation.id, request, room.user)
    again = await service.post(room.ctx, room.conversation.id, request, room.user)
    assert first == again
    assert first.message.content == "" and first.message.files[0].id == upload.id
    assert upload.message_id == first.message.id and first.request is not None
    submission = await room_repo.get(db, first.request.id, organization_id=room.ctx.organization_id)
    assert submission is not None
    _, _, source = await service.authority(submission)
    files = await service.attachments(source, room.user.id, include_content=True)
    assert files[0].storage_path == "room-test/diagram.png"
    with pytest.raises(BadRequestError, match="cannot be attached"):
        await service.post(
            room.ctx,
            room.conversation.id,
            request.model_copy(update={"client_message_id": "take-the-file-again"}),
            room.user,
        )
    assert (
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == room.conversation.id)
        )
        == 1
    )
    await db.delete(upload)
    await db.flush()
    with pytest.raises(AlreadyExistsError, match="attachments are unavailable"):
        await service.authority(submission)
    discard_deferred(db)


async def test_a_foreign_upload_cannot_be_moved_into_a_room(db):
    room = await seed(db)
    foreign = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(foreign)
    await db.flush()
    upload = ChatFile(
        id=uuid4(),
        user_id=foreign.id,
        filename="private.txt",
        mime_type="text/plain",
        file_type="document",
        size=10,
        storage_path="foreign/private.txt",
        parsed_content="private",
    )
    db.add(upload)
    await db.flush()
    with pytest.raises(BadRequestError, match="cannot be attached"):
        await RoomSubmissionService(db).post(
            room.ctx,
            room.conversation.id,
            RoomMessageCreate(client_message_id="foreign-file", file_ids=[upload.id]),
            room.user,
        )
    assert upload.message_id is None
    assert (
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == room.conversation.id)
        )
        == 0
    )
    discard_deferred(db)


async def test_secondary_run_cannot_replace_the_primary_screened_prompt(db):
    room, second, _ = await seed_multiplayer(db)
    result = await RoomSubmissionService(db).post(
        room.ctx,
        room.conversation.id,
        RoomMessageCreate(
            client_message_id="saved-source",
            content="Original prompt",
            mentions=[
                RoomParticipantRef(kind="agent", id=agent.id) for agent in (room.agent, second)
            ],
        ),
        room.user,
    )
    runs = []
    for index, request in enumerate(result.requests):
        submission = await room_repo.get(db, request.id, organization_id=room.ctx.organization_id)
        assert submission is not None
        run = await run_repo.create_run(
            db,
            organization_id=room.ctx.organization_id,
            agent_id=submission.agent_id,
            agent_version_id=submission.version_id,
            user_id=room.user.id,
            conversation_id=room.conversation.id,
            surface="web",
            model_label="test",
            provider="test",
            started_at=datetime.now(UTC),
        )
        submission.run_id, submission.status = run.id, "running"
        await room_repo.save(db, submission)
        if index == 0:
            await conversation_repo.link_message_to_run(
                db,
                message_id=result.message.id,
                run_id=run.id,
                conversation_id=room.conversation.id,
            )
        runs.append(run)
        assert await conversation_repo.prepare_saved_room_prompt(
            db,
            message_id=result.message.id,
            conversation_id=room.conversation.id,
            organization_id=room.ctx.organization_id,
            requester_id=room.user.id,
            run_id=run.id,
            model_content="screened" if index == 0 else "unrestricted",
            attachment_context="first workspace" if index == 0 else "second workspace",
        )
    message = await db.get(Message, result.message.id)
    assert message is not None
    await db.refresh(message)
    assert message.content == "Original prompt" and message.model_content == "screened"
    assert message.attachment_context == "first workspace" and message.run_id == runs[0].id
    assert not await conversation_repo.prepare_saved_room_prompt(
        db,
        message_id=message.id,
        conversation_id=room.conversation.id,
        organization_id=uuid4(),
        requester_id=room.user.id,
        run_id=runs[1].id,
        model_content="foreign",
        attachment_context="foreign",
    )
    await conversation_repo.mark_run_messages_refused(db, run_id=runs[1].id)
    await db.refresh(message)
    assert message.guardrail_refused and message.attachment_context is None
    discard_deferred(db)
