"""Rows in `eval_suites` and `eval_suite_results`."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import delete, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.dataset import DatasetVersion
from app.db.models.eval_run import EvalRun, EvalRunStatus
from app.db.models.eval_suite import EvalSuite, EvalSuiteResult, EvalSuiteResultStatus

_TERMINAL_RUNS = tuple(status.value for status in EvalRunStatus if status.terminal)
_SETTLED = tuple(status.value for status in EvalSuiteResultStatus if not status.open)

EventFlag = Literal["on_publish", "on_promotion", "on_dependency_change"]


async def create(db: AsyncSession, *, organization_id: UUID, suite: EvalSuite) -> EvalSuite:
    suite.organization_id = organization_id
    db.add(suite)
    await db.flush()
    await db.refresh(suite)
    return suite


async def get(db: AsyncSession, suite_id: UUID, *, organization_id: UUID) -> EvalSuite | None:
    result = await db.execute(
        select(EvalSuite).where(
            EvalSuite.id == suite_id, EvalSuite.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def get_by_name(
    db: AsyncSession, *, agent_id: UUID, name: str, organization_id: UUID
) -> EvalSuite | None:
    result = await db.execute(
        select(EvalSuite).where(
            EvalSuite.agent_id == agent_id,
            EvalSuite.name == name,
            EvalSuite.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def lock(db: AsyncSession, suite_id: UUID, *, organization_id: UUID) -> EvalSuite | None:
    """The suite, held until the transaction ends - against a sweep starting it meanwhile.

    `FOR NO KEY UPDATE`, not `FOR UPDATE`: a guard row written in the same
    transaction holds a key share on the suite for its foreign key, and two
    changes to one suite's guards would each wait on the other's.
    """
    result = await db.execute(
        select(EvalSuite)
        .where(EvalSuite.id == suite_id, EvalSuite.organization_id == organization_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def list_for_agents(
    db: AsyncSession, agent_ids: Sequence[UUID], *, organization_id: UUID
) -> list[EvalSuite]:
    """The suites of these agents, each agent's by name."""
    if not agent_ids:
        return []
    result = await db.execute(
        select(EvalSuite)
        .where(EvalSuite.agent_id.in_(agent_ids), EvalSuite.organization_id == organization_id)
        .order_by(EvalSuite.agent_id, EvalSuite.name)
    )
    return list(result.scalars().all())


async def list_for_organization(db: AsyncSession, *, organization_id: UUID) -> list[EvalSuite]:
    """Every suite of the organization, by agent and name - the dashboard narrows them."""
    result = await db.execute(
        select(EvalSuite)
        .where(EvalSuite.organization_id == organization_id)
        .order_by(EvalSuite.agent_id, EvalSuite.name)
    )
    return list(result.scalars().all())


async def list_on_environment(
    db: AsyncSession, environment_id: UUID, *, organization_id: UUID
) -> list[EvalSuite]:
    """The suites that check this environment's version."""
    result = await db.execute(
        select(EvalSuite).where(
            EvalSuite.environment_id == environment_id,
            EvalSuite.organization_id == organization_id,
        )
    )
    return list(result.scalars().all())


async def list_watching(
    db: AsyncSession, *, organization_id: UUID, flag: EventFlag, agent_id: UUID | None = None
) -> list[EvalSuite]:
    """The running suites set to run on an event - of one agent, or the whole organization."""
    query = select(EvalSuite).where(
        EvalSuite.organization_id == organization_id,
        EvalSuite.is_active.is_(True),
        getattr(EvalSuite, flag).is_(True),
    )
    if agent_id is not None:
        query = query.where(EvalSuite.agent_id == agent_id)
    result = await db.execute(query.order_by(EvalSuite.created_at))
    return list(result.scalars().all())


async def update(db: AsyncSession, *, suite: EvalSuite, values: dict[str, Any]) -> EvalSuite:
    for field, value in values.items():
        setattr(suite, field, value)
    await db.flush()
    await db.refresh(suite)
    return suite


async def delete_suite(db: AsyncSession, *, suite: EvalSuite) -> None:
    await db.delete(suite)
    await db.flush()


