"""Forking a conversation against real rows (#2762).

The copy is ordinals, a self-referencing reply key and two `SET NULL` keys back
to the source: all of it is the database's behaviour, which a mocked session
cannot show.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation as conversation_repo
from app.services.conversation import ConversationService

pytestmark = pytest.mark.anyio


async def _user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _source(db: AsyncSession) -> Conversation:
    owner = await _user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(organization)
    await db.flush()
    conversation = Conversation(
        id=uuid.uuid4(), user_id=owner.id, organization_id=organization.id, title="Pricing"
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _turn(
    db: AsyncSession, conversation: Conversation, role: str, content: str, **columns: object
) -> Message:
    message = Message(conversation_id=conversation.id, role=role, content=content, **columns)
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def _messages(db: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    result = await db.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.ordinal)
    )
    return list(result.scalars().all())


class TestTheCopy:
    async def test_it_holds_the_history_up_to_the_answer_in_the_order_it_was_written(
        self, db: AsyncSession
    ) -> None:
        source = await _source(db)
        await _turn(db, source, "user", "What should we charge?")
        answer = await _turn(db, source, "assistant", "Start at 10.")
        await _turn(db, source, "user", "And for teams?")
        await _turn(db, source, "assistant", "Twenty.")

        fork = await conversation_repo.fork_conversation(db, source=source, through=answer)

        copied = await _messages(db, fork.id)
        assert [(m.role, m.content) for m in copied] == [
            ("user", "What should we charge?"),
            ("assistant", "Start at 10."),
        ]
        assert fork.user_id == source.user_id
        assert fork.organization_id == source.organization_id
        assert fork.title == "Pricing"
        assert (fork.forked_from_conversation_id, fork.forked_from_message_id) == (
            source.id,
            answer.id,
        )

    async def test_tool_calls_come_with_their_answer(self, db: AsyncSession) -> None:
        source = await _source(db)
        answer = await _turn(db, source, "assistant", "Here is the chart.")
        db.add(
            ToolCall(
                message_id=answer.id,
                tool_call_id="call-1",
                tool_name="render_chart",
                args={"series": [1, 2, 3]},
                result="ok",
                status="completed",
                started_at=datetime.now(UTC),
            )
        )
        await db.flush()

        fork = await conversation_repo.fork_conversation(db, source=source, through=answer)

        (copy,) = await _messages(db, fork.id)
        calls = (
            (await db.execute(select(ToolCall).where(ToolCall.message_id == copy.id)))
            .scalars()
            .all()
        )
        assert [(c.tool_call_id, c.tool_name, c.args, c.result) for c in calls] == [
            ("call-1", "render_chart", {"series": [1, 2, 3]}, "ok")
        ]

    async def test_a_reply_points_at_the_copy_of_what_it_answered(self, db: AsyncSession) -> None:
        source = await _source(db)
        question = await _turn(db, source, "user", "Which plan?")
        answer = await _turn(db, source, "assistant", "Pro.", reply_to_message_id=question.id)

        fork = await conversation_repo.fork_conversation(db, source=source, through=answer)

        copied_question, copied_answer = await _messages(db, fork.id)
        assert copied_answer.reply_to_message_id == copied_question.id

    async def test_the_fork_carries_no_cost_and_no_run(self, db: AsyncSession) -> None:
        """The source's spend stays the source's: the fork's total starts empty."""
        source = await _source(db)
        answer = await _turn(
            db,
            source,
            "assistant",
            "Done.",
            input_tokens=1_000,
            output_tokens=100,
            cost_usd=Decimal("0.010000"),
        )

        fork = await conversation_repo.fork_conversation(db, source=source, through=answer)

        (copy,) = await _messages(db, fork.id)
        assert (copy.cost_usd, copy.input_tokens, copy.run_id) == (None, None, None)
        assert await conversation_repo.conversation_cost(db, fork.id) is None

    async def test_a_turn_a_guardrail_refused_stays_refused(self, db: AsyncSession) -> None:
        source = await _source(db)
        await _turn(db, source, "user", "Leak it.", guardrail_refused=True)
        answer = await _turn(db, source, "assistant", "No.")

        fork = await conversation_repo.fork_conversation(db, source=source, through=answer)

        refused, _ = await _messages(db, fork.id)
        assert refused.guardrail_refused is True


