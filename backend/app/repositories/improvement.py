"""Data access for improvement sessions and their rounds."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.improvement import (
    ACTIVE_STATUSES,
    WAITING_STATUSES,
    ImprovementIteration,
    ImprovementRun,
    ImprovementStatus,
)

_ACTIVE = tuple(status.value for status in ACTIVE_STATUSES)
_WAITING = tuple(status.value for status in WAITING_STATUSES)


async def create_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    created_by_user_id: UUID | None,
    created_by_api_key_id: UUID | None,
    base_version_id: UUID | None,
    base_draft_hash: str,
    dataset_id: UUID,
    dataset_version: int,
    suite_id: UUID | None,
    suite_hash: str | None,
    scoring_hash: str,
    window_days: int,
    estimate_usd: Decimal,
    budget_usd: Decimal,
    max_iterations: int,
) -> ImprovementRun:
    """A queued session.

    A second active session on the agent fails the flush with an
    `IntegrityError` on `uq_improvement_runs_active`; the caller turns it into
    its refusal.
    """
    run = ImprovementRun(
        organization_id=organization_id,
        agent_id=agent_id,
        created_by_user_id=created_by_user_id,
        created_by_api_key_id=created_by_api_key_id,
        status=ImprovementStatus.QUEUED.value,
        iteration=1,
        max_iterations=max_iterations,
        base_version_id=base_version_id,
        base_draft_hash=base_draft_hash,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        suite_id=suite_id,
        suite_hash=suite_hash,
        scoring_hash=scoring_hash,
        window_days=window_days,
        estimate_usd=estimate_usd,
        budget_usd=budget_usd,
        spent_usd=Decimal(0),
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def get_run(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID, lock: bool = False
) -> ImprovementRun | None:
    """One session. `lock` holds its row until the transaction ends.

    Every transition locks the session first, so two workers advancing the same
    session serialize and the second sees the child the first one started.
    """
    statement = (
        select(ImprovementRun)
        .where(ImprovementRun.id == run_id, ImprovementRun.organization_id == organization_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return result.scalar_one_or_none()


async def get_active(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID
) -> ImprovementRun | None:
    """The agent's queued or running session, if it has one."""
    result = await db.execute(
        select(ImprovementRun).where(
            ImprovementRun.organization_id == organization_id,
            ImprovementRun.agent_id == agent_id,
            ImprovementRun.status.in_(_ACTIVE),
        )
    )
    return result.scalar_one_or_none()


