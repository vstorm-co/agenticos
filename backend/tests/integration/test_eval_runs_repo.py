"""Eval run rows against Postgres - claiming, cancelling, baselines and tenancy.

The claims a mocked session cannot make:

- a claim never takes an organization past its limit of running cases, and two
  claims on one run take different cases;
- once a run is cancelled, no claim starts another of its cases;
- the baseline lookup finds the newest completed arm that matches, and a cached
  lookup refuses one that differs in anything it was asked to match;
- an abandoned run is failed and gives back its organization's running slots;
- nothing is readable across organizations.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.background_job import BackgroundJob
from app.db.models.credential import ModelProfile
from app.db.models.eval_run import (
    ArmRole,
    ArmSource,
    CaseAttemptStatus,
    EvalRun,
    EvalRunArm,
    EvalRunCase,
    EvalRunStatus,
)
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import background_task_kind as background_task_kind_repo
from app.repositories import dataset_repo, eval_run_repo
from app.repositories.eval_run import RunExecution
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.services.background_jobs import enqueue
from app.services.dataset import DatasetService
from app.worker.jobs import RUN_EVAL, RunEval

pytestmark = pytest.mark.anyio

_NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


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


async def _agent(db: AsyncSession, ctx: AuthContext) -> tuple[Agent, list[AgentVersion]]:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    versions = []
    for number in (6, 7):
        version = AgentVersion(
            id=uuid.uuid4(),
            agent_id=agent.id,
            organization_id=ctx.organization_id,
            version=number,
            spec={"name": "Clerk"},
        )
        db.add(version)
        versions.append(version)
    await db.flush()
    return agent, versions


async def _dataset(db: AsyncSession, ctx: AuthContext, *, cases: int = 3):
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name=f"refunds-{uuid.uuid4().hex[:6]}"))
    for index in range(cases):
        await service.add_case(
            ctx, dataset.id, DatasetCaseCreate(input=f"Question {index}", reference_answer="yes")
        )
    version = await dataset_repo.get_version(
        db, dataset.id, cases, organization_id=ctx.organization_id
    )
    assert version is not None
    revisions = await dataset_repo.list_cases(
        db, version.id, organization_id=ctx.organization_id, limit=None
    )
    return dataset, version, revisions


async def _run(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    agent: Agent,
    version: AgentVersion,
    dataset,
    dataset_version,
    revisions,
    status: EvalRunStatus = EvalRunStatus.RUNNING,
    model_profile_id: uuid.UUID | None = None,
    scoring_hash: str = "a" * 64,
    ended_at: datetime | None = None,
    from_recordings: bool = False,
    live_reads: bool = False,
) -> tuple[EvalRun, EvalRunArm]:
    run = EvalRun(
        agent_id=agent.id,
        dataset_id=dataset.id,
        dataset_version_id=dataset_version.id,
        created_by_user_id=ctx.user_id,
        status=status.value,
        scoring={},
        scoring_hash=scoring_hash,
        estimate_usd=Decimal("1.00"),
        ended_at=ended_at,
        from_recordings=from_recordings,
        live_reads=live_reads,
    )
    arm = EvalRunArm(
        role=ArmRole.CANDIDATE.value,
        position=0,
        source=ArmSource.VERSION.value,
        agent_version_id=version.id,
        version_number=version.version,
        model_profile_id=model_profile_id,
        model_label="gpt-4.1",
        spec_hash="v",
    )
    run = await eval_run_repo.create(db, organization_id=ctx.organization_id, run=run, arms=[arm])
    await eval_run_repo.add_cases(
        db,
        organization_id=ctx.organization_id,
        cases=[
            EvalRunCase(
                eval_run_id=run.id,
                arm_id=arm.id,
                case_id=revision.case_id,
                case_revision_id=revision.id,
                position=index,
            )
            for index, revision in enumerate(revisions)
        ],
    )
    return run, arm


async def _setup(db: AsyncSession, **kwargs):
    ctx = await _owner(db)
    agent, versions = await _agent(db, ctx)
    dataset, dataset_version, revisions = await _dataset(db, ctx)
    run, arm = await _run(
        db,
        ctx,
        agent=agent,
        version=versions[1],
        dataset=dataset,
        dataset_version=dataset_version,
        revisions=revisions,
        **kwargs,
    )
    return ctx, agent, versions, dataset, dataset_version, revisions, run, arm


async def test_claims_take_cases_in_order_and_stop_at_the_organizations_limit(db) -> None:
    ctx, *_, run, _arm = await _setup(db)

    first = await eval_run_repo.claim_next(
        db, run.id, organization_id=ctx.organization_id, org_limit=2, now=_NOW
    )
    second = await eval_run_repo.claim_next(
        db, run.id, organization_id=ctx.organization_id, org_limit=2, now=_NOW
    )
    third = await eval_run_repo.claim_next(
        db, run.id, organization_id=ctx.organization_id, org_limit=2, now=_NOW
    )

    assert first is not None and second is not None
    assert (first.position, second.position) == (0, 1)
    assert first.status == CaseAttemptStatus.RUNNING.value
    assert first.started_at == _NOW
    # Two running: a third would take the organization past its limit, whichever
    # run it belonged to.
    assert third is None
    counts = await eval_run_repo.count_by_status(db, run.id, organization_id=ctx.organization_id)
    assert counts == {"running": 2, "pending": 1}


async def test_a_cancelled_run_starts_no_further_case(db) -> None:
    ctx, *_, run, _arm = await _setup(db)

    await eval_run_repo.update_run(db, run=run, values={"status": EvalRunStatus.CANCELLED.value})
    skipped = await eval_run_repo.skip_pending(db, run.id, organization_id=ctx.organization_id)
    claimed = await eval_run_repo.claim_next(
        db, run.id, organization_id=ctx.organization_id, org_limit=10, now=_NOW
    )

    assert skipped == 3
    assert claimed is None
    counts = await eval_run_repo.count_by_status(db, run.id, organization_id=ctx.organization_id)
    assert counts == {"skipped": 3}


async def test_a_run_another_organization_owns_is_not_found(db) -> None:
    ctx, agent, *_rest, run, arm = await _setup(db)
    stranger = await _owner(db)

    assert await eval_run_repo.get(db, run.id, organization_id=stranger.organization_id) is None
    assert await eval_run_repo.lock(db, run.id, organization_id=stranger.organization_id) is None
    assert await eval_run_repo.get_arm(db, arm.id, organization_id=stranger.organization_id) is None
    assert (
        await eval_run_repo.list_cases(db, run.id, organization_id=stranger.organization_id) == []
    )
    assert (
        await eval_run_repo.claim_next(
            db, run.id, organization_id=stranger.organization_id, org_limit=10, now=_NOW
        )
        is None
    )
    listed, total = await eval_run_repo.list_for_agent(
        db, agent.id, organization_id=stranger.organization_id
    )
    assert (listed, total) == ([], 0)
    assert await eval_run_repo.get(db, run.id, organization_id=ctx.organization_id) is not None


async def test_listing_narrows_to_the_datasets_the_reader_may_see(db) -> None:
    ctx, agent, _versions, dataset, *_rest = await _setup(db)

    visible, total = await eval_run_repo.list_for_agent(
        db, agent.id, organization_id=ctx.organization_id, dataset_ids=[dataset.id]
    )
    hidden, none = await eval_run_repo.list_for_agent(
        db, agent.id, organization_id=ctx.organization_id, dataset_ids=[uuid.uuid4()]
    )
    recent = await eval_run_repo.list_recent(
        db,
        organization_id=ctx.organization_id,
        agent_ids=[agent.id],
        dataset_ids=[dataset.id],
        limit=5,
    )

    assert total == 1 and len(visible) == 1
    assert (hidden, none) == ([], 0)
    assert [run.id for run in recent] == [visible[0].id]
    assert (
        await eval_run_repo.list_recent(
            db, organization_id=ctx.organization_id, agent_ids=[], dataset_ids=[dataset.id], limit=5
        )
        == []
    )


async def test_a_cached_baseline_ran_the_way_the_candidate_will(db) -> None:
    """Which test connections answered, and whether recordings did, decide the
    baseline's answers as much as the version does."""
    ctx, agent, versions, dataset, dataset_version, revisions, _run_v7, _arm = await _setup(db)
    replayed, _ = await _run(
        db,
        ctx,
        agent=agent,
        version=versions[0],
        dataset=dataset,
        dataset_version=dataset_version,
        revisions=revisions,
        status=EvalRunStatus.COMPLETED,
        ended_at=_NOW - timedelta(hours=1),
        from_recordings=True,
    )

    def lookup(execution: RunExecution):
        return eval_run_repo.latest_arm(
            db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            dataset_id=dataset.id,
            agent_version_id=versions[0].id,
            execution=execution,
        )

    found = await lookup(RunExecution(environment_id=None, from_recordings=True, live_reads=False))
    assert found is not None and found[1].id == replayed.id
    for other in (
        RunExecution(environment_id=None, from_recordings=False, live_reads=False),
        RunExecution(environment_id=None, from_recordings=True, live_reads=True),
        RunExecution(environment_id=uuid.uuid4(), from_recordings=True, live_reads=False),
    ):
        assert await lookup(other) is None


