"""Rows in `eval_runs`, `eval_run_arms` and `eval_run_cases`."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.locks import LockScope, hold_subject
from app.db.models.case_score import CaseScore
from app.db.models.dataset import Dataset, DatasetCase, DatasetVersion
from app.db.models.eval_run import (
    ArmRole,
    ArmSource,
    CaseAttemptStatus,
    EvalRun,
    EvalRunArm,
    EvalRunCase,
    EvalRunStatus,
)

_LIVE = (EvalRunStatus.QUEUED.value, EvalRunStatus.RUNNING.value)


async def create(
    db: AsyncSession, *, organization_id: UUID, run: EvalRun, arms: Sequence[EvalRunArm]
) -> EvalRun:
    """Write a run with its arms, so the arms can be given their cases."""
    run.organization_id = organization_id
    db.add(run)
    await db.flush()
    for arm in arms:
        arm.eval_run_id = run.id
        arm.organization_id = run.organization_id
        db.add(arm)
    await db.flush()
    await db.refresh(run)
    return run


async def add_cases(
    db: AsyncSession, *, organization_id: UUID, cases: Sequence[EvalRunCase]
) -> None:
    """Queue attempts. They belong to a run of this organization."""
    for case in cases:
        case.organization_id = organization_id
        db.add(case)
    await db.flush()


async def get(db: AsyncSession, eval_run_id: UUID, *, organization_id: UUID) -> EvalRun | None:
    result = await db.execute(
        select(EvalRun).where(EvalRun.id == eval_run_id, EvalRun.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def lock(db: AsyncSession, eval_run_id: UUID, *, organization_id: UUID) -> EvalRun | None:
    """The run, locked for a status change and read fresh rather than from the identity map."""
    result = await db.execute(
        select(EvalRun)
        .where(EvalRun.id == eval_run_id, EvalRun.organization_id == organization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def update_run(db: AsyncSession, *, run: EvalRun, values: dict[str, Any]) -> EvalRun:
    for name, value in values.items():
        setattr(run, name, value)
    await db.flush()
    await db.refresh(run)
    return run


async def list_arms(
    db: AsyncSession, eval_run_ids: Sequence[UUID], *, organization_id: UUID
) -> list[EvalRunArm]:
    """The arms of these runs, each run's in position order."""
    if not eval_run_ids:
        return []
    result = await db.execute(
        select(EvalRunArm)
        .where(
            EvalRunArm.eval_run_id.in_(eval_run_ids),
            EvalRunArm.organization_id == organization_id,
        )
        .order_by(EvalRunArm.eval_run_id, EvalRunArm.position)
    )
    return list(result.scalars().all())


