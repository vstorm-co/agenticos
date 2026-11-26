"""Current and revoked multi-author chats never copy hidden evidence into a fork."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelMessagesTypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ephemeral_media import dump_messages
from app.core.permissions import AuthContext
from app.db.models.conversation import ToolCall
from app.db.models.conversation_share import ConversationShare
from app.db.models.organization import OrganizationMember
from app.db.models.project import Project
from app.repositories import conversation_repo
from app.services.conversation import ConversationService
from tests.history_fixtures import stored_checkpoint as _checkpoint
from tests.integration.test_conversation_fork import _messages, _source, _turn, _user
from tests.test_history_audience_privacy import hidden_exchange

pytestmark = pytest.mark.anyio


@pytest.mark.security
@pytest.mark.parametrize("scope", ["private", "edit-share", "revoked-share", "project"])
async def test_reads_and_real_forks_do_not_copy_a_shared_sources_hidden_tool_evidence(
    db: AsyncSession, scope: str
) -> None:
    source = await _source(db)
    assert source.user_id is not None
    owner_id = source.user_id
    other = await _user(db)
    db.add_all(
        [
            OrganizationMember(
                organization_id=source.organization_id, user_id=owner_id, role="owner"
            ),
            OrganizationMember(
                organization_id=source.organization_id, user_id=other.id, role="member"
            ),
        ]
    )
    if scope == "project":
        project = Project(
            id=uuid4(), organization_id=source.organization_id, owner_user_id=owner_id, name="Team"
        )
        db.add(project)
        await db.flush()
        source.project_id = project.id
    share = None
    if scope in {"edit-share", "revoked-share"}:
        share = ConversationShare(
            conversation_id=source.id, shared_by=owner_id, shared_with=other.id, permission="edit"
        )
        db.add(share)
    await db.flush()
    await _turn(
        db,
        source,
        "user",
        "Check my calendar",
        author_user_id=other.id if share is not None else owner_id,
    )
    answer = await _turn(db, source, "assistant", "You have an appointment.")
    db.add(
        ToolCall(
            message_id=answer.id,
            tool_call_id="private-1",
            tool_name="personal_calendar_list_events",
            args={},
            result="PRIVATE_EVENT_THERAPY",
            status="completed",
            started_at=datetime.now(UTC),
        )
    )
    source.summary_messages = _checkpoint(dump_messages(hidden_exchange()))
    source.summary_ordinal = answer.ordinal
    if scope == "revoked-share":
        assert share is not None
        await db.delete(share)
    await db.flush()
    service = ConversationService(db)
    history = await service.model_history(source.id, limit=50)
    assert ("PRIVATE_EVENT_THERAPY" in ModelMessagesTypeAdapter.dump_json(history).decode()) is (
        scope == "private"
    )
    fork = await service.fork(
        source.id,
        message_id=answer.id,
        organization_id=source.organization_id,
        user_id=owner_id,
        ctx=AuthContext(user_id=owner_id, organization_id=source.organization_id, role="owner"),
    )
    assert (fork.summary_messages is not None) is (scope == "private")
    assert (fork.summary_ordinal is not None) is (scope == "private")
    copied = await _messages(db, fork.id)
    assert [(row.role, row.content) for row in copied] == [
        ("user", "Check my calendar"),
        ("assistant", "You have an appointment."),
    ]
    replayed = ModelMessagesTypeAdapter.dump_json(
        await service.model_history(fork.id, limit=50)
    ).decode()
    assert ("PRIVATE_EVENT_THERAPY" in replayed) is (scope == "private")
    assert "You have an appointment." in replayed


@pytest.mark.security
@pytest.mark.parametrize("scope", ["private-dm", "room", "detached-room", "unlinked-author"])
async def test_a_room_checkpoint_cannot_be_replayed_or_forked_through_the_console(
    db: AsyncSession, scope: str
) -> None:
    from app.db.models.channel_bot import ChannelBot
    from app.db.models.channel_identity import ChannelIdentity
    from app.db.models.channel_session import ChannelSession

    source = await _source(db)
    assert source.user_id is not None
    owner_id = source.user_id
    other = await _user(db)
    owner = ChannelIdentity(
        id=uuid4(), platform="mattermost", platform_user_id=uuid4().hex, user_id=owner_id
    )
    colleague = ChannelIdentity(
        id=uuid4(), platform="mattermost", platform_user_id=uuid4().hex, user_id=other.id
    )
    bot = ChannelBot(
        id=uuid4(),
        organization_id=source.organization_id,
        platform="mattermost",
        name="Assistant",
        token_encrypted="unused-fixture",
    )
    db.add_all([owner, colleague, bot])
    await db.flush()
    session = ChannelSession(
        bot_id=bot.id,
        identity_id=owner.id,
        conversation_id=source.id,
        platform_chat_id=uuid4().hex,
        chat_type="private" if scope == "private-dm" else "group",
    )
    db.add(session)
    if scope != "unlinked-author":
        await _turn(db, source, "user", "Check my calendar", channel_identity_id=owner.id)
    if scope in {"detached-room", "unlinked-author"}:
        await _turn(db, source, "user", "My private event", channel_identity_id=colleague.id)
        colleague.user_id = None
        await db.flush()
        await db.delete(session)
    answer = await _turn(db, source, "assistant", "You have an appointment.")
    source.summary_messages = _checkpoint(dump_messages(hidden_exchange()))
    source.summary_ordinal = answer.ordinal
    await db.flush()
    service = ConversationService(db)
    private = scope == "private-dm"
    history = await service.model_history(source.id, limit=50)
    assert (
        "PRIVATE_EVENT_THERAPY" in ModelMessagesTypeAdapter.dump_json(history).decode()
    ) is private
    fork = await service.fork(
        source.id,
        message_id=answer.id,
        organization_id=source.organization_id,
        user_id=owner_id,
        ctx=AuthContext(user_id=owner_id, organization_id=source.organization_id, role="owner"),
    )
    assert (fork.summary_messages is not None) is private
    replayed = ModelMessagesTypeAdapter.dump_json(
        await service.model_history(fork.id, limit=50)
    ).decode()
    assert ("PRIVATE_EVENT_THERAPY" in replayed) is private
    assert "You have an appointment." in replayed


@pytest.mark.security
@pytest.mark.parametrize("scope", ["web", "channel", "retained-project"])
async def test_account_erasure_fences_foreign_authored_checkpoints_before_author_links_disappear(
    db: AsyncSession, scope: str
) -> None:
    from app.db.models.channel_identity import ChannelIdentity
    from app.schemas.conversation import HistoryCheckpointFrontier
    from app.services.user import UserService

    source = await _source(db)
    assert source.user_id is not None
    owner_id = source.user_id
    removed = await _user(db)
    if scope == "retained-project":
        project = Project(
            id=uuid4(), organization_id=source.organization_id, owner_user_id=owner_id, name="Team"
        )
        db.add(project)
        await db.flush()
        source.project_id = project.id
        source.user_id = removed.id
    if scope == "channel":
        identity = ChannelIdentity(
            id=uuid4(), platform="mattermost", platform_user_id=uuid4().hex, user_id=removed.id
        )
        db.add(identity)
        await db.flush()
        await _turn(db, source, "user", "Check my calendar", channel_identity_id=identity.id)
    else:
        await _turn(db, source, "user", "Check my calendar", author_user_id=removed.id)
    answer = await _turn(db, source, "assistant", "You have an appointment.")
    source.summary_messages = _checkpoint(dump_messages(hidden_exchange()))
    source.summary_ordinal = answer.ordinal
    unrelated = await _source(db)
    other_answer = await _turn(db, unrelated, "assistant", "Only its owner spoke.")
    unrelated.summary_messages = _checkpoint(dump_messages(hidden_exchange()))
    unrelated.summary_ordinal = other_answer.ordinal
    await db.flush()
    revision = source.guardrail_revision
    frontier = HistoryCheckpointFrontier(
        summary_ordinal=answer.ordinal, message_ordinal=answer.ordinal
    )
    removed_id = removed.id
    await UserService(db).delete(removed_id)
    await db.refresh(source)
    await db.refresh(unrelated)
    assert source.guardrail_revision == revision + 1
    assert source.summary_messages is None and source.summary_ordinal is None
    assert unrelated.guardrail_revision == 0 and unrelated.summary_messages is not None
    assert unrelated.summary_ordinal == other_answer.ordinal
    stale = await conversation_repo.set_summary(
        db,
        db_conversation=source,
        messages=dump_messages(hidden_exchange()),
        ordinal=answer.ordinal,
        expected_revision=revision,
        expected_frontier=frontier,
    )
    assert stale is False
    history = await ConversationService(db).model_history(source.id, limit=50)
    assert "PRIVATE_EVENT_THERAPY" not in ModelMessagesTypeAdapter.dump_json(history).decode()
    assert "You have an appointment." in ModelMessagesTypeAdapter.dump_json(history).decode()


@pytest.mark.security
@pytest.mark.parametrize(
    "scope", ["foreign-authored", "empty-owned", "empty-owned-project", "assistant-only-owned"]
)
async def test_account_deletion_refuses_a_busy_history_before_cleanup_without_locking_cycle(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    from unittest.mock import AsyncMock

    from sqlalchemy import select

    from app.core.exceptions import ConcurrentChangeError
    from app.db.models.conversation import Conversation
    from app.db.models.user import User
    from app.services import user as user_service

    source = await _source(db)
    removed = await _user(db)
    if scope == "foreign-authored":
        await _turn(db, source, "user", "My private event", author_user_id=removed.id)
    else:
        if scope == "empty-owned-project":
            project = Project(
                organization_id=source.organization_id,
                owner_user_id=source.user_id,
                name="Retained",
            )
            db.add(project)
            await db.flush()
            source.project_id = project.id
        source.user_id = removed.id
    if scope in {"foreign-authored", "assistant-only-owned"}:
        answer = await _turn(db, source, "assistant", "You have an appointment.")
        source.summary_messages = _checkpoint(dump_messages(hidden_exchange()))
        source.summary_ordinal = answer.ordinal
    original_summary = source.summary_messages
    source_id, removed_id = source.id, removed.id
    await db.commit()
    await db.execute(select(Conversation.id).where(Conversation.id == source_id).with_for_update())
    monkeypatch.setattr(user_service, "_ACCOUNT_LOCK_SECONDS", 0)
    cleanup = AsyncMock()
    monkeypatch.setattr(user_service.UserService, "_delete_locked", cleanup)
    async with AsyncSession(bind=db.bind) as deleting:
        with pytest.raises(ConcurrentChangeError, match="Nothing was deleted"):
            await user_service.UserService(deleting).delete(removed_id)
    cleanup.assert_not_awaited()
    assert await db.get(User, removed_id) is not None
    await db.refresh(source)
    assert source.guardrail_revision == 0 and source.summary_messages == original_summary
    await db.rollback()
