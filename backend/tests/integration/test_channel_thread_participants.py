"""Whose conversation list a channel thread appears in, against real rows.

A room is one conversation with several people in it, and until #639 it belonged
to whoever spoke first - or, once an unlinked sender could be answered at all, to
nobody, which left it invisible to everybody including the people who were in it.

Participation starts from `messages.channel_identity_id` - who *spoke* - and
since #641 speaking is a claim, not access: every claim is checked against the
platform's current membership before the listing shows the thread or the read
opens it. These tests stub exactly that boundary - `membership.is_still_member`,
the one call that would leave the process - and let everything under it run on
real rows: the claims query, the session and bot joins, the same predicate
reaching the count as well as the page.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_session import ChannelSession
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation as conversation_repo
from app.schemas.conversation import MessageCreate
from app.services.channels import membership
from app.services.conversation import ConversationService

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


async def _channel(
    db, organization: Organization, conversation: Conversation, identity: ChannelIdentity
) -> ChannelSession:
    """The room the thread came from: a bot of the organization's, one session.

    Without this row the thread has no channel anybody can ask about, and a
    participation claim on it is refused - which one test below pins on purpose.
    """
    bot = ChannelBot(
        id=uuid.uuid4(),
        organization_id=organization.id,
        platform="mattermost",
        name="Support",
        token_encrypted="sealed-elsewhere",
        api_base_url="https://mattermost.acme.com",
    )
    db.add(bot)
    await db.flush()
    session = ChannelSession(
        id=uuid.uuid4(),
        bot_id=bot.id,
        identity_id=identity.id,
        conversation_id=conversation.id,
        platform_chat_id="town-square",
        chat_type="group",
    )
    db.add(session)
    await db.flush()
    return session


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


@pytest.fixture
def still_in_the_channel(monkeypatch) -> AsyncMock:
    """The platform's answer, stubbed at the one call that would leave the
    process. Defaults to "still a member"; a test about removal flips it."""
    answer = AsyncMock(return_value=True)
    monkeypatch.setattr(membership, "is_still_member", answer)
    return answer


async def _listed(db, reader: User, organization: Organization) -> list[uuid.UUID]:
    items, _total = await ConversationService(db).list_conversations(
        user_id=reader.id, organization_id=organization.id
    )
    return [c.id for c in items]


class TestWhoSeesARoomThread:
    async def test_a_participant_still_in_the_channel_sees_it(
        self, db, still_in_the_channel
    ) -> None:
        organization = await _org(db)
        reader = await _user(db)
        identity = await _identity(db, user=reader)
        thread = await _room_thread(db, organization)
        await _channel(db, organization, thread, identity)
        await _said(db, thread, identity)

        assert await _listed(db, reader, organization) == [thread.id]
        asked_bot, asked_chat, asked_account = still_in_the_channel.await_args.args
        assert asked_bot.platform == "mattermost"
        assert asked_chat == "town-square"
        assert asked_account == identity.platform_user_id

    async def test_a_participant_removed_from_the_channel_loses_the_thread(
        self, db, still_in_the_channel
    ) -> None:
        """The defect #641 names: they spoke, the platform removed them, and the
        thread must leave their list rather than outlive their access."""
        still_in_the_channel.return_value = False
        organization = await _org(db)
        reader = await _user(db)
        identity = await _identity(db, user=reader)
        thread = await _room_thread(db, organization)
        await _channel(db, organization, thread, identity)
        await _said(db, thread, identity)

        assert await _listed(db, reader, organization) == []

    async def test_a_thread_whose_session_moved_on_is_not_reachable_by_participation(
        self, db, still_in_the_channel
    ) -> None:
        """`/new` re-points the session at a fresh conversation, so the old
        thread names no channel anybody can ask about - and a claim that cannot
        be checked is refused rather than trusted."""
        organization = await _org(db)
        reader = await _user(db)
        identity = await _identity(db, user=reader)
        thread = await _room_thread(db, organization)
        await _said(db, thread, identity)

        assert await _listed(db, reader, organization) == []
        still_in_the_channel.assert_not_awaited()

    async def test_somebody_who_never_spoke_in_it_does_not_see_it(
        self, db, still_in_the_channel
    ) -> None:
        organization = await _org(db)
        reader = await _user(db)
        stranger = await _user(db)
        identity = await _identity(db, user=stranger)
        thread = await _room_thread(db, organization)
        await _channel(db, organization, thread, identity)
        await _said(db, thread, identity)

        assert await _listed(db, reader, organization) == []

    async def test_an_unlinked_account_reaches_nobody(self, db, still_in_the_channel) -> None:
        """The turn is recorded and attributable; it is nobody's list yet.

        This is the state every room thread starts in, and the reason the thread
        was invisible to everybody before participation existed.
        """
        organization = await _org(db)
        reader = await _user(db)
        identity = await _identity(db, user=None)
        thread = await _room_thread(db, organization)
        await _channel(db, organization, thread, identity)
        await _said(db, thread, identity)

        assert await _listed(db, reader, organization) == []

    async def test_linking_the_account_is_what_makes_it_appear(
        self, db, still_in_the_channel
    ) -> None:
        """No backfill, and none needed: the message points at the identity, and
        the identity gains a person."""
        organization = await _org(db)
        reader = await _user(db)
        identity = await _identity(db, user=None)
        thread = await _room_thread(db, organization)
        await _channel(db, organization, thread, identity)
        await _said(db, thread, identity)

        before = await _listed(db, reader, organization)
        identity.user_id = reader.id
        await db.flush()
        after = await _listed(db, reader, organization)

        assert before == []
        assert after == [thread.id]

    async def test_a_thread_appears_once_however_often_they_spoke(
        self, db, still_in_the_channel
    ) -> None:
        """Four turns are one claim, one platform question and one row."""
        organization = await _org(db)
        reader = await _user(db)
        identity = await _identity(db, user=reader)
        thread = await _room_thread(db, organization)
        await _channel(db, organization, thread, identity)
        for _ in range(4):
            await _said(db, thread, identity)

        assert await _listed(db, reader, organization) == [thread.id]
        still_in_the_channel.assert_awaited_once()

    async def test_the_count_agrees_with_the_page(self, db, still_in_the_channel) -> None:
        """A total counted without the vetted participation set is a number that
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
        identity = await _identity(db, user=reader)
        thread = await _room_thread(db, organization)
        await _channel(db, organization, thread, identity)
        await _said(db, thread, identity)
        await _said(db, thread, await _identity(db, user=await _user(db)))

        items, total = await ConversationService(db).list_conversations(
            user_id=reader.id, organization_id=organization.id
        )

        assert total == len(items) == 2

    async def test_another_organizations_room_is_not_reachable_by_speaking_in_it(
        self, db, still_in_the_channel
    ) -> None:
        """Participation widens whose list a thread is in - never which tenant."""
        organization = await _org(db)
        other = await _org(db)
        reader = await _user(db)
        identity = await _identity(db, user=reader)
        thread = await _room_thread(db, other)
        await _channel(db, other, thread, identity)
        await _said(db, thread, identity)

        assert await _listed(db, reader, organization) == []

    async def test_a_dashboard_thread_still_reaches_its_owner(
        self, db, still_in_the_channel
    ) -> None:
        """The predicate widens the listing; it must not narrow the ordinary
        case, and a dashboard-only user costs no platform call at all."""
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

        assert await _listed(db, reader, organization) == [owned.id]
        still_in_the_channel.assert_not_awaited()