async def test_the_baseline_lookup_matches_what_it_is_asked_to_and_nothing_else(db) -> None:
    ctx, agent, versions, dataset, dataset_version, revisions, _run_v7, _arm = await _setup(db)
    older, _ = await _run(
        db,
        ctx,
        agent=agent,
        version=versions[0],
        dataset=dataset,
        dataset_version=dataset_version,
        revisions=revisions,
        status=EvalRunStatus.COMPLETED,
        ended_at=_NOW - timedelta(hours=30),
    )
    newer, newer_arm = await _run(
        db,
        ctx,
        agent=agent,
        version=versions[0],
        dataset=dataset,
        dataset_version=dataset_version,
        revisions=revisions,
        status=EvalRunStatus.COMPLETED,
        ended_at=_NOW - timedelta(hours=2),
        scoring_hash="b" * 64,
    )

    found = await eval_run_repo.latest_arm(
        db,
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        dataset_id=dataset.id,
        agent_version_id=versions[0].id,
    )
    assert found is not None and found[1].id == newer.id and found[0].id == newer_arm.id

    cached = await eval_run_repo.latest_arm(
        db,
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        dataset_id=dataset.id,
        agent_version_id=versions[0].id,
        dataset_version_id=dataset_version.id,
        scoring_hash="a" * 64,
        since=_NOW - timedelta(hours=24),
    )
    # The run with matching scoring is too old, the recent one was scored
    # differently: no cache, a baseline arm has to run.
    assert cached is None

    excluded = await eval_run_repo.latest_arm(
        db,
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        dataset_id=dataset.id,
        agent_version_id=versions[0].id,
        exclude_run_id=newer.id,
        model_profile_id=uuid.uuid4(),
    )
    assert excluded is None
    assert older.status == EvalRunStatus.COMPLETED.value
    # A running run is never a baseline.
    assert (
        await eval_run_repo.latest_arm(
            db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            dataset_id=dataset.id,
            agent_version_id=versions[1].id,
        )
        is None
    )
    assert (
        len(
            await eval_run_repo.list_arm_cases(
                db, newer_arm.id, organization_id=ctx.organization_id
            )
        )
        == 3
    )


