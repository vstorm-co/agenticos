"""Whose conversation list a channel thread appears in, against real rows.

A room is one conversation with several people in it, and until #639 it belonged
to whoever spoke first - or, once an unlinked sender could be answered at all, to
nobody, which left it invisible to everybody including the people who were in it.

Participation is now a `DISTINCT` over `messages.channel_identity_id`, and what
has to be true of it is exactly what a statement test cannot show: the correlated
`EXISTS` lands on real rows, the same predicate reaches the count as well as the
page, and a thread somebody never spoke in stays out of their list.

**It says who spoke, not who may read** (#641). The test that pins the good half
of that - a thread reaching somebody the moment they link - is also the test that
pins the cost: nothing here consults the platform, so nothing here can know they
have since been removed from the channel.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation as conversation_repo

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


async def _org(db) -> Organization:
    founder = await _user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _identity(db, *, user: User | None) -> ChannelIdentity:
    identity = ChannelIdentity(
        id=uuid.uuid4(),
        platform="mattermost",
        platform_user_id=uuid.uuid4().hex,
        platform_username="kacper.wlodarczyk",
        platform_display_name="Kacper",
        user_id=None if user is None else user.id,
    )
    db.add(identity)
    await db.flush()
    return identity


async def _room_thread(db, organization: Organization) -> Conversation:
    """A thread from a channel: no owner, because the room has none."""
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=None,
        organization_id=organization.id,
        title="Mattermost Chat",
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _said(db, conversation: Conversation, identity: ChannelIdentity | None) -> None:
    db.add(
        Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            role="user",
            content="hej",
            channel_identity_id=None if identity is None else identity.id,
        )
    )
    await db.flush()


class TestWhoSeesARoomThread:
    async def test_somebody_who_spoke_in_it_sees_it(self, db) -> None:
        organization = await _org(db)
        reader = await _user(db)
        thread = await _room_thread(db, organization)
        await _said(db, thread, await _identity(db, user=reader))

        listed = await conversation_repo.get_conversations_by_user(
            db, user_id=reader.id, organization_id=organization.id
        )

        assert [c.id for c in listed] == [thread.id]

    async def test_somebody_who_never_spoke_in_it_does_not(self, db) -> None:
        organization = await _org(db)
        reader = await _user(db)
        stranger = await _user(db)
        thread = await _room_thread(db, organization)
        await _said(db, thread, await _identity(db, user=stranger))

        listed = await conversation_repo.get_conversations_by_user(
            db, user_id=reader.id, organization_id=organization.id
        )

        assert listed == []

    async def test_an_unlinked_account_reaches_nobody(self, db) -> None:
        """The turn is recorded and attributable; it is nobody's list yet.

        This is the state every room thread starts in, and the reason the thread
        was invisible to everybody before participation existed.
        """
        organization = await _org(db)
        reader = await _user(db)
        thread = await _room_thread(db, organization)
        await _said(db, thread, await _identity(db, user=None))

        listed = await conversation_repo.get_conversations_by_user(
            db, user_id=reader.id, organization_id=organization.id
        )

        assert listed == []

    async def test_linking_the_account_is_what_makes_it_appear(self, db) -> None:
        """No backfill, and none needed: the message points at the identity, and
        the identity gains a person."""
        organization = await _org(db)
        reader = await _user(db)
        identity = await _identity(db, user=None)
        thread = await _room_thread(db, organization)
        await _said(db, thread, identity)

        before = await conversation_repo.get_conversations_by_user(
            db, user_id=reader.id, organization_id=organization.id
        )
        identity.user_id = reader.id
        await db.flush()
        after = await conversation_repo.get_conversations_by_user(
            db, user_id=reader.id, organization_id=organization.id
        )

        assert before == []
        assert [c.id for c in after] == [thread.id]

    async def test_a_thread_appears_once_however_often_they_spoke(self, db) -> None:
        """`EXISTS`, not a join: four turns must not be four rows in the list."""
        organization = await _org(db)
        reader = await _user(db)
        identity = await _identity(db, user=reader)
        thread = await _room_thread(db, organization)
        for _ in range(4):
            await _said(db, thread, identity)

        listed = await conversation_repo.get_conversations_by_user(
            db, user_id=reader.id, organization_id=organization.id
        )

        assert [c.id for c in listed] == [thread.id]

    async def test_the_count_agrees_with_the_page(self, db) -> None:
        """A total counted without the participation predicate is a number that
        contradicts the rows under it."""
        organization = await _org(db)
        reader = await _user(db)
        owned = Conversation(
            id=uuid.uuid4(),
            user_id=reader.id,
            organization_id=organization.id,
            title="Mine",
        )
        db.add(owned)
        thread = await _room_thread(db, organization)
        await _said(db, thread, await _identity(db, user=reader))
        await _said(db, thread, await _identity(db, user=await _user(db)))

        listed = await conversation_repo.get_conversations_by_user(
            db, user_id=reader.id, organization_id=organization.id
        )
        total = await conversation_repo.count_conversations(
            db, user_id=reader.id, organization_id=organization.id
        )

        assert total == len(listed) == 2

    async def test_another_organizations_room_is_not_reachable_by_speaking_in_it(self, db) -> None:
        """Participation widens whose list a thread is in - never which tenant."""
        organization = await _org(db)
        other = await _org(db)
        reader = await _user(db)
        thread = await _room_thread(db, other)
        await _said(db, thread, await _identity(db, user=reader))

        listed = await conversation_repo.get_conversations_by_user(
            db, user_id=reader.id, organization_id=organization.id
        )

        assert listed == []

    async def test_a_dashboard_thread_still_reaches_its_owner(self, db) -> None:
        """The predicate widens the listing; it must not narrow the ordinary case."""
        organization = await _org(db)
        reader = await _user(db)
        owned = Conversation(
            id=uuid.uuid4(),
            user_id=reader.id,
            organization_id=organization.id,
            title="Mine",
        )
        db.add(owned)
        await db.flush()
        await _said(db, owned, None)

        listed = await conversation_repo.get_conversations_by_user(
            db, user_id=reader.id, organization_id=organization.id
        )

        assert [c.id for c in listed] == [owned.id]
