"""What a whole conversation has cost, added up against real rows.

A mocked session cannot show any of this: the aggregate *is* the behaviour. Three
things it has to get right, and each is wrong in a way that renders as a
confident number rather than as an error.

`bool_or` over a nullable column - one unpriced turn makes the whole total a
floor, and a thread whose every row predates the column has no answer at all
rather than "exact". `COUNT` over a nullable column - a conversation nobody
measured must answer nothing, because `$0.0000` is a claim. And the sum ignoring
nulls, so one unmeasured turn among ten does not zero the other nine.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation as conversation_repo

pytestmark = pytest.mark.anyio


async def _conversation(db) -> Conversation:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(founder)
    await db.flush()
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


async def _turn(
    db,
    conversation: Conversation,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: str | None = None,
    cost_is_partial: bool | None = None,
) -> None:
    db.add(
        Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            role="assistant",
            content="…",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=None if cost_usd is None else Decimal(cost_usd),
            cost_is_partial=cost_is_partial,
        )
    )
    await db.flush()


class TestWhatTheThreadCost:
    async def test_it_adds_up_every_turn_that_was_measured(self, db) -> None:
        conversation = await _conversation(db)
        await _turn(db, conversation, input_tokens=1_000, output_tokens=100, cost_usd="0.010000")
        await _turn(db, conversation, input_tokens=2_000, output_tokens=200, cost_usd="0.020000")

        totals = await conversation_repo.conversation_cost(db, conversation.id)

        assert totals == (3_000, 300, Decimal("0.030000"), None)

    async def test_an_unmeasured_turn_does_not_zero_the_measured_ones(self, db) -> None:
        """A turn that failed before a cost was read is null, not zero."""
        conversation = await _conversation(db)
        await _turn(db, conversation, input_tokens=1_000, output_tokens=100, cost_usd="0.010000")
        await _turn(db, conversation)

        totals = await conversation_repo.conversation_cost(db, conversation.id)

        assert totals is not None
        assert totals[:3] == (1_000, 100, Decimal("0.010000"))

    async def test_a_thread_nobody_measured_answers_nothing_rather_than_zero(self, db) -> None:
        """`$0.0000` under a conversation that spent money is worse than silence."""
        conversation = await _conversation(db)
        await _turn(db, conversation)

        assert await conversation_repo.conversation_cost(db, conversation.id) is None

    async def test_one_unpriced_turn_makes_the_whole_total_a_floor(self, db) -> None:
        conversation = await _conversation(db)
        await _turn(
            db,
            conversation,
            input_tokens=1_000,
            output_tokens=100,
            cost_usd="0.010000",
            cost_is_partial=False,
        )
        await _turn(
            db,
            conversation,
            input_tokens=2_000,
            output_tokens=200,
            cost_usd="0.000000",
            cost_is_partial=True,
        )

        totals = await conversation_repo.conversation_cost(db, conversation.id)

        assert totals is not None
        assert totals[3] is True

    async def test_a_thread_that_recorded_the_flag_nowhere_says_nobody_knows(self, db) -> None:
        """Not `false`. Every message written before the column has no answer, and
        claiming they were priced exactly is the same lie one turn further out."""
        conversation = await _conversation(db)
        await _turn(db, conversation, input_tokens=1_000, output_tokens=100, cost_usd="0.010000")

        totals = await conversation_repo.conversation_cost(db, conversation.id)

        assert totals is not None
        assert totals[3] is None

    async def test_every_turn_priced_exactly_says_so(self, db) -> None:
        conversation = await _conversation(db)
        await _turn(
            db,
            conversation,
            input_tokens=1_000,
            output_tokens=100,
            cost_usd="0.010000",
            cost_is_partial=False,
        )

        totals = await conversation_repo.conversation_cost(db, conversation.id)

        assert totals is not None
        assert totals[3] is False

    async def test_another_conversation_is_not_in_the_total(self, db) -> None:
        conversation = await _conversation(db)
        other = await _conversation(db)
        await _turn(db, conversation, input_tokens=1_000, output_tokens=100, cost_usd="0.010000")
        await _turn(db, other, input_tokens=9_000, output_tokens=900, cost_usd="0.900000")

        totals = await conversation_repo.conversation_cost(db, conversation.id)

        assert totals == (1_000, 100, Decimal("0.010000"), None)
