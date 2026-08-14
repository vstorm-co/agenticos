"""Narrowing run history, against Postgres.

Every one of these is a claim about which rows a `WHERE` returns, which is the one
thing a mocked session cannot answer. Two of them are also claims about a number:
`list_runs` runs a page query and a count query, so a filter that reaches one and
not the other produces a total describing a different set from the rows under it -
and that reads as a paging bug rather than as a missing clause.

The window filter is the whole of #198. The Runs figure counted all time while the
spend beside it counted one calendar month, so an organization three years old
showed "8,412 runs" next to "$31.20" and the obvious reading of those two numbers
was wrong by three years.

Delegation is the trap in the environment filter, and it is deliberate rather than
an oversight: a delegated run's version comes from a pin, so its `environment_id`
is never written. Narrowing to an environment therefore cannot return one, which
is a fact the surface has to state rather than one a reader should have to notice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.agent_run import AgentRun, RunOrder, RunRating, RunStatus, RunSurface
from app.db.models.conversation import Conversation, Message
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories.agent_run import RunFilters, down_rated_run_ids
from app.repositories.message_rating import get_down_rating_comments_for_messages
from app.services.agent_runner import AgentRunnerService

pytestmark = pytest.mark.anyio

_NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


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


async def _org(db) -> tuple[Organization, User]:
    owner = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id, role="owner")
    )
    await db.flush()
    return org, owner


async def _agent(db, org: Organization) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _version(db, agent: Agent) -> AgentVersion:
    version = AgentVersion(
        id=uuid.uuid4(),
        organization_id=agent.organization_id,
        agent_id=agent.id,
        version=1,
        spec={"name": agent.name},
    )
    db.add(version)
    await db.flush()
    return version


async def _environment(db, agent: Agent, name: str) -> AgentEnvironment:
    environment = AgentEnvironment(
        id=uuid.uuid4(),
        organization_id=agent.organization_id,
        agent_id=agent.id,
        name=name,
        version_id=(await _version(db, agent)).id,
    )
    db.add(environment)
    await db.flush()
    return environment


async def _run(db, org: Organization, agent: Agent, **overrides) -> AgentRun:
    row = {
        "id": uuid.uuid4(),
        "organization_id": org.id,
        "agent_id": agent.id,
        "status": RunStatus.COMPLETED.value,
        "surface": RunSurface.WEB.value,
        "started_at": _NOW,
    }
    row.update(overrides)
    run = AgentRun(**row)
    db.add(run)
    await db.flush()
    return run


def _ctx(org: Organization, user: User) -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER)


async def _listed(db, org: Organization, user: User, **kwargs) -> tuple[list[str], int]:
    """The rows and the count, so every test asserts on both."""
    items, total = await AgentRunnerService(db).list_runs(_ctx(org, user), **kwargs)
    return [str(item.id) for item in items], total


class TestNarrowingByStatus:
    async def test_two_statuses_at_once_is_the_show_me_the_problems_query(self, db) -> None:
        """`failed` and `budget_exceeded` are separate statuses on purpose - one is
        a malfunction and one is the platform working - so an operator looking for
        trouble has to be able to ask for both without asking for `completed`."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        failed = await _run(db, org, agent, status=RunStatus.FAILED.value)
        stopped = await _run(db, org, agent, status=RunStatus.BUDGET_EXCEEDED.value)
        await _run(db, org, agent, status=RunStatus.COMPLETED.value)

        rows, total = await _listed(
            db,
            org,
            user,
            filters=RunFilters(statuses=[RunStatus.FAILED.value, RunStatus.BUDGET_EXCEEDED.value]),
        )

        assert set(rows) == {str(failed.id), str(stopped.id)}
        assert total == 2

    async def test_an_empty_status_list_narrows_nothing(self, db) -> None:
        """A client that sends no `status` and one that sends an empty list mean the
        same thing. Reading it as "match no status" would answer an unfiltered
        request with an empty page."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        await _run(db, org, agent)

        assert (await _listed(db, org, user, filters=RunFilters(statuses=[])))[1] == 1


class TestNarrowingByWindow:
    async def test_a_window_is_what_makes_the_count_reconcilable_with_the_spend(self, db) -> None:
        """#198. Unwindowed, this count reads all time while the money beside it
        reads one calendar month, and the two invite a comparison that is wrong by
        however old the organization is."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        this_month = await _run(db, org, agent, started_at=_NOW)
        await _run(db, org, agent, started_at=_NOW - timedelta(days=400))

        rows, total = await _listed(
            db, org, user, filters=RunFilters(started_from=_NOW - timedelta(days=6))
        )

        assert rows == [str(this_month.id)]
        assert total == 1

    async def test_both_ends_of_the_window_are_inclusive(self, db) -> None:
        """A range picker hands over whole days. A run at exactly midnight on the
        last day of the range belongs to it, and an exclusive bound would drop the
        first and last day of every range somebody selected."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        edge = await _run(db, org, agent, started_at=_NOW)

        rows, _ = await _listed(
            db, org, user, filters=RunFilters(started_from=_NOW, started_to=_NOW)
        )

        assert rows == [str(edge.id)]

    async def test_a_run_that_never_started_is_outside_every_window(self, db) -> None:
        """`started_at` is nullable, and a null is not "before the range" - it is
        not comparable to it at all. The row is simply not in a windowed answer."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        await _run(db, org, agent, started_at=None)

        assert (await _listed(db, org, user, filters=RunFilters(started_from=_NOW)))[1] == 0
        assert (await _listed(db, org, user))[1] == 1


