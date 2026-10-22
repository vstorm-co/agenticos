"""Data access for improvement sessions and their rounds."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.improvement import ImprovementIteration, ImprovementRun, ImprovementStatus

_ACTIVE = (ImprovementStatus.QUEUED.value, ImprovementStatus.RUNNING.value)
_OPEN = (*_ACTIVE, ImprovementStatus.READY.value)


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
    statement = select(ImprovementRun).where(
        ImprovementRun.id == run_id, ImprovementRun.organization_id == organization_id
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


async def list_open(db: AsyncSession, *, limit: int = 200) -> list[tuple[UUID, UUID]]:
    """`(run id, organization id)` of sessions the sweep looks at, across organizations.

    The sweep runs as nobody, so it only learns which sessions to advance; each
    transition then reads its session under the session's own organization.
    """
    result = await db.execute(
        select(ImprovementRun.id, ImprovementRun.organization_id)
        .where(ImprovementRun.status.in_(_OPEN))
        .order_by(ImprovementRun.heartbeat_at.asc().nulls_first())
        .limit(limit)
    )
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