async def test_an_abandoned_run_is_failed_and_frees_its_slots(db) -> None:
    ctx, *_, run, _arm = await _setup(db)
    claimed = await eval_run_repo.claim_next(
        db, run.id, organization_id=ctx.organization_id, org_limit=10, now=_NOW
    )
    assert claimed is not None
    run.created_at = _NOW - timedelta(hours=3)
    run.status = EvalRunStatus.RUNNING.value
    await db.flush()
    still_moving = await eval_run_repo.fail_abandoned(
        db, idle_since=_NOW - timedelta(hours=1), job_kind=RUN_EVAL.kind, now=_NOW
    )
    assert still_moving == 0

    # A worker that still beats is not dead, though no case has moved since.
    await eval_run_repo.heartbeat(
        db, run.id, organization_id=ctx.organization_id, now=_NOW + timedelta(minutes=5)
    )
    beating = await eval_run_repo.fail_abandoned(
        db, idle_since=_NOW + timedelta(minutes=1), job_kind=RUN_EVAL.kind, now=_NOW
    )
    assert beating == 0

    reaped = await eval_run_repo.fail_abandoned(
        db, idle_since=_NOW + timedelta(minutes=10), job_kind=RUN_EVAL.kind, now=_NOW
    )
    await db.refresh(run)
    cases = await eval_run_repo.list_cases(db, run.id, organization_id=ctx.organization_id)

    assert reaped == 1
    assert run.status == EvalRunStatus.FAILED.value
    assert run.ended_at == _NOW
    assert sorted(case.status for case in cases) == ["failed", "skipped", "skipped"]
    assert claimed.id in {case.id for case in cases if case.error}