class TestPagingIsStableWhenTheSortColumnTies:
    async def test_runs_that_share_an_instant_still_have_a_total_order(self, db) -> None:
        """A fan-out starts several runs in the same instant, so `started_at` is
        not unique - and a page boundary drawn through a set of equal keys lets
        Postgres return a row on two pages or skip one between them. `id` is the
        secondary key that makes the order total: with every `started_at` equal,
        the rows come back in `id` order, which is what lets paging carve them
        cleanly. Without the tiebreaker this order is arbitrary and the assertion
        below is at the mercy of the planner."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        for _ in range(5):
            await _run(db, org, agent, started_at=_NOW)

        expected = sorted(
            str(run_id)
            for (run_id,) in (
                await db.execute(select(AgentRun.id).where(AgentRun.organization_id == org.id))
            ).all()
        )

        first, _ = await _listed(db, org, user, skip=0, limit=2)
        second, _ = await _listed(db, org, user, skip=2, limit=2)
        third, _ = await _listed(db, org, user, skip=4, limit=2)
        paged = first + second + third

        # No row repeats or is skipped across the three pages, and the order is
        # the one the tiebreaker fixes.
        assert paged == expected
        assert len(set(paged)) == 5


class TestNarrowingByWhereItCameFrom:
    async def test_one_surface_at_a_time(self, db) -> None:
        org, user = await _org(db)
        agent = await _agent(db, org)
        slack = await _run(db, org, agent, surface=RunSurface.SLACK.value)
        await _run(db, org, agent, surface=RunSurface.WEB.value)

        rows, total = await _listed(
            db, org, user, filters=RunFilters(surface=RunSurface.SLACK.value)
        )

        assert (rows, total) == ([str(slack.id)], 1)

    async def test_who_the_run_ran_as(self, db) -> None:
        """Not always who asked: a widget's runs carry the widget owner's id,
        because the visitor is anonymous and has no row anywhere."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        someone_else = await _user(db)
        theirs = await _run(db, org, agent, user_id=someone_else.id)
        await _run(db, org, agent, user_id=user.id)

        rows, total = await _listed(db, org, user, filters=RunFilters(user_id=someone_else.id))

        assert (rows, total) == ([str(theirs.id)], 1)

    async def test_runs_admitted_through_one_binding(self, db) -> None:
        """`exposure_id` is null for the dashboard, the playground and the API, so
        this is the only filter on the page that can say "the Slack bot's traffic"
        rather than "Slack-shaped traffic"."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        await _run(db, org, agent, exposure_id=None)
        unbound, total = await _listed(db, org, user, filters=RunFilters(exposure_id=uuid.uuid4()))

        assert (unbound, total) == ([], 0)


class TestNarrowingByWhatRan:
    async def test_one_version_of_one_agent(self, db) -> None:
        """The version strip's "show me the runs behind this number"."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        version_id = uuid.uuid4()
        await _run(db, org, agent, agent_version_id=None)
        rows, total = await _listed(db, org, user, filters=RunFilters(agent_version_id=version_id))

        assert (rows, total) == ([], 0)

    async def test_an_environment_filter_cannot_return_a_delegated_run(self, db) -> None:
        """Deliberate, and the reason it is asserted here rather than assumed: a
        delegate's version comes from a pin, so `environment_id` is never written
        on a delegated row. Narrowing to `production` therefore drops every
        delegation - which the surface has to say, because a reader comparing a
        filtered count against an unfiltered one has no other way to learn it."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        production = await _environment(db, agent, "production")
        parent = await _run(db, org, agent, environment_id=production.id)
        await _run(db, org, agent, environment_id=None, parent_run_id=parent.id)

        rows, total = await _listed(
            db,
            org,
            user,
            include_delegations=True,
            filters=RunFilters(environment_id=production.id),
        )

        assert (rows, total) == ([str(parent.id)], 1)


class TestSortingByHowLongItTook:
    """#210. The dashboard says p95 is 14.8s and nothing reaches *those runs*.

    Computed in SQL over the whole narrowed set, because sorting one page of
    twenty-five sorts the wrong set - the slowest run of a month is not in
    whichever rows the newest-first page happened to return.
    """

    async def test_the_slowest_completed_run_comes_first(self, db) -> None:
        org, user = await _org(db)
        agent = await _agent(db, org)
        quick = await _run(db, org, agent, started_at=_NOW, ended_at=_NOW + timedelta(seconds=1))
        slow = await _run(db, org, agent, started_at=_NOW, ended_at=_NOW + timedelta(seconds=30))
        middling = await _run(db, org, agent, started_at=_NOW, ended_at=_NOW + timedelta(seconds=8))

        rows, _ = await _listed(db, org, user, order_by=RunOrder.DURATION)

        assert rows == [str(slow.id), str(middling.id), str(quick.id)]

    async def test_a_run_still_going_does_not_compete_for_the_top(self, db) -> None:
        """It has no duration, and treating a null as zero would put it at one end
        of the sort by accident. Its *age* is a different question, and the one an
        operator actually asks about a stuck run."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        slow = await _run(db, org, agent, started_at=_NOW, ended_at=_NOW + timedelta(seconds=30))
        running = await _run(
            db, org, agent, status=RunStatus.RUNNING.value, started_at=_NOW, ended_at=None
        )

        slowest_first, _ = await _listed(db, org, user, order_by=RunOrder.DURATION)
        quickest_first, _ = await _listed(
            db, org, user, order_by=RunOrder.DURATION, descending=False
        )

        assert slowest_first == [str(slow.id), str(running.id)]
        # Last in *both* directions - not "the fastest run" either.
        assert quickest_first == [str(slow.id), str(running.id)]

    async def test_the_most_expensive_run_comes_first_under_the_cost_order(self, db) -> None:
        """Same arrangement as duration, for money: SQL over the whole narrowed
        set, so the priciest run of a month is found even when the newest-first
        page would never have shown it."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        cheap = await _run(db, org, agent, cost_usd=Decimal("0.01"))
        pricey = await _run(db, org, agent, cost_usd=Decimal("4.20"))
        middling = await _run(db, org, agent, cost_usd=Decimal("0.90"))

        priciest_first, _ = await _listed(db, org, user, order_by=RunOrder.COST)
        cheapest_first, _ = await _listed(db, org, user, order_by=RunOrder.COST, descending=False)

        assert priciest_first == [str(pricey.id), str(middling.id), str(cheap.id)]
        assert cheapest_first == [str(cheap.id), str(middling.id), str(pricey.id)]

    async def test_the_heaviest_run_comes_first_under_the_tokens_order(self, db) -> None:
        """Input and output together: a run that read a huge context and answered
        in one line is heavier than one that chatted both ways, and an operator
        hunting context bloat needs the sum, not either half."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        light = await _run(db, org, agent, input_tokens=100, output_tokens=50)
        heavy = await _run(db, org, agent, input_tokens=90_000, output_tokens=200)
        chatty = await _run(db, org, agent, input_tokens=1_000, output_tokens=4_000)

        heaviest_first, _ = await _listed(db, org, user, order_by=RunOrder.TOKENS)
        lightest_first, _ = await _listed(db, org, user, order_by=RunOrder.TOKENS, descending=False)

        assert heaviest_first == [str(heavy.id), str(chatty.id), str(light.id)]
        assert lightest_first == [str(light.id), str(chatty.id), str(heavy.id)]

    async def test_the_default_order_is_still_the_feed(self, db) -> None:
        org, user = await _org(db)
        agent = await _agent(db, org)
        older = await _run(db, org, agent, started_at=_NOW - timedelta(hours=2))
        newer = await _run(db, org, agent, started_at=_NOW)

        rows, _ = await _listed(db, org, user)

        assert rows == [str(newer.id), str(older.id)]


