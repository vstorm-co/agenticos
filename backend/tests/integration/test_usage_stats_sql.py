"""The SQL behind GET /stats/usage, asked of a real Postgres.

The unit suite proves the service's arithmetic with the repository mocked;
none of it can tell whether `percentile_cont` interpolates, whether day
buckets split on UTC midnight rather than the session's timezone, or whether
COUNT(DISTINCT user_id) really ignores anonymous runs. Those are properties
of the database, so they are asserted against one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun as AgentRunModel
from app.db.models.agent_run import ApprovalStatus, RunStatus, RunSurface, ToolApproval
from app.db.models.conversation import Conversation, Message
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import agent_run_repo, message_rating_repo
from app.services.stats import StatsService

pytestmark = pytest.mark.anyio

# A fixed window, so every assertion is about dates the test placed there.
START = datetime(2026, 7, 1, tzinfo=UTC)
END = datetime(2026, 8, 1, tzinfo=UTC)


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


async def _org_with_owner(db, name: str) -> tuple[Organization, User]:
    owner = await _user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(organization)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=organization.id,
            user_id=owner.id,
            role=OrgRoleName.OWNER.value,
        )
    )
    await db.flush()
    return organization, owner


async def _agent(db, organization: Organization, owner: User, slug: str = "support") -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=organization.id,
        owner_user_id=owner.id,
        slug=slug,
        name=slug.title(),
        draft_spec={"name": slug.title()},
        visibility=Visibility.PRIVATE.value,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _run(
    db,
    *,
    organization: Organization,
    agent: Agent,
    started_at: datetime,
    duration_seconds: float | None = None,
    user_id: uuid.UUID | None = None,
    status: str = RunStatus.COMPLETED.value,
    surface: str = RunSurface.WEB.value,
    provider: str | None = None,
    cost: Decimal = Decimal("0"),
) -> AgentRunModel:
    run = AgentRunModel(
        id=uuid.uuid4(),
        organization_id=organization.id,
        agent_id=agent.id,
        user_id=user_id,
        status=status,
        surface=surface,
        provider=provider,
        cost_usd=cost,
        started_at=started_at,
        ended_at=(
            started_at + timedelta(seconds=duration_seconds)
            if duration_seconds is not None
            else None
        ),
    )
    db.add(run)
    await db.flush()
    return run


class TestLatencyPercentiles:
    async def test_percentile_cont_interpolates_over_known_durations(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Latency")
        agent = await _agent(db, organization, owner)
        for seconds in (1, 2, 10):
            await _run(
                db,
                organization=organization,
                agent=agent,
                started_at=START,
                duration_seconds=seconds,
            )

        p50, p95 = await agent_run_repo.latency_percentiles_ms(
            db, organization_id=organization.id, start=START, end=END
        )

        # percentile_cont over [1000, 2000, 10000]: the median is the middle
        # value, p95 interpolates between the 2nd and 3rd (2000 + 0.9 * 8000).
        assert (p50, p95) == (2000.0, 9200.0)

    async def test_an_unfinished_run_does_not_enter_the_distribution(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Parked")
        agent = await _agent(db, organization, owner)
        await _run(db, organization=organization, agent=agent, started_at=START, duration_seconds=2)
        await _run(
            db,
            organization=organization,
            agent=agent,
            started_at=START,
            status=RunStatus.RUNNING.value,
        )

        p50, _p95 = await agent_run_repo.latency_percentiles_ms(
            db, organization_id=organization.id, start=START, end=END
        )

        assert p50 == 2000.0

    async def test_no_finished_runs_answers_null_not_zero(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Fresh")
        agent = await _agent(db, organization, owner)
        await _run(
            db,
            organization=organization,
            agent=agent,
            started_at=START,
            status=RunStatus.RUNNING.value,
        )

        assert await agent_run_repo.latency_percentiles_ms(
            db, organization_id=organization.id, start=START, end=END
        ) == (None, None)


class TestDayBuckets:
    async def test_runs_split_on_utc_midnight_whatever_the_session_timezone(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Midnight")
        agent = await _agent(db, organization, owner)
        await _run(
            db,
            organization=organization,
            agent=agent,
            started_at=datetime(2026, 7, 1, 23, 30, tzinfo=UTC),
        )
        await _run(
            db,
            organization=organization,
            agent=agent,
            started_at=datetime(2026, 7, 2, 0, 30, tzinfo=UTC),
        )

        buckets = await agent_run_repo.runs_by_day(
            db, organization_id=organization.id, start=START, end=END
        )

        assert [(day.isoformat(), count) for day, count in buckets] == [
            ("2026-07-01", 1),
            ("2026-07-02", 1),
        ]

    async def test_the_window_edges_are_inclusive_from_and_exclusive_end(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Edges")
        agent = await _agent(db, organization, owner)
        await _run(db, organization=organization, agent=agent, started_at=START)
        await _run(
            db,
            organization=organization,
            agent=agent,
            started_at=datetime(2026, 7, 31, 23, 59, 59, tzinfo=UTC),
        )
        await _run(db, organization=organization, agent=agent, started_at=END)

        total = await agent_run_repo.count_runs(
            db, organization_id=organization.id, start=START, end=END
        )

        assert total == 2


class TestTenantAndScopeBoundaries:
    async def test_another_organizations_runs_never_enter_the_numbers(self, db) -> None:
        home, home_owner = await _org_with_owner(db, "Home")
        other, other_owner = await _org_with_owner(db, "Other")
        home_agent = await _agent(db, home, home_owner)
        other_agent = await _agent(db, other, other_owner)
        await _run(
            db,
            organization=home,
            agent=home_agent,
            started_at=START,
            user_id=home_owner.id,
            cost=Decimal("1"),
        )
        await _run(
            db,
            organization=other,
            agent=other_agent,
            started_at=START,
            user_id=home_owner.id,
            cost=Decimal("9"),
        )

        ctx = AuthContext(
            user_id=home_owner.id, organization_id=home.id, role=OrgRoleName.OWNER.value
        )
        result = await StatsService(db).usage(
            ctx, from_date=START.date(), to_date=END.date() - timedelta(days=1)
        )

        # The other tenant's run is owned by the same user - the exact case an
        # owner-keyed query would leak.
        assert result.total_runs == 1
        assert result.cost is not None and result.cost.period_usd == Decimal("1")

    async def test_own_scope_counts_only_the_callers_rows(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Own")
        colleague = await _user(db)
        db.add(
            OrganizationMember(
                id=uuid.uuid4(),
                organization_id=organization.id,
                user_id=colleague.id,
                role=OrgRoleName.MEMBER.value,
            )
        )
        agent = await _agent(db, organization, owner)
        await _run(db, organization=organization, agent=agent, started_at=START, user_id=owner.id)
        await _run(
            db, organization=organization, agent=agent, started_at=START, user_id=colleague.id
        )
        await _run(
            db, organization=organization, agent=agent, started_at=START, user_id=colleague.id
        )

        ctx = AuthContext(
            user_id=colleague.id, organization_id=organization.id, role=OrgRoleName.MEMBER.value
        )
        result = await StatsService(db).usage(
            ctx, scope="own", from_date=START.date(), to_date=END.date() - timedelta(days=1)
        )

        assert result.total_runs == 2

    async def test_active_users_ignores_anonymous_runs(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Anon")
        agent = await _agent(db, organization, owner)
        second = await _user(db)
        await _run(db, organization=organization, agent=agent, started_at=START, user_id=owner.id)
        await _run(db, organization=organization, agent=agent, started_at=START, user_id=second.id)
        # An embedded widget's visitor: a run with no subject is not a person.
        await _run(db, organization=organization, agent=agent, started_at=START, user_id=None)

        active = await agent_run_repo.count_distinct_users(
            db, organization_id=organization.id, start=START, end=END
        )

        assert active == 2


class TestPendingApprovals:
    async def test_counts_the_callers_parked_runs_not_their_approvals(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Queue")
        agent = await _agent(db, organization, owner)
        colleague = await _user(db)
        parked = await _run(
            db,
            organization=organization,
            agent=agent,
            started_at=START,
            user_id=owner.id,
            status=RunStatus.AWAITING_APPROVAL.value,
        )
        someone_elses = await _run(
            db,
            organization=organization,
            agent=agent,
            started_at=START,
            user_id=colleague.id,
            status=RunStatus.AWAITING_APPROVAL.value,
        )
        # Two pending calls on one run are one stuck run, not two.
        for tool in ("send_email", "post_message"):
            db.add(
                ToolApproval(
                    id=uuid.uuid4(),
                    organization_id=organization.id,
                    run_id=parked.id,
                    agent_id=agent.id,
                    tool_id=tool,
                )
            )
        db.add(
            ToolApproval(
                id=uuid.uuid4(),
                organization_id=organization.id,
                run_id=parked.id,
                agent_id=agent.id,
                tool_id="run_sql",
                status=ApprovalStatus.APPROVED.value,
            )
        )
        db.add(
            ToolApproval(
                id=uuid.uuid4(),
                organization_id=organization.id,
                run_id=someone_elses.id,
                agent_id=agent.id,
                tool_id="send_email",
            )
        )
        await db.flush()

        count = await agent_run_repo.count_pending_approval_runs(
            db, organization_id=organization.id, user_id=owner.id
        )

        assert count == 1


class TestSurfacesAndCost:
    async def test_embed_and_mattermost_are_their_own_surface_rows(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Surfaces")
        agent = await _agent(db, organization, owner)
        for surface in (RunSurface.EMBED.value, RunSurface.MATTERMOST.value, RunSurface.WEB.value):
            await _run(
                db, organization=organization, agent=agent, started_at=START, surface=surface
            )

        rows = dict(
            await agent_run_repo.runs_by_dimension(
                db,
                organization_id=organization.id,
                start=START,
                end=END,
                dimension="surface",
            )
        )

        assert rows == {"embed": 1, "mattermost": 1, "web": 1}

    async def test_the_cost_window_sums_only_its_own_days(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Cost")
        agent = await _agent(db, organization, owner)
        await _run(
            db,
            organization=organization,
            agent=agent,
            started_at=START,
            provider="anthropic",
            cost=Decimal("1.5"),
        )
        await _run(
            db,
            organization=organization,
            agent=agent,
            started_at=START,
            provider="openai",
            cost=Decimal("0.5"),
        )
        await _run(
            db,
            organization=organization,
            agent=agent,
            started_at=START - timedelta(days=1),
            provider="anthropic",
            cost=Decimal("9"),
        )

        total = await agent_run_repo.sum_cost_window(
            db, organization_id=organization.id, start=START, end=END
        )
        by_provider = dict(
            await agent_run_repo.cost_by_provider_window(
                db, organization_id=organization.id, start=START, end=END
            )
        )

        assert total == Decimal("2")
        assert by_provider == {"anthropic": Decimal("1.5"), "openai": Decimal("0.5")}


class TestScopedRatings:
    async def _rated_conversation(
        self,
        db,
        *,
        organization: Organization,
        owner_id: uuid.UUID | None,
        rater: User,
        rating: int,
        rated_at: datetime,
    ) -> None:
        conversation = Conversation(
            id=uuid.uuid4(), organization_id=organization.id, user_id=owner_id, title="Chat"
        )
        db.add(conversation)
        await db.flush()
        message = Message(
            id=uuid.uuid4(), conversation_id=conversation.id, role="assistant", content="answer"
        )
        db.add(message)
        await db.flush()
        db.add(
            MessageRating(
                id=uuid.uuid4(),
                message_id=message.id,
                user_id=rater.id,
                rating=rating,
                created_at=rated_at,
            )
        )
        await db.flush()

    async def test_a_rating_in_another_organizations_conversation_is_excluded(self, db) -> None:
        home, home_owner = await _org_with_owner(db, "HomeRatings")
        other, other_owner = await _org_with_owner(db, "OtherRatings")
        in_window = START + timedelta(days=1)
        await self._rated_conversation(
            db,
            organization=home,
            owner_id=home_owner.id,
            rater=home_owner,
            rating=1,
            rated_at=in_window,
        )
        # Owned by the home owner but living in the other tenant - the case an
        # owner-keyed query would leak.
        await self._rated_conversation(
            db,
            organization=other,
            owner_id=home_owner.id,
            rater=home_owner,
            rating=-1,
            rated_at=in_window,
        )

        ctx = AuthContext(
            user_id=home_owner.id, organization_id=home.id, role=OrgRoleName.OWNER.value
        )
        result = await StatsService(db).ratings_summary(
            ctx, from_date=START.date(), to_date=END.date() - timedelta(days=1)
        )

        assert (result.total_ratings, result.like_count, result.dislike_count) == (1, 1, 0)

    async def test_own_scope_sees_only_the_callers_conversations(self, db) -> None:
        organization, owner = await _org_with_owner(db, "OwnRatings")
        colleague = await _user(db)
        db.add(
            OrganizationMember(
                id=uuid.uuid4(),
                organization_id=organization.id,
                user_id=colleague.id,
                role=OrgRoleName.MEMBER.value,
            )
        )
        in_window = START + timedelta(days=1)
        await self._rated_conversation(
            db,
            organization=organization,
            owner_id=colleague.id,
            rater=colleague,
            rating=1,
            rated_at=in_window,
        )
        await self._rated_conversation(
            db,
            organization=organization,
            owner_id=owner.id,
            rater=owner,
            rating=-1,
            rated_at=in_window,
        )

        ctx = AuthContext(
            user_id=colleague.id, organization_id=organization.id, role=OrgRoleName.MEMBER.value
        )
        result = await StatsService(db).ratings_summary(
            ctx, scope="own", from_date=START.date(), to_date=END.date() - timedelta(days=1)
        )

        assert (result.total_ratings, result.like_count) == (1, 1)
        assert result.ratings_by_day == [
            {"date": in_window.date().isoformat(), "likes": 1, "dislikes": 0}
        ]

    async def test_a_rating_outside_the_window_is_not_counted(self, db) -> None:
        organization, owner = await _org_with_owner(db, "WindowRatings")
        await self._rated_conversation(
            db,
            organization=organization,
            owner_id=owner.id,
            rater=owner,
            rating=1,
            rated_at=END + timedelta(days=1),
        )

        ctx = AuthContext(
            user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER.value
        )
        result = await StatsService(db).ratings_summary(
            ctx, from_date=START.date(), to_date=END.date() - timedelta(days=1)
        )

        assert result.total_ratings == 0
        assert result.ratings_by_day == []


class TestVersionRows:
    async def _version(self, db, agent: Agent, number: int) -> AgentVersion:
        version = AgentVersion(
            id=uuid.uuid4(),
            agent_id=agent.id,
            organization_id=agent.organization_id,
            version=number,
            spec={"name": agent.name},
        )
        db.add(version)
        await db.flush()
        return version

    async def test_each_version_aggregates_its_own_runs(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Versions")
        agent = await _agent(db, organization, owner)
        v1 = await self._version(db, agent, 1)
        v2 = await self._version(db, agent, 2)

        for duration, status in ((2, RunStatus.COMPLETED.value), (4, RunStatus.FAILED.value)):
            run = await _run(
                db,
                organization=organization,
                agent=agent,
                started_at=START,
                duration_seconds=duration,
                status=status,
            )
            run.agent_version_id = v1.id
        for _ in range(3):
            run = await _run(
                db,
                organization=organization,
                agent=agent,
                started_at=START,
                duration_seconds=1,
            )
            run.agent_version_id = v2.id
        # A run whose version was deleted afterwards: the id SET-NULLed.
        await _run(db, organization=organization, agent=agent, started_at=START)
        await db.flush()

        rows = await agent_run_repo.usage_by_version(
            db, organization_id=organization.id, agent_id=agent.id, start=START, end=END
        )

        assert [(row[1], row[2], row[3]) for row in rows] == [
            (None, 1, 1),  # the deleted version's run, completed
            (1, 2, 1),  # v1: two runs, one completed
            (2, 3, 3),  # v2: three runs, all completed
        ]
        v1_row = rows[1]
        assert v1_row[4] is not None and round(v1_row[4]) == 3900  # p95 of [2000, 4000]

    async def test_ratings_land_on_the_version_that_produced_the_words(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Rated")
        agent = await _agent(db, organization, owner)
        v1 = await self._version(db, agent, 1)
        v2 = await self._version(db, agent, 2)
        rater = await _user(db)
        conversation = Conversation(
            id=uuid.uuid4(), organization_id=organization.id, user_id=owner.id, title="Chat"
        )
        db.add(conversation)
        await db.flush()

        def message(version_id):
            row = Message(
                id=uuid.uuid4(),
                conversation_id=conversation.id,
                role="assistant",
                content="answer",
                agent_id=agent.id,
                agent_version_id=version_id,
            )
            db.add(row)
            return row

        liked = message(v2.id)
        disliked = message(v2.id)
        old_version = message(v1.id)
        await db.flush()
        in_window = START + timedelta(days=1)
        for row, rating in ((liked, 1), (disliked, -1), (old_version, 1)):
            db.add(
                MessageRating(
                    id=uuid.uuid4(),
                    message_id=row.id,
                    user_id=rater.id,
                    rating=rating,
                    created_at=in_window,
                )
            )
        await db.flush()

        counts = await message_rating_repo.rating_counts_by_version(
            db, version_ids=[v1.id, v2.id], start=START, end=END
        )

        assert counts == {v1.id: (1, 1), v2.id: (1, 2)}

    async def test_the_service_composes_rows_with_their_ratings(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Composed")
        agent = await _agent(db, organization, owner)
        v1 = await self._version(db, agent, 1)
        run = await _run(
            db, organization=organization, agent=agent, started_at=START, duration_seconds=2
        )
        run.agent_version_id = v1.id
        await db.flush()

        ctx = AuthContext(
            user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER.value
        )
        result = await StatsService(db).usage_by_version(
            ctx,
            agent_id=agent.id,
            from_date=START.date(),
            to_date=END.date() - timedelta(days=1),
        )

        assert result.agent_id == agent.id
        assert result.total_runs is None
        assert result.by_version is not None and len(result.by_version) == 1
        row = result.by_version[0]
        assert (row.version, row.runs, row.completed_runs) == (1, 1, 1)
        assert row.p95_ms == 2000
        assert (row.like_count, row.rating_count) == (0, 0)


class TestPersonRows:
    async def test_people_rank_by_runs_and_carry_what_they_cost(self, db) -> None:
        organization, owner = await _org_with_owner(db, "People")
        agent = await _agent(db, organization, owner)
        busy, quiet = await _user(db), await _user(db)

        for _ in range(3):
            await _run(
                db,
                organization=organization,
                agent=agent,
                started_at=START,
                user_id=busy.id,
                cost=Decimal("1.50"),
            )
        await _run(
            db,
            organization=organization,
            agent=agent,
            started_at=START + timedelta(days=2),
            user_id=quiet.id,
            cost=Decimal("0.25"),
        )

        rows = await agent_run_repo.usage_by_user(
            db, organization_id=organization.id, start=START, end=END, limit=10
        )

        assert [(row[0], row[3], row[4]) for row in rows] == [
            (busy.id, 3, Decimal("4.50")),
            (quiet.id, 1, Decimal("0.25")),
        ]
        assert rows[1][5] == START + timedelta(days=2)

    async def test_a_run_with_nobody_behind_it_names_nobody(self, db) -> None:
        """The same rows COUNT(DISTINCT user_id) skips - the two must agree."""
        organization, owner = await _org_with_owner(db, "Anonymous")
        agent = await _agent(db, organization, owner)
        person = await _user(db)
        await _run(db, organization=organization, agent=agent, started_at=START, user_id=person.id)
        await _run(db, organization=organization, agent=agent, started_at=START, user_id=None)

        rows = await agent_run_repo.usage_by_user(
            db, organization_id=organization.id, start=START, end=END, limit=10
        )
        active = await agent_run_repo.count_distinct_users(
            db, organization_id=organization.id, start=START, end=END
        )

        assert [row[0] for row in rows] == [person.id]
        assert active == len(rows)

    async def test_the_limit_keeps_the_busiest_not_an_arbitrary_page(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Limited")
        agent = await _agent(db, organization, owner)
        people = [await _user(db) for _ in range(4)]
        for index, person in enumerate(people):
            for _ in range(index + 1):
                await _run(
                    db,
                    organization=organization,
                    agent=agent,
                    started_at=START,
                    user_id=person.id,
                )

        rows = await agent_run_repo.usage_by_user(
            db, organization_id=organization.id, start=START, end=END, limit=2
        )

        assert [(row[0], row[3]) for row in rows] == [(people[3].id, 4), (people[2].id, 3)]

    async def test_another_organizations_people_are_not_named(self, db) -> None:
        mine, my_owner = await _org_with_owner(db, "Mine")
        theirs, their_owner = await _org_with_owner(db, "Theirs")
        my_agent = await _agent(db, mine, my_owner)
        their_agent = await _agent(db, theirs, their_owner)
        shared_person = await _user(db)
        await _run(
            db, organization=mine, agent=my_agent, started_at=START, user_id=shared_person.id
        )
        for _ in range(9):
            await _run(
                db,
                organization=theirs,
                agent=their_agent,
                started_at=START,
                user_id=shared_person.id,
            )

        rows = await agent_run_repo.usage_by_user(
            db, organization_id=mine.id, start=START, end=END, limit=10
        )

        assert [(row[0], row[3]) for row in rows] == [(shared_person.id, 1)]

    async def test_own_scope_answers_with_the_callers_single_row(self, db) -> None:
        organization, owner = await _org_with_owner(db, "OwnRow")
        agent = await _agent(db, organization, owner)
        someone_else = await _user(db)
        await _run(db, organization=organization, agent=agent, started_at=START, user_id=owner.id)
        for _ in range(5):
            await _run(
                db,
                organization=organization,
                agent=agent,
                started_at=START,
                user_id=someone_else.id,
            )

        ctx = AuthContext(
            user_id=owner.id, organization_id=organization.id, role=OrgRoleName.MEMBER.value
        )
        result = await StatsService(db).usage_by_user(
            ctx,
            scope="own",
            from_date=START.date(),
            to_date=END.date() - timedelta(days=1),
            limit=10,
        )

        assert result.by_user is not None
        assert [(row.user_id, row.runs) for row in result.by_user] == [(owner.id, 1)]
        assert result.total_runs is None


class TestDelegationsAndDoubleCounting:
    """Which side of `include_delegations` each dashboard aggregate takes.

    A delegated run's tokens are already inside its parent's row, so an
    aggregate that counts both bills one run twice - the failure that is
    invisible in a mocked test, because it is a property of the predicate and
    not of the arithmetic above it.
    """

    async def _parent_and_child(
        self, db, organization, agent, child_agent, *, user_id, cost, child_cost
    ):
        parent = await _run(
            db,
            organization=organization,
            agent=agent,
            started_at=START,
            duration_seconds=10,
            user_id=user_id,
            cost=cost,
        )
        child = await _run(
            db,
            organization=organization,
            agent=child_agent,
            started_at=START,
            duration_seconds=1,
            user_id=user_id,
            cost=child_cost,
        )
        child.parent_run_id = parent.id
        await db.flush()
        return parent, child

    async def test_the_period_cost_does_not_bill_a_delegation_twice(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Billing")
        agent = await _agent(db, organization, owner)
        delegate = await _agent(db, organization, owner, slug="researcher")
        await self._parent_and_child(
            db,
            organization,
            agent,
            delegate,
            user_id=owner.id,
            cost=Decimal("1.00"),
            child_cost=Decimal("0.40"),
        )

        total = await agent_run_repo.sum_cost_window(
            db, organization_id=organization.id, start=START, end=END
        )
        by_provider = await agent_run_repo.cost_by_provider_window(
            db, organization_id=organization.id, start=START, end=END
        )

        # The parent's 1.00 already contains the child's 0.40.
        assert total == Decimal("1.00")
        assert sum(cost for _, cost in by_provider) == Decimal("1.00")

    async def test_a_delegation_is_not_a_second_run_a_second_person_or_a_second_arrival(
        self, db
    ) -> None:
        organization, owner = await _org_with_owner(db, "Counting")
        agent = await _agent(db, organization, owner)
        delegate = await _agent(db, organization, owner, slug="researcher")
        await self._parent_and_child(
            db,
            organization,
            agent,
            delegate,
            user_id=owner.id,
            cost=Decimal("1.00"),
            child_cost=Decimal("0.40"),
        )

        assert (
            await agent_run_repo.count_runs(
                db, organization_id=organization.id, start=START, end=END
            )
        ) == 1
        assert (
            await agent_run_repo.count_distinct_users(
                db, organization_id=organization.id, start=START, end=END
            )
        ) == 1
        surfaces = await agent_run_repo.runs_by_dimension(
            db, organization_id=organization.id, start=START, end=END, dimension="surface"
        )
        assert surfaces == [(RunSurface.WEB.value, 1)]
        people = await agent_run_repo.usage_by_user(
            db, organization_id=organization.id, start=START, end=END, limit=10
        )
        assert [(row[0], row[3]) for row in people] == [(owner.id, 1)]

    async def test_the_status_split_still_sums_to_the_total(self, db) -> None:
        """The donut's invariant, which a half-applied filter would break."""
        organization, owner = await _org_with_owner(db, "Donut")
        agent = await _agent(db, organization, owner)
        delegate = await _agent(db, organization, owner, slug="researcher")
        await self._parent_and_child(
            db,
            organization,
            agent,
            delegate,
            user_id=owner.id,
            cost=Decimal("1.00"),
            child_cost=Decimal("0.40"),
        )

        total = await agent_run_repo.count_runs(
            db, organization_id=organization.id, start=START, end=END
        )
        statuses = await agent_run_repo.runs_by_dimension(
            db, organization_id=organization.id, start=START, end=END, dimension="status"
        )

        assert sum(count for _, count in statuses) == total

    async def test_latency_measures_what_the_person_waited_not_the_delegate(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Latency2")
        agent = await _agent(db, organization, owner)
        delegate = await _agent(db, organization, owner, slug="researcher")
        await self._parent_and_child(
            db,
            organization,
            agent,
            delegate,
            user_id=owner.id,
            cost=Decimal("1.00"),
            child_cost=Decimal("0.40"),
        )

        p50, _ = await agent_run_repo.latency_percentiles_ms(
            db, organization_id=organization.id, start=START, end=END
        )

        # The parent's ten seconds, not a median pulled down by the child's one.
        assert p50 == 10000.0

    async def test_a_delegate_only_agent_is_not_reported_as_forgotten(self, db) -> None:
        """The one block that counts delegations, and the reason it does.

        Excluded, this agent has no row, and the adoption card names every
        published agent without one as forgotten and offers to archive it.
        """
        organization, owner = await _org_with_owner(db, "Adoption")
        agent = await _agent(db, organization, owner)
        delegate = await _agent(db, organization, owner, slug="researcher")
        await self._parent_and_child(
            db,
            organization,
            agent,
            delegate,
            user_id=owner.id,
            cost=Decimal("1.00"),
            child_cost=Decimal("0.40"),
        )

        rows = await agent_run_repo.runs_by_agent(
            db, organization_id=organization.id, start=START, end=END
        )

        assert {row[0] for row in rows} == {agent.id, delegate.id}

    async def test_a_delegate_only_agent_can_still_compare_its_versions(self, db) -> None:
        organization, owner = await _org_with_owner(db, "Versions2")
        parent_agent = await _agent(db, organization, owner)
        delegate = await _agent(db, organization, owner, slug="researcher")
        version = AgentVersion(
            id=uuid.uuid4(),
            agent_id=delegate.id,
            organization_id=organization.id,
            version=1,
            spec={"name": delegate.name},
        )
        db.add(version)
        await db.flush()
        _, child = await self._parent_and_child(
            db,
            organization,
            parent_agent,
            delegate,
            user_id=owner.id,
            cost=Decimal("1.00"),
            child_cost=Decimal("0.40"),
        )
        child.agent_version_id = version.id
        await db.flush()

        rows = await agent_run_repo.usage_by_version(
            db, organization_id=organization.id, agent_id=delegate.id, start=START, end=END
        )

        assert [(row[1], row[2]) for row in rows] == [(1, 1)]

    async def test_a_deleted_parent_makes_its_child_count(self, db) -> None:
        """`ondelete=SET NULL`: the cost is no longer inside anything."""
        organization, owner = await _org_with_owner(db, "Orphaned")
        agent = await _agent(db, organization, owner)
        delegate = await _agent(db, organization, owner, slug="researcher")
        parent, _ = await self._parent_and_child(
            db,
            organization,
            agent,
            delegate,
            user_id=owner.id,
            cost=Decimal("1.00"),
            child_cost=Decimal("0.40"),
        )

        await db.delete(parent)
        await db.flush()

        total = await agent_run_repo.sum_cost_window(
            db, organization_id=organization.id, start=START, end=END
        )
        assert total == Decimal("0.40")