async def get_arm(db: AsyncSession, arm_id: UUID, *, organization_id: UUID) -> EvalRunArm | None:
    result = await db.execute(
        select(EvalRunArm).where(
            EvalRunArm.id == arm_id, EvalRunArm.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def list_for_agent(
    db: AsyncSession,
    agent_id: UUID,
    *,
    organization_id: UUID,
    dataset_ids: Sequence[UUID] | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[EvalRun], int]:
    """An agent's runs, newest first, narrowed to datasets the reader may see."""
    conditions = [EvalRun.organization_id == organization_id, EvalRun.agent_id == agent_id]
    if dataset_ids is not None:
        conditions.append(EvalRun.dataset_id.in_(dataset_ids))
    total = await db.scalar(select(func.count()).select_from(EvalRun).where(*conditions))
    result = await db.execute(
        select(EvalRun)
        .where(*conditions)
        .order_by(EvalRun.created_at.desc(), EvalRun.id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), int(total or 0)


async def referenced_ids(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID | None = None,
    dataset_id: UUID | None = None,
) -> tuple[set[UUID], set[UUID]]:
    """Every agent and dataset this organization's runs name, optionally for one of either.

    Small by nature - a handful of datasets per agent - and what a listing
    narrows by access before it pages, so its total counts only what the
    reader may see.
    """
    conditions = [EvalRun.organization_id == organization_id]
    if agent_id is not None:
        conditions.append(EvalRun.agent_id == agent_id)
    if dataset_id is not None:
        conditions.append(EvalRun.dataset_id == dataset_id)
    result = await db.execute(
        select(EvalRun.agent_id, EvalRun.dataset_id).where(*conditions).distinct()
    )
    rows = result.all()
    return {row[0] for row in rows}, {row[1] for row in rows}


async def list_for_dataset(
    db: AsyncSession,
    dataset_id: UUID,
    *,
    organization_id: UUID,
    agent_ids: Sequence[UUID],
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[EvalRun], int]:
    """A dataset's runs, newest first, narrowed to agents the reader may see."""
    conditions = [
        EvalRun.organization_id == organization_id,
        EvalRun.dataset_id == dataset_id,
        EvalRun.agent_id.in_(agent_ids),
    ]
    total = await db.scalar(select(func.count()).select_from(EvalRun).where(*conditions))
    result = await db.execute(
        select(EvalRun)
        .where(*conditions)
        .order_by(EvalRun.created_at.desc(), EvalRun.id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), int(total or 0)


async def draft_runs(
    db: AsyncSession,
    agent_id: UUID,
    *,
    organization_id: UUID,
    dataset_ids: Sequence[UUID],
    spec_hash: str,
) -> list[EvalRun]:
    """An agent's runs that tested one draft, by the hash of its spec, newest first."""
    tested = select(EvalRunArm.eval_run_id).where(
        EvalRunArm.organization_id == organization_id,
        EvalRunArm.source == ArmSource.DRAFT.value,
        EvalRunArm.role == ArmRole.CANDIDATE.value,
        EvalRunArm.spec_hash == spec_hash,
    )
    result = await db.execute(
        select(EvalRun)
        .where(
            EvalRun.organization_id == organization_id,
            EvalRun.agent_id == agent_id,
            EvalRun.dataset_id.in_(dataset_ids),
            EvalRun.id.in_(tested),
        )
        .order_by(EvalRun.created_at.desc(), EvalRun.id)
    )
    return list(result.scalars().all())


async def reviewed_since(
    db: AsyncSession, eval_run_ids: Sequence[UUID], *, since: datetime, organization_id: UUID
) -> bool:
    """Whether a person decided any score of these runs after `since`."""
    return bool(
        await db.scalar(
            select(
                exists().where(
                    CaseScore.organization_id == organization_id,
                    CaseScore.eval_run_id.in_(eval_run_ids),
                    CaseScore.reviewed_at > since,
                )
            )
        )
    )


async def list_recent(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_ids: Sequence[UUID],
    dataset_ids: Sequence[UUID],
    limit: int,
) -> list[EvalRun]:
    """The organization's latest runs over agents and datasets the reader may see."""
    if not agent_ids or not dataset_ids:
        return []
    result = await db.execute(
        select(EvalRun)
        .where(
            EvalRun.organization_id == organization_id,
            EvalRun.agent_id.in_(agent_ids),
            EvalRun.dataset_id.in_(dataset_ids),
        )
        .order_by(EvalRun.created_at.desc(), EvalRun.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_cases(
    db: AsyncSession, eval_run_id: UUID, *, organization_id: UUID
) -> list[EvalRunCase]:
    """Every attempt of a run, in case order and then attempt order."""
    result = await db.execute(
        select(EvalRunCase)
        .where(
            EvalRunCase.eval_run_id == eval_run_id,
            EvalRunCase.organization_id == organization_id,
        )
        .order_by(EvalRunCase.position, EvalRunCase.arm_id, EvalRunCase.attempt)
    )
    return list(result.scalars().all())


async def case_of_agent_run(
    db: AsyncSession, agent_run_id: UUID, *, organization_id: UUID
) -> EvalRunCase | None:
    """The attempt an agent run answered, when an eval run started it."""
    result = await db.execute(
        select(EvalRunCase).where(
            EvalRunCase.agent_run_id == agent_run_id,
            EvalRunCase.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def score_graded_by(
    db: AsyncSession, judge_run_id: UUID, *, organization_id: UUID
) -> CaseScore | None:
    """The eval score a judge's run graded, by the run its results name."""
    result = await db.execute(
        select(CaseScore)
        .where(
            CaseScore.organization_id == organization_id,
            CaseScore.eval_run_id.is_not(None),
            CaseScore.results.contains([{"judge_run_id": str(judge_run_id)}]),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def cases_of_agent_runs(
    db: AsyncSession, agent_run_ids: Sequence[UUID], *, organization_id: UUID
) -> list[EvalRunCase]:
    """The attempts these agent runs answered, for the ones an eval run started."""
    result = await db.execute(
        select(EvalRunCase).where(
            EvalRunCase.agent_run_id.in_(agent_run_ids),
            EvalRunCase.organization_id == organization_id,
        )
    )
    return list(result.scalars().all())


async def get_many(
    db: AsyncSession, eval_run_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, EvalRun]:
    result = await db.execute(
        select(EvalRun).where(
            EvalRun.id.in_(eval_run_ids), EvalRun.organization_id == organization_id
        )
    )
    return {run.id: run for run in result.scalars().all()}


async def list_arm_cases(
    db: AsyncSession, arm_id: UUID, *, organization_id: UUID
) -> list[EvalRunCase]:
    """Every attempt of one arm - how a cached or past arm is read as a baseline."""
    result = await db.execute(
        select(EvalRunCase)
        .where(EvalRunCase.arm_id == arm_id, EvalRunCase.organization_id == organization_id)
        .order_by(EvalRunCase.position, EvalRunCase.attempt)
    )
    return list(result.scalars().all())


async def get_case(
    db: AsyncSession, attempt_id: UUID, *, organization_id: UUID
) -> EvalRunCase | None:
    result = await db.execute(
        select(EvalRunCase).where(
            EvalRunCase.id == attempt_id, EvalRunCase.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def update_case(
    db: AsyncSession, *, case: EvalRunCase, values: dict[str, Any]
) -> EvalRunCase:
    for name, value in values.items():
        setattr(case, name, value)
    await db.flush()
    await db.refresh(case)
    return case


async def claim_next(
    db: AsyncSession, eval_run_id: UUID, *, organization_id: UUID, org_limit: int, now: datetime
) -> EvalRunCase | None:
    """Mark the run's next pending attempt running, if the organization has room.

    The organization's running attempts are counted under a lock on the
    organization, so two workers - of this run or of another - cannot both read
    a count one below the limit and both start. A run that is no longer live
    yields nothing, which is how cancelling stops what has not started.
    `SKIP LOCKED` lets two workers of one run claim different attempts at once.
    """
    await hold_subject(db, LockScope.EVAL_CASES_PER_ORGANIZATION, organization_id)
    running = await db.scalar(
        select(func.count())
        .select_from(EvalRunCase)
        .where(
            EvalRunCase.organization_id == organization_id,
            EvalRunCase.status == CaseAttemptStatus.RUNNING.value,
        )
    )
    if int(running or 0) >= org_limit:
        return None
    result = await db.execute(
        select(EvalRunCase)
        .join(EvalRun, EvalRun.id == EvalRunCase.eval_run_id)
        .where(
            EvalRunCase.eval_run_id == eval_run_id,
            EvalRunCase.organization_id == organization_id,
            EvalRunCase.status == CaseAttemptStatus.PENDING.value,
            EvalRun.status.in_(_LIVE),
        )
        .order_by(EvalRunCase.attempt, EvalRunCase.position, EvalRunCase.arm_id)
        .limit(1)
        .with_for_update(of=EvalRunCase, skip_locked=True)
    )
    case = result.scalar_one_or_none()
    if case is None:
        return None
    case.status = CaseAttemptStatus.RUNNING.value
    case.started_at = now
    await db.flush()
    return case


async def count_by_status(
    db: AsyncSession, eval_run_id: UUID, *, organization_id: UUID
) -> dict[str, int]:
    result = await db.execute(
        select(EvalRunCase.status, func.count())
        .where(
            EvalRunCase.eval_run_id == eval_run_id,
            EvalRunCase.organization_id == organization_id,
        )
        .group_by(EvalRunCase.status)
    )
    return {status: int(count) for status, count in result.all()}


async def skip_pending(db: AsyncSession, eval_run_id: UUID, *, organization_id: UUID) -> int:
    """Mark every attempt that has not started as skipped. Returns how many."""
    result = await db.execute(
        update(EvalRunCase)
        .where(
            EvalRunCase.eval_run_id == eval_run_id,
            EvalRunCase.organization_id == organization_id,
            EvalRunCase.status == CaseAttemptStatus.PENDING.value,
        )
        .values(status=CaseAttemptStatus.SKIPPED.value)
    )
    await db.flush()
    # `execute` is typed to return `Result`, which has no `rowcount`; a DML
    # statement's result does have one.
    return int(result.rowcount or 0)  # ty: ignore[unresolved-attribute]


async def latest_arm(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    dataset_id: UUID,
    agent_version_id: UUID,
    dataset_version_id: UUID | None = None,
    model_profile_id: UUID | None = None,
    scoring_hash: str | None = None,
    since: datetime | None = None,
    exclude_run_id: UUID | None = None,
) -> tuple[EvalRunArm, EvalRun] | None:
    """The newest arm of a completed run that ran this version on this dataset.

    Each narrowing argument left `None` matches anything. With all of them it is
    the cached-baseline lookup; with none it is the default comparison's "the
    last run of the previous version".
    """
    conditions = [
        EvalRunArm.organization_id == organization_id,
        EvalRunArm.agent_version_id == agent_version_id,
        EvalRun.agent_id == agent_id,
        EvalRun.dataset_id == dataset_id,
        EvalRun.status == EvalRunStatus.COMPLETED.value,
        EvalRunArm.reused_from_arm_id.is_(None),
    ]
    if dataset_version_id is not None:
        conditions.append(EvalRun.dataset_version_id == dataset_version_id)
    if model_profile_id is not None:
        conditions.append(EvalRunArm.model_profile_id == model_profile_id)
    if scoring_hash is not None:
        conditions.append(EvalRun.scoring_hash == scoring_hash)
    if since is not None:
        conditions.append(EvalRun.ended_at >= since)
    if exclude_run_id is not None:
        conditions.append(EvalRun.id != exclude_run_id)
    result = await db.execute(
        select(EvalRunArm, EvalRun)
        .join(EvalRun, EvalRun.id == EvalRunArm.eval_run_id)
        .where(*conditions)
        .order_by(EvalRun.ended_at.desc(), EvalRunArm.position)
        .limit(1)
    )
    row = result.first()
    return (row[0], row[1]) if row is not None else None


async def fail_abandoned(db: AsyncSession, *, idle_since: datetime, now: datetime) -> int:
    """Fail live runs whose worker is gone, across every organization.

    Unscoped by design: the sweep that calls it runs for the deployment, and a
    dead worker leaves runs behind in whichever organizations it was serving.

    A run is abandoned when it is live and nothing about it has moved since
    `idle_since`: no attempt started or ended after it, and it was not created
    after it either. Its unstarted attempts are skipped and its running ones
    failed, so the organization's concurrency count does not keep them forever.
    """
    last_activity = (
        select(
            EvalRunCase.eval_run_id,
            func.max(func.greatest(EvalRunCase.started_at, EvalRunCase.ended_at)).label("moved"),
        )
        .group_by(EvalRunCase.eval_run_id)
        .subquery()
    )
    result = await db.execute(
        select(EvalRun.id)
        .outerjoin(last_activity, last_activity.c.eval_run_id == EvalRun.id)
        .where(
            EvalRun.status.in_(_LIVE),
            EvalRun.created_at < idle_since,
            func.coalesce(last_activity.c.moved, EvalRun.created_at) < idle_since,
        )
        .with_for_update(of=EvalRun, skip_locked=True)
    )
    abandoned = [row[0] for row in result.all()]
    if not abandoned:
        return 0
    await db.execute(
        update(EvalRunCase)
        .where(
            EvalRunCase.eval_run_id.in_(abandoned),
            EvalRunCase.status == CaseAttemptStatus.PENDING.value,
        )
        .values(status=CaseAttemptStatus.SKIPPED.value)
    )
    await db.execute(
        update(EvalRunCase)
        .where(
            EvalRunCase.eval_run_id.in_(abandoned),
            EvalRunCase.status == CaseAttemptStatus.RUNNING.value,
        )
        .values(status=CaseAttemptStatus.FAILED.value, error="The worker stopped mid-case.")
    )
    await db.execute(
        update(EvalRun)
        .where(EvalRun.id.in_(abandoned))
        .values(
            status=EvalRunStatus.FAILED.value,
            error="The worker running this eval stopped before it finished.",
            ended_at=now,
        )
    )
    await db.flush()
    return len(abandoned)


async def scores(
    db: AsyncSession, score_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, CaseScore]:
    """The case scores behind a set of attempts, by id."""
    if not score_ids:
        return {}
    result = await db.execute(
        select(CaseScore).where(
            CaseScore.id.in_(list(score_ids)), CaseScore.organization_id == organization_id
        )
    )
    return {score.id: score for score in result.scalars().all()}


async def revisions(
    db: AsyncSession, revision_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, DatasetCase]:
    """The case revisions a run answered, by id - whatever version holds them now."""
    if not revision_ids:
        return {}
    result = await db.execute(
        select(DatasetCase).where(
            DatasetCase.id.in_(list(revision_ids)), DatasetCase.organization_id == organization_id
        )
    )
    return {revision.id: revision for revision in result.scalars().all()}


async def datasets(
    db: AsyncSession, dataset_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, Dataset]:
    if not dataset_ids:
        return {}
    result = await db.execute(
        select(Dataset).where(
            Dataset.id.in_(list(dataset_ids)), Dataset.organization_id == organization_id
        )
    )
    return {dataset.id: dataset for dataset in result.scalars().all()}


async def dataset_version_numbers(
    db: AsyncSession, version_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, int]:
    if not version_ids:
        return {}
    result = await db.execute(
        select(DatasetVersion.id, DatasetVersion.number).where(
            DatasetVersion.id.in_(list(version_ids)),
            DatasetVersion.organization_id == organization_id,
        )
    )
    return {row[0]: int(row[1]) for row in result.all()}