class TestNarrowingByHowLongItTook:
    async def test_only_runs_over_the_threshold(self, db) -> None:
        org, user = await _org(db)
        agent = await _agent(db, org)
        slow = await _run(db, org, agent, started_at=_NOW, ended_at=_NOW + timedelta(seconds=31))
        await _run(db, org, agent, started_at=_NOW, ended_at=_NOW + timedelta(seconds=2))

        rows, total = await _listed(db, org, user, filters=RunFilters(took_over_ms=30_000))

        assert (rows, total) == ([str(slow.id)], 1)

    async def test_a_run_with_no_end_is_excluded_rather_than_counted_as_zero(self, db) -> None:
        """ "Everything slower than 30 seconds" must not answer with the runs that
        have not finished - they may well be slower, and the question is about what
        is measurable."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        await _run(db, org, agent, status=RunStatus.RUNNING.value, started_at=_NOW, ended_at=None)

        assert (await _listed(db, org, user, filters=RunFilters(took_over_ms=1)))[1] == 0


class TestNarrowingByWhatPeopleThoughtOfIt:
    """#209, and the reason `messages.run_id` had to land first.

    A rating hangs off a message. Until a message named its run there was no way
    to ask a run whether it earned a thumb down - so the highest-signal debugging
    queue the platform has, the answers real people said were wrong, was
    reachable only by the app admin over the whole deployment.
    """

    @staticmethod
    async def _rated(db, run: AgentRun, *, by: User, rating: int) -> None:
        conversation = Conversation(
            id=uuid.uuid4(), organization_id=run.organization_id, user_id=by.id
        )
        db.add(conversation)
        await db.flush()
        message = Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            run_id=run.id,
            role="assistant",
            content="the refund window is 30 days",
        )
        db.add(message)
        await db.flush()
        db.add(MessageRating(id=uuid.uuid4(), message_id=message.id, user_id=by.id, rating=rating))
        await db.flush()

    async def test_only_the_runs_somebody_said_were_wrong(self, db) -> None:
        org, user = await _org(db)
        agent = await _agent(db, org)
        disliked = await _run(db, org, agent)
        liked = await _run(db, org, agent)
        await _run(db, org, agent)
        await self._rated(db, disliked, by=user, rating=-1)
        await self._rated(db, liked, by=user, rating=1)

        rows, total = await _listed(db, org, user, filters=RunFilters(rated=RunRating.DOWN))

        assert (rows, total) == ([str(disliked.id)], 1)

    async def test_the_same_question_from_the_other_side(self, db) -> None:
        org, user = await _org(db)
        agent = await _agent(db, org)
        liked = await _run(db, org, agent)
        await self._rated(db, liked, by=user, rating=1)

        rows, total = await _listed(db, org, user, filters=RunFilters(rated=RunRating.UP))

        assert (rows, total) == ([str(liked.id)], 1)

    async def test_a_run_several_people_disliked_is_one_row_and_not_three(self, db) -> None:
        """An `EXISTS`, not a join. A join would multiply the page and the count by
        however many people happened to press the button, and the count is what a
        reader uses to decide whether the list is worth reading."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        disliked = await _run(db, org, agent)
        for _ in range(3):
            await self._rated(db, disliked, by=await _user(db), rating=-1)

        rows, total = await _listed(db, org, user, filters=RunFilters(rated=RunRating.DOWN))

        assert (rows, total) == ([str(disliked.id)], 1)

    async def test_a_run_one_person_liked_and_another_did_not_matches_both(self, db) -> None:
        """Both are true of it. Reducing it to one verdict would invent a consensus
        the rows do not record - and the disliked half is the half worth reading."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        divisive = await _run(db, org, agent)
        await self._rated(db, divisive, by=user, rating=1)
        await self._rated(db, divisive, by=await _user(db), rating=-1)

        assert (await _listed(db, org, user, filters=RunFilters(rated=RunRating.DOWN)))[1] == 1
        assert (await _listed(db, org, user, filters=RunFilters(rated=RunRating.UP)))[1] == 1

    async def test_a_rating_on_another_runs_message_does_not_pull_this_one_in(self, db) -> None:
        """The join is through `messages.run_id`, so two runs in one conversation
        keep their own ratings - which is the whole reason the column exists rather
        than a time window over the thread."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        blameless = await _run(db, org, agent)
        disliked = await _run(db, org, agent)
        await self._rated(db, disliked, by=user, rating=-1)

        rows, _ = await _listed(db, org, user, filters=RunFilters(rated=RunRating.DOWN))

        assert str(blameless.id) not in rows


