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