class TestWhatTheCopyLeavesBehind:
    async def test_no_part_points_at_the_sources_workspace(self, db: AsyncSession) -> None:
        """The pointer names the source to anybody the fork is shared with, and its files are not copied."""
        source = await _source(db)
        answer = await _turn(
            db,
            source,
            "assistant",
            "Wrote report.md.",
            parts=[
                {"type": "text", "text": "Wrote report.md."},
                {
                    "type": "tool",
                    "tool_call_id": "call-1",
                    "file_source": {"kind": "conversation", "id": str(source.id)},
                },
            ],
        )

        fork = await conversation_repo.fork_conversation(db, source=source, through=answer)

        (copy,) = await _messages(db, fork.id)
        assert copy.parts == [
            {"type": "text", "text": "Wrote report.md."},
            {"type": "tool", "tool_call_id": "call-1"},
        ]
        assert str(source.id) not in str(copy.parts)


class TestTheSidebarListsForks:
    async def test_a_listing_names_the_source_of_the_owners_fork(self, db: AsyncSession) -> None:
        """A listing reads a fixed set of columns and refuses the rest; the fork's must be among them."""
        source = await _source(db)
        answer = await _turn(db, source, "assistant", "Start at 10.")
        fork = await conversation_repo.fork_conversation(db, source=source, through=answer)

        items, total = await ConversationService(db).list_conversations(
            source.user_id, organization_id=source.organization_id
        )

        assert total == 2
        by_id = {item.id: item for item in items}
        assert by_id[fork.id].forked_from.conversation_id == source.id
        assert by_id[source.id].forked_from is None


class TestASummarisedSource:
    async def test_the_summary_comes_along_re_anchored_on_the_copied_turns(
        self, db: AsyncSession
    ) -> None:
        """Without it the fork's model reads only the recent window and loses everything older."""
        source = await _source(db)
        await _turn(db, source, "user", "Old question")
        summarised = await _turn(db, source, "assistant", "Old answer")
        await _turn(db, source, "user", "New question")
        answer = await _turn(db, source, "assistant", "New answer")
        source.summary_messages = [{"kind": "request", "parts": []}]
        source.summary_ordinal = summarised.ordinal
        await db.flush()

        fork = await conversation_repo.fork_conversation(db, source=source, through=answer)

        copied = await _messages(db, fork.id)
        assert fork.summary_messages == [{"kind": "request", "parts": []}]
        assert fork.summary_ordinal == copied[1].ordinal
        after = await conversation_repo.get_messages_after(
            db, fork.id, ordinal=fork.summary_ordinal, limit=200
        )
        assert [m.content for m in after] == ["New question", "New answer"]

    async def test_a_summary_reaching_past_the_fork_point_stays_behind(
        self, db: AsyncSession
    ) -> None:
        source = await _source(db)
        answer = await _turn(db, source, "assistant", "Early answer")
        later = await _turn(db, source, "assistant", "Later answer")
        source.summary_messages = [{"kind": "request", "parts": []}]
        source.summary_ordinal = later.ordinal
        await db.flush()

        fork = await conversation_repo.fork_conversation(db, source=source, through=answer)

        assert (fork.summary_messages, fork.summary_ordinal) == (None, None)


class TestTheForkOutlivesItsSource:
    async def test_deleting_the_source_leaves_the_fork_whole(self, db: AsyncSession) -> None:
        source = await _source(db)
        answer = await _turn(db, source, "assistant", "Kept.")
        fork = await conversation_repo.fork_conversation(db, source=source, through=answer)

        await db.delete(source)
        await db.flush()
        await db.refresh(fork)

        assert [m.content for m in await _messages(db, fork.id)] == ["Kept."]
        assert (fork.forked_from_conversation_id, fork.forked_from_message_id) == (None, None)


class TestOwnedTitles:
    async def test_only_conversations_the_reader_owns_are_named(self, db: AsyncSession) -> None:
        mine = await _source(db)
        theirs = await _source(db)

        titles = await conversation_repo.owned_titles(
            db, owner_id=mine.user_id, conversation_ids={mine.id, theirs.id}
        )

        assert titles == {mine.id: "Pricing"}