class TestTheDownRatedMarker:
    """`down_rated_run_ids` - the set a 👎 is drawn from, one query for a page.

    It answers the same "did anybody rate this down" the `rated=down` filter
    does, so a marked row is exactly a row the filter would return. And it
    carries the same tenant bound every read in this layer does: a neighbour's
    run, even one rated down, is never in the answer for another organization.
    """

    @staticmethod
    async def _rated(db, run: AgentRun, *, by: User, rating: int) -> None:
        conversation = Conversation(
            id=uuid.uuid4(), organization_id=run.organization_id, user_id=by.id
        )
        db.add(conversation)
        await db.flush()
        message = Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            run_id=run.id,
            role="assistant",
            content="the refund window is 30 days",
        )
        db.add(message)
        await db.flush()
        db.add(MessageRating(id=uuid.uuid4(), message_id=message.id, user_id=by.id, rating=rating))
        await db.flush()

    async def test_it_marks_the_runs_somebody_rated_down_and_no_others(self, db) -> None:
        org, user = await _org(db)
        agent = await _agent(db, org)
        disliked = await _run(db, org, agent)
        liked = await _run(db, org, agent)
        untouched = await _run(db, org, agent)
        await self._rated(db, disliked, by=user, rating=-1)
        await self._rated(db, liked, by=user, rating=1)

        marked = await down_rated_run_ids(
            db, organization_id=org.id, run_ids=[disliked.id, liked.id, untouched.id]
        )

        assert marked == {disliked.id}

    async def test_several_dislikes_mark_a_run_once(self, db) -> None:
        """A set, not a count - `distinct`, so three thumbs down are one id and
        the marker query cannot multiply a page the way a bare join would."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        disliked = await _run(db, org, agent)
        for _ in range(3):
            await self._rated(db, disliked, by=await _user(db), rating=-1)

        marked = await down_rated_run_ids(db, organization_id=org.id, run_ids=[disliked.id])

        assert marked == {disliked.id}

    async def test_a_neighbours_down_rated_run_is_never_marked(self, db) -> None:
        """The tenant bound, tested where it bites: a run in another organization,
        rated down, asked about with this organization's id. The rating is real
        and the id is real, and the marker must still be empty - the same refusal
        the listing makes, held at the one query a caller could otherwise pass a
        borrowed id to."""
        mine, _me = await _org(db)
        theirs, them = await _org(db)
        their_agent = await _agent(db, theirs)
        their_run = await _run(db, theirs, their_agent)
        await self._rated(db, their_run, by=them, rating=-1)

        marked = await down_rated_run_ids(db, organization_id=mine.id, run_ids=[their_run.id])

        assert marked == set()

    async def test_no_run_ids_asks_the_database_nothing(self, db) -> None:
        org, _user = await _org(db)

        assert await down_rated_run_ids(db, organization_id=org.id, run_ids=[]) == set()


class TestFiltersAndTheTenantBoundary:
    async def test_a_filter_can_only_shrink_what_a_caller_sees(self, db) -> None:
        """The organization clause is applied whatever the filters say, so no
        combination of them reaches a neighbour's run."""
        mine, me = await _org(db)
        theirs, _them = await _org(db)
        my_agent = await _agent(db, mine)
        their_agent = await _agent(db, theirs)
        await _run(db, theirs, their_agent, status=RunStatus.FAILED.value)
        my_failure = await _run(db, mine, my_agent, status=RunStatus.FAILED.value)

        rows, total = await _listed(
            db, mine, me, filters=RunFilters(statuses=[RunStatus.FAILED.value])
        )

        assert (rows, total) == ([str(my_failure.id)], 1)

    async def test_the_count_narrows_with_the_page_and_not_after_it(self, db) -> None:
        """The two are separate queries. A filter reaching only the page produces a
        total describing a different set from the rows under it, which reads as a
        paging bug rather than as a missing clause."""
        org, user = await _org(db)
        agent = await _agent(db, org)
        for _ in range(3):
            await _run(db, org, agent, status=RunStatus.COMPLETED.value)
        await _run(db, org, agent, status=RunStatus.FAILED.value)

        rows, total = await _listed(
            db,
            org,
            user,
            filters=RunFilters(statuses=[RunStatus.COMPLETED.value]),
            limit=2,
        )

        assert (len(rows), total) == (2, 3)


