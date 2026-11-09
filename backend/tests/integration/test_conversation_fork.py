"""Forking a conversation against real rows (#2762).

The copy is ordinals, a self-referencing reply key and two `SET NULL` keys back
to the source: all of it is the database's behaviour, which a mocked session
cannot show.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError, InvalidRequestError
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


@pytest.mark.parametrize("limit", ["messages", "tool_calls", "bytes"])
async def test_an_oversized_fork_is_refused_before_any_copy_is_inserted(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    from app.core.exceptions import BadRequestError
    from app.core.permissions import AuthContext
    from app.services import conversation as service_module

    source = await _source(db)
    assert source.user_id is not None
    assert source.organization_id is not None
    await _turn(db, source, "user", "A long question with preserved context")
    answer = await _turn(db, source, "assistant", "An answer with context")
    for index in range(2):
        db.add(
            ToolCall(
                message_id=answer.id,
                tool_call_id=f"call-{index}",
                tool_name="search",
                args={"query": "context"},
                result="result",
                status="completed",
                started_at=datetime.now(UTC),
            )
        )
    await db.flush()
    constant = {
        "messages": "MAX_FORK_MESSAGES",
        "tool_calls": "MAX_FORK_TOOL_CALLS",
        "bytes": "MAX_FORK_BYTES",
    }[limit]
    monkeypatch.setattr(service_module, constant, 1, raising=False)
    ctx = AuthContext(user_id=source.user_id, organization_id=source.organization_id, role="owner")
    with pytest.raises(BadRequestError, match="too large to fork"):
        await ConversationService(db).fork(
            source.id,
            message_id=answer.id,
            organization_id=source.organization_id,
            user_id=source.user_id,
            ctx=ctx,
        )
    assert list((await db.scalars(select(Conversation.id))).all()) == [source.id]


async def test_copied_tools_keep_their_stable_identity_and_presentation(db: AsyncSession) -> None:
    source = await _source(db)
    answer = await _turn(db, source, "assistant", "A prepared reply")
    db.add(
        ToolCall(
            message_id=answer.id,
            tool_call_id="reply-1",
            tool_name="prepare_reply",
            tool_id="draft",
            presentation_kind="draft",
            args={"subject": "A quote"},
            result="Prepared",
            status="completed",
            started_at=datetime.now(UTC),
        )
    )
    await db.flush()
    fork = await conversation_repo.fork_conversation(db, source=source, through=answer)
    copied = (
        await db.scalars(select(ToolCall).join(Message).where(Message.conversation_id == fork.id))
    ).one()
    assert copied.tool_id == "draft"
    assert copied.presentation_kind == "draft"


@pytest.mark.parametrize(
    "field",
    ["content", "thinking", "attachment_context", "parts", "tool_args", "tool_result", "summary"],
)
async def test_the_byte_quota_covers_every_copied_payload(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    from app.core.exceptions import BadRequestError
    from app.core.permissions import AuthContext
    from app.services import conversation as service_module

    source = await _source(db)
    assert source.user_id is not None and source.organization_id is not None
    payload = "ż" * 100
    columns = {field: payload} if field in {"thinking", "attachment_context"} else {}
    if field == "parts":
        columns = {"parts": [{"type": "text", "text": payload}]}
    answer = await _turn(
        db, source, "assistant", payload if field == "content" else "OK", **columns
    )
    if field in {"tool_args", "tool_result"}:
        db.add(
            ToolCall(
                message_id=answer.id,
                tool_call_id="big",
                tool_name="search",
                args={"query": payload} if field == "tool_args" else {},
                result=payload if field == "tool_result" else "OK",
                status="completed",
                started_at=datetime.now(UTC),
            )
        )
    if field == "summary":
        source.summary_messages = [
            {"kind": "request", "parts": [{"part_kind": "user-prompt", "content": payload}]}
        ]
        source.summary_ordinal = answer.ordinal
    await db.flush()
    monkeypatch.setattr(service_module, "MAX_FORK_BYTES", 64)
    with pytest.raises(BadRequestError, match="too large to fork"):
        await ConversationService(db).fork(
            source.id,
            message_id=answer.id,
            organization_id=source.organization_id,
            user_id=source.user_id,
            ctx=AuthContext(
                user_id=source.user_id, organization_id=source.organization_id, role="owner"
            ),
        )
    assert len((await db.scalars(select(Conversation.id))).all()) == 1
    assert await db.scalar(text("SHOW lock_timeout")) == "0"


@pytest.mark.parametrize("target", ["message", "tool_call", "new_message", "new_call", "summary"])
async def test_copy_locks_fence_concurrent_payload_changes(db: AsyncSession, target: str) -> None:
    source = await _source(db)
    answer = await _turn(db, source, "assistant", "The original answer")
    call = ToolCall(
        message_id=answer.id,
        tool_call_id="original",
        tool_name="search",
        args={},
        result="The original result",
        status="completed",
        started_at=datetime.now(UTC),
    )
    db.add(call)
    await db.commit()
    counts = await conversation_repo.lock_fork_history(
        db, source=source, through=answer, message_limit=10, tool_call_limit=10
    )
    assert counts == conversation_repo.ForkRowCounts(1, 1)
    if target == "message":
        statement = update(Message).where(Message.id == answer.id).values(content="Changed")
    elif target == "tool_call":
        statement = update(ToolCall).where(ToolCall.id == call.id).values(result="Changed")
    elif target == "new_message":
        statement = insert(Message).values(
            conversation_id=source.id, role="assistant", content="Late"
        )
    elif target == "new_call":
        statement = insert(ToolCall).values(
            message_id=answer.id,
            tool_call_id="late",
            tool_name="search",
            args={},
            result="Late",
            status="completed",
            started_at=datetime.now(UTC),
        )
    else:
        statement = (
            update(Conversation).where(Conversation.id == source.id).values(summary_messages=[])
        )
    assert db.bind is not None
    async with AsyncSession(bind=db.bind, expire_on_commit=False) as other:
        await other.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(DBAPIError) as failed:
            await other.execute(statement)
        assert getattr(failed.value.orig, "sqlstate", None) == "55P03"
        await other.rollback()
        fork = await conversation_repo.fork_conversation(db, source=source, through=answer)
        await db.commit()
        await other.execute(statement)
        await other.commit()
    assert (
        await db.scalar(select(Message.content).where(Message.conversation_id == fork.id))
        == "The original answer"
    )


async def test_busy_history_is_a_retryable_conflict_without_partial_copies(
    db: AsyncSession,
) -> None:
    from app.core.exceptions import ConcurrentChangeError
    from app.core.permissions import AuthContext

    source = await _source(db)
    answer = await _turn(db, source, "assistant", "An answer")
    assert source.user_id is not None and source.organization_id is not None and db.bind is not None
    source_id, answer_id, owner_id, org_id = (
        source.id,
        answer.id,
        source.user_id,
        source.organization_id,
    )
    await db.commit()
    ctx = AuthContext(user_id=owner_id, organization_id=org_id, role="owner")
    async with AsyncSession(bind=db.bind) as other:
        await other.execute(
            update(Message).where(Message.id == answer_id).values(content="Being written")
        )
        with pytest.raises(ConcurrentChangeError):
            await ConversationService(db).fork(
                source_id, message_id=answer_id, organization_id=org_id, user_id=owner_id, ctx=ctx
            )
        assert len((await db.scalars(select(Conversation.id))).all()) == 1
        assert await db.scalar(text("SHOW lock_timeout")) == "0"
        await other.rollback()
    fork = await ConversationService(db).fork(
        source_id, message_id=answer_id, organization_id=org_id, user_id=owner_id, ctx=ctx
    )
    assert fork.forked_from_conversation_id == source_id
    assert len((await db.scalars(select(Conversation.id))).all()) == 2


async def test_the_fork_point_does_not_materialize_transcript_payloads(db: AsyncSession) -> None:
    source = await _source(db)
    answer = await _turn(
        db, source, "assistant", "A large answer", parts=[{"type": "text", "text": "large"}]
    )
    answer_id = answer.id
    db.expunge_all()
    point = await conversation_repo.get_fork_point(db, answer_id)
    assert point is not None and point.id == answer_id
    for field in ("content", "thinking", "parts", "tool_calls"):
        with pytest.raises(InvalidRequestError):
            getattr(point, field)