async def test_a_live_run_is_failed_with_what_it_had_not_finished(db) -> None:
    ctx, *_, run, _arm = await _setup(db)
    claimed = await eval_run_repo.claim_next(
        db, run.id, organization_id=ctx.organization_id, org_limit=10, now=_NOW
    )
    assert claimed is not None
    run.status = EvalRunStatus.RUNNING.value
    await db.flush()

    elsewhere = await eval_run_repo.fail_live(
        db, run.id, organization_id=uuid.uuid4(), now=_NOW, error="Stopped."
    )
    assert elsewhere is False

    failed = await eval_run_repo.fail_live(
        db, run.id, organization_id=ctx.organization_id, now=_NOW, error="Stopped."
    )
    await db.refresh(run)
    cases = await eval_run_repo.list_cases(db, run.id, organization_id=ctx.organization_id)

    assert failed is True
    assert (run.status, run.error, run.ended_at) == (EvalRunStatus.FAILED.value, "Stopped.", _NOW)
    assert sorted(case.status for case in cases) == ["failed", "skipped", "skipped"]

    # An ended run keeps its outcome.
    again = await eval_run_repo.fail_live(
        db, run.id, organization_id=ctx.organization_id, now=_NOW, error="Later."
    )
    await db.refresh(run)
    assert (again, run.error) == (False, "Stopped.")


async def _two_runs(db: AsyncSession, **kwargs) -> tuple[AuthContext, EvalRun, EvalRun]:
    """Two runs of one agent over one dataset, in one organization."""
    ctx, agent, versions, dataset, dataset_version, revisions, run, _arm = await _setup(
        db, **kwargs
    )
    other, _arm = await _run(
        db,
        ctx,
        agent=agent,
        version=versions[1],
        dataset=dataset,
        dataset_version=dataset_version,
        revisions=revisions,
        **kwargs,
    )
    return ctx, run, other


async def _job(db: AsyncSession, ctx: AuthContext, run: EvalRun, status: str) -> None:
    job_id = await enqueue(
        db,
        RUN_EVAL,
        RunEval(eval_run_id=run.id, organization_id=ctx.organization_id),
        organization_id=ctx.organization_id,
    )
    job = await db.get(BackgroundJob, job_id)
    assert job is not None
    job.status = status
    await db.flush()