class TestDownRatingComments:
    """The comment the run-detail feedback panel shows against a down-rated turn.

    `get_down_rating_comments_for_messages` is what makes #209's "the comment is
    readable in the detail view" true. Only a down rating's words count - an up
    rating's note is not what went wrong - and when one turn drew more than one
    objection the most recent word is the one shown.
    """

    @staticmethod
    async def _message(db, org: Organization, by: User) -> Message:
        conversation = Conversation(id=uuid.uuid4(), organization_id=org.id, user_id=by.id)
        db.add(conversation)
        await db.flush()
        message = Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            role="assistant",
            content="the refund window is 30 days",
        )
        db.add(message)
        await db.flush()
        return message

    @staticmethod
    def _rating(message: Message, by: User, *, rating: int, comment, at: datetime) -> MessageRating:
        # created_at is set explicitly: func.now() is the transaction's clock, so
        # two ratings written in one test would tie and "most recent" would be a
        # coin toss - which the ordering the panel relies on must not be.
        return MessageRating(
            id=uuid.uuid4(),
            message_id=message.id,
            user_id=by.id,
            rating=rating,
            comment=comment,
            created_at=at,
        )

    async def test_a_down_ratings_comment_is_returned_an_up_ratings_is_not(self, db) -> None:
        org, user = await _org(db)
        down = await self._message(db, org, user)
        up = await self._message(db, org, user)
        db.add(self._rating(down, user, rating=-1, comment="it invented a policy", at=_NOW))
        db.add(self._rating(up, user, rating=1, comment="perfect", at=_NOW))
        await db.flush()

        comments = await get_down_rating_comments_for_messages(db, message_ids=[down.id, up.id])

        assert comments == {down.id: "it invented a policy"}

    async def test_a_down_rating_with_no_comment_leaves_the_message_absent(self, db) -> None:
        org, user = await _org(db)
        message = await self._message(db, org, user)
        db.add(self._rating(message, user, rating=-1, comment=None, at=_NOW))
        await db.flush()

        assert await get_down_rating_comments_for_messages(db, message_ids=[message.id]) == {}

    async def test_the_most_recent_objection_is_the_one_shown(self, db) -> None:
        org, user = await _org(db)
        message = await self._message(db, org, user)
        db.add(self._rating(message, user, rating=-1, comment="first take", at=_NOW))
        db.add(
            self._rating(
                message,
                await _user(db),
                rating=-1,
                comment="later take",
                at=_NOW + timedelta(minutes=5),
            )
        )
        await db.flush()

        comments = await get_down_rating_comments_for_messages(db, message_ids=[message.id])

        assert comments == {message.id: "later take"}

    async def test_no_message_ids_asks_the_database_nothing(self, db) -> None:
        assert await get_down_rating_comments_for_messages(db, message_ids=[]) == {}
