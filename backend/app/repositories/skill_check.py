"""Skill checks and their agents, and the questions an agent's answers loaded a skill on."""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.eval_run import EvalRun, EvalRunArm, EvalRunCase, EvalRunStatus
from app.db.models.skill_check import AgentState, CheckStatus, SkillCheck, SkillCheckAgent
from app.db.models.skill_usage import RunSkillUse
from app.repositories.skill_usage import used


class LoadedCase(NamedTuple):
    """A question whose newest answer from the agent loaded the skill, and when it answered."""

    case_id: UUID
    answered_at: datetime


async def create(db: AsyncSession, *, organization_id: UUID, check: SkillCheck) -> SkillCheck:
    check.organization_id = organization_id
    db.add(check)
    await db.flush()
    await db.refresh(check)
    return check


async def add_agents(
    db: AsyncSession, *, organization_id: UUID, rows: Sequence[SkillCheckAgent]
) -> list[SkillCheckAgent]:
    for row in rows:
        row.organization_id = organization_id
        db.add(row)
    await db.flush()
    return list(rows)


async def get(
    db: AsyncSession,
    check_id: UUID,
    *,
    organization_id: UUID,
    skill_id: UUID | None = None,
    lock: bool = False,
) -> SkillCheck | None:
    statement = select(SkillCheck).where(
        SkillCheck.id == check_id, SkillCheck.organization_id == organization_id
    )
    if skill_id is not None:
        statement = statement.where(SkillCheck.skill_id == skill_id)
    if lock:
        # Read afresh once the lock is held: a decision committed while it waited must
        # be seen, not the copy an earlier unlocked read left in the session.
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(statement)).scalar_one_or_none()


async def open_for_proposal(
    db: AsyncSession, proposal_id: UUID, *, organization_id: UUID
) -> list[SkillCheck]:
    """The checks of a proposal still running or finished and not yet decided."""
    rows = await db.execute(
        select(SkillCheck).where(
            SkillCheck.organization_id == organization_id,
            SkillCheck.proposal_id == proposal_id,
            SkillCheck.status.in_([CheckStatus.RUNNING.value, CheckStatus.DONE.value]),
        )
    )
    return list(rows.scalars())


async def list_for_skill(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skill_id: UUID,
    fork_id: UUID | None,
    skip: int,
    limit: int,
) -> tuple[list[SkillCheck], int]:
    """A line's checks, newest first."""
    where = [
        SkillCheck.organization_id == organization_id,
        SkillCheck.skill_id == skill_id,
        SkillCheck.fork_id.is_(None) if fork_id is None else SkillCheck.fork_id == fork_id,
    ]
    total = (
        await db.execute(select(func.count()).select_from(SkillCheck).where(*where))
    ).scalar_one()
    rows = await db.execute(
        select(SkillCheck)
        .where(*where)
        .order_by(SkillCheck.created_at.desc(), SkillCheck.id)
        .offset(skip)
        .limit(limit)
    )
    return list(rows.scalars()), total


async def list_agents(
    db: AsyncSession, check_ids: Collection[UUID], *, organization_id: UUID
) -> list[SkillCheckAgent]:
    if not check_ids:
        return []
    rows = await db.execute(
        select(SkillCheckAgent)
        .where(
            SkillCheckAgent.organization_id == organization_id,
            SkillCheckAgent.check_id.in_(check_ids),
        )
        .order_by(SkillCheckAgent.check_id, SkillCheckAgent.id)
    )
    return list(rows.scalars())


async def update(db: AsyncSession, *, row: SkillCheck, values: dict[str, Any]) -> SkillCheck:
    for name, value in values.items():
        setattr(row, name, value)
    await db.flush()
    await db.refresh(row)
    return row


async def update_agent(
    db: AsyncSession, *, row: SkillCheckAgent, values: dict[str, Any]
) -> SkillCheckAgent:
    for name, value in values.items():
        setattr(row, name, value)
    await db.flush()
    await db.refresh(row)
    return row


async def agent_for_run(
    db: AsyncSession, eval_run_id: UUID, *, organization_id: UUID
) -> SkillCheckAgent | None:
    """The check agent one of whose stages this eval run is."""
    return (
        await db.execute(
            select(SkillCheckAgent).where(
                SkillCheckAgent.organization_id == organization_id,
                or_(
                    SkillCheckAgent.skill_set_run_id == eval_run_id,
                    SkillCheckAgent.dataset_run_id == eval_run_id,
                ),
            )
        )
    ).scalar_one_or_none()


