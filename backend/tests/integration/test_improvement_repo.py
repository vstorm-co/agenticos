"""Improvement sessions against Postgres.

What only a database shows:

- an agent holds at most one queued or running session, whatever two writers
  attempt, while a session waiting at `ready` or finished does not block a new one;
- the CHECKs refuse a status, a stage, a stop reason or a verdict nobody defined,
  a round past the limit and negative money;
- a round's number is unique within its session;
- a candidate batch sits beside the agent's open batch without counting as one;
- deleting a session takes its rounds with it and leaves its authoring request;
- and nothing is read across organizations, except by the sweep, which only
  learns which sessions to look at.
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.authoring import AuthoringRequest, BatchStatus, SpecProposalBatch
from app.db.models.dataset import Dataset
from app.db.models.improvement import ImprovementIteration, ImprovementRun, ImprovementStatus
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import improvement_repo

pytestmark = pytest.mark.anyio


async def _org(db: AsyncSession) -> tuple[Organization, User]:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
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
    return org, user


async def _agent(db: AsyncSession, org: Organization, user: User) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=user.id,
        visibility="org",
        slug=f"refunds-{uuid.uuid4().hex[:8]}",
        name="Refund desk",
        status="draft",
        draft_spec={"name": "Refund desk"},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _dataset(db: AsyncSession, org: Organization) -> Dataset:
    dataset = Dataset(id=uuid.uuid4(), organization_id=org.id, name=f"d-{uuid.uuid4().hex[:6]}")
    db.add(dataset)
    await db.flush()
    return dataset


async def _session(
    db: AsyncSession, org: Organization, agent: Agent, user: User, dataset: Dataset
) -> ImprovementRun:
    return await improvement_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        created_by_api_key_id=None,
        base_version_id=None,
        base_draft_hash="a" * 64,
        dataset_id=dataset.id,
        dataset_version=1,
        suite_id=None,
        scoring_hash="s" * 64,
        window_days=30,
        estimate_usd=Decimal("0.04"),
        budget_usd=Decimal("0.04"),
        max_iterations=3,
    )


async def _world(db: AsyncSession) -> tuple[Organization, User, Agent, Dataset]:
    org, user = await _org(db)
    return org, user, await _agent(db, org, user), await _dataset(db, org)


async def _refused(db: AsyncSession, run: ImprovementRun, values: dict[str, Any]) -> None:
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await improvement_repo.update_run(db, run=run, values=values)
    await db.refresh(run)


class TestOneSessionPerAgent:
    async def test_a_second_session_on_a_busy_agent_is_refused(self, db: AsyncSession):
        org, user, agent, dataset = await _world(db)
        await _session(db, org, agent, user, dataset)

        with pytest.raises(IntegrityError, match="uq_improvement_runs_active"):
            async with db.begin_nested():
                await _session(db, org, agent, user, dataset)

    @pytest.mark.parametrize(
        "status", [ImprovementStatus.READY, ImprovementStatus.STOPPED, ImprovementStatus.FAILED]
    )
    async def test_a_ready_or_finished_session_does_not_block_a_new_one(
        self, db: AsyncSession, status: ImprovementStatus
    ):
        org, user, agent, dataset = await _world(db)
        first = await _session(db, org, agent, user, dataset)
        await improvement_repo.update_run(db, run=first, values={"status": status.value})

        second = await _session(db, org, agent, user, dataset)

        active = await improvement_repo.get_active(db, organization_id=org.id, agent_id=agent.id)
        assert active is not None
        assert active.id == second.id

    async def test_sessions_on_different_agents_run_side_by_side(self, db: AsyncSession):
        org, user, agent, dataset = await _world(db)
        other = await _agent(db, org, user)

        await _session(db, org, agent, user, dataset)
        await _session(db, org, other, user, dataset)

        assert await improvement_repo.get_active(db, organization_id=org.id, agent_id=other.id)


class TestChecks:
    @pytest.mark.parametrize(
        "values",
        [
            {"status": "paused"},
            {"stage": "publishing"},
            {"stop_reason": "bored"},
            {"iteration": 4},
            {"max_iterations": 11},
            {"spent_usd": Decimal("-0.01")},
            {"budget_usd": Decimal("-1")},
        ],
        ids=["status", "stage", "stop-reason", "past-limit", "limit", "spent", "budget"],
    )
    async def test_a_value_nobody_defined_is_refused(
        self, db: AsyncSession, values: dict[str, Any]
    ):
        org, user, agent, dataset = await _world(db)
        run = await _session(db, org, agent, user, dataset)

        await _refused(db, run, values)

    async def test_a_round_is_numbered_once_per_session(self, db: AsyncSession):
        org, user, agent, dataset = await _world(db)
        run = await _session(db, org, agent, user, dataset)
        await improvement_repo.create_iteration(db, organization_id=org.id, run_id=run.id, number=1)

        with pytest.raises(IntegrityError, match="uq_improvement_iterations_number"):
            async with db.begin_nested():
                await improvement_repo.create_iteration(
                    db, organization_id=org.id, run_id=run.id, number=1
                )

    @pytest.mark.parametrize(
        "values",
        [{"verdict": "great"}, {"cost_usd": Decimal("-0.01")}],
        ids=["verdict", "cost"],
    )
    async def test_a_round_refuses_an_unknown_verdict_and_negative_cost(
        self, db: AsyncSession, values: dict[str, Any]
    ):
        org, user, agent, dataset = await _world(db)
        run = await _session(db, org, agent, user, dataset)
        iteration = await improvement_repo.create_iteration(
            db, organization_id=org.id, run_id=run.id, number=1
        )

        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await improvement_repo.update_iteration(db, iteration=iteration, values=values)


class TestRounds:
    async def test_a_round_records_its_children_and_verdict(self, db: AsyncSession):
        org, user, agent, dataset = await _world(db)
        run = await _session(db, org, agent, user, dataset)
        second = await improvement_repo.create_iteration(
            db, organization_id=org.id, run_id=run.id, number=2
        )
        first = await improvement_repo.create_iteration(
            db, organization_id=org.id, run_id=run.id, number=1
        )
        checks = [uuid.uuid4(), uuid.uuid4()]

        await improvement_repo.update_iteration(
            db,
            iteration=first,
            values={
                "eval_run_ids": checks,
                "dropped": [{"hunk_id": str(uuid.uuid4()), "reason": "weakens_guardrail"}],
                "verdict": "better",
                "verdict_detail": {"fixed": 3, "broken": 0},
                "cost_usd": Decimal("0.03"),
            },
        )
        await improvement_repo.update_run(db, run=run, values={"best_iteration_id": first.id})

        rounds = await improvement_repo.list_iterations(db, organization_id=org.id, run_id=run.id)
        found = await improvement_repo.get_iteration(
            db, organization_id=org.id, run_id=run.id, number=1
        )
        assert [r.id for r in rounds] == [first.id, second.id]
        assert found is not None
        assert found.eval_run_ids == checks
        assert found.verdict_detail == {"fixed": 3, "broken": 0}
        assert second.dropped == []
        assert second.dropped_hunk_ids == []
        assert run.best_iteration_id == first.id

    async def test_deleting_a_session_takes_its_rounds_and_keeps_its_request(
        self, db: AsyncSession
    ):
        org, user, agent, dataset = await _world(db)
        run = await _session(db, org, agent, user, dataset)
        request = AuthoringRequest(
            organization_id=org.id,
            kind="improve",
            target="agent",
            agent_id=agent.id,
            status="completed",
            estimate_usd=Decimal(0),
            window_days=30,
            evidence={},
            improvement_run_id=run.id,
        )
        db.add(request)
        await db.flush()
        iteration = await improvement_repo.create_iteration(
            db, organization_id=org.id, run_id=run.id, number=1
        )
        await improvement_repo.update_iteration(
            db, iteration=iteration, values={"authoring_request_id": request.id}
        )
        await improvement_repo.update_run(db, run=run, values={"best_iteration_id": iteration.id})

        await db.delete(run)
        await db.flush()
        await db.refresh(request)

        left = await db.scalar(
            select(ImprovementIteration).where(ImprovementIteration.id == iteration.id)
        )
        assert left is None
        assert request.improvement_run_id is None


class TestPins:
    async def test_a_pin_outlives_the_dataset_and_suite_it_names(self, db: AsyncSession):
        """Deleting what a session is pinned to must not erase the pin, or nothing goes stale."""
        org, user, agent, dataset = await _world(db)
        run = await _session(db, org, agent, user, dataset)
        suite_id = uuid.uuid4()
        await improvement_repo.update_run(db, run=run, values={"suite_id": suite_id})

        await db.delete(dataset)
        await db.flush()
        await db.refresh(run)

        assert run.dataset_id == dataset.id
        assert run.suite_id == suite_id

    async def test_deleting_the_agent_takes_its_sessions(self, db: AsyncSession):
        org, user, agent, dataset = await _world(db)
        run = await _session(db, org, agent, user, dataset)
        await improvement_repo.create_iteration(db, organization_id=org.id, run_id=run.id, number=1)

        await db.delete(agent)
        await db.flush()
        db.expunge_all()

        assert await improvement_repo.get_run(db, run.id, organization_id=org.id) is None
        assert (
            await improvement_repo.list_iterations(db, organization_id=org.id, run_id=run.id) == []
        )


class TestCandidateBatch:
    async def test_a_candidate_sits_beside_the_open_batch(self, db: AsyncSession):
        org, user, agent, dataset = await _world(db)
        run = await _session(db, org, agent, user, dataset)

        def batch(status: BatchStatus) -> SpecProposalBatch:
            return SpecProposalBatch(
                organization_id=org.id,
                agent_id=agent.id,
                source_started_at=run.created_at,
                status=status.value,
                improvement_run_id=None if status is BatchStatus.OPEN else run.id,
            )

        db.add_all([batch(BatchStatus.OPEN), batch(BatchStatus.CANDIDATE)])
        await db.flush()
        db.add(batch(BatchStatus.CANDIDATE))
        await db.flush()

        statuses = (
            await db.scalars(
                select(SpecProposalBatch.status).where(SpecProposalBatch.agent_id == agent.id)
            )
        ).all()
        assert sorted(statuses) == ["candidate", "candidate", "open"]


class TestOrganizations:
    async def test_nothing_is_read_across_organizations(self, db: AsyncSession):
        org, user, agent, dataset = await _world(db)
        other, _ = await _org(db)
        run = await _session(db, org, agent, user, dataset)
        await improvement_repo.create_iteration(db, organization_id=org.id, run_id=run.id, number=1)

        assert await improvement_repo.get_run(db, run.id, organization_id=other.id) is None
        assert (
            await improvement_repo.get_active(db, organization_id=other.id, agent_id=agent.id)
            is None
        )
        assert (
            await improvement_repo.list_for_agent(db, organization_id=other.id, agent_id=agent.id)
            == []
        )
        assert (
            await improvement_repo.list_iterations(db, organization_id=other.id, run_id=run.id)
            == []
        )
        assert (
            await improvement_repo.get_iteration(
                db, organization_id=other.id, run_id=run.id, number=1
            )
            is None
        )

    async def test_a_session_is_read_and_locked_in_its_own_organization(self, db: AsyncSession):
        org, user, agent, dataset = await _world(db)
        older = await _session(db, org, agent, user, dataset)
        await improvement_repo.update_run(
            db,
            run=older,
            values={
                "status": ImprovementStatus.STOPPED.value,
                "created_at": older.created_at - timedelta(hours=1),
            },
        )
        newer = await _session(db, org, agent, user, dataset)

        locked = await improvement_repo.get_run(db, newer.id, organization_id=org.id, lock=True)
        listed = await improvement_repo.list_for_agent(
            db, organization_id=org.id, agent_id=agent.id
        )

        assert locked is not None
        assert locked.id == newer.id
        assert [r.id for r in listed] == [newer.id, older.id]

    async def test_the_sweep_sees_moving_sessions_in_every_organization(self, db: AsyncSession):
        org, user, agent, dataset = await _world(db)
        other_org, other_user, other_agent, other_dataset = await _world(db)
        queued = await _session(db, org, agent, user, dataset)
        running = await _session(db, other_org, other_agent, other_user, other_dataset)
        await improvement_repo.update_run(
            db, run=running, values={"status": ImprovementStatus.RUNNING.value}
        )
        ready = await _session(db, org, await _agent(db, org, user), user, dataset)
        await improvement_repo.update_run(
            db, run=ready, values={"status": ImprovementStatus.READY.value}
        )

        found = await improvement_repo.list_active(db)

        assert (queued.id, org.id) in found
        assert (running.id, other_org.id) in found
        assert (ready.id, org.id) not in found

    async def test_the_sweep_pages_through_waiting_sessions(self, db: AsyncSession):
        """A waiting session never changes on its own, so a fixed first page would starve the rest."""
        org, user, _, dataset = await _world(db)
        waiting = []
        for status in (
            ImprovementStatus.READY,
            ImprovementStatus.ACCEPTED,
            ImprovementStatus.READY,
        ):
            run = await _session(db, org, await _agent(db, org, user), user, dataset)
            await improvement_repo.update_run(db, run=run, values={"status": status.value})
            waiting.append(run.id)
        finished = await _session(db, org, await _agent(db, org, user), user, dataset)
        await improvement_repo.update_run(
            db, run=finished, values={"status": ImprovementStatus.PUBLISHED.value}
        )
        mine = set(waiting)

        pages: list[uuid.UUID] = []
        after = None
        while True:
            page = await improvement_repo.list_waiting(db, after=after, limit=1)
            if not page:
                break
            pages.extend(run_id for run_id, _ in page)
            after = page[-1][0]

        assert [run_id for run_id in pages if run_id in mine] == sorted(waiting)
        assert finished.id not in pages


async def test_rows_describe_themselves(db: AsyncSession):
    org, user, agent, dataset = await _world(db)
    run = await _session(db, org, agent, user, dataset)
    iteration = await improvement_repo.create_iteration(
        db, organization_id=org.id, run_id=run.id, number=1
    )

    assert repr(run) == (
        f"<ImprovementRun(id={run.id}, agent={agent.id}, status=queued, stage=None)>"
    )
    assert repr(iteration) == (
        f"<ImprovementIteration(id={iteration.id}, run={run.id}, number=1, verdict=None)>"
    )
