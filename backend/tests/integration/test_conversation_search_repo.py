"""Conversation search against a real PostgreSQL, because the search is PostgreSQL.

Nothing here can be asserted against a mock. Whether `websearch_to_tsquery` finds
`pricing` in "the pricing floor" and not in "priceless", whether the generated
column is maintained when a message is written, whether `ts_headline` marks the
term and whether the access predicate keeps somebody else's conversation out of
the results are all facts about the database rather than about our Python.

The access half is the important half. `readable_by` is the whole of what stands
between an agent and every conversation in the organization, and a mistake in it
is not a wrong answer - it is one person's threads read out to another.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.channel_identity import ChannelIdentity
from app.db.models.conversation import Conversation, Message
from app.db.models.conversation_share import ConversationShare
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation_search as search_repo

pytestmark = pytest.mark.anyio

_START = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


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


async def _thread(db, organization: Organization, owner: User | None, *, title: str):
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=None if owner is None else owner.id,
        organization_id=organization.id,
        title=title,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _say(
    db,
    conversation: Conversation,
    text: str,
    *,
    role: str = "user",
    at: datetime = _START,
    identity: ChannelIdentity | None = None,
) -> Message:
    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role=role,
        content=text,
        created_at=at,
        channel_identity_id=None if identity is None else identity.id,
    )
    db.add(message)
    await db.flush()
    return message


async def _identity(db, name: str) -> ChannelIdentity:
    identity = ChannelIdentity(
        id=uuid.uuid4(),
        platform="slack",
        platform_user_id=uuid.uuid4().hex,
        platform_display_name=name,
    )
    db.add(identity)
    await db.flush()
    return identity


async def _search(db, organization, user, query: str, *, participants=(), limit: int = 10):
    return await search_repo.search(
        db,
        query=query,
        organization_id=organization.id,
        readable=search_repo.readable_by(user.id, participants),
        limit=limit,
    )


class TestWhatTheIndexMatches:
    async def test_a_word_in_a_message_finds_the_conversation_its_title_never_would(self, db):
        """The point of the whole feature: a title is generated from the first turn,
        so everything decided later was unfindable."""
        organization = await _org(db)
        owner = await _user(db)
        thread = await _thread(db, organization, owner, title="Monday catch-up")
        await _say(db, thread, "we agreed the pricing floor stays at forty")

        found = await _search(db, organization, owner, "pricing")

        assert [hit.conversation_id for hit in found] == [thread.id]
        assert found[0].title == "Monday catch-up"

    async def test_a_word_inside_another_word_is_not_a_match(self, db):
        """This is what "not an `ILIKE`" means concretely: `LIKE '%price%'` matches
        `priceless` and cannot be told to stop."""
        organization = await _org(db)
        owner = await _user(db)
        await _say(
            db,
            await _thread(db, organization, owner, title="t"),
            "the offer was priceless and unrepeatable",
        )

        assert await _search(db, organization, owner, "price") == []

    async def test_case_and_punctuation_do_not_decide_a_match(self, db):
        organization = await _org(db)
        owner = await _user(db)
        thread = await _thread(db, organization, owner, title="t")
        await _say(db, thread, "PRICING, finally.")

        assert [
            hit.conversation_id for hit in await _search(db, organization, owner, "pricing")
        ] == [thread.id]

    async def test_a_quoted_phrase_means_the_words_in_that_order(self, db):
        organization = await _org(db)
        owner = await _user(db)
        ordered = await _thread(db, organization, owner, title="ordered")
        scattered = await _thread(db, organization, owner, title="scattered")
        await _say(db, ordered, "the pricing floor was agreed")
        await _say(db, scattered, "the floor of the room, and pricing later")

        found = await _search(db, organization, owner, '"pricing floor"')

        assert [hit.conversation_id for hit in found] == [ordered.id]

    async def test_a_leading_minus_excludes(self, db):
        organization = await _org(db)
        owner = await _user(db)
        wanted = await _thread(db, organization, owner, title="wanted")
        unwanted = await _thread(db, organization, owner, title="unwanted")
        await _say(db, wanted, "pricing for the enterprise tier")
        await _say(db, unwanted, "pricing for the hobby tier")

        found = await _search(db, organization, owner, "pricing -hobby")

        assert [hit.conversation_id for hit in found] == [wanted.id]

    async def test_a_query_of_nothing_matches_nothing_rather_than_everything(self, db):
        organization = await _org(db)
        owner = await _user(db)
        await _say(db, await _thread(db, organization, owner, title="t"), "something")

        assert await _search(db, organization, owner, "   ") == []

    async def test_the_vector_follows_an_edit_because_the_database_maintains_it(self, db):
        """A generated column rather than a trigger: an `UPDATE` that forgot to
        refresh a trigger-maintained one would leave a row that can never be found
        again, and nothing would say so."""
        organization = await _org(db)
        owner = await _user(db)
        thread = await _thread(db, organization, owner, title="t")
        message = await _say(db, thread, "the original wording")

        message.content = "the amended wording about pricing"
        await db.flush()

        assert [
            hit.conversation_id for hit in await _search(db, organization, owner, "pricing")
        ] == [thread.id]


class TestWhatComesBack:
    async def test_the_snippet_marks_the_matched_word(self, db):
        organization = await _org(db)
        owner = await _user(db)
        thread = await _thread(db, organization, owner, title="t")
        await _say(db, thread, "we agreed the pricing floor stays at forty for the year")

        found = await _search(db, organization, owner, "pricing")

        assert "**pricing**" in found[0].snippet

    async def test_a_channel_hit_names_the_person_who_said_it(self, db):
        """A room has several people in it, so a snippet with no name is a quote
        the model attributes to whoever it assumes."""
        organization = await _org(db)
        owner = await _user(db)
        thread = await _thread(db, organization, owner, title="#general")
        await _say(db, thread, "pricing again", identity=await _identity(db, "Anna Kowalska"))

        found = await _search(db, organization, owner, "pricing")

        assert found[0].speaker_name == "Anna Kowalska"
        assert found[0].speaker_role == "user"

    async def test_every_matching_turn_is_counted_though_one_is_quoted(self, db):
        organization = await _org(db)
        owner = await _user(db)
        thread = await _thread(db, organization, owner, title="t")
        for turn in range(3):
            await _say(db, thread, f"pricing, take {turn}", at=_START + timedelta(minutes=turn))

        found = await _search(db, organization, owner, "pricing")

        assert len(found) == 1
        assert found[0].hits == 3

    async def test_a_thread_that_says_it_squarely_outranks_one_that_mentions_it(self, db):
        """Ranked on its best message rather than the sum of them: summing rewards
        length, and a long thread that mentions the word in passing forty times is
        not a better answer than the one that settled it."""
        organization = await _org(db)
        owner = await _user(db)
        squarely = await _thread(db, organization, owner, title="squarely")
        passing = await _thread(db, organization, owner, title="passing")
        await _say(db, squarely, "pricing")
        for turn in range(6):
            await _say(
                db,
                passing,
                "a long message about many other things which also mentions pricing "
                "somewhere near the end of a great deal of unrelated text",
                at=_START + timedelta(minutes=turn),
            )

        found = await _search(db, organization, owner, "pricing")

        assert [hit.title for hit in found] == ["squarely", "passing"]

    async def test_two_equal_matches_come_back_most_recent_first_every_time(self, db):
        """A short query matches several threads equally often, and without a total
        order the same search returns a different page each run - which reads to a
        model as the results having changed. Recency is the tiebreak because "the
        one I was in last week" is the better guess."""
        organization = await _org(db)
        owner = await _user(db)
        older = await _thread(db, organization, owner, title="older")
        newer = await _thread(db, organization, owner, title="newer")
        await _say(db, older, "pricing")
        await _say(db, newer, "pricing")
        older.updated_at = _START
        newer.updated_at = _START + timedelta(days=1)
        await db.flush()

        for _ in range(3):
            found = await _search(db, organization, owner, "pricing")
            assert [hit.title for hit in found] == ["newer", "older"]

    async def test_the_limit_is_the_number_of_conversations_not_of_turns(self, db):
        organization = await _org(db)
        owner = await _user(db)
        for index in range(4):
            thread = await _thread(db, organization, owner, title=f"t{index}")
            await _say(db, thread, "pricing")
            await _say(db, thread, "pricing again", at=_START + timedelta(minutes=1))

        assert len(await _search(db, organization, owner, "pricing", limit=2)) == 2