async def test_a_queued_run_is_given_up_once_no_job_is_left_to_run_it(db) -> None:
    ctx, run, other = await _two_runs(db, status=EvalRunStatus.QUEUED)
    # Another run's job does not keep this one.
    await _job(db, ctx, other, "queued")

    async def sweep() -> int:
        return await eval_run_repo.fail_abandoned(
            db, idle_since=_NOW, job_kind=RUN_EVAL.kind, now=_NOW
        )

    await _job(db, ctx, run, "queued")
    # Waiting behind a paused kind is waiting, not lost.
    await background_task_kind_repo.pause(db, RUN_EVAL.kind, None, reason="maintenance")
    assert await sweep() == 0
    job = (
        await db.execute(
            select(BackgroundJob).where(BackgroundJob.payload["eval_run_id"].astext == str(run.id))
        )
    ).scalar_one()
    job.status = "running"
    await db.flush()
    assert await sweep() == 0

    # Withdrawn, its settler not run yet: the settler says how it ends, not the sweep.
    job.status = "cancelled"
    job.finished_at = datetime.now(UTC)
    await db.flush()
    assert await sweep() == 0
    # A job that ended well is never settled, and holds nothing back.
    job.status = "succeeded"
    await db.flush()
    assert await sweep() == 1
    await db.refresh(run)
    await db.refresh(other)
    assert run.status == EvalRunStatus.FAILED.value
    assert other.status == EvalRunStatus.QUEUED.value


async def test_a_queued_run_with_no_job_at_all_is_given_up(db) -> None:
    ctx, *_, run, _arm = await _setup(db, status=EvalRunStatus.QUEUED)
    await _job(db, ctx, run, "dead")

    given_up = await eval_run_repo.fail_abandoned(
        db, idle_since=_NOW, job_kind=RUN_EVAL.kind, now=_NOW
    )
    await db.refresh(run)
    cases = await eval_run_repo.list_cases(db, run.id, organization_id=ctx.organization_id)
    assert (given_up, run.status) == (1, EvalRunStatus.FAILED.value)
    assert {case.status for case in cases} == {"skipped"}


async def test_a_started_case_holds_its_slot_until_it_ends_even_once_its_run_is_cancelled(
    db,
) -> None:
    ctx, run, other = await _two_runs(db)
    for _ in range(2):
        assert await eval_run_repo.claim_next(
            db, run.id, organization_id=ctx.organization_id, org_limit=2, now=_NOW
        )

    async def claim():
        return await eval_run_repo.claim_next(
            db, other.id, organization_id=ctx.organization_id, org_limit=2, now=_NOW
        )

    assert await claim() is None
    # Cancelled, its started cases still answering: cancelling and starting
    # another run must not take the organization past its limit.
    await eval_run_repo.update_run(
        db, run=run, values={"status": EvalRunStatus.CANCELLED.value, "ended_at": _NOW}
    )
    assert await claim() is None

    # Their worker died: the sweep ends them after its window, and the slots free.
    await eval_run_repo.close_orphaned_attempts(db, ended_before=_NOW + timedelta(minutes=1))
    claimed = await claim()
    assert claimed is not None and claimed.eval_run_id == other.id


async def test_attempts_left_running_by_an_ended_run_are_closed_after_the_window(db) -> None:
    ctx, run, other = await _two_runs(db)
    orphan = await eval_run_repo.claim_next(
        db, run.id, organization_id=ctx.organization_id, org_limit=10, now=_NOW
    )
    live = await eval_run_repo.claim_next(
        db, other.id, organization_id=ctx.organization_id, org_limit=10, now=_NOW
    )
    assert orphan is not None and live is not None
    await eval_run_repo.update_run(
        db, run=run, values={"status": EvalRunStatus.CANCELLED.value, "ended_at": _NOW}
    )

    # Within the window, the attempt a cancelled run's worker is answering may finish -
    # and for as long as that worker says it is alive.
    assert await eval_run_repo.close_orphaned_attempts(db, ended_before=_NOW) == 0
    await eval_run_repo.heartbeat(
        db, run.id, organization_id=ctx.organization_id, now=_NOW + timedelta(minutes=30)
    )
    assert (
        await eval_run_repo.close_orphaned_attempts(db, ended_before=_NOW + timedelta(minutes=29))
        == 0
    )
    closed = await eval_run_repo.close_orphaned_attempts(
        db, ended_before=_NOW + timedelta(minutes=31)
    )
    await db.refresh(orphan)
    await db.refresh(live)

    assert closed == 1
    assert (orphan.status, orphan.error) == ("failed", "The worker stopped mid-case.")
    assert live.status == CaseAttemptStatus.RUNNING.value


