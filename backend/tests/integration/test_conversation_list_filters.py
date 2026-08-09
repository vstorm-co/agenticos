"""Searching, filtering and sorting the member conversation list, against real rows.

The sidebar's filters are server-side for a reason: it holds the pages fetched so
far, never the history, so a client-side filter searches thirty rows and reports
"no results" for a thread from March. That makes these predicates the whole
feature, and three of them cannot be shown by a statement test.

**The agent filter is an EXISTS over messages, not a column.** A thread whose
picker was changed mid-way was answered by two agents and matches both - a fact
about rows in `messages`, which only a database can answer.

**A foreign `agent_id` matches nothing rather than raising.** The predicate runs
inside the caller's own organization, so an agent from somewhere else is a filter
that finds no threads - not an error confirming the agent exists. That is the
shape #1 was the failure of.

**The total is counted the way the page was fetched.** Two queries with two
copies of the same narrowing is exactly how a count comes to disagree with the
rows under it, which is why the predicates are built once and both take them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import conversation as conversation_repo

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


async def _agent(db, organization: Organization, owner: User, name: str) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=organization.id,
        owner_user_id=owner.id,
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name=name).model_dump(mode="json"),
        visibility=Visibility.PRIVATE.value,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _conversation(
    db,
    organization: Organization,
    owner: User,
    *,
    title: str | None,
    archived: bool = False,
    created_at: datetime = _START,
    updated_at: datetime | None = None,
) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=owner.id,
        organization_id=organization.id,
        title=title,
        is_archived=archived,
        created_at=created_at,
        updated_at=updated_at,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _answer(db, conversation: Conversation, agent: Agent, *, at: datetime) -> None:
    db.add(
        Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            role="assistant",
            content="answered",
            agent_id=agent.id,
            created_at=at,
        )
    )
    await db.flush()


async def _titles(db, organization: Organization, owner: User, **kwargs) -> list[str | None]:
    rows = await conversation_repo.get_conversations_by_user(
        db, owner.id, organization_id=organization.id, **kwargs
    )
    return [row.title for row in rows]


class TestTheAgentFilter:
    async def test_a_thread_whose_picker_changed_mid_way_matches_both_agents(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db)
        analyst = await _agent(db, organization, owner, "Analyst")
        support = await _agent(db, organization, owner, "Support")
        thread = await _conversation(db, organization, owner, title="Quarterly numbers")
        await _answer(db, thread, analyst, at=_START)
        await _answer(db, thread, support, at=_START + timedelta(minutes=5))

        assert await _titles(db, organization, owner, agent_id=analyst.id) == ["Quarterly numbers"]
        assert await _titles(db, organization, owner, agent_id=support.id) == ["Quarterly numbers"]

    async def test_a_thread_the_agent_never_answered_in_is_left_out(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db)
        analyst = await _agent(db, organization, owner, "Analyst")
        support = await _agent(db, organization, owner, "Support")
        answered = await _conversation(db, organization, owner, title="Quarterly numbers")
        await _answer(db, answered, analyst, at=_START)
        await _conversation(db, organization, owner, title="Holiday rota")

        assert await _titles(db, organization, owner, agent_id=analyst.id) == ["Quarterly numbers"]
        assert await _titles(db, organization, owner, agent_id=support.id) == []

    async def test_a_thread_matches_once_however_often_the_agent_answered(self, db) -> None:
        """An EXISTS, not a join: a join would return the thread once per answer."""
        organization = await _org(db)
        owner = await _user(db)
        analyst = await _agent(db, organization, owner, "Analyst")
        thread = await _conversation(db, organization, owner, title="Quarterly numbers")
        await _answer(db, thread, analyst, at=_START)
        await _answer(db, thread, analyst, at=_START + timedelta(minutes=1))
        await _answer(db, thread, analyst, at=_START + timedelta(minutes=2))

        assert await _titles(db, organization, owner, agent_id=analyst.id) == ["Quarterly numbers"]

    async def test_an_agent_from_another_organization_finds_nothing(self, db) -> None:
        """Nothing, not an error - an error would confirm the agent exists.

        The thread here is answered by that very agent, which is the case a
        predicate applied outside the tenant filter would return.
        """
        theirs = await _org(db)
        their_owner = await _user(db)
        their_agent = await _agent(db, theirs, their_owner, "Analyst")
        their_thread = await _conversation(db, theirs, their_owner, title="Their quarter")
        await _answer(db, their_thread, their_agent, at=_START)

        ours = await _org(db)
        our_owner = await _user(db)
        await _conversation(db, ours, our_owner, title="Our quarter")

        assert await _titles(db, ours, our_owner, agent_id=their_agent.id) == []


class TestSearchAndArchive:
    async def test_the_search_matches_a_title_regardless_of_case(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db)
        await _conversation(db, organization, owner, title="Quarterly numbers")
        await _conversation(db, organization, owner, title="Holiday rota")

        assert await _titles(db, organization, owner, search="QUARTERLY") == ["Quarterly numbers"]

    async def test_an_untitled_thread_survives_no_search(self, db) -> None:
        """A null title matches nothing rather than everything.

        `LIKE` against NULL is NULL, which is not true - so the row drops out, and
        this pins that it drops out only once a search is actually being made.
        """
        organization = await _org(db)
        owner = await _user(db)
        await _conversation(db, organization, owner, title=None)

        assert await _titles(db, organization, owner) == [None]
        assert await _titles(db, organization, owner, search="anything") == []

    async def test_archived_only_and_active_are_two_disjoint_lists(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db)
        await _conversation(db, organization, owner, title="Live one")
        await _conversation(db, organization, owner, title="Old one", archived=True)

        assert await _titles(db, organization, owner) == ["Live one"]
        assert await _titles(db, organization, owner, archived_only=True) == ["Old one"]
        assert sorted(await _titles(db, organization, owner, include_archived=True)) == [
            "Live one",
            "Old one",
        ]

    async def test_a_search_narrows_inside_the_archive(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db)
        await _conversation(db, organization, owner, title="Quarterly numbers", archived=True)
        await _conversation(db, organization, owner, title="Holiday rota", archived=True)
        await _conversation(db, organization, owner, title="Quarterly plan")

        assert await _titles(db, organization, owner, search="quarterly", archived_only=True) == [
            "Quarterly numbers"
        ]


class TestSorting:
    async def test_by_title_ascending_with_the_untitled_thread_last(self, db) -> None:
        """ "No title" is not the smallest title, and not the largest either."""
        organization = await _org(db)
        owner = await _user(db)
        await _conversation(db, organization, owner, title="Beta")
        await _conversation(db, organization, owner, title=None)
        await _conversation(db, organization, owner, title="Alpha")

        assert await _titles(db, organization, owner, sort_by="title", sort_dir="asc") == [
            "Alpha",
            "Beta",
            None,
        ]

    async def test_a_thread_never_edited_does_not_hold_the_top_of_the_page(self, db) -> None:
        """`updated_at` is null until the first edit, and NULL sorts first on a
        descending order - so the coalesce is what keeps a stale thread below a
        thread updated a second ago.

        The edited thread is the *older* of the two by `created_at`, which is
        what makes the ordering a statement about `updated_at` rather than one
        the row order would have produced anyway.
        """
        organization = await _org(db)
        owner = await _user(db)
        await _conversation(
            db, organization, owner, title="Never edited", created_at=_START, updated_at=None
        )
        await _conversation(
            db,
            organization,
            owner,
            title="Edited just now",
            created_at=_START - timedelta(days=1),
            updated_at=_START + timedelta(days=1),
        )

        assert await _titles(db, organization, owner) == ["Edited just now", "Never edited"]


class TestTheTotalDescribesThePage:
    async def test_the_count_narrows_the_way_the_page_did(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db)
        analyst = await _agent(db, organization, owner, "Analyst")
        matching = await _conversation(db, organization, owner, title="Quarterly numbers")
        await _answer(db, matching, analyst, at=_START)
        await _conversation(db, organization, owner, title="Quarterly plan")
        await _conversation(db, organization, owner, title="Holiday rota", archived=True)

        for narrowing in (
            {},
            {"search": "quarterly"},
            {"agent_id": analyst.id},
            {"archived_only": True},
            {"include_archived": True},
        ):
            rows = await conversation_repo.get_conversations_by_user(
                db, owner.id, organization_id=organization.id, **narrowing
            )
            total = await conversation_repo.count_conversations(
                db, owner.id, organization_id=organization.id, **narrowing
            )
            assert total == len(rows), narrowing
