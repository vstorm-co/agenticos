"""Rows in `eval_runs`, `eval_run_arms` and `eval_run_cases`."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import String, and_, cast, column, exists, func, not_, or_, select, true, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.locks import LockScope, hold_subject
from app.db.models.authoring import HunkStatus, SpecProposalBatch, SpecProposalHunk
from app.db.models.background_job import BackgroundJob
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
_STOPPED_MID_CASE = "The worker stopped mid-case."
# How long the worker goes on retrying a job's settler (`background_job.unsettled_ends`).
_SETTLED_WITHIN = timedelta(days=1)


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
    if EvalRunStatus(run.status).terminal:
        await clear_knowledge_overlays(db, [run.id])
    await db.refresh(run)
    return run


async def clear_knowledge_overlays(db: AsyncSession, eval_run_ids: Sequence[UUID]) -> None:
    """Drop run-only draft bodies while retaining the measured fingerprint and outcome."""
    runs = select(EvalRun.id).where(
        EvalRun.id.in_(eval_run_ids),
        EvalRun.proposal_check["knowledge"]["topic_id"].astext.is_not(None),
    )
    await db.execute(
        update(EvalRunArm).where(EvalRunArm.eval_run_id.in_(runs)).values(context_bodies=None)
    )
    await db.flush()


async def invalidate_knowledge_topics(
    db: AsyncSession, topic_ids: Sequence[UUID], *, only_live: bool = False
) -> list[UUID]:
    """Revoke checks and run-only bodies derived from replaced or erased drafts."""
    from app.schemas.eval_run import ProposalCheckRecord

    rows = await db.scalars(
        select(EvalRun)
        .where(
            EvalRun.proposal_check["knowledge"]["topic_id"].astext.in_(
                [str(key) for key in topic_ids]
            ),
            *([EvalRun.status.in_(_LIVE)] if only_live else []),
        )
        .order_by(EvalRun.id)
        .with_for_update()
    )
    ids: list[UUID] = []
    for run in rows:
        record = ProposalCheckRecord.model_validate(run.proposal_check)
        assert record.knowledge is not None
        record.knowledge.invalidated = True
        run.proposal_check = record.model_dump(mode="json")
        run.outcome = None
        run.outcome_at = None
        ids.append(run.id)
        if run.status in _LIVE:
            await _end_unfinished(
                db,
                [run.id],
                now=datetime.now(UTC),
                error="The knowledge draft changed or was removed",
            )
    await clear_knowledge_overlays(db, ids)
    return ids


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
    earlier: bool = False,
    since: datetime | None = None,
) -> list[EvalRun]:
    """An agent's runs that tested one draft, by the hash of its spec, newest first.

    A check of the authoring assistant's suggestions tested the draft they
    would make, so its candidate counts as a draft once they are accepted -
    unless it was measured against the draft itself, which says nothing of
    the draft against the published version it would replace.

    `earlier` turns it round: the runs that tested some other draft, made at
    `since` or later - a test the draft has since moved away from. A check
    counts there only once a suggestion it checked was accepted: one whose
    suggestions were all dismissed never tested any draft.
    """
    checked = and_(
        EvalRunArm.source == ArmSource.EXPLICIT.value,
        EvalRun.proposal_check["on_draft"].astext == "false",
    )
    if earlier:
        accepted = (
            select(SpecProposalHunk.id)
            .join(SpecProposalBatch, SpecProposalBatch.id == SpecProposalHunk.batch_id)
            .where(
                SpecProposalBatch.organization_id == organization_id,
                EvalRun.id == func.any(SpecProposalBatch.check_eval_run_ids),
                SpecProposalHunk.status == HunkStatus.ACCEPTED.value,
            )
        )
        checked = and_(checked, exists(accepted))
    tested = (
        select(EvalRunArm.eval_run_id)
        .join(EvalRun, EvalRun.id == EvalRunArm.eval_run_id)
        .where(
            EvalRunArm.organization_id == organization_id,
            EvalRunArm.role == ArmRole.CANDIDATE.value,
            or_(EvalRunArm.source == ArmSource.DRAFT.value, checked),
            EvalRunArm.spec_hash != spec_hash if earlier else EvalRunArm.spec_hash == spec_hash,
        )
    )
    after = [EvalRun.created_at >= since] if since is not None else []
    result = await db.execute(
        select(EvalRun)
        .where(
            EvalRun.organization_id == organization_id,
            EvalRun.agent_id == agent_id,
            EvalRun.dataset_id.in_(dataset_ids),
            EvalRun.id.in_(tested),
            *after,
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


async def forget_outcomes(
    db: AsyncSession, eval_run_ids: Sequence[UUID], *, organization_id: UUID
) -> list[UUID]:
    """Drop the kept verdict of these runs and of every run measured against one."""
    ids = [str(run_id) for run_id in eval_run_ids]
    result = await db.execute(
        update(EvalRun)
        .where(
            EvalRun.organization_id == organization_id,
            or_(
                EvalRun.id.in_(eval_run_ids),
                EvalRun.outcome["baseline"]["run_id"].astext.in_(ids),
            ),
        )
        .values(outcome=None, outcome_at=None)
        .returning(EvalRun.id)
        .execution_options(synchronize_session="fetch")
    )

    return list(result.scalars().all())


async def list_recent(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_ids: Sequence[UUID],
    dataset_ids: Sequence[UUID],
    skip: int = 0,
    limit: int,
) -> tuple[list[EvalRun], int]:
    """The organization's latest runs over agents and datasets the reader may see, and how many."""
    if not agent_ids or not dataset_ids:
        return [], 0
    conditions = [
        EvalRun.organization_id == organization_id,
        EvalRun.agent_id.in_(agent_ids),
        EvalRun.dataset_id.in_(dataset_ids),
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


async def scores_graded_by(
    db: AsyncSession, judge_run_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, CaseScore]:
    """The eval scores these judge runs graded, by the run each result names."""
    result = (
        func.jsonb_array_elements(CaseScore.results)
        .table_valued(column("value", JSONB))
        .render_derived(name="result")
    )
    graded_by = result.c.value["judge_run_id"].astext
    rows = await db.execute(
        select(CaseScore, graded_by)
        .join(result, true())
        .where(
            CaseScore.organization_id == organization_id,
            CaseScore.eval_run_id.is_not(None),
            graded_by.in_([str(run_id) for run_id in judge_run_ids]),
        )
    )
    return {UUID(run_id): score for score, run_id in rows.all()}


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


async def case_of_score(
    db: AsyncSession, case_score_id: UUID, *, organization_id: UUID
) -> EvalRunCase | None:
    """The attempt a score graded."""
    result = await db.execute(
        select(EvalRunCase).where(
            EvalRunCase.case_score_id == case_score_id,
            EvalRunCase.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_case(
    db: AsyncSession, attempt_id: UUID, *, organization_id: UUID
) -> EvalRunCase | None:
    result = await db.execute(
        select(EvalRunCase).where(
            EvalRunCase.id == attempt_id, EvalRunCase.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def finish_case(db: AsyncSession, *, case: EvalRunCase, values: dict[str, Any]) -> bool:
    """Write how a running attempt ended. `False` when it is not running any more.

    A worker whose lease ran out may still be answering while its job's settler
    failed the run and the attempt; what it writes afterwards is dropped, so a
    failed attempt never turns done, nor spends after its run ended.
    """
    result = await db.execute(
        update(EvalRunCase)
        .where(
            EvalRunCase.id == case.id,
            EvalRunCase.organization_id == case.organization_id,
            EvalRunCase.status == CaseAttemptStatus.RUNNING.value,
        )
        .values(**values)
        .returning(EvalRunCase.id)
    )
    return result.scalar_one_or_none() is not None


async def record_overlay_hits(
    db: AsyncSession, case: EvalRunCase, topic_ids: Sequence[UUID]
) -> None:
    """Keep only final retrieved topic identities, without resurrecting a closed attempt."""
    await db.execute(
        update(EvalRunCase)
        .where(
            EvalRunCase.id == case.id,
            EvalRunCase.organization_id == case.organization_id,
            EvalRunCase.status == CaseAttemptStatus.RUNNING.value,
        )
        .values(knowledge_overlay_topic_ids=list(topic_ids))
    )
    await db.flush()


async def link_run(db: AsyncSession, *, case: EvalRunCase, agent_run_id: UUID) -> bool:
    """Record the run answering an attempt as soon as it exists. `False` when the attempt is gone.

    Written before the model is called, so a run that then fails or is stopped
    can still be found from the attempt. An update rather than a write through
    the attempt's object, which a deleted dataset or eval run may have taken
    with it meanwhile.
    """
    result = await db.execute(
        update(EvalRunCase)
        .where(EvalRunCase.id == case.id, EvalRunCase.organization_id == case.organization_id)
        .values(agent_run_id=agent_run_id)
        .returning(EvalRunCase.id)
    )
    return result.scalar_one_or_none() is not None


async def claim_next(
    db: AsyncSession, eval_run_id: UUID, *, organization_id: UUID, org_limit: int, now: datetime
) -> EvalRunCase | None:
    """Mark the run's next pending attempt running, if the organization has room.

    The organization's running attempts are counted under a lock on the
    organization, so two workers - of this run or of another - cannot both read
    a count one below the limit and both start. A run that is no longer live
    yields nothing, which is how cancelling stops what has not started.
    `SKIP LOCKED` lets two workers of one run claim different attempts at once.

    An attempt holds its slot until it ends, whatever its run did meanwhile: a
    cancelled run lets the cases it started finish, and they still call the
    provider. One whose worker died is ended by the job's settler or, failing
    that, by `close_orphaned_attempts`.
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


class RunExecution(NamedTuple):
    """What a run executed under besides the version: which environment's test
    connections it reached, and whether recorded tool results answered its calls."""

    environment_id: UUID | None
    from_recordings: bool
    live_reads: bool


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
    execution: RunExecution | None = None,
    since: datetime | None = None,
    exclude_run_id: UUID | None = None,
) -> tuple[EvalRunArm, EvalRun] | None:
    """The newest arm of a completed run that ran this version, as published, on this dataset.

    Only an arm that can stand for the version: one that served no proposed
    skill or context body, in a run that left out none of its cases. Each
    narrowing argument left `None` matches anything. `execution` matches a run
    with no environment only to one with none.
    """
    conditions = [
        EvalRunArm.organization_id == organization_id,
        EvalRunArm.agent_version_id == agent_version_id,
        EvalRun.agent_id == agent_id,
        EvalRun.dataset_id == dataset_id,
        EvalRun.status == EvalRunStatus.COMPLETED.value,
        EvalRunArm.reused_from_arm_id.is_(None),
        EvalRunArm.skill_bodies.is_(None),
        EvalRunArm.context_bodies.is_(None),
        func.cardinality(EvalRun.excluded_case_ids) == 0,
    ]
    if dataset_version_id is not None:
        conditions.append(EvalRun.dataset_version_id == dataset_version_id)
    if model_profile_id is not None:
        conditions.append(EvalRunArm.model_profile_id == model_profile_id)
    if scoring_hash is not None:
        conditions.append(EvalRun.scoring_hash == scoring_hash)
    if execution is not None:
        conditions += [
            EvalRun.environment_id.is_not_distinct_from(execution.environment_id),
            EvalRun.from_recordings.is_(execution.from_recordings),
            EvalRun.live_reads.is_(execution.live_reads),
        ]
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


async def count_live_in_environment(
    db: AsyncSession, *, environment_id: UUID, organization_id: UUID
) -> int:
    """How many eval runs in an environment are queued or running."""
    count = await db.scalar(
        select(func.count())
        .select_from(EvalRun)
        .where(
            EvalRun.environment_id == environment_id,
            EvalRun.organization_id == organization_id,
            EvalRun.status.in_(_LIVE),
        )
    )
    return count or 0


async def count_live_with_model(
    db: AsyncSession, *, model_profile_id: UUID, organization_id: UUID
) -> int:
    """How many queued or running eval runs have a side that runs on this model."""
    count = await db.scalar(
        select(func.count(func.distinct(EvalRun.id)))
        .select_from(EvalRunArm)
        .join(EvalRun, EvalRun.id == EvalRunArm.eval_run_id)
        .where(
            EvalRunArm.model_profile_id == model_profile_id,
            EvalRunArm.organization_id == organization_id,
            EvalRun.status.in_(_LIVE),
        )
    )
    return count or 0


async def heartbeat(
    db: AsyncSession, eval_run_id: UUID, *, organization_id: UUID, now: datetime
) -> None:
    """Record that a run's worker is still at it.

    Also once the run has ended: a cancelled run's worker goes on finishing the
    cases it started, and this is how the sweep tells it from one that died.
    """
    await db.execute(
        update(EvalRun)
        .where(EvalRun.id == eval_run_id, EvalRun.organization_id == organization_id)
        .values(heartbeat_at=now)
    )
    await db.flush()


async def fail_abandoned(
    db: AsyncSession, *, idle_since: datetime, job_kind: str, now: datetime
) -> int:
    """Fail live runs whose worker is gone, across every organization.

    Unscoped by design: the sweep that calls it runs for the deployment, and a
    dead worker leaves runs behind in whichever organizations it was serving.

    A running run is abandoned when nothing about it has moved since
    `idle_since`: its worker has not beaten, no attempt started or ended, and it
    did not start after it either. A queued run has no worker to beat yet, so it
    is abandoned once no `job_kind` job is left to run it - however long a
    paused kind or a full pool keeps a job that is. Its unstarted attempts are skipped and its
    running ones failed, so the organization's concurrency count does not keep
    them forever.
    """
    # A job that ended but whose settler has not run yet still decides how its
    # run ends - cancelled, when an administrator withdrew it - for as long as
    # the settler is retried.
    job_left = exists().where(
        BackgroundJob.kind == job_kind,
        BackgroundJob.payload["eval_run_id"].astext == cast(EvalRun.id, String),
        or_(
            BackgroundJob.status.in_(("queued", "running")),
            and_(
                BackgroundJob.status.in_(("dead", "cancelled")),
                BackgroundJob.settled_at.is_(None),
                BackgroundJob.finished_at > now - _SETTLED_WITHIN,
            ),
        ),
    )
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
            or_(
                and_(
                    EvalRun.status == EvalRunStatus.RUNNING.value,
                    func.greatest(
                        EvalRun.created_at,
                        EvalRun.started_at,
                        EvalRun.heartbeat_at,
                        last_activity.c.moved,
                    )
                    < idle_since,
                ),
                and_(EvalRun.status == EvalRunStatus.QUEUED.value, not_(job_left)),
            )
        )
        .with_for_update(of=EvalRun, skip_locked=True)
    )
    abandoned = [row[0] for row in result.all()]
    if abandoned:
        await _end_unfinished(
            db,
            abandoned,
            now=now,
            error="The worker running this eval stopped before it finished.",
        )
    return len(abandoned)


async def close_orphaned_attempts(db: AsyncSession, *, ended_before: datetime) -> int:
    """Fail the attempts left running by ended runs whose worker is silent since `ended_before`.

    Unscoped, for the deployment's sweep, as `fail_abandoned` is. A run
    cancelled while its worker answered a case lets that case finish, however
    long it takes, for as long as the worker says it is alive. One whose worker
    died with it would otherwise stay running for good.
    """
    ended = select(EvalRun.id).where(
        EvalRun.status.not_in(_LIVE),
        func.greatest(EvalRun.ended_at, EvalRun.heartbeat_at) < ended_before,
    )
    result = await db.execute(
        update(EvalRunCase)
        .where(
            EvalRunCase.status == CaseAttemptStatus.RUNNING.value,
            EvalRunCase.eval_run_id.in_(ended),
        )
        .values(status=CaseAttemptStatus.FAILED.value, error=_STOPPED_MID_CASE)
        .returning(EvalRunCase.id)
    )
    return len(result.all())


async def fail_live(
    db: AsyncSession, eval_run_id: UUID, *, organization_id: UUID, now: datetime, error: str
) -> bool:
    """Fail a run that is still live, with the attempts it had not finished.

    Returns:
        False when the run is gone or had already ended, which keeps its outcome.
    """
    run = await lock(db, eval_run_id, organization_id=organization_id)
    if run is None or run.status not in _LIVE:
        return False
    await _end_unfinished(db, [run.id], now=now, error=error)
    return True


async def cancel_live(
    db: AsyncSession, eval_run_id: UUID, *, organization_id: UUID, now: datetime
) -> bool:
    """Cancel a run that is still live, and skip the attempts it had not started.

    Returns:
        False when the run is gone or had already ended, which keeps its outcome.
    """
    run = await lock(db, eval_run_id, organization_id=organization_id)
    if run is None or run.status not in _LIVE:
        return False
    await update_run(db, run=run, values={"status": EvalRunStatus.CANCELLED.value, "ended_at": now})
    await skip_pending(db, run.id, organization_id=organization_id)
    return True


async def _end_unfinished(
    db: AsyncSession, eval_run_ids: Sequence[UUID], *, now: datetime, error: str
) -> None:
    """Fail the runs, their running attempts with them, and skip what never started.

    The organization's eval concurrency counts running attempts, so an attempt
    left running would hold its slot for good.
    """
    await db.execute(
        update(EvalRunCase)
        .where(
            EvalRunCase.eval_run_id.in_(eval_run_ids),
            EvalRunCase.status == CaseAttemptStatus.PENDING.value,
        )
        .values(status=CaseAttemptStatus.SKIPPED.value)
    )
    await db.execute(
        update(EvalRunCase)
        .where(
            EvalRunCase.eval_run_id.in_(eval_run_ids),
            EvalRunCase.status == CaseAttemptStatus.RUNNING.value,
        )
        .values(status=CaseAttemptStatus.FAILED.value, error=_STOPPED_MID_CASE)
    )
    await db.execute(
        update(EvalRun)
        .where(EvalRun.id.in_(eval_run_ids))
        .values(status=EvalRunStatus.FAILED.value, error=error, ended_at=now)
    )
    await clear_knowledge_overlays(db, eval_run_ids)
    await db.flush()


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
