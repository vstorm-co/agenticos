"""Skill improvement sessions and their attempts."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.authoring import AuthoringRequest
from app.db.models.eval_run import EvalRunCase
from app.db.models.improvement import ACTIVE_STATUSES, OPEN_STATUSES
from app.db.models.skill_check import SkillCheckAgent
from app.db.models.skill_improvement import SkillImprovementIteration, SkillImprovementRun

_ACTIVE = tuple(status.value for status in ACTIVE_STATUSES)
_RESTING = tuple(status.value for status in OPEN_STATUSES if status not in ACTIVE_STATUSES)
"""Open but still: waiting for a person, with a result, stopped or failed - each ends in time."""

TIMELINE_TARGET = "skill_improvement"
"""The audit target type a session's steps are recorded under, and read back as its timeline."""


async def create_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skill_id: UUID,
    fork_id: UUID | None,
    base_version_id: UUID,
    created_by_user_id: UUID | None,
    created_by_api_key_id: UUID | None,
    window_days: int,
    max_iterations: int,
    estimate_usd: Decimal,
    budget_usd: Decimal,
    seed: dict[str, JsonValue] | None,
    purpose: str = "improve",
    source_fork_id: UUID | None = None,
    improver_agent_id: UUID | None = None,
) -> SkillImprovementRun:
    """A queued session.

    A second open session on the line fails the flush with an `IntegrityError` on
    `uq_skill_improvement_runs_open`; the caller turns it into its refusal.
    """
    run = SkillImprovementRun(
        organization_id=organization_id,
        skill_id=skill_id,
        fork_id=fork_id,
        base_version_id=base_version_id,
        created_by_user_id=created_by_user_id,
        created_by_api_key_id=created_by_api_key_id,
        window_days=window_days,
        max_iterations=max_iterations,
        estimate_usd=estimate_usd,
        budget_usd=budget_usd,
        seed=seed,
        purpose=purpose,
        source_fork_id=source_fork_id,
        improver_agent_id=improver_agent_id,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def get_run(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID, lock: bool = False
) -> SkillImprovementRun | None:
    """One session. `lock` holds its row until the transaction ends, so two advances serialize."""
    statement = (
        select(SkillImprovementRun)
        .where(
            SkillImprovementRun.id == run_id,
            SkillImprovementRun.organization_id == organization_id,
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update()
    return (await db.execute(statement)).scalar_one_or_none()


async def list_runs(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skill_id: UUID,
    lines: Sequence[UUID | None] | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[SkillImprovementRun]:
    """A skill's sessions, newest first - on the given lines only, when given (`None` is main)."""
    statement = select(SkillImprovementRun).where(
        SkillImprovementRun.organization_id == organization_id,
        SkillImprovementRun.skill_id == skill_id,
    )
    if lines is not None:
        forks = [line for line in lines if line is not None]
        on_line = SkillImprovementRun.fork_id.in_(forks)
        if None in lines:
            on_line = on_line | SkillImprovementRun.fork_id.is_(None)
        statement = statement.where(on_line)
    result = await db.execute(
        statement.order_by(SkillImprovementRun.created_at.desc()).offset(skip).limit(limit)
    )
    return list(result.scalars().all())


async def list_for_person(
    db: AsyncSession,
    *,
    organization_id: UUID,
    statuses: Sequence[str],
    skip: int = 0,
    limit: int = 20,
) -> list[SkillImprovementRun]:
    """The organization's sessions in these statuses, newest first."""
    result = await db.execute(
        select(SkillImprovementRun)
        .where(
            SkillImprovementRun.organization_id == organization_id,
            SkillImprovementRun.status.in_(statuses),
        )
        .order_by(SkillImprovementRun.created_at.desc(), SkillImprovementRun.id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_active(
    db: AsyncSession, *, after: UUID | None = None, limit: int = 200
) -> list[tuple[UUID, UUID]]:
    """`(run id, organization id)` of queued and running sessions, a page at a time by id.

    Unscoped, for the deployment's sweep, which runs as nobody: it only learns
    which sessions to advance, and each advance reads its session under the
    session's own organization.
    """
    return await _page(db, _ACTIVE, after=after, limit=limit)


async def list_resting(
    db: AsyncSession, *, after: UUID | None = None, limit: int = 200
) -> list[tuple[UUID, UUID]]:
    """`(run id, organization id)` of open sessions not working on their own, a page at a time by id.

    Unscoped, for the deployment's sweep, which ends the ones nobody took on in
    time; each is then read under its own organization.
    """
    return await _page(db, _RESTING, after=after, limit=limit)


async def _page(
    db: AsyncSession, statuses: Sequence[str], *, after: UUID | None, limit: int
) -> list[tuple[UUID, UUID]]:
    statement = select(SkillImprovementRun.id, SkillImprovementRun.organization_id).where(
        SkillImprovementRun.status.in_(statuses)
    )
    if after is not None:
        statement = statement.where(SkillImprovementRun.id > after)
    result = await db.execute(statement.order_by(SkillImprovementRun.id).limit(limit))
    return [(row.id, row.organization_id) for row in result.all()]


async def update_run(
    db: AsyncSession, *, run: SkillImprovementRun, values: dict[str, Any]
) -> SkillImprovementRun:
    for field, value in values.items():
        setattr(run, field, value)
    await db.flush()
    await db.refresh(run)
    return run


async def create_iteration(
    db: AsyncSession, *, organization_id: UUID, run_id: UUID, number: int, note: str | None
) -> SkillImprovementIteration:
    iteration = SkillImprovementIteration(
        organization_id=organization_id, run_id=run_id, number=number, note=note
    )
    db.add(iteration)
    await db.flush()
    await db.refresh(iteration)
    return iteration


async def get_iteration(
    db: AsyncSession, *, organization_id: UUID, run_id: UUID, number: int
) -> SkillImprovementIteration | None:
    result = await db.execute(
        select(SkillImprovementIteration).where(
            SkillImprovementIteration.organization_id == organization_id,
            SkillImprovementIteration.run_id == run_id,
            SkillImprovementIteration.number == number,
        )
    )
    return result.scalar_one_or_none()


async def list_iterations(
    db: AsyncSession, *, organization_id: UUID, run_id: UUID
) -> list[SkillImprovementIteration]:
    result = await db.execute(
        select(SkillImprovementIteration)
        .where(
            SkillImprovementIteration.organization_id == organization_id,
            SkillImprovementIteration.run_id == run_id,
        )
        .order_by(SkillImprovementIteration.number)
    )
    return list(result.scalars().all())


async def update_iteration(
    db: AsyncSession, *, iteration: SkillImprovementIteration, values: dict[str, Any]
) -> SkillImprovementIteration:
    for field, value in values.items():
        setattr(iteration, field, value)
    await db.flush()
    await db.refresh(iteration)
    return iteration


async def iteration_for_check(
    db: AsyncSession, check_id: UUID, *, organization_id: UUID
) -> SkillImprovementIteration | None:
    """The attempt a skill check measured, when a session started it - its check of the
    candidate, or a catch-up's of main alone."""
    result = await db.execute(
        select(SkillImprovementIteration).where(
            SkillImprovementIteration.organization_id == organization_id,
            or_(
                SkillImprovementIteration.skill_check_id == check_id,
                SkillImprovementIteration.main_alone_check_id == check_id,
            ),
        )
    )
    return result.scalar_one_or_none()


async def sessions_of_checks(
    db: AsyncSession, check_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, UUID]:
    """The session each of these skill checks measured an attempt of; others are absent."""
    if not check_ids:
        return {}
    ids = list(check_ids)
    result = await db.execute(
        select(
            SkillImprovementIteration.skill_check_id,
            SkillImprovementIteration.main_alone_check_id,
            SkillImprovementIteration.run_id,
        ).where(
            SkillImprovementIteration.organization_id == organization_id,
            or_(
                SkillImprovementIteration.skill_check_id.in_(ids),
                SkillImprovementIteration.main_alone_check_id.in_(ids),
            ),
        )
    )
    found: dict[UUID, UUID] = {}
    for row in result.all():
        for check_id in (row.skill_check_id, row.main_alone_check_id):
            if check_id in ids:
                found[check_id] = row.run_id
    return found


async def spent(db: AsyncSession, run_id: UUID, *, organization_id: UUID) -> Decimal:
    """What the session has cost: its analysis and proposals, and its attempts' checks."""
    requests = await db.scalar(
        select(func.coalesce(func.sum(AuthoringRequest.cost_usd), 0)).where(
            AuthoringRequest.organization_id == organization_id,
            AuthoringRequest.skill_improvement_run_id == run_id,
        )
    )
    checks = await db.scalar(
        select(func.coalesce(func.sum(SkillImprovementIteration.cost_usd), 0)).where(
            SkillImprovementIteration.organization_id == organization_id,
            SkillImprovementIteration.run_id == run_id,
        )
    )
    return Decimal(requests or 0) + Decimal(checks or 0)


async def check_cost(db: AsyncSession, check_id: UUID, *, organization_id: UUID) -> Decimal:
    """What a check's eval runs cost, across every agent and stage it ran."""
    runs = (
        select(SkillCheckAgent.skill_set_run_id.label("run_id"))
        .where(
            SkillCheckAgent.check_id == check_id,
            SkillCheckAgent.organization_id == organization_id,
        )
        .union_all(
            select(SkillCheckAgent.dataset_run_id).where(
                SkillCheckAgent.check_id == check_id,
                SkillCheckAgent.organization_id == organization_id,
            )
        )
        .subquery()
    )
    total = await db.scalar(
        select(func.coalesce(func.sum(EvalRunCase.cost_usd), 0)).where(
            EvalRunCase.organization_id == organization_id,
            EvalRunCase.eval_run_id.in_(select(runs.c.run_id)),
        )
    )
    return Decimal(total or 0)


async def timeline(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID
) -> list[AppAdminAuditLog]:
    rows = await db.scalars(
        select(AppAdminAuditLog)
        .where(
            AppAdminAuditLog.organization_id == organization_id,
            AppAdminAuditLog.target_type == TIMELINE_TARGET,
            AppAdminAuditLog.target_id == str(run_id),
        )
        .order_by(AppAdminAuditLog.seq)
    )
    return list(rows)