class TestWhoMayFindIt:
    async def test_somebody_elses_conversation_is_not_searchable(self, db):
        """The one that matters. `readable_by` is all that stands between an agent
        and every conversation in the organization."""
        organization = await _org(db)
        owner = await _user(db)
        stranger = await _user(db)
        await _say(db, await _thread(db, organization, owner, title="theirs"), "pricing")

        assert await _search(db, organization, stranger, "pricing") == []

    async def test_a_conversation_shared_with_them_is(self, db):
        organization = await _org(db)
        owner = await _user(db)
        reader = await _user(db)
        thread = await _thread(db, organization, owner, title="shared")
        await _say(db, thread, "pricing")
        db.add(
            ConversationShare(
                id=uuid.uuid4(),
                conversation_id=thread.id,
                shared_by=owner.id,
                shared_with=reader.id,
                permission="view",
            )
        )
        await db.flush()

        assert [
            hit.conversation_id for hit in await _search(db, organization, reader, "pricing")
        ] == [thread.id]

    async def test_a_link_share_with_nobody_named_grants_nobody(self, db):
        """`shared_with` is null for a share-by-token, which is a different way in
        with its own route - not a grant to every member of the organization."""
        organization = await _org(db)
        owner = await _user(db)
        stranger = await _user(db)
        thread = await _thread(db, organization, owner, title="link")
        await _say(db, thread, "pricing")
        db.add(
            ConversationShare(
                id=uuid.uuid4(),
                conversation_id=thread.id,
                shared_by=owner.id,
                shared_with=None,
                share_token=uuid.uuid4().hex,
                permission="view",
            )
        )
        await db.flush()

        assert await _search(db, organization, stranger, "pricing") == []

    async def test_a_vetted_participant_reaches_the_room_they_are_still_in(self, db):
        """The ids arrive already confirmed against the platform - having spoken is
        a claim, not access (#641) - so what this asserts is that the predicate
        honours them and nothing wider."""
        organization = await _org(db)
        member = await _user(db)
        room = await _thread(db, organization, None, title="#general")
        await _say(db, room, "pricing in the channel")

        assert await _search(db, organization, member, "pricing") == []
        found = await _search(db, organization, member, "pricing", participants={room.id})
        assert [hit.conversation_id for hit in found] == [room.id]

    async def test_another_organizations_conversation_is_not_searchable(self, db):
        """Even the owner's own: the corpus is scoped to the organization the run
        is in, so switching organizations does not carry a thread across."""
        here = await _org(db)
        elsewhere = await _org(db)
        owner = await _user(db)
        await _say(db, await _thread(db, elsewhere, owner, title="theirs"), "pricing")

        assert await _search(db, here, owner, "pricing") == []


