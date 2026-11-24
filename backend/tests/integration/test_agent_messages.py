"""Agent messages on real rows: the pair is one thread, reactions toggle, and
one organization cannot read another's threads.

A mock cannot tell you whether the canonical-pair CHECK rejects a row, whether
deleting an agent takes its threads with it, or whether the partial unique
index actually prevents a second identical reaction. Those are the guarantees
the schema is supposed to provide, and the only way to know is to ask Postgres.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_message import AgentMessage, AgentMessageThread
from app.db.models.chat_file import ChatFile
from app.repositories import agent_message_repo
from app.schemas.agent_message import AgentMessageReactionCreate, AgentMessageSend
from app.services.agent_messages import AgentMessageService
from tests.integration.virtual_table_support import make_org, make_user

pytestmark = pytest.mark.anyio


async def _agent(db: AsyncSession, org_id: uuid.UUID, *, slug: str) -> Agent:
    agent = Agent(
        organization_id=org_id,
        slug=slug,
        name=slug.replace("-", " ").title(),
        status="published",
    )
    db.add(agent)
    await db.flush()
    return agent


class TestThreads:
    async def test_the_pair_shares_one_thread_whichever_way_it_is_addressed(
        self, db: AsyncSession
    ) -> None:
        owner = await make_user(db)
        org = await make_org(db, owner=owner)
        first = await _agent(db, org.id, slug="researcher")
        second = await _agent(db, org.id, slug="summariser")
        ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
        service = AgentMessageService(db)

        sent = await service.send(
            ctx,
            AgentMessageSend(sender_agent_id=first.id, recipient=second.slug, body="hello"),
        )
        back = await service.send(
            ctx,
            AgentMessageSend(sender_agent_id=second.id, recipient=first.slug, body="hello back"),
        )

        assert sent.thread_id == back.thread_id
        threads = await agent_message_repo.list_threads(db, organization_id=org.id, agent_ids=None)
        assert len(threads[0]) == 1

    async def test_a_thread_in_another_organization_reads_as_absent(self, db: AsyncSession) -> None:
        owner = await make_user(db)
        org = await make_org(db, owner=owner)
        first = await _agent(db, org.id, slug="researcher")
        second = await _agent(db, org.id, slug="summariser")
        ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
        service = AgentMessageService(db)
        sent = await service.send(
            ctx,
            AgentMessageSend(sender_agent_id=first.id, recipient=second.slug, body="hello"),
        )

        stranger = await make_user(db)
        other_org = await make_org(db, owner=stranger)
        foreign = AuthContext(
            user_id=stranger.id,
            organization_id=other_org.id,
            role=OrgRoleName.OWNER,
        )

        with pytest.raises(NotFoundError):
            await service.get_thread(foreign, sent.thread_id)

    async def test_deleting_an_agent_takes_its_threads_with_it(self, db: AsyncSession) -> None:
        owner = await make_user(db)
        org = await make_org(db, owner=owner)
        first = await _agent(db, org.id, slug="researcher")
        second = await _agent(db, org.id, slug="summariser")
        ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
        service = AgentMessageService(db)
        sent = await service.send(
            ctx,
            AgentMessageSend(sender_agent_id=first.id, recipient=second.slug, body="hello"),
        )

        await db.delete(first)
        await db.flush()

        assert await agent_message_repo.get_thread(db, sent.thread_id) is None


class TestReactions:
    async def test_the_same_emoji_twice_is_one_reaction_then_none(self, db: AsyncSession) -> None:
        owner = await make_user(db)
        org = await make_org(db, owner=owner)
        first = await _agent(db, org.id, slug="researcher")
        second = await _agent(db, org.id, slug="summariser")
        ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
        service = AgentMessageService(db)
        sent = await service.send(
            ctx,
            AgentMessageSend(sender_agent_id=first.id, recipient=second.slug, body="hello"),
        )

        added = await service.react(
            ctx,
            message_id=sent.id,
            data=AgentMessageReactionCreate(emoji="👍"),
        )
        assert added.reacted is True
        assert len(added.reactions) == 1

        taken_back = await service.react(
            ctx,
            message_id=sent.id,
            data=AgentMessageReactionCreate(emoji="👍"),
        )
        assert taken_back.reacted is False
        assert taken_back.reactions == []
        assert await agent_message_repo.list_reactions(db, message_ids=[sent.id]) == []


async def _repository_pair(
    db: AsyncSession,
) -> tuple[uuid.UUID, uuid.UUID, Agent, Agent, AgentMessageThread]:
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    first = await _agent(db, org.id, slug="sender")
    second = await _agent(db, org.id, slug="recipient")
    thread = await agent_message_repo.create_thread(
        db, organization_id=org.id, agent_a_id=first.id, agent_b_id=second.id
    )
    return org.id, owner.id, first, second, thread


async def _write_message(
    db: AsyncSession,
    thread: AgentMessageThread,
    sender: Agent,
    user_id: uuid.UUID,
    *,
    body: str = "private message body",
    reply_to: uuid.UUID | None = None,
) -> AgentMessage:
    return await agent_message_repo.create_message(
        db,
        thread=thread,
        organization_id=thread.organization_id,
        sender_agent_id=sender.id,
        sender_user_id=user_id,
        body=body,
        reply_to_message_id=reply_to,
    )


class TestRepositoryReads:
    @pytest.mark.security
    async def test_filtered_thread_pages_keep_the_tenant_and_total_count(
        self, db: AsyncSession
    ) -> None:
        org_id, _, first, second, active = await _repository_pair(db)
        third = await _agent(db, org_id, slug="third")
        empty = await agent_message_repo.create_thread(
            db, organization_id=org_id, agent_a_id=first.id, agent_b_id=third.id
        )
        await _repository_pair(db)
        await agent_message_repo.touch_thread(
            db, thread=active, at=datetime(2026, 11, 14, 8, tzinfo=UTC)
        )

        page, total = await agent_message_repo.list_threads(
            db, organization_id=org_id, agent_ids=None, skip=1, limit=1
        )
        assert [item.id for item in page] == [empty.id]
        assert total == 2
        page, total = await agent_message_repo.list_threads(
            db, organization_id=org_id, agent_ids={second.id}
        )
        assert [item.id for item in page] == [active.id]
        assert total == 1
        assert await agent_message_repo.list_threads(
            db, organization_id=org_id, agent_ids=set()
        ) == ([], 0)

    async def test_message_pages_and_previews_use_the_same_deterministic_tie_break(
        self, db: AsyncSession
    ) -> None:
        org_id, owner_id, first, second, thread = await _repository_pair(db)
        first_message = await _write_message(db, thread, first, owner_id, body="first")
        second_message = await _write_message(
            db, thread, second, owner_id, body="reply", reply_to=first_message.id
        )
        same_time = datetime(2026, 11, 14, 8, tzinfo=UTC)
        first_message.created_at = second_message.created_at = same_time
        third = await _agent(db, org_id, slug="third")
        other_thread = await agent_message_repo.create_thread(
            db, organization_id=org_id, agent_a_id=first.id, agent_b_id=third.id
        )
        other_message = await _write_message(db, other_thread, first, owner_id, body="other")
        empty_thread = await agent_message_repo.create_thread(
            db, organization_id=org_id, agent_a_id=second.id, agent_b_id=third.id
        )
        await db.flush()

        expected = sorted([first_message, second_message], key=lambda item: item.id)
        page, total = await agent_message_repo.list_messages(
            db, thread_id=thread.id, skip=1, limit=1
        )
        assert [item.id for item in page] == [expected[1].id]
        assert total == 2
        assert second_message.reply_to_message_id == first_message.id
        assert await agent_message_repo.list_messages(db, thread_id=empty_thread.id) == ([], 0)
        previews = await agent_message_repo.latest_messages(
            db, thread_ids=[thread.id, other_thread.id, empty_thread.id]
        )
        assert {key: value.id for key, value in previews.items()} == {
            thread.id: expected[1].id,
            other_thread.id: other_message.id,
        }

    async def test_an_agents_reaction_and_a_readers_reaction_remain_distinct(
        self, db: AsyncSession
    ) -> None:
        org_id, owner_id, first, _, thread = await _repository_pair(db)
        message = await _write_message(db, thread, first, owner_id)
        agent_reaction = await agent_message_repo.add_reaction(
            db, message=message, organization_id=org_id, emoji="ok", reactor_agent_id=first.id
        )
        person_reaction = await agent_message_repo.add_reaction(
            db, message=message, organization_id=org_id, emoji="ok", reactor_user_id=owner_id
        )

        assert (
            await agent_message_repo.get_reaction(
                db, message_id=message.id, emoji="ok", reactor_agent_id=first.id
            )
            is agent_reaction
        )
        assert (
            await agent_message_repo.get_reaction(
                db, message_id=message.id, emoji="ok", reactor_user_id=owner_id
            )
            is person_reaction
        )
        await agent_message_repo.remove_reaction(db, reaction=agent_reaction)
        remaining = await agent_message_repo.list_reactions(db, message_ids=[message.id])
        assert [item.id for item in remaining] == [person_reaction.id]

    async def test_attachment_lookups_are_exact_and_file_deletion_removes_the_link(
        self, db: AsyncSession
    ) -> None:
        org_id, owner_id, first, _, thread = await _repository_pair(db)
        message = await _write_message(db, thread, first, owner_id)
        another_message = await _write_message(db, thread, first, owner_id)
        file = ChatFile(
            user_id=owner_id,
            filename="private-report.txt",
            mime_type="text/plain",
            size=12,
            storage_path="private/storage/report",
            file_type="text",
        )
        unrelated = ChatFile(
            user_id=owner_id,
            filename="not-attached.txt",
            mime_type="text/plain",
            size=9,
            storage_path="private/storage/unattached",
            file_type="text",
        )
        db.add_all([file, unrelated])
        await db.flush()
        attachment = await agent_message_repo.add_attachment(
            db, message=message, organization_id=org_id, chat_file_id=file.id
        )

        assert (
            await agent_message_repo.get_attachment(db, message_id=message.id, chat_file_id=file.id)
            is attachment
        )
        assert (
            await agent_message_repo.get_attachment(
                db, message_id=another_message.id, chat_file_id=file.id
            )
            is None
        )
        assert [
            item.id
            for item in await agent_message_repo.list_attachments(db, message_ids=[message.id])
        ] == [attachment.id]
        assert [
            item.id for item in await agent_message_repo.list_chat_files(db, file_ids=[file.id])
        ] == [file.id]

        await db.delete(file)
        await db.flush()
        assert await agent_message_repo.list_attachments(db, message_ids=[message.id]) == []

    async def test_delayed_reads_do_not_move_a_readers_watermark_backwards(
        self, db: AsyncSession
    ) -> None:
        _, owner_id, _, _, thread = await _repository_pair(db)
        other_reader = await make_user(db)
        first_time = datetime(2026, 11, 14, 8, tzinfo=UTC)
        latest_time = first_time + timedelta(minutes=5)
        await agent_message_repo.mark_read(
            db, thread_id=thread.id, user_id=owner_id, read_at=first_time
        )
        await agent_message_repo.mark_read(
            db, thread_id=thread.id, user_id=owner_id, read_at=latest_time
        )
        await agent_message_repo.mark_read(
            db, thread_id=thread.id, user_id=other_reader.id, read_at=first_time
        )
        delayed = await agent_message_repo.mark_read(
            db, thread_id=thread.id, user_id=owner_id, read_at=first_time
        )

        assert delayed.read_at == latest_time
        mine = await agent_message_repo.get_reads(db, thread_ids=[thread.id], user_id=owner_id)
        theirs = await agent_message_repo.get_reads(
            db, thread_ids=[thread.id], user_id=other_reader.id
        )
        assert list(mine) == list(theirs) == [thread.id]
        assert mine[thread.id].read_at == latest_time
        assert theirs[thread.id].read_at == first_time

    async def test_empty_lookup_sets_do_not_expand_to_existing_messages_or_files(
        self, db: AsyncSession
    ) -> None:
        _, owner_id, first, _, thread = await _repository_pair(db)
        await _write_message(db, thread, first, owner_id)

        assert await agent_message_repo.latest_messages(db, thread_ids=[]) == {}
        assert await agent_message_repo.list_reactions(db, message_ids=[]) == []
        assert await agent_message_repo.list_attachments(db, message_ids=[]) == []
        assert await agent_message_repo.list_chat_files(db, file_ids=[]) == []
        assert await agent_message_repo.get_reads(db, thread_ids=[], user_id=owner_id) == {}

    @pytest.mark.security
    async def test_message_debug_representations_identify_rows_without_private_content(
        self, db: AsyncSession
    ) -> None:
        org_id, owner_id, first, _, thread = await _repository_pair(db)
        message = await _write_message(db, thread, first, owner_id)
        reaction = await agent_message_repo.add_reaction(
            db, message=message, organization_id=org_id, emoji="ok", reactor_agent_id=first.id
        )
        file = ChatFile(
            user_id=owner_id,
            filename="private-report.txt",
            mime_type="text/plain",
            size=12,
            storage_path="private/storage/report",
            file_type="text",
        )
        db.add(file)
        await db.flush()
        attachment = await agent_message_repo.add_attachment(
            db, message=message, organization_id=org_id, chat_file_id=file.id
        )
        read = await agent_message_repo.mark_read(
            db, thread_id=thread.id, user_id=owner_id, read_at=datetime.now(UTC)
        )

        representations = [repr(row) for row in (thread, message, reaction, attachment, read)]
        expected_names = [
            "AgentMessageThread",
            "AgentMessage",
            "AgentMessageReaction",
            "AgentMessageAttachment",
            "AgentMessageRead",
        ]
        assert all(name in value for name, value in zip(expected_names, representations))
        assert str(org_id) in representations[0]
        assert str(message.id) in representations[2]
        combined = "\n".join(representations)
        assert message.body not in combined
        assert file.filename not in combined
        assert file.storage_path not in combined