async def test_a_live_run_is_cancelled_with_what_it_had_not_started(db) -> None:
    ctx, *_, run, _arm = await _setup(db, status=EvalRunStatus.QUEUED)

    elsewhere = await eval_run_repo.cancel_live(db, run.id, organization_id=uuid.uuid4(), now=_NOW)
    assert elsewhere is False

    cancelled = await eval_run_repo.cancel_live(
        db, run.id, organization_id=ctx.organization_id, now=_NOW
    )
    await db.refresh(run)
    cases = await eval_run_repo.list_cases(db, run.id, organization_id=ctx.organization_id)

    assert cancelled is True
    assert (run.status, run.ended_at) == (EvalRunStatus.CANCELLED.value, _NOW)
    assert {case.status for case in cases} == {"skipped"}
    assert (
        await eval_run_repo.cancel_live(db, run.id, organization_id=ctx.organization_id, now=_NOW)
        is False
    )


async def test_an_attempt_is_finished_once_and_never_after_it_was_closed(db) -> None:
    """A worker that lost its lease may still answer; the settler's word stands."""
    ctx, *_, run, _arm = await _setup(db)
    claimed = await eval_run_repo.claim_next(
        db, run.id, organization_id=ctx.organization_id, org_limit=10, now=_NOW
    )
    stale = await eval_run_repo.claim_next(
        db, run.id, organization_id=ctx.organization_id, org_limit=10, now=_NOW
    )
    assert claimed is not None and stale is not None

    finished = await eval_run_repo.finish_case(
        db, case=claimed, values={"status": CaseAttemptStatus.DONE.value, "answer": "30 days"}
    )
    await eval_run_repo.fail_live(
        db, run.id, organization_id=ctx.organization_id, now=_NOW, error="Stopped."
    )
    late = await eval_run_repo.finish_case(
        db, case=stale, values={"status": CaseAttemptStatus.DONE.value, "cost_usd": Decimal("1")}
    )
    read = await eval_run_repo.get_case(db, claimed.id, organization_id=ctx.organization_id)
    closed = await eval_run_repo.get_case(db, stale.id, organization_id=ctx.organization_id)

    assert (finished, late) == (True, False)
    assert closed is not None
    await db.refresh(closed)
    assert (closed.status, closed.cost_usd) == (CaseAttemptStatus.FAILED.value, None)
    arms = await eval_run_repo.list_arms(db, [run.id], organization_id=ctx.organization_id)

    assert read is not None and read.answer == "30 days"
    assert [arm.role for arm in arms] == ["candidate"]
    assert await eval_run_repo.list_arms(db, [], organization_id=ctx.organization_id) == []
    for empty in (
        eval_run_repo.scores,
        eval_run_repo.revisions,
        eval_run_repo.datasets,
        eval_run_repo.dataset_version_numbers,
    ):
        assert await empty(db, [], organization_id=ctx.organization_id) == {}


async def test_a_live_run_is_counted_on_the_model_its_side_runs_on(db) -> None:
    ctx, *_, run, arm = await _setup(db)
    profile = ModelProfile(
        organization_id=ctx.organization_id, label="nano", provider="openai", model="nano"
    )
    db.add(profile)
    await db.flush()
    arm.model_profile_id = profile.id
    await db.flush()

    count = await eval_run_repo.count_live_with_model(
        db, model_profile_id=profile.id, organization_id=ctx.organization_id
    )
    assert count == 1
    run.status = EvalRunStatus.COMPLETED.value
    await db.flush()
    count = await eval_run_repo.count_live_with_model(
        db, model_profile_id=profile.id, organization_id=ctx.organization_id
    )
    assert count == 0
