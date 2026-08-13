"""The order a conversation's turns come back in, against real rows.

This is the one defect a mocked session cannot show, because the bug *is*
Postgres: `created_at` defaults to `func.now()`, which is the transaction's start
time, and one turn writes the question and the answer inside a single transaction.
Both rows therefore carried the same timestamp to the microsecond, `ORDER BY
created_at` had nothing to break the tie with, and the answer came back above the
question whenever the planner preferred it - which is why it read as intermittent.

So what is pinned here is the two halves of the fix. The timestamps really are
equal (otherwise this test would pass for the wrong reason on a schema that never
had `ordinal`), and the rows still come back in the order they were written.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation as conversation_repo
from app.services.transcript import TranscriptService

pytestmark = pytest.mark.anyio


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _conversation(db) -> Conversation:
    founder = await _user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=founder.id,
        organization_id=organization.id,
        title="Quarterly numbers",
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _run(db, conversation: Conversation) -> AgentRun:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=conversation.organization_id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=conversation.organization_id,
        agent_id=agent.id,
        user_id=conversation.user_id,
        conversation_id=conversation.id,
        surface=RunSurface.EMBED.value,
        status=RunStatus.COMPLETED.value,
    )
    db.add(run)
    await db.flush()
    return run


class TestATurnComesBackInTheOrderItWasWritten:
    async def test_the_question_precedes_the_answer_it_got(self, db) -> None:
        """The whole defect, end to end: one `record` call writes both rows."""
        conversation = await _conversation(db)
        run = await _run(db, conversation)

        await TranscriptService(db).record(
            run, prompt="co tu widzisz", answer="A screenshot of a dashboard."
        )

        written = await conversation_repo.get_messages_by_conversation(db, conversation.id)
        assert [(message.role, message.content) for message in written] == [
            ("user", "co tu widzisz"),
            ("assistant", "A screenshot of a dashboard."),
        ]

    async def test_both_rows_of_one_turn_carry_the_same_timestamp(self, db) -> None:
        """Why `created_at` could not be the ordering key.

        Without this the test above would pass on the old schema too, on any
        machine whose planner happened to return the rows in insertion order.
        """
        conversation = await _conversation(db)
        run = await _run(db, conversation)

        await TranscriptService(db).record(run, prompt="ask", answer="answer")

        rows = (
            (
                await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation.id)
                    .order_by(Message.ordinal)
                )
            )
            .scalars()
            .all()
        )
        assert rows[0].created_at == rows[1].created_at
        assert rows[0].ordinal < rows[1].ordinal

    async def test_the_ordinal_is_allocated_by_the_database(self, db) -> None:
        """Nobody passes one, and two writers cannot be handed the same value.

        The identity column is what makes that true; a `MAX(ordinal) + 1` read in
        the repository would not be, and the failure would be a lost transcript
        rather than a visible error - the write runs inside a savepoint that
        swallows it.
        """
        conversation = await _conversation(db)

        first = await conversation_repo.create_message(
            db, conversation_id=conversation.id, role="user", content="one"
        )
        second = await conversation_repo.create_message(
            db, conversation_id=conversation.id, role="user", content="two"
        )

        assert first.ordinal is not None
        # Strictly greater, not exactly +1: the design disclaims contiguity - a
        # gap costs nothing and only the order is read - so a concurrent insert or
        # a sequence-cache change must not fail this for a property nobody promised.
        assert second.ordinal > first.ordinal

    async def test_a_window_over_a_long_thread_is_the_most_recent_turns(self, db) -> None:
        """What the hosted page and the widget read history with.

        `skip` + `limit` is only a *window* if the ordering is total; with ties it
        is a sample. Forty turns of ten characters each is cheaper to write than to
        argue about.
        """
        conversation = await _conversation(db)
        for index in range(10):
            await conversation_repo.create_message(
                db, conversation_id=conversation.id, role="user", content=f"turn-{index}"
            )

        window = await conversation_repo.get_messages_by_conversation(
            db, conversation.id, skip=7, limit=3
        )
        assert [message.content for message in window] == ["turn-7", "turn-8", "turn-9"]