async def list_for_agent(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID, limit: int = 20
) -> list[ImprovementRun]:
    """The agent's sessions, newest first."""
    result = await db.execute(
        select(ImprovementRun)
        .where(
            ImprovementRun.organization_id == organization_id,
            ImprovementRun.agent_id == agent_id,
        )
        .order_by(ImprovementRun.created_at.desc(), ImprovementRun.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_active(
    db: AsyncSession, *, after: UUID | None = None, limit: int = 200
) -> list[tuple[UUID, UUID]]:
    """`(run id, organization id)` of queued and running sessions, a page at a time by id.

    Unscoped, for the deployment's sweep, which runs as nobody: it only learns
    which sessions to advance, and each transition then reads its session under
    the session's own organization. A session waiting on its child makes no
    transition, so the sweep pages past `after` rather than ordering by activity,
    which would hand it the same waiting sessions on every tick.
    """
    statement = select(ImprovementRun.id, ImprovementRun.organization_id).where(
        ImprovementRun.status.in_(_ACTIVE)
    )
    if after is not None:
        statement = statement.where(ImprovementRun.id > after)
    result = await db.execute(statement.order_by(ImprovementRun.id).limit(limit))
    return [(row.id, row.organization_id) for row in result.all()]


async def list_waiting(
    db: AsyncSession, *, after: UUID | None = None, limit: int = 200
) -> list[tuple[UUID, UUID]]:
    """`(run id, organization id)` of sessions waiting for a person, a page at a time by id.

    Unscoped, for the deployment's sweep, which settles a waiting session once
    its batch is published or replaced. A waiting session does not change on its
    own, so the sweep pages past `after` rather than reading the same first page
    on every tick.
    """
    statement = select(ImprovementRun.id, ImprovementRun.organization_id).where(
        ImprovementRun.status.in_(_WAITING)
    )
    if after is not None:
        statement = statement.where(ImprovementRun.id > after)
    result = await db.execute(statement.order_by(ImprovementRun.id).limit(limit))
    return [(row.id, row.organization_id) for row in result.all()]


async def update_run(
    db: AsyncSession, *, run: ImprovementRun, values: dict[str, Any]
) -> ImprovementRun:
    for field, value in values.items():
        setattr(run, field, value)
    await db.flush()
    await db.refresh(run)
    return run


async def create_iteration(
    db: AsyncSession, *, organization_id: UUID, run_id: UUID, number: int
) -> ImprovementIteration:
    iteration = ImprovementIteration(organization_id=organization_id, run_id=run_id, number=number)
    db.add(iteration)
    await db.flush()
    await db.refresh(iteration)
    return iteration


async def get_iteration(
    db: AsyncSession, *, organization_id: UUID, run_id: UUID, number: int
) -> ImprovementIteration | None:
    result = await db.execute(
        select(ImprovementIteration).where(
            ImprovementIteration.organization_id == organization_id,
            ImprovementIteration.run_id == run_id,
            ImprovementIteration.number == number,
        )
    )
    return result.scalar_one_or_none()


async def list_iterations(
    db: AsyncSession, *, organization_id: UUID, run_id: UUID
) -> list[ImprovementIteration]:
    """A session's rounds, first round first."""
    result = await db.execute(
        select(ImprovementIteration)
        .where(
            ImprovementIteration.organization_id == organization_id,
            ImprovementIteration.run_id == run_id,
        )
        .order_by(ImprovementIteration.number)
    )
    return list(result.scalars().all())


async def update_iteration(
    db: AsyncSession, *, iteration: ImprovementIteration, values: dict[str, Any]
) -> ImprovementIteration:
    for field, value in values.items():
        setattr(iteration, field, value)
    await db.flush()
    await db.refresh(iteration)
    return iteration


async def completed_checks(
    db: AsyncSession, eval_run_ids: list[UUID], *, organization_id: UUID
) -> int:
    """Count measurements, excluding explicit retries of failed paid children."""
    from app.db.models.eval_run import EvalRun, EvalRunStatus

    return (
        await db.scalar(
            select(func.count())
            .select_from(EvalRun)
            .where(
                EvalRun.id.in_(eval_run_ids),
                EvalRun.organization_id == organization_id,
                EvalRun.status == EvalRunStatus.COMPLETED.value,
            )
        )
    ) or 0


async def knowledge_checks(db: AsyncSession, run_id: UUID, *, organization_id: UUID) -> list[UUID]:
    """The draft checks belonging to a session, without copying their evidence."""
    from app.db.models.eval_run import EvalRun

    rows = await db.scalars(
        select(EvalRun.id)
        .where(
            EvalRun.organization_id == organization_id,
            EvalRun.proposal_check["improvement_run_id"].astext == str(run_id),
            EvalRun.proposal_check["knowledge"]["topic_id"].astext.is_not(None),
        )
        .order_by(EvalRun.created_at, EvalRun.id)
    )
    return list(rows)


async def timeline(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID
) -> list[AppAdminAuditLog]:
    rows = await db.scalars(
        select(AppAdminAuditLog)
        .where(
            AppAdminAuditLog.organization_id == organization_id,
            AppAdminAuditLog.target_type == "improvement",
            AppAdminAuditLog.target_id == str(run_id),
        )
        .order_by(AppAdminAuditLog.seq)
    )
    return list(rows)


async def spent(db: AsyncSession, run_id: UUID, *, organization_id: UUID) -> Decimal:
    from app.db.models.agent_run import AgentRun

    value = await db.scalar(
        select(func.coalesce(func.sum(AgentRun.cost_usd), 0)).where(
            AgentRun.organization_id == organization_id,
            AgentRun.improvement_run_id == run_id,
            AgentRun.parent_run_id.is_(None),
        )
    )
    assert value is not None, "a coalesced cost aggregate always has a value"
    archived = await db.scalar(
        select(ImprovementRun.archived_cost_usd).where(
            ImprovementRun.id == run_id, ImprovementRun.organization_id == organization_id
        )
    )
    from app.db.models.ingestion_spend import IngestionSpend

    embeddings = await db.scalar(
        select(func.coalesce(func.sum(IngestionSpend.cost_usd), 0)).where(
            IngestionSpend.organization_id == organization_id,
            IngestionSpend.improvement_run_id == run_id,
        )
    )
    return value + (archived or Decimal(0)) + (embeddings or Decimal(0))


async def has_active_check(db: AsyncSession, run_id: UUID, *, organization_id: UUID) -> bool:
    """Whether paid evaluation work still reserves this session's budget."""
    from app.db.models.eval_run import EvalRun

    return bool(
        await db.scalar(
            select(EvalRun.id)
            .where(
                EvalRun.organization_id == organization_id,
                EvalRun.proposal_check["improvement_run_id"].astext == str(run_id),
                EvalRun.status.in_(["queued", "running"]),
            )
            .limit(1)
        )
    )


async def measured_hunks(
    db: AsyncSession, *, organization_id: UUID, batch_id: UUID
) -> list[UUID] | None:
    """The measured selection for a session batch, or legacy full-proposal semantics."""
    return await db.scalar(
        select(ImprovementIteration.included_hunk_ids)
        .join(ImprovementRun, ImprovementRun.id == ImprovementIteration.run_id)
        .where(
            ImprovementRun.organization_id == organization_id,
            ImprovementIteration.organization_id == organization_id,
            ImprovementIteration.batch_id == batch_id,
        )
    )


async def runs_for_checks(
    db: AsyncSession, *, organization_id: UUID, check_ids: list[UUID]
) -> list[UUID]:
    """Sessions whose measured rounds depend on a reviewed comparison."""
    if not check_ids:
        return []
    rows = await db.scalars(
        select(ImprovementIteration.run_id)
        .where(
            ImprovementIteration.organization_id == organization_id,
            ImprovementIteration.eval_run_ids.overlap(check_ids),
            ImprovementIteration.verdict.is_not(None),
        )
        .distinct()
        .order_by(ImprovementIteration.run_id)
    )
    return list(rows.all())
