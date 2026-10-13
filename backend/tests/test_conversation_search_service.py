"""What the conversation-search service resolves before it queries anything.

The query itself is `tests/integration/test_conversation_search_repo.py`, against
a real database. What is worth asserting without one is the layer above it: that
both entry points build the *same* access predicate from the *same* vetted
participation set, and that a turn is attributed to whoever actually said it.

The two matter for different reasons. A search that lists a thread the read then
refuses has already told the model the thread exists; and a transcript that names
the thread's owner on a turn a colleague typed puts words in somebody's mouth.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.repositories import conversation_search as search_repo
from app.services import conversation_search as service

pytestmark = pytest.mark.anyio

ORG = uuid4()
PERSON = uuid4()
THREAD = uuid4()
AT = datetime(2026, 8, 14, 10, 4, tzinfo=UTC)


@pytest.fixture
def db(monkeypatch) -> MagicMock:
    """A session the service opens for itself, as it does mid-run.

    Every function here goes through `get_db_context` rather than taking a
    session: a run must not touch the database on the session it runs on, because
    holding that one across a model call is the idle-in-transaction #12 exists to
    avoid.
    """
    session = MagicMock()

    @asynccontextmanager
    async def _context():
        yield session

    monkeypatch.setattr(service, "get_db_context", _context)
    monkeypatch.setattr(
        service.channel_membership,
        "confirmed_participant_threads",
        AsyncMock(return_value={THREAD}),
    )
    return session


class TestWhatMayBeReached:
    async def test_the_search_confirms_channel_membership_before_it_queries(self, db, monkeypatch):
        """Having spoken in a channel is a claim, not access: somebody removed from
        it kept reading everything said afterwards until the claim was checked
        (#641). The check is a platform call and it fails closed, which is the
        right way round here too - the alternative is an agent quoting a channel
        the person was thrown out of."""
        readable = MagicMock()
        by = MagicMock(return_value=readable)
        monkeypatch.setattr(search_repo, "readable_by", by)
        monkeypatch.setattr(search_repo, "search", AsyncMock(return_value=[]))

        await service.search(query="x", organization_id=ORG, user_id=PERSON, limit=5)

        assert by.call_args.args == (PERSON, {THREAD})
        assert search_repo.search.await_args.kwargs["readable"] is readable

    async def test_the_read_resolves_access_the_same_way_the_search_does(self, db, monkeypatch):
        """One resolver for both, so a thread the search offers is a thread the
        read opens. Two answers to "may they see this" is how a search becomes a
        way of asking whether a conversation exists."""
        readable = MagicMock()
        monkeypatch.setattr(search_repo, "readable_by", MagicMock(return_value=readable))
        monkeypatch.setattr(search_repo, "readable_conversation", AsyncMock(return_value=None))

        await service.read(conversation_id=THREAD, organization_id=ORG, user_id=PERSON, skip=0)

        assert search_repo.readable_conversation.await_args.kwargs["readable"] is readable

    async def test_a_conversation_this_person_may_not_read_is_simply_nothing(self, db, monkeypatch):
        monkeypatch.setattr(search_repo, "readable_by", MagicMock())
        monkeypatch.setattr(search_repo, "readable_conversation", AsyncMock(return_value=None))
        monkeypatch.setattr(search_repo, "turns", AsyncMock())

        found = await service.read(
            conversation_id=THREAD, organization_id=ORG, user_id=PERSON, skip=0
        )

        assert found is None
        assert not search_repo.turns.await_count, "nothing is read before access is settled"


class TestWhoSaidIt:
    def _turn(self, **overrides) -> search_repo.Turn:
        return search_repo.Turn(
            **{
                "role": "user",
                "content": "hello",
                "created_at": AT,
                "agent_id": None,
                "speaker_name": None,
                **overrides,
            }
        )

    def test_a_chat_account_names_itself(self):
        """A room has several people in it, and the thread's owner is not the one
        who spoke - so the identity on the row wins over everything."""
        speaker = service._speaker(
            self._turn(speaker_name="Anna Kowalska"), agents={}, owner_name="Somebody Else"
        )

        assert speaker == "Anna Kowalska"

    def test_an_answer_names_the_agent_that_gave_it(self):
        """A thread can be answered by more than one agent - the picker changes
        mid-conversation, which is why `agent_id` is on the message."""
        agent_id = uuid4()
        speaker = service._speaker(
            self._turn(role="assistant", agent_id=agent_id),
            agents={agent_id: SimpleNamespace(name="Support")},
            owner_name="Kacper",
        )

        assert speaker == "Support"

    def test_a_deleted_agent_leaves_the_answer_unattributed(self):
        """`messages.agent_id` is `SET NULL` on delete and a version can outlive
        its agent, so an answer whose agent is gone is anonymous rather than
        attributed to the person who asked."""
        assert (
            service._speaker(
                self._turn(role="assistant", agent_id=uuid4()), agents={}, owner_name="Kacper"
            )
            is None
        )
        assert (
            service._speaker(self._turn(role="assistant"), agents={}, owner_name="Kacper") is None
        )

    def test_a_dashboard_turn_is_the_owners(self):
        """Nothing on the row says who typed it, and nothing has to: a thread from
        the console has exactly one human in it."""
        assert service._speaker(self._turn(), agents={}, owner_name="Kacper") == "Kacper"


class TestReadingOne:
    async def test_a_thread_with_no_owner_still_reads(self, db, monkeypatch):
        """A channel thread nobody has linked an account in has `user_id` null, and
        its turns are named by their chat accounts anyway."""
        monkeypatch.setattr(search_repo, "readable_by", MagicMock())
        monkeypatch.setattr(
            search_repo,
            "readable_conversation",
            AsyncMock(return_value=SimpleNamespace(user_id=None, title="#general")),
        )
        monkeypatch.setattr(
            search_repo,
            "turns",
            AsyncMock(
                return_value=(
                    [
                        search_repo.Turn(
                            role="user",
                            content="hi",
                            created_at=AT,
                            agent_id=None,
                            speaker_name="Anna",
                        )
                    ],
                    1,
                )
            ),
        )
        monkeypatch.setattr(service.user_repo, "get_by_id", AsyncMock())

        transcript = await service.read(
            conversation_id=THREAD, organization_id=ORG, user_id=PERSON, skip=0
        )

        assert transcript is not None
        assert transcript.turns[0].speaker == "Anna"
        assert not service.user_repo.get_by_id.await_count

    async def test_a_named_owner_beats_their_email(self, db, monkeypatch):
        """An email is the fallback, not the label: a transcript reading "USER
        (dev@vstorm.co)" is a transcript nobody recognises themselves in."""
        monkeypatch.setattr(search_repo, "readable_by", MagicMock())
        monkeypatch.setattr(
            search_repo,
            "readable_conversation",
            AsyncMock(return_value=SimpleNamespace(user_id=PERSON, title="t")),
        )
        monkeypatch.setattr(
            search_repo,
            "turns",
            AsyncMock(
                return_value=(
                    [
                        search_repo.Turn(
                            role="user",
                            content="hi",
                            created_at=AT,
                            agent_id=None,
                            speaker_name=None,
                        )
                    ],
                    9,
                )
            ),
        )
        monkeypatch.setattr(service.agent_repo, "get_many", AsyncMock(return_value={}))
        monkeypatch.setattr(
            service.user_repo,
            "get_by_id",
            AsyncMock(return_value=SimpleNamespace(full_name="Kacper", email="dev@vstorm.co")),
        )

        transcript = await service.read(
            conversation_id=THREAD, organization_id=ORG, user_id=PERSON, skip=3
        )

        assert transcript is not None
        assert transcript.turns[0].speaker == "Kacper"
        assert (transcript.total, transcript.skip) == (9, 3)

    async def test_an_owner_with_no_name_falls_back_to_their_email(self, db, monkeypatch):
        monkeypatch.setattr(search_repo, "readable_by", MagicMock())
        monkeypatch.setattr(
            search_repo,
            "readable_conversation",
            AsyncMock(return_value=SimpleNamespace(user_id=PERSON, title="t")),
        )
        monkeypatch.setattr(search_repo, "turns", AsyncMock(return_value=([], 0)))
        monkeypatch.setattr(service.agent_repo, "get_many", AsyncMock(return_value={}))
        monkeypatch.setattr(
            service.user_repo,
            "get_by_id",
            AsyncMock(return_value=SimpleNamespace(full_name=None, email="dev@vstorm.co")),
        )

        transcript = await service.read(
            conversation_id=THREAD, organization_id=ORG, user_id=PERSON, skip=0
        )

        assert transcript is not None
        assert transcript.turns == []


class TestSearching:
    async def test_a_hit_travels_whole(self, db, monkeypatch):
        monkeypatch.setattr(search_repo, "readable_by", MagicMock())
        monkeypatch.setattr(
            search_repo,
            "search",
            AsyncMock(
                return_value=[
                    search_repo.ConversationHit(
                        conversation_id=THREAD,
                        title="Q3 pricing",
                        updated_at=AT,
                        hits=4,
                        snippet="the **pricing** floor",
                        speaker_role="assistant",
                        speaker_name=None,
                    )
                ]
            ),
        )

        found = await service.search(query="pricing", organization_id=ORG, user_id=PERSON, limit=5)

        assert [hit.conversation_id for hit in found] == [THREAD]
        assert found[0].hits == 4
        assert found[0].snippet == "the **pricing** floor"