class TestWhoMayOpenARoomThread:
    """The read path of the same rule, so the list and the read cannot disagree:
    a participant the platform still places in the channel opens the thread, a
    removed one gets the same 404 a stranger does, and the owner and a share are
    doors the membership check never touches.
    """

    async def test_a_participant_still_in_the_channel_may_open_it(
        self, db, still_in_the_channel
    ) -> None:
        organization = await _org(db)
        reader = await _user(db)
        identity = await _identity(db, user=reader)
        thread = await _room_thread(db, organization)
        await _channel(db, organization, thread, identity)
        await _said(db, thread, identity)

        opened = await ConversationService(db).get_conversation(
            thread.id, organization_id=organization.id, user_id=reader.id
        )

        assert opened.id == thread.id

    async def test_a_participant_removed_from_the_channel_is_refused(
        self, db, still_in_the_channel
    ) -> None:
        still_in_the_channel.return_value = False
        organization = await _org(db)
        reader = await _user(db)
        identity = await _identity(db, user=reader)
        thread = await _room_thread(db, organization)
        await _channel(db, organization, thread, identity)
        await _said(db, thread, identity)

        with pytest.raises(NotFoundError):
            await ConversationService(db).get_conversation(
                thread.id, organization_id=organization.id, user_id=reader.id
            )

    async def test_the_owner_keeps_the_thread_even_after_leaving_the_channel(
        self, db, still_in_the_channel
    ) -> None:
        """Ownership is the platform's business to grant and ours to keep: the
        membership check gates participation, never the owner's own thread."""
        still_in_the_channel.return_value = False
        organization = await _org(db)
        owner = await _user(db)
        identity = await _identity(db, user=owner)
        thread = Conversation(
            id=uuid.uuid4(),
            user_id=owner.id,
            organization_id=organization.id,
            title="Mattermost Chat",
        )
        db.add(thread)
        await db.flush()
        await _channel(db, organization, thread, identity)
        await _said(db, thread, identity)

        opened = await ConversationService(db).get_conversation(
            thread.id, organization_id=organization.id, user_id=owner.id
        )

        assert opened.id == thread.id

    async def test_a_member_who_never_spoke_cannot_open_an_unowned_room_thread(
        self, db, still_in_the_channel
    ) -> None:
        """The hole #639 closed: user_id is None, so the owner guard was skipped
        and every member of the organization could read it."""
        organization = await _org(db)
        stranger = await _user(db)
        identity = await _identity(db, user=await _user(db))
        thread = await _room_thread(db, organization)
        await _channel(db, organization, thread, identity)
        await _said(db, thread, identity)

        with pytest.raises(NotFoundError):
            await ConversationService(db).get_conversation(
                thread.id, organization_id=organization.id, user_id=stranger.id
            )

    async def test_the_owner_of_a_dashboard_thread_still_opens_it(
        self, db, still_in_the_channel
    ) -> None:
        organization = await _org(db)
        owner = await _user(db)
        owned = Conversation(
            id=uuid.uuid4(), user_id=owner.id, organization_id=organization.id, title="Mine"
        )
        db.add(owned)
        await db.flush()

        opened = await ConversationService(db).get_conversation(
            owned.id, organization_id=organization.id, user_id=owner.id
        )

        assert opened.id == owned.id
        still_in_the_channel.assert_not_awaited()

    async def test_a_stranger_cannot_open_a_dashboard_thread_that_is_not_theirs(
        self, db, still_in_the_channel
    ) -> None:
        organization = await _org(db)
        owner = await _user(db)
        stranger = await _user(db)
        owned = Conversation(
            id=uuid.uuid4(), user_id=owner.id, organization_id=organization.id, title="Mine"
        )
        db.add(owned)
        await db.flush()

        with pytest.raises(NotFoundError):
            await ConversationService(db).get_conversation(
                owned.id, organization_id=organization.id, user_id=stranger.id
            )


