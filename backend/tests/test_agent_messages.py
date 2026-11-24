"""Agent-to-agent messages: who may send, read, react, and what a thread shows."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent_message import (
    AgentMessage,
    AgentMessageReaction,
    AgentMessageThread,
)
from app.db.models.chat_file import ChatFile
from app.schemas.agent_message import AgentMessageReactionCreate, AgentMessageSend
from app.services import agent_messages
from app.services.agent_messages import AgentMessageService

pytestmark = pytest.mark.anyio

PATH = "app.services.agent_messages"
NOW = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)


def _ctx(org: uuid.UUID, user: uuid.UUID) -> AuthContext:
    return AuthContext(user_id=user, organization_id=org, role=OrgRoleName.MEMBER)


def _agent(
    org: uuid.UUID, *, slug: str, status: str = "published", agent_id: uuid.UUID | None = None
) -> MagicMock:
    agent = MagicMock()
    agent.id = agent_id or uuid.uuid4()
    agent.organization_id = org
    agent.slug = slug
    agent.name = slug.replace("-", " ").title()
    agent.status = status
    return agent


def _thread(org: uuid.UUID, a: MagicMock, b: MagicMock) -> AgentMessageThread:
    return AgentMessageThread(
        id=uuid.uuid4(),
        organization_id=org,
        agent_a_id=a.id,
        agent_b_id=b.id,
        last_message_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _message(
    org: uuid.UUID, thread: AgentMessageThread, sender: MagicMock, *, body: str = "hello"
) -> AgentMessage:
    return AgentMessage(
        id=uuid.uuid4(),
        thread_id=thread.id,
        organization_id=org,
        sender_agent_id=sender.id,
        sender_user_id=None,
        body=body,
        reply_to_message_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _service() -> AgentMessageService:
    return AgentMessageService(MagicMock())


class TestSend:
    async def test_a_message_is_stored_in_the_pair_s_thread(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        sender, recipient = _agent(org, slug="researcher"), _agent(org, slug="summariser")
        thread = _thread(org, sender, recipient)
        stored = _message(org, thread, sender)

        async def create_message(_db: Any, **kwargs: Any) -> AgentMessage:
            assert kwargs["thread"] is thread
            return stored

        with (
            patch(f"{PATH}.agent_repo.get", new=AsyncMock(side_effect=[sender, recipient])),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{PATH}.agent_message_repo.get_or_create_thread",
                new=AsyncMock(return_value=thread),
            ),
            patch(f"{PATH}.agent_message_repo.create_message", new=create_message),
            patch(f"{PATH}.agent_message_repo.touch_thread", new=AsyncMock()),
            patch(f"{PATH}.agent_message_repo.list_reactions", new=AsyncMock(return_value=[])),
            patch(
                f"{PATH}.agent_message_repo.list_attachments",
                new=AsyncMock(return_value=[]),
            ),
        ):
            sent = await _service().send(
                _ctx(org, user),
                AgentMessageSend(
                    sender_agent_id=sender.id, recipient=str(recipient.id), body="hello"
                ),
            )

        assert sent.thread_id == thread.id
        assert sent.sender_agent_slug == "researcher"
        assert sent.body == "hello"

    async def test_an_agent_cannot_message_itself(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        sender = _agent(org, slug="researcher")
        with (
            patch(f"{PATH}.agent_repo.get", new=AsyncMock(return_value=sender)),
            pytest.raises(BadRequestError),
        ):
            await _service().send(
                _ctx(org, user),
                AgentMessageSend(sender_agent_id=sender.id, recipient=str(sender.id), body="hello"),
            )

    async def test_a_draft_agent_cannot_be_messaged(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        sender = _agent(org, slug="researcher")
        recipient = _agent(org, slug="draft-one", status="draft")
        with (
            patch(
                f"{PATH}.agent_repo.get",
                new=AsyncMock(side_effect=[sender, recipient]),
            ),
            pytest.raises(BadRequestError),
        ):
            await _service().send(
                _ctx(org, user),
                AgentMessageSend(
                    sender_agent_id=sender.id, recipient=str(recipient.id), body="hello"
                ),
            )

    async def test_sending_needs_run_on_both_agents(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        sender, recipient = _agent(org, slug="researcher"), _agent(org, slug="summariser")

        async def may(_db: Any, _ctx: Any, agent: Any, _perm: Perm, **_kw: Any) -> bool:
            return agent.id == sender.id

        with (
            patch(
                f"{PATH}.agent_repo.get",
                new=AsyncMock(side_effect=[sender, recipient]),
            ),
            patch(f"{PATH}.resolve_access", new=may),
            pytest.raises(AuthorizationError),
        ):
            await _service().send(
                _ctx(org, user),
                AgentMessageSend(
                    sender_agent_id=sender.id, recipient=str(recipient.id), body="hello"
                ),
            )

    async def test_a_recipient_in_another_organization_is_not_found(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        sender = _agent(org, slug="researcher")
        foreign = _agent(uuid.uuid4(), slug="outsider")
        with (
            patch(
                f"{PATH}.agent_repo.get",
                new=AsyncMock(side_effect=[sender, None]),
            ),
            patch(
                f"{PATH}.agent_repo.get_by_slug",
                new=AsyncMock(return_value=foreign),
            ),
            pytest.raises(NotFoundError),
        ):
            await _service().send(
                _ctx(org, user),
                AgentMessageSend(sender_agent_id=sender.id, recipient="outsider", body="hello"),
            )

    async def test_a_reply_must_answer_a_message_in_the_same_thread(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        sender, recipient = _agent(org, slug="researcher"), _agent(org, slug="summariser")
        thread = _thread(org, sender, recipient)
        other_thread = _thread(org, sender, recipient)
        stray = _message(org, other_thread, recipient, body="elsewhere")
        with (
            patch(
                f"{PATH}.agent_repo.get",
                new=AsyncMock(side_effect=[sender, recipient]),
            ),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{PATH}.agent_message_repo.get_or_create_thread",
                new=AsyncMock(return_value=thread),
            ),
            patch(
                f"{PATH}.agent_message_repo.get_message",
                new=AsyncMock(return_value=stray),
            ),
            pytest.raises(BadRequestError),
        ):
            await _service().send(
                _ctx(org, user),
                AgentMessageSend(
                    sender_agent_id=sender.id,
                    recipient=str(recipient.id),
                    body="hello",
                    reply_to_message_id=stray.id,
                ),
            )

    async def test_an_attachment_uploaded_by_somebody_else_is_refused(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        sender, recipient = _agent(org, slug="researcher"), _agent(org, slug="summariser")
        thread = _thread(org, sender, recipient)
        with (
            patch(
                f"{PATH}.agent_repo.get",
                new=AsyncMock(side_effect=[sender, recipient]),
            ),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{PATH}.agent_message_repo.get_or_create_thread",
                new=AsyncMock(return_value=thread),
            ),
            patch(f"{PATH}.chat_file_repo.get_many", new=AsyncMock(return_value=[])),
            pytest.raises(NotFoundError),
        ):
            await _service().send(
                _ctx(org, user),
                AgentMessageSend(
                    sender_agent_id=sender.id,
                    recipient=str(recipient.id),
                    body="hello",
                    attachment_file_ids=[uuid.uuid4()],
                ),
            )

    async def test_eleven_attachments_are_refused(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        sender, recipient = _agent(org, slug="researcher"), _agent(org, slug="summariser")
        create_thread = AsyncMock()
        with (
            patch(
                f"{PATH}.agent_repo.get",
                new=AsyncMock(side_effect=[sender, recipient]),
            ),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{PATH}.agent_message_repo.get_or_create_thread",
                new=create_thread,
            ),
            pytest.raises(BadRequestError),
        ):
            await _service().send(
                _ctx(org, user),
                AgentMessageSend.model_construct(
                    sender_agent_id=sender.id,
                    recipient=str(recipient.id),
                    body="hello",
                    reply_to_message_id=None,
                    attachment_file_ids=[uuid.uuid4() for _ in range(11)],
                ),
            )
        # The refusal happens before the thread is touched: no empty thread
        # is left behind for a send that never happened.
        assert create_thread.await_count == 0


class TestReact:
    async def test_the_same_emoji_twice_takes_the_reaction_back(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        sender, recipient = _agent(org, slug="researcher"), _agent(org, slug="summariser")
        thread = _thread(org, sender, recipient)
        message = _message(org, thread, sender)
        reaction = AgentMessageReaction(
            id=uuid.uuid4(),
            message_id=message.id,
            organization_id=org,
            emoji="👍",
            reactor_agent_id=None,
            reactor_user_id=user,
            created_at=NOW,
        )
        removed = AsyncMock()
        with (
            patch(
                f"{PATH}.agent_message_repo.get_message",
                new=AsyncMock(return_value=message),
            ),
            patch(
                f"{PATH}.agent_message_repo.get_thread",
                new=AsyncMock(return_value=thread),
            ),
            patch(
                f"{PATH}.agent_repo.get",
                new=AsyncMock(return_value=sender),
            ),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(
                f"{PATH}.agent_message_repo.get_reaction",
                new=AsyncMock(return_value=reaction),
            ),
            patch(f"{PATH}.agent_message_repo.remove_reaction", new=removed),
            patch(f"{PATH}.agent_message_repo.list_reactions", new=AsyncMock(return_value=[])),
        ):
            result = await _service().react(
                _ctx(org, user),
                message_id=message.id,
                data=AgentMessageReactionCreate(emoji="👍"),
            )

        removed.assert_awaited_once()
        assert result.reacted is False
        assert result.reactions == []

    async def test_an_agent_outside_the_thread_cannot_react_as_itself(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        sender, recipient = _agent(org, slug="researcher"), _agent(org, slug="summariser")
        outsider = _agent(org, slug="outsider")
        thread = _thread(org, sender, recipient)
        message = _message(org, thread, sender)
        with (
            patch(
                f"{PATH}.agent_message_repo.get_message",
                new=AsyncMock(return_value=message),
            ),
            patch(
                f"{PATH}.agent_message_repo.get_thread",
                new=AsyncMock(return_value=thread),
            ),
            patch(
                f"{PATH}.agent_repo.get",
                new=AsyncMock(side_effect=[sender, outsider]),
            ),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            pytest.raises(BadRequestError),
        ):
            await _service().react(
                _ctx(org, user),
                message_id=message.id,
                data=AgentMessageReactionCreate(emoji="👍", as_agent_id=outsider.id),
            )

    async def test_a_message_in_another_thread_is_not_found_there(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        sender, recipient = _agent(org, slug="researcher"), _agent(org, slug="summariser")
        thread = _thread(org, sender, recipient)
        message = _message(org, thread, sender)
        with (
            patch(
                f"{PATH}.agent_message_repo.get_message",
                new=AsyncMock(return_value=message),
            ),
            pytest.raises(NotFoundError),
        ):
            await _service().react(
                _ctx(org, user),
                message_id=message.id,
                data=AgentMessageReactionCreate(emoji="👍"),
                thread_id=uuid.uuid4(),
            )


class TestListing:
    async def test_a_thread_shows_unread_until_the_reader_opens_it(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        sender, recipient = _agent(org, slug="researcher"), _agent(org, slug="summariser")
        thread = _thread(org, sender, recipient)
        last = _message(org, thread, sender, body="the latest word")
        with (
            patch(f"{PATH}.visible_resource_ids", new=AsyncMock(return_value=None)),
            patch(
                f"{PATH}.agent_message_repo.list_threads",
                new=AsyncMock(return_value=([thread], 1)),
            ),
            patch(
                f"{PATH}.agent_repo.list_by_ids",
                new=AsyncMock(return_value=([sender, recipient], 2)),
            ),
            patch(
                f"{PATH}.agent_message_repo.latest_messages",
                new=AsyncMock(return_value={thread.id: last}),
            ),
            patch(f"{PATH}.agent_message_repo.get_reads", new=AsyncMock(return_value={})),
        ):
            listed = await _service().list_threads(_ctx(org, user))

        assert listed.total == 1
        row = listed.items[0]
        assert row.agent_a.slug == "researcher"
        assert row.agent_b.slug == "summariser"
        assert row.last_message is not None and row.last_message.body == "the latest word"
        assert row.unread is True

    async def test_recipients_are_the_published_agents_the_caller_may_run(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        runnable = _agent(org, slug="researcher")
        with (
            patch(
                f"{PATH}.visible_resource_ids",
                new=AsyncMock(return_value=[runnable.id]),
            ),
            patch(
                f"{PATH}.agent_repo.list_visible_ids",
                new=AsyncMock(return_value={runnable.id}),
            ),
            patch(
                f"{PATH}.agent_repo.list_by_ids",
                new=AsyncMock(return_value=([runnable], 1)),
            ),
        ):
            recipients = await _service().list_recipients(_ctx(org, user))

        assert [item.slug for item in recipients.items] == ["researcher"]

    async def test_marking_a_thread_read_records_the_watermark(self) -> None:
        org, user = uuid.uuid4(), uuid.uuid4()
        sender, recipient = _agent(org, slug="researcher"), _agent(org, slug="summariser")
        thread = _thread(org, sender, recipient)
        marked = AsyncMock()
        with (
            patch(
                f"{PATH}.agent_message_repo.get_thread",
                new=AsyncMock(return_value=thread),
            ),
            patch(
                f"{PATH}.agent_repo.get",
                new=AsyncMock(return_value=sender),
            ),
            patch(f"{PATH}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{PATH}.agent_message_repo.mark_read", new=marked),
        ):
            await _service().mark_read(_ctx(org, user), thread.id)

        marked.assert_awaited_once()
        assert marked.await_args is not None
        assert marked.await_args.kwargs["thread_id"] == thread.id
        assert marked.await_args.kwargs["user_id"] == user


@dataclass
class MessagingWorld:
    ctx: AuthContext
    sender: MagicMock
    recipient: MagicMock
    thread: AgentMessageThread
    message: AgentMessage
    service: AgentMessageService
    agents: MagicMock
    messages: MagicMock
    files: MagicMock
    access: AsyncMock
    visible: AsyncMock


@pytest.fixture
def messaging(monkeypatch: pytest.MonkeyPatch) -> MessagingWorld:
    org, user = uuid.uuid4(), uuid.uuid4()
    sender, recipient = _agent(org, slug="writer"), _agent(org, slug="reviewer")
    thread = _thread(org, sender, recipient)
    message = _message(org, thread, sender)
    message.sender_user_id = user
    agents, messages, files = MagicMock(), MagicMock(), MagicMock()

    async def get_agent(
        _db: object, agent_id: uuid.UUID, *, organization_id: uuid.UUID
    ) -> MagicMock | None:
        if organization_id != org:
            return None
        return {sender.id: sender, recipient.id: recipient}.get(agent_id)

    agents.get = AsyncMock(side_effect=get_agent)
    agents.get_by_slug = AsyncMock(return_value=recipient)
    agents.list_by_ids = AsyncMock(return_value=([sender, recipient], 2))
    agents.list_visible_ids = AsyncMock(return_value={sender.id})
    messages.get_or_create_thread = AsyncMock(return_value=thread)
    messages.get_thread = AsyncMock(return_value=thread)
    messages.get_message = AsyncMock(return_value=message)
    messages.create_message = AsyncMock(return_value=message)
    messages.touch_thread = AsyncMock()
    messages.add_attachment = AsyncMock()
    messages.list_attachments = AsyncMock(return_value=[])
    messages.list_chat_files = AsyncMock(return_value=[])
    messages.get_attachment = AsyncMock(return_value=None)
    messages.list_reactions = AsyncMock(return_value=[])
    messages.get_reaction = AsyncMock(return_value=None)
    messages.add_reaction = AsyncMock()
    messages.remove_reaction = AsyncMock()
    messages.list_threads = AsyncMock(return_value=([], 0))
    messages.latest_messages = AsyncMock(return_value={})
    messages.get_reads = AsyncMock(return_value={})
    messages.list_messages = AsyncMock(return_value=([], 0))
    files.get_many = AsyncMock(return_value=[])
    files.get_by_id = AsyncMock(return_value=None)
    access = AsyncMock(return_value=True)
    visible = AsyncMock(return_value=None)
    monkeypatch.setattr(agent_messages, "agent_repo", agents)
    monkeypatch.setattr(agent_messages, "agent_message_repo", messages)
    monkeypatch.setattr(agent_messages, "chat_file_repo", files)
    monkeypatch.setattr(agent_messages, "resolve_access", access)
    monkeypatch.setattr(agent_messages, "visible_resource_ids", visible)
    return MessagingWorld(
        _ctx(org, user),
        sender,
        recipient,
        thread,
        message,
        _service(),
        agents,
        messages,
        files,
        access,
        visible,
    )


def _uploaded_file(user_id: uuid.UUID, filename: str) -> ChatFile:
    return ChatFile(
        id=uuid.uuid4(),
        user_id=user_id,
        filename=filename,
        mime_type="text/plain",
        size=12,
        file_type="document",
        storage_path=f"chat/{filename}",
    )


async def test_a_reply_keeps_its_author_and_links_distinct_files_in_requested_order(
    messaging: MessagingWorld,
) -> None:
    w = messaging
    first, second = (
        _uploaded_file(w.ctx.subject_id, "first.txt"),
        _uploaded_file(w.ctx.subject_id, "second.txt"),
    )
    reply = _message(w.ctx.organization_id, w.thread, w.recipient, body="question")
    w.messages.get_message.return_value = reply
    w.message.reply_to_message_id = reply.id
    w.files.get_many.return_value = [second, first]
    w.messages.list_attachments.return_value = [
        MagicMock(message_id=w.message.id, chat_file_id=first.id),
        MagicMock(message_id=w.message.id, chat_file_id=second.id),
    ]
    w.messages.list_chat_files.return_value = [second, first]
    result = await w.service.send(
        w.ctx,
        AgentMessageSend(
            sender_agent_id=w.sender.id,
            recipient=w.recipient.slug,
            body="hello",
            reply_to_message_id=reply.id,
            attachment_file_ids=[first.id, second.id, first.id],
        ),
    )
    assert result.sender_user_id == w.ctx.subject_id
    assert result.reply_to_message_id == reply.id
    assert [item.filename for item in result.attachments] == ["first.txt", "second.txt"]
    w.files.get_many.assert_awaited_once_with(
        w.service.db, [first.id, second.id], user_id=w.ctx.subject_id
    )
    w.messages.create_message.assert_awaited_once_with(
        w.service.db,
        thread=w.thread,
        organization_id=w.ctx.organization_id,
        sender_agent_id=w.sender.id,
        sender_user_id=w.ctx.subject_id,
        body="hello",
        reply_to_message_id=reply.id,
    )
    assert [item.kwargs["chat_file_id"] for item in w.messages.add_attachment.await_args_list] == [
        first.id,
        second.id,
    ]
    w.messages.touch_thread.assert_awaited_once_with(
        w.service.db, thread=w.thread, at=w.message.created_at
    )


@pytest.mark.security
async def test_the_service_body_ceiling_refuses_before_a_thread_or_file_is_written(
    messaging: MessagingWorld,
) -> None:
    w = messaging
    with pytest.raises(BadRequestError, match="at most 100000") as raised:
        await w.service.send(
            w.ctx,
            AgentMessageSend.model_construct(
                sender_agent_id=w.sender.id,
                recipient=str(w.recipient.id),
                body="x" * 100_001,
                reply_to_message_id=None,
                attachment_file_ids=[],
            ),
        )
    assert raised.value.details == {"body_chars": 100_001}
    w.messages.get_or_create_thread.assert_not_awaited()
    w.messages.create_message.assert_not_awaited()
    w.files.get_many.assert_not_awaited()


@pytest.mark.security
async def test_an_unknown_sender_cannot_create_a_thread(messaging: MessagingWorld) -> None:
    w = messaging
    with pytest.raises(NotFoundError, match="Agent not found"):
        await w.service.send(
            w.ctx,
            AgentMessageSend(
                sender_agent_id=uuid.uuid4(), recipient=str(w.recipient.id), body="hello"
            ),
        )
    w.messages.get_or_create_thread.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("recipient", ["missing-agent", str(uuid.UUID(int=7))])
async def test_a_missing_recipient_is_not_found_by_slug_or_identifier(
    messaging: MessagingWorld,
    recipient: str,
) -> None:
    w = messaging
    w.agents.get_by_slug.return_value = None
    with pytest.raises(NotFoundError, match="No agent named"):
        await w.service.send(
            w.ctx, AgentMessageSend(sender_agent_id=w.sender.id, recipient=recipient, body="hello")
        )
    w.agents.get_by_slug.assert_awaited_once_with(
        w.service.db, recipient, organization_id=w.ctx.organization_id
    )
    w.messages.create_message.assert_not_awaited()


async def test_a_reply_to_a_deleted_message_is_refused_before_storing_a_message(
    messaging: MessagingWorld,
) -> None:
    w = messaging
    w.messages.get_message.return_value = None
    with pytest.raises(NotFoundError, match="being replied to"):
        await w.service.send(
            w.ctx,
            AgentMessageSend(
                sender_agent_id=w.sender.id,
                recipient=str(w.recipient.id),
                body="hello",
                reply_to_message_id=uuid.uuid4(),
            ),
        )
    w.messages.create_message.assert_not_awaited()
    w.messages.touch_thread.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("allowed", [False, True])
async def test_an_agents_thread_listing_requires_run_and_keeps_the_agent_filter(
    messaging: MessagingWorld,
    allowed: bool,
) -> None:
    w = messaging
    w.access.return_value = allowed
    if not allowed:
        with pytest.raises(AuthorizationError, match="not one you may run"):
            await w.service.list_threads_for_agent(w.ctx, agent_id=w.sender.id, skip=4, limit=9)
        w.messages.list_threads.assert_not_awaited()
    else:
        listed = await w.service.list_threads_for_agent(
            w.ctx, agent_id=w.sender.id, skip=4, limit=9
        )
        assert listed.items == []
        assert listed.total == 0
        w.messages.list_threads.assert_awaited_once_with(
            w.service.db,
            organization_id=w.ctx.organization_id,
            agent_ids={w.sender.id},
            skip=4,
            limit=9,
        )
    w.access.assert_awaited_once_with(
        w.service.db, w.ctx, w.sender, Perm.AGENTS_RUN, resource_type=agent_messages.AGENT
    )
    w.agents.list_by_ids.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("missing", ["subject", "key-scope"])
async def test_a_missing_subject_or_run_scope_sees_no_threads(
    messaging: MessagingWorld,
    missing: str,
) -> None:
    w = messaging
    ctx = AuthContext(
        user_id=None if missing == "subject" else w.ctx.subject_id,
        organization_id=w.ctx.organization_id,
        role=OrgRoleName.MEMBER,
        key_scopes=frozenset() if missing == "key-scope" else None,
    )
    result = await w.service.list_threads(ctx, skip=2, limit=8)
    assert result.items == [] and result.total == 0
    w.visible.assert_not_awaited()
    w.agents.list_visible_ids.assert_not_awaited()
    w.messages.list_threads.assert_awaited_once_with(
        w.service.db, organization_id=w.ctx.organization_id, agent_ids=set(), skip=2, limit=8
    )


@pytest.mark.security
@pytest.mark.parametrize("absent", ["missing", "other-tenant"])
async def test_a_missing_or_foreign_thread_is_indistinguishable(
    messaging: MessagingWorld,
    absent: str,
) -> None:
    w = messaging
    if absent == "missing":
        w.messages.get_thread.return_value = None
    else:
        w.thread.organization_id = uuid.uuid4()
    with pytest.raises(NotFoundError, match="Thread not found"):
        await w.service.get_thread(w.ctx, w.thread.id)
    w.access.assert_not_awaited()
    w.messages.latest_messages.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("first", ["missing", "ungranted"])
async def test_reading_checks_the_other_participant_when_the_first_cannot_be_run(
    messaging: MessagingWorld,
    first: str,
) -> None:
    w = messaging
    w.agents.get.side_effect = [None if first == "missing" else w.sender, w.recipient]
    w.access.side_effect = [True] if first == "missing" else [False, True]
    result = await w.service.get_thread(w.ctx, w.thread.id)
    assert result.id == w.thread.id
    assert result.agent_b.id == w.recipient.id
    assert result.last_message is None
    assert result.unread is False
    assert [call.args[1] for call in w.agents.get.await_args_list] == [w.sender.id, w.recipient.id]
    for call in w.agents.get.await_args_list:
        assert call.kwargs["organization_id"] == w.ctx.organization_id


@pytest.mark.security
async def test_neither_participants_run_permission_means_no_message_read(
    messaging: MessagingWorld,
) -> None:
    w = messaging
    w.access.return_value = False
    with pytest.raises(AuthorizationError, match="agents you may not run"):
        await w.service.list_messages(w.ctx, w.thread.id)
    w.messages.list_messages.assert_not_awaited()
    w.messages.list_attachments.assert_not_awaited()
    w.messages.list_reactions.assert_not_awaited()


async def test_an_empty_message_page_needs_no_author_file_or_reaction_lookups(
    messaging: MessagingWorld,
) -> None:
    w = messaging
    result = await w.service.list_messages(w.ctx, w.thread.id, skip=5, limit=6)
    assert result.items == [] and result.total == 0
    w.messages.list_messages.assert_awaited_once_with(
        w.service.db, thread_id=w.thread.id, skip=5, limit=6
    )
    w.agents.list_by_ids.assert_not_awaited()
    w.messages.list_reactions.assert_not_awaited()
    w.messages.list_attachments.assert_not_awaited()


async def test_message_projection_preserves_order_actors_and_surviving_attachments(
    messaging: MessagingWorld,
) -> None:
    w = messaging
    second = _message(w.ctx.organization_id, w.thread, w.recipient, body="answer")
    second.reply_to_message_id = w.message.id
    w.messages.list_messages.return_value = ([w.message, second], 12)
    # A separate metadata query may see a deletion after the page was fetched.
    w.agents.list_by_ids.side_effect = [([w.sender], 1), ([w.recipient], 1)]
    missing_agent_id = uuid.uuid4()
    w.messages.list_reactions.return_value = [
        AgentMessageReaction(
            id=uuid.uuid4(),
            message_id=w.message.id,
            organization_id=w.ctx.organization_id,
            emoji="👍",
            reactor_agent_id=w.recipient.id,
            reactor_user_id=None,
            created_at=NOW,
        ),
        AgentMessageReaction(
            id=uuid.uuid4(),
            message_id=w.message.id,
            organization_id=w.ctx.organization_id,
            emoji="✅",
            reactor_agent_id=None,
            reactor_user_id=w.ctx.subject_id,
            created_at=NOW,
        ),
        AgentMessageReaction(
            id=uuid.uuid4(),
            message_id=second.id,
            organization_id=w.ctx.organization_id,
            emoji="👀",
            reactor_agent_id=missing_agent_id,
            reactor_user_id=None,
            created_at=NOW,
        ),
    ]
    kept = _uploaded_file(w.ctx.subject_id, "kept.txt")
    gone_id = uuid.uuid4()
    w.messages.list_attachments.return_value = [
        MagicMock(message_id=w.message.id, chat_file_id=gone_id),
        MagicMock(message_id=second.id, chat_file_id=kept.id),
    ]
    w.messages.list_chat_files.return_value = [kept]
    result = await w.service.list_messages(w.ctx, w.thread.id, skip=2, limit=2)
    assert result.total == 12
    assert [item.id for item in result.items] == [w.message.id, second.id]
    one, two = result.items
    assert one.sender_agent_slug == "writer"
    assert one.sender_user_id == w.ctx.subject_id
    assert two.sender_agent_slug == "?"
    assert two.reply_to_message_id == w.message.id
    assert one.attachments == []
    assert [
        (item.filename, item.mime_type, item.size, item.file_type) for item in two.attachments
    ] == [("kept.txt", "text/plain", 12, "document")]
    assert [(item.reactor_agent_slug, item.reactor_user_id) for item in one.reactions] == [
        ("reviewer", None),
        (None, w.ctx.subject_id),
    ]
    assert two.reactions[0].reactor_agent_id == missing_agent_id
    assert two.reactions[0].reactor_agent_slug is None


@pytest.mark.parametrize(
    ("watermark", "unread"), [(None, True), (-1, True), (0, False), (1, False)]
)
async def test_thread_previews_compare_the_read_watermark_and_bound_message_text(
    messaging: MessagingWorld,
    watermark: int | None,
    unread: bool,
) -> None:
    w = messaging
    w.message.body = "x" * 230
    w.messages.list_threads.return_value = ([w.thread], 1)
    w.messages.latest_messages.return_value = {w.thread.id: w.message}
    if watermark is not None:
        w.messages.get_reads.return_value = {
            w.thread.id: MagicMock(read_at=NOW + timedelta(seconds=watermark))
        }
    listed = await w.service.list_threads(w.ctx)
    item = listed.items[0]
    assert item.unread is unread
    assert item.last_message is not None
    assert item.last_message.body == "x" * 200
    assert item.last_message.created_at == NOW
    assert item.last_message.sender_agent_slug == "writer"
    assert item.last_message_at == w.thread.last_message_at


async def test_a_preview_with_a_missing_sender_keeps_text_without_inventing_an_identity(
    messaging: MessagingWorld,
) -> None:
    w = messaging
    w.message.sender_agent_id = uuid.uuid4()
    w.messages.latest_messages.return_value = {w.thread.id: w.message}
    item = await w.service.get_thread(w.ctx, w.thread.id)
    assert item.last_message is not None
    assert item.last_message.body == "hello"
    assert item.last_message.sender_agent_slug == "?"


@pytest.mark.security
@pytest.mark.parametrize("emoji", ["", "   ", "👍 ✅", "👍\n✅"])
async def test_empty_or_multiword_reactions_fail_before_loading_a_message(
    messaging: MessagingWorld,
    emoji: str,
) -> None:
    w = messaging
    with pytest.raises(BadRequestError, match="one emoji"):
        await w.service.react(
            w.ctx,
            message_id=w.message.id,
            data=AgentMessageReactionCreate.model_construct(emoji=emoji, as_agent_id=None),
        )
    w.messages.get_message.assert_not_awaited()
    w.messages.add_reaction.assert_not_awaited()


@pytest.mark.security
async def test_reading_as_one_agent_does_not_authorize_reacting_as_the_other(
    messaging: MessagingWorld,
) -> None:
    w = messaging
    w.access.side_effect = [True, False]
    with pytest.raises(AuthorizationError, match="not one you may run"):
        await w.service.react(
            w.ctx,
            message_id=w.message.id,
            data=AgentMessageReactionCreate(emoji="👍", as_agent_id=w.recipient.id),
        )
    w.messages.get_reaction.assert_not_awaited()
    w.messages.add_reaction.assert_not_awaited()
    w.messages.remove_reaction.assert_not_awaited()


@pytest.mark.parametrize("as_agent", [False, True])
async def test_new_reactions_record_exactly_the_person_or_the_authorized_agent(
    messaging: MessagingWorld,
    as_agent: bool,
) -> None:
    w = messaging
    agent_id = w.sender.id if as_agent else None
    user_id = None if as_agent else w.ctx.subject_id
    w.messages.list_reactions.return_value = [
        AgentMessageReaction(
            id=uuid.uuid4(),
            message_id=w.message.id,
            organization_id=w.ctx.organization_id,
            emoji="👍",
            reactor_agent_id=agent_id,
            reactor_user_id=user_id,
            created_at=NOW,
        )
    ]
    result = await w.service.react(
        w.ctx,
        message_id=w.message.id,
        thread_id=w.thread.id,
        data=AgentMessageReactionCreate(emoji=" 👍 ", as_agent_id=agent_id),
    )
    assert result.reacted is True
    assert len(result.reactions) == 1
    assert result.reactions[0].emoji == "👍"
    assert result.reactions[0].reactor_agent_id == agent_id
    assert result.reactions[0].reactor_user_id == user_id
    assert result.reactions[0].reactor_agent_slug == ("writer" if as_agent else None)
    w.messages.get_reaction.assert_awaited_once_with(
        w.service.db,
        message_id=w.message.id,
        emoji="👍",
        reactor_agent_id=agent_id,
        reactor_user_id=user_id,
    )
    w.messages.add_reaction.assert_awaited_once_with(
        w.service.db,
        message=w.message,
        organization_id=w.ctx.organization_id,
        emoji="👍",
        reactor_agent_id=agent_id,
        reactor_user_id=user_id,
    )
    w.messages.remove_reaction.assert_not_awaited()


@pytest.mark.security
async def test_a_deleted_message_cannot_be_reacted_to(messaging: MessagingWorld) -> None:
    w = messaging
    w.messages.get_message.return_value = None
    with pytest.raises(NotFoundError, match="Message not found"):
        await w.service.react(
            w.ctx, message_id=w.message.id, data=AgentMessageReactionCreate(emoji="👍")
        )
    w.messages.get_thread.assert_not_awaited()
    w.messages.add_reaction.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("thread_id_given", [False, True])
async def test_an_attachment_is_returned_only_after_thread_access_and_link_validation(
    messaging: MessagingWorld,
    thread_id_given: bool,
) -> None:
    w = messaging
    stored = _uploaded_file(w.ctx.subject_id, "report.txt")
    w.messages.get_attachment.return_value = MagicMock(chat_file_id=stored.id)
    w.files.get_by_id.return_value = stored
    result = await w.service.download_attachment(
        w.ctx,
        message_id=w.message.id,
        chat_file_id=stored.id,
        thread_id=w.thread.id if thread_id_given else None,
    )
    assert result is stored
    w.messages.get_attachment.assert_awaited_once_with(
        w.service.db, message_id=w.message.id, chat_file_id=stored.id
    )
    w.files.get_by_id.assert_awaited_once_with(w.service.db, stored.id)


@pytest.mark.security
@pytest.mark.parametrize(
    "refusal", ["wrong-thread", "foreign-thread", "no-permission", "unlinked", "deleted-file"]
)
async def test_attachment_refusals_do_not_leak_unlinked_or_unreadable_files(
    messaging: MessagingWorld,
    refusal: str,
) -> None:
    w = messaging
    stored = _uploaded_file(w.ctx.subject_id, "private.txt")
    thread_id = w.thread.id
    w.messages.get_attachment.return_value = MagicMock(chat_file_id=stored.id)
    w.files.get_by_id.return_value = stored
    expected: type[Exception] = NotFoundError
    if refusal == "wrong-thread":
        thread_id = uuid.uuid4()
    elif refusal == "foreign-thread":
        w.thread.organization_id = uuid.uuid4()
    elif refusal == "no-permission":
        w.access.return_value = False
        expected = AuthorizationError
    elif refusal == "unlinked":
        w.messages.get_attachment.return_value = None
    else:
        w.files.get_by_id.return_value = None
    with pytest.raises(expected):
        await w.service.download_attachment(
            w.ctx, message_id=w.message.id, chat_file_id=stored.id, thread_id=thread_id
        )
    if refusal != "deleted-file":
        w.files.get_by_id.assert_not_awaited()
    if refusal in {"wrong-thread", "foreign-thread", "no-permission"}:
        w.messages.get_attachment.assert_not_awaited()
