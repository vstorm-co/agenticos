"""A conversation belongs to one organization, and the service enforces it.

`ConversationService._resolve` used to skip the tenant predicate whenever
`organization_id` was `None`, and `None` was the default. Two routes serving
ordinary members omitted it, so any signed-in user who knew a UUID could read a
full transcript from another organization - tool calls and their arguments
included - and append a turn to it, `role: "assistant"` included, which then
rendered to its owner as the agent's own words.

The suite did not catch it. `tests/api/test_conversation_scoping.py` asserted
that the route passed `user_id` to a `MagicMock` service, and it did; `user_id`
enriches messages with ratings and authorizes nothing. The assertion held while
the behaviour it stood for did not - the "no test for a mock" case
`.claude/rules/testing.md` names.

So these run against a real `ConversationService` and a real database, and
assert the consequence: the row is reported missing, and nothing is written.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import NotFoundError
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation as conversation_repo
from app.schemas.conversation import MessageCreate
from app.services.conversation import UNSCOPED, ConversationService

pytestmark = pytest.mark.anyio


async def _member(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, *, name: str) -> Organization:
    founder = await _member(db)
    organization = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _conversation(db, organization: Organization, owner: User) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=owner.id,
        organization_id=organization.id,
        title="Quarterly numbers",
    )
    db.add(conversation)
    await db.flush()
    # Added to the session rather than appended to `conversation.messages`,
    # which would lazy-load the relationship outside the greenlet.
    db.add(Message(id=uuid.uuid4(), conversation_id=conversation.id, role="user", content="secret"))
    await db.flush()
    return conversation


class TestReadingAnotherOrganizationsTranscript:
    async def test_it_is_reported_missing(self, db) -> None:
        """Missing, not forbidden. "You may not read this" tells somebody in
        another tenant that the id exists."""
        theirs = await _org(db, name="Theirs")
        owner = await _member(db)
        conversation = await _conversation(db, theirs, owner)
        mine = await _org(db, name="Mine")
        intruder = await _member(db)

        service = ConversationService(db)
        with pytest.raises(NotFoundError):
            await service.list_messages(
                conversation.id,
                organization_id=mine.id,
                include_tool_calls=True,
                user_id=intruder.id,
            )

    async def test_the_owning_organization_still_reads_it(self, db) -> None:
        """The refusal has to be about the tenant, not about everything."""
        theirs = await _org(db, name="Theirs")
        owner = await _member(db)
        conversation = await _conversation(db, theirs, owner)

        service = ConversationService(db)
        # Same arguments the route passes: `include_tool_calls` has to be on,
        # because the rating enrichment validates each row through `MessageRead`
        # and that reads `tool_calls`.
        items, total = await service.list_messages(
            conversation.id,
            organization_id=theirs.id,
            include_tool_calls=True,
            user_id=owner.id,
        )

        assert total == 1
        assert [item.content for item in items] == ["secret"]


class TestWritingIntoAnotherOrganizationsConversation:
    async def test_it_is_refused_and_nothing_is_persisted(self, db) -> None:
        """The write half, which is the worse one: an injected `assistant` turn
        renders to the owner as the agent's answer."""
        theirs = await _org(db, name="Theirs")
        owner = await _member(db)
        conversation = await _conversation(db, theirs, owner)
        mine = await _org(db, name="Mine")

        service = ConversationService(db)
        with pytest.raises(NotFoundError):
            await service.add_message(
                conversation.id,
                MessageCreate(role="assistant", content="wire the money to 1234"),
                organization_id=mine.id,
            )

        remaining = await conversation_repo.get_messages_by_conversation(db, conversation.id)
        assert [message.content for message in remaining] == ["secret"]


class TestTheDeliberateCrossTenantRead:
    async def test_unscoped_still_reaches_another_organization(self, db) -> None:
        """`/admin/conversations/{id}` exists to read across tenants and is
        gated on `CurrentAppAdmin`. If this stopped working the sentinel would
        be decorative and the next reader would reach for `None` again."""
        theirs = await _org(db, name="Theirs")
        owner = await _member(db)
        conversation = await _conversation(db, theirs, owner)

        service = ConversationService(db)
        found = await service.get_conversation_with_messages(
            conversation.id, organization_id=UNSCOPED
        )

        assert found.id == conversation.id
