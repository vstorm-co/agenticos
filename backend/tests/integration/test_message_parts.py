"""`messages.parts` against real rows.

The column exists so a reloaded conversation is the one somebody watched. Two
things about it cannot be checked against a mocked session, and both are the
whole point of it.

The first is that the order survives a round trip through JSONB at all - that a
list of Pydantic models goes in, comes back as the same sequence, and reads back
through `MessageRead` as parts rather than as dicts. The second is that the text
inside it survives: a part is *accumulated* from streamed deltas, so
`MessagePart` turns off the whitespace stripping `BaseSchema` applies to every
other schema, and a mock cannot tell you whether the value that reached Postgres
still had the space in it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation as conversation_repo
from app.schemas.conversation import MessagePart
from app.services.chat_timeline import TurnTimeline

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


async def _write(db, conversation: Conversation, parts: list[MessagePart] | None) -> Message:
    """Write an assistant turn the way the service does, dumping the parts."""
    return await conversation_repo.create_message(
        db,
        conversation_id=conversation.id,
        role="assistant",
        content="Done - three charts.",
        parts=(None if parts is None else [part.model_dump(exclude_none=True) for part in parts]),
    )


class TestATurnsOrderSurvivesTheDatabase:
    async def test_the_sequence_comes_back_in_the_order_it_went_in(self, db) -> None:
        """JSONB preserves array order; a dict of parts keyed by type would not.

        This is the turn the column was added for - text, three tools, text.
        """
        conversation = await _conversation(db)
        timeline = TurnTimeline()
        timeline.add_text("Below are a few example charts.")
        for index in range(3):
            timeline.add_tool(f"call-{index}")
        timeline.add_text("Done - three charts.")

        written = await _write(db, conversation, timeline.stored())
        db.expunge(written)
        stored = (await db.execute(select(Message).where(Message.id == written.id))).scalar_one()

        assert stored.parts is not None
        assert [
            (part["type"], part.get("text") or part.get("tool_call_id")) for part in stored.parts
        ] == [
            ("text", "Below are a few example charts."),
            ("tool", "call-0"),
            ("tool", "call-1"),
            ("tool", "call-2"),
            ("text", "Done - three charts."),
        ]

    async def test_the_space_between_two_deltas_reaches_postgres(self, db) -> None:
        """`BaseSchema` strips every string field, and a part is accumulated from
        deltas - so stripping turns "Two " + "are open." into "Twoare open.".
        `MessagePart` opts out, and this is where that is actually observable."""
        conversation = await _conversation(db)
        timeline = TurnTimeline()
        timeline.add_text("Two ")
        timeline.add_text("are open.")
        timeline.add_tool("call-1")

        written = await _write(db, conversation, timeline.stored())
        db.expunge(written)
        stored = (await db.execute(select(Message).where(Message.id == written.id))).scalar_one()

        assert stored.parts is not None
        assert stored.parts[0]["text"] == "Two are open."

    async def test_what_is_stored_validates_as_the_schema_a_client_reads(self, db) -> None:
        """The column is JSONB, so nothing in the database enforces its shape.

        What keeps a client honest is that `MessageRead` validates it into
        `MessagePart` - so the entries the writer dumped have to be the entries the
        reader can parse, and `exclude_none` on the way in must not drop something
        required on the way out.
        """
        conversation = await _conversation(db)
        timeline = TurnTimeline()
        timeline.add_thinking("Deciding what to plot.")
        timeline.add_tool("call-1")
        timeline.add_text("Here it is.")

        written = await _write(db, conversation, timeline.stored())
        db.expunge(written)
        stored = (await db.execute(select(Message).where(Message.id == written.id))).scalar_one()

        assert stored.parts is not None
        parsed = [MessagePart.model_validate(entry) for entry in stored.parts]
        assert [(part.type, part.text, part.tool_call_id) for part in parsed] == [
            ("thinking", "Deciding what to plot.", None),
            ("tool", None, "call-1"),
            ("text", "Here it is.", None),
        ]

    async def test_a_turn_written_without_an_order_reads_back_as_none(self, db) -> None:
        """The nullable half, and what tells a client to reconstruct one instead.

        Every assistant turn written before this column existed is this row, and
        there is no backfill that could honestly fill it in.
        """
        conversation = await _conversation(db)

        written = await _write(db, conversation, None)
        db.expunge(written)
        stored = (await db.execute(select(Message).where(Message.id == written.id))).scalar_one()

        assert stored.parts is None