async def claim_due_schedules(
    db: AsyncSession, *, now: datetime, limit: int = 100
) -> list[EvalSuite]:
    """Running suites whose schedule has come due, locked for this transaction.

    Unscoped - every organization's: the sweep is the deployment's, and each
    claimed suite carries its own organization. `SKIP LOCKED`, so two workers ticking at once
    each take a different suite, never the same one twice.
    """
    result = await db.execute(
        select(EvalSuite)
        .where(EvalSuite.is_active.is_(True), EvalSuite.next_fire_at <= now)
        .order_by(EvalSuite.next_fire_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def add_result(
    db: AsyncSession, *, organization_id: UUID, values: dict[str, Any]
) -> EvalSuiteResult | None:
    """Write a result, or nothing when this suite already waits to check this version.

    A waiting result absorbs the next one for the same version and baseline -
    whichever trigger asked - so a burst of changes is one run, due when the
    first said.
    """
    statement = (
        insert(EvalSuiteResult)
        .values(organization_id=organization_id, **values)
        .on_conflict_do_nothing(
            index_elements=[
                "suite_id",
                "agent_version_id",
                literal_column("coalesce(baseline_version_number, -1)"),
            ],
            index_where=EvalSuiteResult.status == EvalSuiteResultStatus.PENDING.value,
        )
        .returning(EvalSuiteResult.id)
    )
    written = (await db.execute(statement)).scalar_one_or_none()
    if written is None:
        return None
    return await get_result(db, written, organization_id=organization_id)


async def get_result(
    db: AsyncSession, result_id: UUID, *, organization_id: UUID
) -> EvalSuiteResult | None:
    result = await db.execute(
        select(EvalSuiteResult).where(
            EvalSuiteResult.id == result_id, EvalSuiteResult.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def update_result(
    db: AsyncSession, *, result: EvalSuiteResult, values: dict[str, Any]
) -> EvalSuiteResult:
    for field, value in values.items():
        setattr(result, field, value)
    await db.flush()
    await db.refresh(result)
    return result


async def discard_pending(db: AsyncSession, suite_id: UUID, *, organization_id: UUID) -> None:
    """Forget what a suite was waiting to run - it was paused, and paused means off."""
    await db.execute(
        delete(EvalSuiteResult).where(
            EvalSuiteResult.suite_id == suite_id,
            EvalSuiteResult.organization_id == organization_id,
            EvalSuiteResult.status == EvalSuiteResultStatus.PENDING.value,
        )
    )
    await db.flush()


async def claim_pending(
    db: AsyncSession, *, now: datetime, limit: int = 20
) -> list[EvalSuiteResult]:
    """Results due to start, of suites not already running, locked for this transaction.

    Unscoped, for the deployment's sweep; each result carries its organization.

    One run per suite at a time: a suite still running leaves its next result
    waiting, which is what lets that one absorb the changes made meanwhile.
    """
    running = aliased(EvalSuiteResult)
    busy = (
        select(running.id)
        .where(
            running.suite_id == EvalSuiteResult.suite_id,
            running.status == EvalSuiteResultStatus.RUNNING.value,
        )
        .correlate(EvalSuiteResult)
        .exists()
    )
    result = await db.execute(
        select(EvalSuiteResult)
        .where(
            EvalSuiteResult.status == EvalSuiteResultStatus.PENDING.value,
            EvalSuiteResult.due_at <= now,
            ~busy,
        )
        .order_by(EvalSuiteResult.due_at)
        .limit(limit)
        .with_for_update(skip_locked=True, of=EvalSuiteResult)
    )
    # Two waiting results of one suite may both be due; the first starts and the
    # other waits for it, as it would have a tick later.
    seen: set[UUID] = set()
    claimed: list[EvalSuiteResult] = []
    for row in result.scalars().all():
        if row.suite_id not in seen:
            seen.add(row.suite_id)
            claimed.append(row)
    return claimed


async def claim_finished(db: AsyncSession, *, limit: int = 50) -> list[EvalSuiteResult]:
    """Running results whose eval run has ended, or is gone, locked for this transaction.

    Unscoped, for the deployment's sweep; each result carries its organization.
    """
    result = await db.execute(
        select(EvalSuiteResult)
        .outerjoin(EvalRun, EvalRun.id == EvalSuiteResult.eval_run_id)
        .where(
            EvalSuiteResult.status == EvalSuiteResultStatus.RUNNING.value,
            or_(EvalRun.id.is_(None), EvalRun.status.in_(_TERMINAL_RUNS)),
        )
        .order_by(EvalSuiteResult.started_at)
        .limit(limit)
        .with_for_update(skip_locked=True, of=EvalSuiteResult)
    )
    return list(result.scalars().all())


async def awaits_run(db: AsyncSession, run_id: UUID, *, organization_id: UUID) -> bool:
    """Whether a running suite result is waiting on this eval run to settle."""
    found = await db.scalar(
        select(EvalSuiteResult.id)
        .where(
            EvalSuiteResult.organization_id == organization_id,
            EvalSuiteResult.eval_run_id == run_id,
            EvalSuiteResult.status == EvalSuiteResultStatus.RUNNING.value,
        )
        .limit(1)
    )
    return found is not None


async def running_for(
    db: AsyncSession, suite_id: UUID, *, organization_id: UUID
) -> EvalSuiteResult | None:
    result = await db.execute(
        select(EvalSuiteResult)
        .where(
            EvalSuiteResult.suite_id == suite_id,
            EvalSuiteResult.organization_id == organization_id,
            EvalSuiteResult.status == EvalSuiteResultStatus.RUNNING.value,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def previous_settled(
    db: AsyncSession,
    *,
    suite_id: UUID,
    agent_version_id: UUID | None,
    before: datetime,
    organization_id: UUID,
    passed_on_dataset: UUID | None = None,
) -> EvalSuiteResult | None:
    """The last result of this suite on this version that came out one way or another.

    `passed_on_dataset` narrows to the last pass or initial baseline, with its
    eval run still answering that dataset. A failed run never replaces it.
    """
    query = select(EvalSuiteResult).where(
        EvalSuiteResult.suite_id == suite_id,
        EvalSuiteResult.organization_id == organization_id,
        (
            EvalSuiteResult.agent_version_id.is_(None)
            if agent_version_id is None
            else EvalSuiteResult.agent_version_id == agent_version_id
        ),
        EvalSuiteResult.status.in_(_SETTLED),
        EvalSuiteResult.settled_at < before,
    )
    if passed_on_dataset is not None:
        query = query.join(EvalRun, EvalRun.id == EvalSuiteResult.eval_run_id).where(
            EvalSuiteResult.status.in_(
                (EvalSuiteResultStatus.PASSED.value, EvalSuiteResultStatus.BASELINE_SET.value)
            ),
            EvalRun.dataset_id == passed_on_dataset,
        )
    result = await db.execute(query.order_by(EvalSuiteResult.settled_at.desc()).limit(1))
    return result.scalar_one_or_none()


async def incomparable_since(
    db: AsyncSession,
    *,
    suite_id: UUID,
    agent_version_id: UUID,
    since: datetime,
    organization_id: UUID,
) -> bool:
    """Whether a result of this suite on this version settled after `since` with a
    comparison that could not be read - its two sides graded differently."""
    result = await db.execute(
        select(EvalSuiteResult.id)
        .where(
            EvalSuiteResult.suite_id == suite_id,
            EvalSuiteResult.organization_id == organization_id,
            EvalSuiteResult.agent_version_id == agent_version_id,
            EvalSuiteResult.status == EvalSuiteResultStatus.INCONCLUSIVE.value,
            EvalSuiteResult.summary["invalid_reason"].astext.is_not(None),
            EvalSuiteResult.settled_at > since,
        )
        .limit(1)
    )
    return result.first() is not None


async def list_results(
    db: AsyncSession, suite_id: UUID, *, organization_id: UUID, skip: int = 0, limit: int = 20
) -> tuple[list[EvalSuiteResult], int]:
    """One suite's results, newest first, and how many there are."""
    where = (
        EvalSuiteResult.suite_id == suite_id,
        EvalSuiteResult.organization_id == organization_id,
    )
    total = (
        await db.execute(select(func.count()).select_from(EvalSuiteResult).where(*where))
    ).scalar_one()
    result = await db.execute(
        select(EvalSuiteResult)
        .where(*where)
        .order_by(
            EvalSuiteResult.created_at.desc(), EvalSuiteResult.due_at.desc(), EvalSuiteResult.id
        )
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), int(total)


async def latest_results(
    db: AsyncSession, suite_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, EvalSuiteResult]:
    """Each suite's newest result that has come out, keyed by suite."""
    if not suite_ids:
        return {}
    result = await db.execute(
        select(EvalSuiteResult)
        .where(
            EvalSuiteResult.suite_id.in_(suite_ids),
            EvalSuiteResult.organization_id == organization_id,
            EvalSuiteResult.status.in_(_SETTLED),
        )
        .order_by(EvalSuiteResult.suite_id, EvalSuiteResult.settled_at.desc())
        .ext(distinct_on(EvalSuiteResult.suite_id))
    )
    return {row.suite_id: row for row in result.scalars().all()}


async def settled_on_version(
    db: AsyncSession,
    suite_ids: Sequence[UUID],
    version_id: UUID,
    *,
    baseline_version: int,
    organization_id: UUID,
) -> dict[UUID, tuple[EvalSuiteResult, int | None, str | None, UUID | None, bool | None]]:
    """Prefer this baseline; retain the latest older-baseline result as stale evidence,
    with the number of the dataset version its eval run read and the scoring it
    was graded under - none when it never started one."""
    if not suite_ids:
        return {}
    result = await db.execute(
        select(
            EvalSuiteResult,
            DatasetVersion.number,
            EvalRun.scoring_hash,
            EvalRun.judge_version_id,
            EvalRun.judge_pinned,
        )
        .outerjoin(EvalRun, EvalRun.id == EvalSuiteResult.eval_run_id)
        .outerjoin(DatasetVersion, DatasetVersion.id == EvalRun.dataset_version_id)
        .where(
            EvalSuiteResult.suite_id.in_(suite_ids),
            EvalSuiteResult.organization_id == organization_id,
            EvalSuiteResult.agent_version_id == version_id,
            EvalSuiteResult.status.in_(_SETTLED),
        )
        .order_by(
            EvalSuiteResult.suite_id,
            (EvalSuiteResult.baseline_version_number == baseline_version).is_(True).desc(),
            EvalSuiteResult.settled_at.desc(),
        )
        .ext(distinct_on(EvalSuiteResult.suite_id))
    )
    return {
        row.suite_id: (row, number, hashed, judge_version, pinned)
        for row, number, hashed, judge_version, pinned in result.all()
    }


async def open_on_version(
    db: AsyncSession,
    suite_ids: Sequence[UUID],
    version_id: UUID,
    *,
    baseline_version: int,
    organization_id: UUID,
) -> dict[UUID, EvalSuiteResult]:
    """Each suite's result on this agent version beside this baseline that is
    waiting or running."""
    if not suite_ids:
        return {}
    result = await db.execute(
        select(EvalSuiteResult)
        .where(
            EvalSuiteResult.suite_id.in_(suite_ids),
            EvalSuiteResult.organization_id == organization_id,
            EvalSuiteResult.agent_version_id == version_id,
            EvalSuiteResult.baseline_version_number == baseline_version,
            EvalSuiteResult.status.in_(
                [EvalSuiteResultStatus.PENDING.value, EvalSuiteResultStatus.RUNNING.value]
            ),
        )
        .order_by(EvalSuiteResult.suite_id, EvalSuiteResult.status.desc(), EvalSuiteResult.due_at)
        .ext(distinct_on(EvalSuiteResult.suite_id))
    )
    return {row.suite_id: row for row in result.scalars().all()}


async def open_results(
    db: AsyncSession, suite_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, EvalSuiteResult]:
    """Each suite's result that is waiting or running, the running one first."""
    if not suite_ids:
        return {}
    result = await db.execute(
        select(EvalSuiteResult)
        .where(
            EvalSuiteResult.suite_id.in_(suite_ids),
            EvalSuiteResult.organization_id == organization_id,
            EvalSuiteResult.status.in_(
                (EvalSuiteResultStatus.PENDING.value, EvalSuiteResultStatus.RUNNING.value)
            ),
        )
        # 'running' sorts after 'pending', so descending puts it first.
        .order_by(EvalSuiteResult.suite_id, EvalSuiteResult.status.desc(), EvalSuiteResult.due_at)
        .ext(distinct_on(EvalSuiteResult.suite_id))
    )
    return {row.suite_id: row for row in result.scalars().all()}


async def started_runs(
    db: AsyncSession, eval_run_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, tuple[EvalSuite, EvalSuiteResult]]:
    """For each of these eval runs a suite started, the suite and the result it ran for."""
    if not eval_run_ids:
        return {}
    result = await db.execute(
        select(EvalSuite, EvalSuiteResult)
        .join(EvalSuiteResult, EvalSuiteResult.suite_id == EvalSuite.id)
        .where(
            EvalSuiteResult.eval_run_id.in_(list(eval_run_ids)),
            EvalSuiteResult.organization_id == organization_id,
        )
    )
    return {
        row.EvalSuiteResult.eval_run_id: (row.EvalSuite, row.EvalSuiteResult)
        for row in result.all()
    }


async def names(
    db: AsyncSession, suite_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, str]:
    """Several suites' names at once, by id, inside one organization."""
    if not suite_ids:
        return {}
    result = await db.execute(
        select(EvalSuite.id, EvalSuite.name).where(
            EvalSuite.id.in_(list(suite_ids)), EvalSuite.organization_id == organization_id
        )
    )
    return dict(result.tuples().all())


async def results_for_runs(
    db: AsyncSession, run_ids: Sequence[UUID], *, organization_id: UUID
) -> list[EvalSuiteResult]:
    """Settled results affected by a review, including comparisons using an older baseline."""
    if not run_ids:
        return []
    rows = await db.scalars(
        select(EvalSuiteResult)
        .where(
            EvalSuiteResult.organization_id == organization_id,
            EvalSuiteResult.eval_run_id.in_(run_ids),
            EvalSuiteResult.status.in_(_SETTLED),
        )
        .order_by(EvalSuiteResult.id)
        .with_for_update()
    )
    return list(rows)
