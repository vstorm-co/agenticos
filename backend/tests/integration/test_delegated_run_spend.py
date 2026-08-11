"""What a delegated run row does to every spend total, against Postgres.

A run has one spend ledger, so a delegate's tokens are already inside the parent
run's `cost_usd`. That makes the child row a second copy of the same money - and
the two questions asked of it want opposite answers:

* the **organization's** money is the bill, so it must skip the child row;
* the **delegate's own** spend is what its cap meters, and the child rows are the
  only place that spend is recorded at all.

Five queries read `agent_runs.cost_usd` and every one of them has to say which of
those two it is answering. `sum_cost_since` did from the start; `cost_breakdown`,
`spend_by_provider` and `spend_by_key` did not, and the consequence was two live
wrong numbers - a dashboard whose three breakdowns each totalled more than the
month-to-date figure printed above them, and a usage email that billed an
organization $1.40 for $1.00 of work. That hole is why the sibling queries are
covered here beside the one that always was.

A mock cannot tell you which rows a `WHERE` actually returned, and it certainly
cannot tell you what `ON DELETE SET NULL` does to the arithmetic afterwards.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.user import User
from app.repositories import agent_run_repo
from app.services.agent_runner import AgentRunnerService
from app.services.spend import month_start, organization_monthly_spend

pytestmark = pytest.mark.anyio


async def _org(db) -> Organization:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="owner")
    )
    await db.flush()
    return org


async def _agent(db, org: Organization, *, slug: str) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=slug,
        name=slug.title(),
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _run(
    db,
    *,
    org: Organization,
    agent: Agent,
    cost: Decimal,
    secret: OrganizationSecret | None = None,
    partial: bool = False,
) -> AgentRun:
    """A run somebody started, opened and finished the way every surface does.

    On OpenAI, because the delegate below runs on Anthropic: the provider split is
    where double-counting is least visible - the same money appears under two
    vendors at once, and each looks plausible on its own.

    `partial` is what the run's ledger answered about pricing, which is a question
    about the whole tree: a delegate on a model with no price makes this row a
    floor too, because parent and delegate book into one ledger.
    """
    run = await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=None,
        user_id=None,
        conversation_id=None,
        surface="api",
        model_label="gpt-4.1",
        provider="openai",
        secret_id=None if secret is None else secret.id,
        started_at=datetime.now(UTC),
    )
    return await agent_run_repo.finish_run(
        db,
        run=run,
        status=RunStatus.COMPLETED.value,
        input_tokens=1000,
        output_tokens=100,
        cost_usd=cost,
        cost_is_partial=partial,
        ended_at=datetime.now(UTC),
    )


async def _delegated(
    db,
    *,
    org: Organization,
    agent: Agent,
    version: AgentVersion,
    parent: AgentRun,
    cost: Decimal,
    task_id: str = "4f2a1b8c",
    secret: OrganizationSecret | None = None,
    partial: bool = False,
) -> AgentRun:
    """A delegation, written the way `finish` writes one: complete, in one insert.

    The id is supplied, as it is in production - the parent's model was handed it
    while the run was still going - and the foreign key is the thing this proves:
    the parent's row has to exist by the time these are written.
    """
    moment = datetime.now(UTC)
    return await agent_run_repo.record_delegated_run(
        db,
        run_id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        parent_run_id=parent.id,
        subagent_task_id=task_id,
        user_id=None,
        conversation_id=None,
        exposure_id=None,
        surface="api",
        model_label="claude-sonnet-4-5",
        provider="anthropic",
        secret_id=None if secret is None else secret.id,
        status=RunStatus.COMPLETED.value,
        input_tokens=500,
        output_tokens=50,
        cost_usd=cost,
        # This delegation's own requests, not the run's - the parent carries the
        # tree's answer, and both are written from the one terminal write.
        cost_is_partial=partial,
        started_at=moment,
        ended_at=moment,
    )


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


async def _secret(db, org: Organization, *, name: str) -> OrganizationSecret:
    """A stored key, so `spend_by_key` has a label to group under."""
    secret = OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=name,
        kind="api_key",
        purpose="openai",
        sealed_secret="sealed",
        hint="sk-...ab",
    )
    db.add(secret)
    await db.flush()
    return secret


@dataclass(frozen=True)
class _Delegated:
    """One $1.00 parent run, $0.40 of which a delegate on another vendor spent."""

    org: Organization
    orchestrator: Agent
    researcher: Agent
    key: OrganizationSecret


async def _one_delegated_request(db) -> _Delegated:
    org = await _org(db)
    orchestrator = await _agent(db, org, slug="orchestrator")
    researcher = await _agent(db, org, slug="researcher")
    key = await _secret(db, org, name="Shared key")
    parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("1.00"), secret=key)
    await _delegated(
        db,
        org=org,
        agent=researcher,
        version=await _version(db, researcher),
        parent=parent,
        cost=Decimal("0.40"),
        secret=key,
    )
    return _Delegated(org=org, orchestrator=orchestrator, researcher=researcher, key=key)


class TestTheTwoTotals:
    async def test_the_organizations_month_counts_the_parent_once(self, db):
        """Both rows would bill the organization twice for one request."""
        org = await _org(db)
        orchestrator = await _agent(db, org, slug="orchestrator")
        researcher = await _agent(db, org, slug="researcher")
        parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("1.00"))
        await _delegated(
            db,
            org=org,
            agent=researcher,
            version=await _version(db, researcher),
            parent=parent,
            cost=Decimal("0.40"),
        )

        assert await organization_monthly_spend(db, org.id) == Decimal("1.00")

    async def test_the_delegates_own_month_counts_the_run_it_was_delegated_into(self, db):
        """It is the only record of what the researcher itself cost, and what a
        budget alert on that agent has to fire on."""
        org = await _org(db)
        orchestrator = await _agent(db, org, slug="orchestrator")
        researcher = await _agent(db, org, slug="researcher")
        parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("1.00"))
        await _delegated(
            db,
            org=org,
            agent=researcher,
            version=await _version(db, researcher),
            parent=parent,
            cost=Decimal("0.40"),
        )

        delegated = await agent_run_repo.sum_cost_since(
            db,
            organization_id=org.id,
            since=month_start(),
            agent_id=researcher.id,
            include_delegations=True,
        )
        # And without it the agent's own spend is invisible, which is the state
        # this pair exists to keep apart.
        top_level_only = await agent_run_repo.sum_cost_since(
            db, organization_id=org.id, since=month_start(), agent_id=researcher.id
        )

        assert (delegated, top_level_only) == (Decimal("0.40"), Decimal("0"))

    async def test_a_delegation_row_stays_inside_its_own_tenant(self, db):
        """The delegate's month is read against the caller's organization, so a
        row in another one is not in it however the ids line up."""
        mine, theirs = await _org(db), await _org(db)
        researcher = await _agent(db, mine, slug="researcher")
        parent = await _run(db, org=mine, agent=researcher, cost=Decimal("1.00"))
        await _delegated(
            db,
            org=mine,
            agent=researcher,
            version=await _version(db, researcher),
            parent=parent,
            cost=Decimal("0.40"),
        )

        assert await organization_monthly_spend(db, theirs.id) == Decimal("0")


class TestTheThreeBreakdowns:
    """`cost_breakdown`, `spend_by_provider` and `spend_by_key`, which had no null
    test at all - so each returned $1.40 for $1.00 of work, in the same payload as
    the $1.00 the budget enforces."""

    async def test_the_per_agent_breakdown_totals_the_bill(self, db):
        """Rendered directly beside `month_to_date_usd` on one screen. A breakdown
        summing to more than the total above it is not a rounding difference - it is
        the delegate's $0.40 counted twice, once inside the parent's row and once as
        its own."""
        fixture = await _one_delegated_request(db)

        rows = await agent_run_repo.cost_breakdown(
            db, organization_id=fixture.org.id, since=month_start()
        )

        assert sum(row[2] for row in rows) == Decimal("1.00")
        assert [(row[0], row[2], row[3]) for row in rows] == [
            (fixture.orchestrator.id, Decimal("1.00"), 1)
        ]

    async def test_the_per_agent_breakdown_can_be_asked_for_the_delegates_own_spend(self, db):
        """The one question that wants the child rows: what did the researcher cost.
        Its own runs are the only record, and this is what the per-agent usage email
        reports."""
        fixture = await _one_delegated_request(db)

        rows = await agent_run_repo.cost_breakdown(
            db,
            organization_id=fixture.org.id,
            since=month_start(),
            include_delegations=True,
        )

        assert {row[0]: row[2] for row in rows} == {
            fixture.orchestrator.id: Decimal("1.00"),
            fixture.researcher.id: Decimal("0.40"),
        }

    async def test_each_vendor_is_paid_its_own_share_and_only_its_own(self, db):
        """The least visible of the three, and it has now been wrong twice in
        opposite directions.

        Counting every row billed OpenAI $1.00 and Anthropic $0.40 for $1.00 of
        work - each figure plausible next to the other. Counting only top-level
        rows totalled correctly and attributed the delegate's $0.40 to the
        *parent's* vendor, because that is the provider on the row being summed:
        Anthropic did not appear at all, and nothing on screen could say so
        (#194).

        Own spend per row answers both at once. $0.60 stayed at OpenAI, $0.40 went
        to Anthropic, and the two add up to the bill."""
        fixture = await _one_delegated_request(db)

        rows = await agent_run_repo.spend_by_provider(
            db, organization_id=fixture.org.id, since=month_start()
        )

        assert {provider: cost for provider, cost, _runs in rows} == {
            "openai": Decimal("0.60"),
            "anthropic": Decimal("0.40"),
        }
        assert sum(cost for _provider, cost, _runs in rows) == Decimal("1.00")

    async def test_a_key_is_charged_once_for_the_whole_request(self, db):
        """One key paid for both rows here, which is the ordinary case: a delegate
        usually runs on the organization's key too. Own spend per row means the two
        halves reassemble into one figure rather than doubling it - and a delegate
        on a *different* key would now show up under that one."""
        fixture = await _one_delegated_request(db)

        rows = await agent_run_repo.spend_by_key(
            db, organization_id=fixture.org.id, since=month_start()
        )

        assert [(row[0], row[1], row[2]) for row in rows] == [
            (fixture.key.id, "Shared key", Decimal("1.00"))
        ]

    async def test_a_delegate_on_its_own_key_appears_under_that_key(self, db):
        """The case #194 named and the old shape could not express. Attributing a
        delegate's spend to the key its *parent* used is the same error as
        attributing it to the parent's vendor, and it matters more here: a key is
        what somebody rotates or revokes when a bill looks wrong."""
        org = await _org(db)
        orchestrator = await _agent(db, org, slug="orchestrator")
        researcher = await _agent(db, org, slug="researcher")
        shared = await _secret(db, org, name="Shared key")
        theirs = await _secret(db, org, name="Research key")
        parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("1.00"), secret=shared)
        await _delegated(
            db,
            org=org,
            agent=researcher,
            version=await _version(db, researcher),
            parent=parent,
            cost=Decimal("0.40"),
            secret=theirs,
        )

        rows = await agent_run_repo.spend_by_key(db, organization_id=org.id, since=month_start())

        assert {label: cost for _id, label, cost, _runs in rows} == {
            "Shared key": Decimal("0.60"),
            "Research key": Decimal("0.40"),
        }

    async def test_a_delegation_two_levels_deep_is_subtracted_once(self, db):
        """Own spend nests. A delegate that delegates further has its own
        grandchildren taken out by it, not twice and not by its parent - otherwise
        the middle level's share would be removed at both levels and the totals
        would come to less than the bill."""
        org = await _org(db)
        top = await _agent(db, org, slug="orchestrator")
        middle = await _agent(db, org, slug="researcher")
        bottom = await _agent(db, org, slug="summariser")
        parent = await _run(db, org=org, agent=top, cost=Decimal("1.00"))
        child = await _delegated(
            db,
            org=org,
            agent=middle,
            version=await _version(db, middle),
            parent=parent,
            cost=Decimal("0.40"),
        )
        await _delegated(
            db,
            org=org,
            agent=bottom,
            version=await _version(db, bottom),
            parent=child,
            cost=Decimal("0.15"),
            task_id="9c1d2e3f",
        )

        rows = await agent_run_repo.spend_by_provider(
            db, organization_id=org.id, since=month_start()
        )

        # 1.00 - 0.40 at the top, then 0.40 - 0.15 in the middle and 0.15 at the
        # bottom - the last two on the same vendor, so 0.40 of the 1.00.
        assert {provider: cost for provider, cost, _runs in rows} == {
            "openai": Decimal("0.60"),
            "anthropic": Decimal("0.40"),
        }
        assert sum(cost for _provider, cost, _runs in rows) == await organization_monthly_spend(
            db, org.id
        )

    async def test_every_breakdown_agrees_with_the_bill(self, db):
        """The invariant the three defaults exist for, asserted as one statement.
        Three numbers on one screen that each disagree with the total above them is
        a dashboard nobody can act on - and the fourth of them was emailed."""
        fixture = await _one_delegated_request(db)
        since = month_start()

        by_agent = await agent_run_repo.cost_breakdown(
            db, organization_id=fixture.org.id, since=since
        )
        by_provider = await agent_run_repo.spend_by_provider(
            db, organization_id=fixture.org.id, since=since
        )
        by_key = await agent_run_repo.spend_by_key(db, organization_id=fixture.org.id, since=since)

        bill = await organization_monthly_spend(db, fixture.org.id)
        assert bill == Decimal("1.00")
        assert sum(row[2] for row in by_agent) == bill
        assert sum(row[1] for row in by_provider) == bill
        assert sum(row[2] for row in by_key) == bill


class TestTheCostScreen:
    """Every figure `GET /api/v1/runs/spend` puts on one page, read through the
    service that answers it - because the defect was not one query being wrong, it
    was four numbers rendered together that did not agree."""

    async def test_the_four_numbers_on_one_screen_agree(self, db):
        """`month_to_date_usd` and the three breakdowns beside it. Each of the three
        used to total $1.40 above a month-to-date of $1.00, which is not a figure
        anybody can act on: it makes both numbers suspect and neither checkable.
        """
        fixture = await _one_delegated_request(db)
        service = AgentRunnerService(db)
        ctx = AuthContext(user_id=None, organization_id=fixture.org.id, role=OrgRoleName.OWNER)

        month_to_date = await service.monthly_spend(ctx)
        by_agent = await service.spend_by_agent(ctx, since=month_start())
        by_provider = await service.spend_by_provider(ctx, since=month_start())
        by_key = await service.spend_by_key(ctx, since=month_start())

        assert month_to_date == Decimal("1.00")
        # `spend_by_agent.cost_usd` is the window column the screen renders -
        # top-level runs only - so it sums to the bill. The email's per-model
        # `cost_breakdown` is a different question and is not what this screen shows.
        assert sum(row.cost_usd for row in by_agent) == month_to_date
        assert sum(row[1] for row in by_provider) == month_to_date
        assert sum(row[2] for row in by_key) == month_to_date

    async def test_an_unpriced_delegate_is_marked_above_the_splits_it_makes_a_floor(self, db):
        """No breakdown on this page is a floor without a figure on it saying so.

        The caveat counts top-level runs; By provider and By key sum every row's
        own spend, delegated rows included (#194). So an unpriced *delegate* makes
        those two a floor through a row the caveat never looks at, and the figure
        would read 0 above them if the delegation's row were the only one carrying
        that unpriced request.

        It is not. A tree shares one spend ledger, so the request is in the
        parent's ledger too and the parent's row is written a floor as well -
        which is what keeps the count non-zero above the vendor it marks (#597).
        """
        org = await _org(db)
        orchestrator = await _agent(db, org, slug="orchestrator")
        researcher = await _agent(db, org, slug="researcher")
        key = await _secret(db, org, name="Shared key")
        parent = await _run(
            db, org=org, agent=orchestrator, cost=Decimal("1.00"), secret=key, partial=True
        )
        await _delegated(
            db,
            org=org,
            agent=researcher,
            version=await _version(db, researcher),
            parent=parent,
            cost=Decimal("0.40"),
            secret=key,
            partial=True,
        )
        service = AgentRunnerService(db)
        ctx = AuthContext(user_id=None, organization_id=org.id, role=OrgRoleName.OWNER)

        by_agent = await service.spend_by_agent(ctx, since=month_start())
        by_provider = await service.spend_by_provider(ctx, since=month_start())

        # The sum the route renders above all three breakdowns.
        assert sum(row.partial_run_count for row in by_agent) == 1
        # And the figure it is a caveat about: Anthropic's share is the delegate's
        # own spend, so that row is the floor the count above it is announcing.
        assert {provider: cost for provider, cost, _runs in by_provider}["anthropic"] == Decimal(
            "0.40"
        )

    async def test_the_caveat_counts_trees_rather_than_the_rows_the_splits_sum(self, db):
        """One parent, two unpriced delegates, and the figure reads 1.

        Its magnitude is top-level runs - which is what "3 of 40 runs" is counted
        out of - so it marks By provider and By key without measuring them. The
        delegate's own row is counted nowhere: its agent's `partial_run_count` is
        the top-level runs *it* started, and it started none.
        """
        org = await _org(db)
        orchestrator = await _agent(db, org, slug="orchestrator")
        researcher = await _agent(db, org, slug="researcher")
        version = await _version(db, researcher)
        parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("1.00"), partial=True)
        for cost, task_id in ((Decimal("0.40"), "4f2a1b8c"), (Decimal("0.30"), "9c1d2e3f")):
            await _delegated(
                db,
                org=org,
                agent=researcher,
                version=version,
                parent=parent,
                cost=cost,
                task_id=task_id,
                partial=True,
            )
        ctx = AuthContext(user_id=None, organization_id=org.id, role=OrgRoleName.OWNER)

        by_agent = await AgentRunnerService(db).spend_by_agent(ctx, since=month_start())

        assert {row.agent_name: row.partial_run_count for row in by_agent} == {
            "Orchestrator": 1,
            "Researcher": 0,
        }

    async def test_the_delegates_own_month_is_still_its_own_spend(self, db):
        """The same service, the other question: what a budget alert on the
        researcher fires on, and the number its own cap is metered against."""
        fixture = await _one_delegated_request(db)
        ctx = AuthContext(user_id=None, organization_id=fixture.org.id, role=OrgRoleName.OWNER)

        spent = await AgentRunnerService(db).monthly_spend(ctx, agent_id=fixture.researcher.id)

        assert spent == Decimal("0.40")


class TestWhatRunHistoryLists:
    """The page and the bill have to be readable side by side.

    `organization_monthly_spend` counts the parent once. A list that interleaved
    the children put four rows and an additive cost column next to that figure,
    which is the contradiction #181 reports - so the list carries the same
    default, and the total counts what the page shows.
    """

    async def test_a_fan_out_turn_lists_as_one_run(self, db):
        org = await _org(db)
        orchestrator = await _agent(db, org, slug="orchestrator")
        researcher = await _agent(db, org, slug="researcher")
        version = await _version(db, researcher)
        parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("1.00"))
        for task_id in ("4f2a1b8c", "9abbab49", "c07de1a2"):
            await _delegated(
                db,
                org=org,
                agent=researcher,
                version=version,
                parent=parent,
                cost=Decimal("0.40"),
                task_id=task_id,
            )

        items, total = await agent_run_repo.list_runs(db, organization_id=org.id)

        # One row, and a total that agrees with it - not four rows summing to
        # $2.20 beside a month-to-date of $1.00.
        assert [run.id for run in items] == [parent.id]
        assert total == 1

    async def test_asking_for_one_runs_delegations_returns_them_and_nothing_else(self, db):
        """The query `agent_runs_parent_run_id_idx` was created for."""
        org = await _org(db)
        orchestrator = await _agent(db, org, slug="orchestrator")
        researcher = await _agent(db, org, slug="researcher")
        version = await _version(db, researcher)
        parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("1.00"))
        other_parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("2.00"))
        mine = await _delegated(
            db, org=org, agent=researcher, version=version, parent=parent, cost=Decimal("0.40")
        )
        await _delegated(
            db,
            org=org,
            agent=researcher,
            version=version,
            parent=other_parent,
            cost=Decimal("0.70"),
            task_id="9abbab49",
        )

        items, total = await agent_run_repo.list_runs(
            db, organization_id=org.id, parent_run_id=parent.id
        )

        assert [run.id for run in items] == [mine.id]
        assert total == 1

    async def test_one_agents_history_contains_what_it_did_as_a_delegate(self, db):
        """The other half of the same arithmetic `sum_cost_since` already has.

        A delegate's rows are the only record of what it itself did, so an agent
        that only ever runs as somebody's delegate has no history at all without
        them - beside a per-agent spend figure that is not zero, which is the
        contradiction in the other direction."""
        org = await _org(db)
        orchestrator = await _agent(db, org, slug="orchestrator")
        researcher = await _agent(db, org, slug="researcher")
        parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("1.00"))
        child = await _delegated(
            db,
            org=org,
            agent=researcher,
            version=await _version(db, researcher),
            parent=parent,
            cost=Decimal("0.40"),
        )

        included, total = await agent_run_repo.list_runs(
            db, organization_id=org.id, agent_id=researcher.id, include_delegations=True
        )
        excluded, _ = await agent_run_repo.list_runs(
            db, organization_id=org.id, agent_id=researcher.id
        )

        assert [run.id for run in included] == [child.id]
        assert total == 1
        assert excluded == []

    async def test_a_named_parent_wins_over_including_delegations(self, db):
        """Otherwise "what did this run delegate" would answer with every
        delegation in the organization."""
        org = await _org(db)
        orchestrator = await _agent(db, org, slug="orchestrator")
        researcher = await _agent(db, org, slug="researcher")
        version = await _version(db, researcher)
        parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("1.00"))
        elsewhere = await _run(db, org=org, agent=orchestrator, cost=Decimal("2.00"))
        mine = await _delegated(
            db, org=org, agent=researcher, version=version, parent=parent, cost=Decimal("0.40")
        )
        await _delegated(
            db,
            org=org,
            agent=researcher,
            version=version,
            parent=elsewhere,
            cost=Decimal("0.70"),
            task_id="9abbab49",
        )

        items, total = await agent_run_repo.list_runs(
            db, organization_id=org.id, parent_run_id=parent.id, include_delegations=True
        )

        assert [run.id for run in items] == [mine.id]
        assert total == 1

    async def test_another_tenants_run_delegates_nothing_to_this_caller(self, db):
        """A parent id is guessable; the organization filter is what refuses it."""
        mine, theirs = await _org(db), await _org(db)
        researcher = await _agent(db, theirs, slug="researcher")
        parent = await _run(db, org=theirs, agent=researcher, cost=Decimal("1.00"))
        await _delegated(
            db,
            org=theirs,
            agent=researcher,
            version=await _version(db, researcher),
            parent=parent,
            cost=Decimal("0.40"),
        )

        items, total = await agent_run_repo.list_runs(
            db, organization_id=mine.id, parent_run_id=parent.id
        )

        assert (items, total) == ([], 0)


class TestDeletingTheParent:
    async def test_the_delegation_keeps_its_cost_and_starts_counting(self, db):
        """`SET NULL`, not `CASCADE`, and the reason is arithmetic. The row that
        contained this cost is gone, so a delegation that becomes top-level is
        one that should start counting - and cascading would delete the record of
        money that was spent."""
        org = await _org(db)
        orchestrator = await _agent(db, org, slug="orchestrator")
        researcher = await _agent(db, org, slug="researcher")
        parent = await _run(db, org=org, agent=orchestrator, cost=Decimal("1.00"))
        child = await _delegated(
            db,
            org=org,
            agent=researcher,
            version=await _version(db, researcher),
            parent=parent,
            cost=Decimal("0.40"),
        )

        await db.delete(parent)
        await db.flush()
        await db.refresh(child)

        assert (child.parent_run_id, child.cost_usd) == (None, Decimal("0.40"))
        assert await organization_monthly_spend(db, org.id) == Decimal("0.40")