class TestOpeningOne:
    async def test_a_conversation_this_person_may_read_comes_back(self, db):
        organization = await _org(db)
        owner = await _user(db)
        thread = await _thread(db, organization, owner, title="mine")

        found = await search_repo.readable_conversation(
            db,
            conversation_id=thread.id,
            organization_id=organization.id,
            readable=search_repo.readable_by(owner.id, ()),
        )

        assert found is not None and found.id == thread.id

    async def test_one_they_may_not_is_nothing_at_all(self, db):
        organization = await _org(db)
        owner = await _user(db)
        stranger = await _user(db)
        thread = await _thread(db, organization, owner, title="theirs")

        assert (
            await search_repo.readable_conversation(
                db,
                conversation_id=thread.id,
                organization_id=organization.id,
                readable=search_repo.readable_by(stranger.id, ()),
            )
            is None
        )

    async def test_turns_come_back_in_the_order_they_were_written(self, db):
        """`ordinal`, because `created_at` is the transaction's start time: a
        question and its answer are written in one transaction and carry the same
        timestamp to the microsecond."""
        organization = await _org(db)
        owner = await _user(db)
        thread = await _thread(db, organization, owner, title="t")
        for text in ("first", "second", "third"):
            await _say(db, thread, text)

        turns, total = await search_repo.turns(db, conversation_id=thread.id, skip=0, limit=10)

        assert [turn.content for turn in turns] == ["first", "second", "third"]
        assert total == 3

    async def test_a_window_reports_the_whole_length_not_its_own(self, db):
        organization = await _org(db)
        owner = await _user(db)
        thread = await _thread(db, organization, owner, title="t")
        for index in range(5):
            await _say(db, thread, f"turn {index}")

        turns, total = await search_repo.turns(db, conversation_id=thread.id, skip=3, limit=2)

        assert [turn.content for turn in turns] == ["turn 3", "turn 4"]
        assert total == 5

    async def test_a_turn_carries_the_chat_account_that_wrote_it(self, db):
        organization = await _org(db)
        owner = await _user(db)
        thread = await _thread(db, organization, owner, title="#general")
        await _say(db, thread, "hello", identity=await _identity(db, "Anna Kowalska"))
        await _say(db, thread, "hi", role="assistant")

        turns, _ = await search_repo.turns(db, conversation_id=thread.id, skip=0, limit=10)

        assert [turn.speaker_name for turn in turns] == ["Anna Kowalska", None]
