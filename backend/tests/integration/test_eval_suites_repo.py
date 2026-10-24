"""Eval suite rows against Postgres - coalescing, claiming and what each suite last did.

The claims a mocked session cannot make:

- a second waiting result for the same suite and version is absorbed, and one
  that arrives while the suite runs is kept for the next run;
- a suite still running leaves its next result waiting, and a claimed row is
  skipped by a second claim;
- a running result is settled once its eval run has ended, or is gone;
- a paused suite forgets what it was waiting to run;
- nothing is readable across organizations.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.eval_run import EvalRun, EvalRunStatus
from app.db.models.eval_suite import EvalSuite, EvalSuiteResult, EvalSuiteResultStatus
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import dataset_repo, eval_suite_repo
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.services.dataset import DatasetService

pytestmark = pytest.mark.anyio

_NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


async def _owner(db: AsyncSession) -> AuthContext:
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
    return AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER.value)


async def _suite(
    db: AsyncSession, ctx: AuthContext, **values: Any
) -> tuple[EvalSuite, AgentVersion]:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        organization_id=ctx.organization_id,
        version=1,
        spec={"name": "Clerk"},
    )
    db.add(version)
    await db.flush()
    dataset = await DatasetService(db).create(
        ctx, DatasetCreate(name=f"refunds-{uuid.uuid4().hex[:6]}")
    )
    suite = await eval_suite_repo.create(
        db,
        organization_id=ctx.organization_id,
        suite=EvalSuite(
            agent_id=agent.id,
            dataset_id=dataset.id,
            owner_user_id=ctx.user_id,
            name=f"nightly-{uuid.uuid4().hex[:6]}",
            **values,
        ),
    )
    return suite, version


async def _result(
    db: AsyncSession,
    ctx: AuthContext,
    suite: EvalSuite,
    version: AgentVersion,
    *,
    status: EvalSuiteResultStatus = EvalSuiteResultStatus.PENDING,
    due_at: datetime = _NOW,
    trigger: str = "publish",
    **values: Any,
) -> EvalSuiteResult | None:
    return await eval_suite_repo.add_result(
        db,
        organization_id=ctx.organization_id,
        values={
            "suite_id": suite.id,
            "trigger": trigger,
            "agent_version_id": version.id,
            "version_number": version.version,
            "status": status.value,
            "due_at": due_at,
            "threshold": {"max_confirmed_regressions": 0},
            **values,
        },
    )


async def _eval_run(
    db: AsyncSession, ctx: AuthContext, suite: EvalSuite, status: EvalRunStatus
) -> EvalRun:
    service = DatasetService(db)
    await service.add_case(
        ctx, suite.dataset_id, DatasetCaseCreate(input="Q", reference_answer="A")
    )
    dataset = await service.get(ctx, suite.dataset_id)
    version = await dataset_repo.get_version(
        db, suite.dataset_id, dataset.latest_version, organization_id=ctx.organization_id
    )
    assert version is not None
    run = EvalRun(
        organization_id=ctx.organization_id,
        agent_id=suite.agent_id,
        dataset_id=suite.dataset_id,
        dataset_version_id=version.id,
        status=status.value,
        scoring={},
        scoring_hash="a" * 64,
        estimate_usd=Decimal("1.00"),
    )
    db.add(run)
    await db.flush()
    return run


async def test_a_second_waiting_result_for_the_same_version_is_absorbed(db) -> None:
    ctx = await _owner(db)
    suite, version = await _suite(db, ctx, on_publish=True, on_promotion=True)

    first = await _result(db, ctx, suite, version, trigger="publish")
    second = await _result(db, ctx, suite, version, trigger="promotion")

    assert first is not None
    assert second is None
    rows = (
        (await db.execute(select(EvalSuiteResult).where(EvalSuiteResult.suite_id == suite.id)))
        .scalars()
        .all()
    )
    assert [row.trigger for row in rows] == ["publish"]


async def test_a_change_while_the_suite_runs_waits_for_the_next_run(db) -> None:
    ctx = await _owner(db)
    suite, version = await _suite(db, ctx)
    running = await _result(db, ctx, suite, version, status=EvalSuiteResultStatus.RUNNING)
    waiting = await _result(db, ctx, suite, version, trigger="dependency")

    assert running is not None
    assert waiting is not None
    assert await eval_suite_repo.claim_pending(db, now=_NOW) == []

    await eval_suite_repo.update_result(
        db, result=running, values={"status": "passed", "settled_at": _NOW}
    )
    claimed = await eval_suite_repo.claim_pending(db, now=_NOW)
    assert [row.id for row in claimed] == [waiting.id]


async def test_a_result_due_later_is_not_claimed_yet(db) -> None:
    ctx = await _owner(db)
    suite, version = await _suite(db, ctx)
    await _result(db, ctx, suite, version, due_at=_NOW + timedelta(minutes=10))

    assert await eval_suite_repo.claim_pending(db, now=_NOW) == []
    assert len(await eval_suite_repo.claim_pending(db, now=_NOW + timedelta(minutes=10))) == 1


async def test_two_due_results_of_one_suite_start_one_at_a_time(db) -> None:
    ctx = await _owner(db)
    suite, version = await _suite(db, ctx)
    other = AgentVersion(
        id=uuid.uuid4(),
        agent_id=suite.agent_id,
        organization_id=ctx.organization_id,
        version=2,
        spec={},
    )
    db.add(other)
    await db.flush()
    await _result(db, ctx, suite, version)
    await _result(db, ctx, suite, other)

    assert len(await eval_suite_repo.claim_pending(db, now=_NOW)) == 1


async def test_only_running_suites_whose_schedule_came_due_are_claimed(db) -> None:
    ctx = await _owner(db)
    due, _ = await _suite(
        db, ctx, schedule_cron="0 9 * * *", next_fire_at=_NOW - timedelta(minutes=1)
    )
    await _suite(db, ctx, schedule_cron="0 9 * * *", next_fire_at=_NOW + timedelta(hours=1))
    await _suite(
        db,
        ctx,
        schedule_cron="0 9 * * *",
        next_fire_at=_NOW - timedelta(minutes=1),
        is_active=False,
    )

    claimed = await eval_suite_repo.claim_due_schedules(db, now=_NOW)

    assert [suite.id for suite in claimed] == [due.id]


async def test_a_running_result_is_finished_once_its_eval_run_ended_or_is_gone(db) -> None:
    ctx = await _owner(db)
    suite, version = await _suite(db, ctx)
    still = await _eval_run(db, ctx, suite, EvalRunStatus.RUNNING)
    ended = await _eval_run(db, ctx, suite, EvalRunStatus.COMPLETED)
    other = AgentVersion(
        id=uuid.uuid4(),
        agent_id=suite.agent_id,
        organization_id=ctx.organization_id,
        version=2,
        spec={},
    )
    third = AgentVersion(
        id=uuid.uuid4(),
        agent_id=suite.agent_id,
        organization_id=ctx.organization_id,
        version=3,
        spec={},
    )
    db.add_all([other, third])
    await db.flush()
    await _result(
        db, ctx, suite, version, status=EvalSuiteResultStatus.RUNNING, eval_run_id=still.id
    )
    done = await _result(
        db, ctx, suite, other, status=EvalSuiteResultStatus.RUNNING, eval_run_id=ended.id
    )
    gone = await _result(
        db, ctx, suite, third, status=EvalSuiteResultStatus.RUNNING, eval_run_id=None
    )

    claimed = await eval_suite_repo.claim_finished(db)

    assert done is not None
    assert gone is not None
    assert {row.id for row in claimed} == {done.id, gone.id}


async def test_pausing_forgets_what_was_waiting_and_keeps_what_ran(db) -> None:
    ctx = await _owner(db)
    suite, version = await _suite(db, ctx)
    other = AgentVersion(
        id=uuid.uuid4(),
        agent_id=suite.agent_id,
        organization_id=ctx.organization_id,
        version=2,
        spec={},
    )
    db.add(other)
    await db.flush()
    await _result(db, ctx, suite, version)
    kept = await _result(
        db, ctx, suite, other, status=EvalSuiteResultStatus.PASSED, settled_at=_NOW
    )

    await eval_suite_repo.discard_pending(db, suite.id, organization_id=ctx.organization_id)

    rows, total = await eval_suite_repo.list_results(
        db, suite.id, organization_id=ctx.organization_id
    )
    assert kept is not None
    assert (total, [row.id for row in rows]) == (1, [kept.id])


async def test_the_previous_result_on_the_same_version_is_found(db) -> None:
    ctx = await _owner(db)
    suite, version = await _suite(db, ctx)
    run = await _eval_run(db, ctx, suite, EvalRunStatus.COMPLETED)
    older = await _result(
        db,
        ctx,
        suite,
        version,
        status=EvalSuiteResultStatus.PASSED,
        settled_at=_NOW - timedelta(days=2),
        eval_run_id=run.id,
    )
    newer = await _result(
        db,
        ctx,
        suite,
        version,
        status=EvalSuiteResultStatus.SKIPPED,
        settled_at=_NOW - timedelta(days=1),
    )
    assert older is not None
    assert newer is not None

    found = await eval_suite_repo.previous_settled(
        db,
        suite_id=suite.id,
        agent_version_id=version.id,
        before=_NOW,
        organization_id=ctx.organization_id,
    )
    passed = await eval_suite_repo.previous_settled(
        db,
        suite_id=suite.id,
        agent_version_id=version.id,
        before=_NOW,
        organization_id=ctx.organization_id,
        passed_on_dataset=suite.dataset_id,
    )
    elsewhere = await eval_suite_repo.previous_settled(
        db,
        suite_id=suite.id,
        agent_version_id=version.id,
        before=_NOW,
        organization_id=ctx.organization_id,
        passed_on_dataset=uuid.uuid4(),
    )

    assert found is not None and found.id == newer.id
    assert passed is not None and passed.id == older.id
    assert elsewhere is None


async def test_each_suite_reads_its_latest_and_its_open_result(db) -> None:
    ctx = await _owner(db)
    suite, version = await _suite(db, ctx)
    other = AgentVersion(
        id=uuid.uuid4(),
        agent_id=suite.agent_id,
        organization_id=ctx.organization_id,
        version=2,
        spec={},
    )
    db.add(other)
    await db.flush()
    await _result(
        db,
        ctx,
        suite,
        version,
        status=EvalSuiteResultStatus.FAILED,
        settled_at=_NOW - timedelta(days=1),
    )
    latest = await _result(
        db, ctx, suite, version, status=EvalSuiteResultStatus.PASSED, settled_at=_NOW
    )
    await _result(db, ctx, suite, version)
    running = await _result(db, ctx, suite, other, status=EvalSuiteResultStatus.RUNNING)

    latest_by_suite = await eval_suite_repo.latest_results(
        db, [suite.id], organization_id=ctx.organization_id
    )
    open_by_suite = await eval_suite_repo.open_results(
        db, [suite.id], organization_id=ctx.organization_id
    )

    assert latest is not None and running is not None
    assert latest_by_suite[suite.id].id == latest.id
    assert open_by_suite[suite.id].id == running.id
    assert await eval_suite_repo.latest_results(db, [], organization_id=ctx.organization_id) == {}
    assert await eval_suite_repo.open_results(db, [], organization_id=ctx.organization_id) == {}


@pytest.mark.security
async def test_nothing_is_readable_from_another_organization(db) -> None:
    ctx = await _owner(db)
    stranger = await _owner(db)
    suite, version = await _suite(db, ctx, on_publish=True)
    result = await _result(db, ctx, suite, version)
    assert result is not None

    assert await eval_suite_repo.get(db, suite.id, organization_id=stranger.organization_id) is None
    assert (
        await eval_suite_repo.lock(db, suite.id, organization_id=stranger.organization_id) is None
    )
    assert (
        await eval_suite_repo.get_by_name(
            db, agent_id=suite.agent_id, name=suite.name, organization_id=stranger.organization_id
        )
        is None
    )
    assert (
        await eval_suite_repo.get_result(db, result.id, organization_id=stranger.organization_id)
        is None
    )
    assert (
        await eval_suite_repo.list_for_agents(
            db, [suite.agent_id], organization_id=stranger.organization_id
        )
        == []
    )
    assert (
        await eval_suite_repo.list_watching(
            db, organization_id=stranger.organization_id, flag="on_publish"
        )
        == []
    )
    assert (
        await eval_suite_repo.running_for(db, suite.id, organization_id=stranger.organization_id)
        is None
    )
    assert await eval_suite_repo.list_results(
        db, suite.id, organization_id=stranger.organization_id
    ) == ([], 0)
    assert await eval_suite_repo.list_for_agents(db, [], organization_id=ctx.organization_id) == []


async def test_a_suite_is_found_by_name_and_by_the_event_it_watches(db) -> None:
    ctx = await _owner(db)
    watching, _ = await _suite(db, ctx, on_publish=True)
    await _suite(db, ctx, on_publish=True, is_active=False)
    await _suite(db, ctx, on_promotion=True)

    of_agent = await eval_suite_repo.list_watching(
        db, organization_id=ctx.organization_id, flag="on_publish", agent_id=watching.agent_id
    )
    everywhere = await eval_suite_repo.list_watching(
        db, organization_id=ctx.organization_id, flag="on_publish"
    )
    named = await eval_suite_repo.get_by_name(
        db, agent_id=watching.agent_id, name=watching.name, organization_id=ctx.organization_id
    )

    assert [suite.id for suite in of_agent] == [watching.id]
    assert [suite.id for suite in everywhere] == [watching.id]
    assert named is not None and named.id == watching.id
    locked = await eval_suite_repo.lock(db, watching.id, organization_id=ctx.organization_id)
    assert locked is not None
    updated = await eval_suite_repo.update(db, suite=watching, values={"is_active": False})
    assert updated.is_active is False
    await eval_suite_repo.delete_suite(db, suite=updated)
    assert await eval_suite_repo.get(db, watching.id, organization_id=ctx.organization_id) is None