class TestWhatAParticipantMayChange:
    """Nothing. Opening a room thread and changing it are different questions, and
    against real rows because the distinction is a property of the row: a room whose
    first speaker had linked an account is owned by them, and everybody else in it
    is a participant. Reading widened to that set; writing did not follow, and for a
    while did - a Viewer who said one thing in a channel could delete the room.
    """

    @staticmethod
    async def _owned_room(db, organization: Organization, owner) -> Conversation:
        conversation = Conversation(
            id=uuid.uuid4(),
            user_id=owner.id,
            organization_id=organization.id,
            title="Mattermost Chat",
        )
        db.add(conversation)
        await db.flush()
        return conversation

    async def test_a_participant_opens_the_thread_and_cannot_delete_it(
        self, db, still_in_the_channel
    ) -> None:
        organization = await _org(db)
        owner = await _user(db)
        speaker = await _user(db)
        identity = await _identity(db, user=speaker)
        thread = await self._owned_room(db, organization, owner)
        await _channel(db, organization, thread, identity)
        await _said(db, thread, identity)
        service = ConversationService(db)

        opened = await service.get_conversation(
            thread.id, organization_id=organization.id, user_id=speaker.id
        )
        assert opened.id == thread.id

        with pytest.raises(NotFoundError):
            await service.delete_conversation(
                thread.id, organization_id=organization.id, user_id=speaker.id
            )

        assert (await conversation_repo.get_conversation_by_id(db, thread.id)) is not None, (
            "the row survived the refusal"
        )

    async def test_a_participant_cannot_append_a_turn_as_the_agent(
        self, db, still_in_the_channel
    ) -> None:
        organization = await _org(db)
        owner = await _user(db)
        speaker = await _user(db)
        identity = await _identity(db, user=speaker)
        thread = await self._owned_room(db, organization, owner)
        await _channel(db, organization, thread, identity)
        await _said(db, thread, identity)

        with pytest.raises(NotFoundError):
            await ConversationService(db).add_message(
                thread.id,
                MessageCreate(role="assistant", content="Approved. Wire the money."),
                organization_id=organization.id,
                user_id=speaker.id,
            )

        assert await conversation_repo.count_messages(db, thread.id) == 1, (
            "only what the speaker actually said"
        )

    async def test_the_owner_of_a_room_thread_still_deletes_it(
        self, db, still_in_the_channel
    ) -> None:
        organization = await _org(db)
        owner = await _user(db)
        identity = await _identity(db, user=owner)
        thread = await self._owned_room(db, organization, owner)
        await _channel(db, organization, thread, identity)
        await _said(db, thread, identity)

        assert await ConversationService(db).delete_conversation(
            thread.id, organization_id=organization.id, user_id=owner.id
        )