async def agents_for_runs(
    db: AsyncSession, eval_run_ids: Collection[UUID], *, organization_id: UUID
) -> list[SkillCheckAgent]:
    """The check agents one of whose stages is one of these eval runs."""
    if not eval_run_ids:
        return []
    result = await db.execute(
        select(SkillCheckAgent).where(
            SkillCheckAgent.organization_id == organization_id,
            or_(
                SkillCheckAgent.skill_set_run_id.in_(eval_run_ids),
                SkillCheckAgent.dataset_run_id.in_(eval_run_ids),
            ),
        )
    )
    return list(result.scalars().all())


async def running(db: AsyncSession, *, limit: int) -> list[tuple[UUID, UUID]]:
    """Checks still running in every organization, as `(organization_id, id)`, oldest first.

    The sweep's own read: it re-reads each one in its organization before acting.
    """
    rows = await db.execute(
        select(SkillCheck.organization_id, SkillCheck.id)
        .where(SkillCheck.status == CheckStatus.RUNNING.value)
        .order_by(SkillCheck.created_at)
        .limit(limit)
    )
    return [(org, check) for org, check in rows.all()]


async def loaded_cases(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    dataset_id: UUID,
    skill_id: UUID,
) -> list[LoadedCase]:
    """The dataset's questions whose newest answer from this agent loaded the skill.

    Only answers to the stored text count: an arm serving a projected body - an
    earlier check's candidate - says nothing about what the agent does today.
    """
    newest = (
        select(
            EvalRunCase.case_id.label("case_id"),
            EvalRunCase.agent_run_id.label("run_id"),
            EvalRunCase.ended_at.label("answered_at"),
        )
        .join(EvalRun, EvalRun.id == EvalRunCase.eval_run_id)
        .join(EvalRunArm, EvalRunArm.id == EvalRunCase.arm_id)
        .where(
            EvalRunCase.organization_id == organization_id,
            EvalRun.agent_id == agent_id,
            EvalRun.dataset_id == dataset_id,
            EvalRun.status == EvalRunStatus.COMPLETED.value,
            EvalRunArm.skill_bodies.is_(None),
            EvalRunCase.attempt == 0,
            EvalRunCase.agent_run_id.is_not(None),
            EvalRunCase.ended_at.is_not(None),
        )
        .ext(distinct_on(EvalRunCase.case_id))
        .order_by(EvalRunCase.case_id, EvalRunCase.ended_at.desc())
        .subquery()
    )
    rows = await db.execute(
        select(newest.c.case_id, newest.c.answered_at).where(
            select(RunSkillUse.id)
            .where(
                RunSkillUse.organization_id == organization_id,
                RunSkillUse.run_id == newest.c.run_id,
                RunSkillUse.skill_id == skill_id,
                RunSkillUse.projected.is_(False),
                used(),
            )
            .exists()
        )
    )
    return [LoadedCase(case_id, answered_at) for case_id, answered_at in rows.all()]


async def checked_versions(
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID, agent_ids: Collection[UUID]
) -> list[tuple[UUID, UUID, SkillCheckAgent, datetime]]:
    """For each agent, every version of the skill a check made after measuring it there -
    an agent the check could not measure was not checked on it.

    `(agent_id, version_id, the agent's row, when the check finished)`, newest check first.
    """
    if not agent_ids:
        return []
    rows = await db.execute(
        select(SkillCheckAgent, SkillCheck.applied_version_id, SkillCheck.finished_at)
        .join(SkillCheck, SkillCheck.id == SkillCheckAgent.check_id)
        .where(
            SkillCheck.organization_id == organization_id,
            SkillCheck.skill_id == skill_id,
            SkillCheck.applied_version_id.is_not(None),
            SkillCheck.finished_at.is_not(None),
            SkillCheckAgent.agent_id.in_(agent_ids),
            SkillCheckAgent.state != AgentState.UNKNOWN.value,
        )
        .order_by(SkillCheck.finished_at.desc())
    )
    found: list[tuple[UUID, UUID, SkillCheckAgent, datetime]] = []
    for row, version_id, finished_at in rows.all():
        assert version_id is not None and finished_at is not None
        found.append((row.agent_id, version_id, row, finished_at))
    return found
