"""Which skills runs used: written by the runner, read for a skill's evidence and statistics."""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.skill_usage import RunSkillUse
from app.schemas.skill_usage import SkillUseRecord


class AgentUsage(NamedTuple):
    agent_id: UUID
    loads: int
    resource_reads: int
    workspace_reads: int
    last_loaded_at: datetime | None


class VersionUsage(NamedTuple):
    agent_id: UUID
    skill_version_id: UUID | None
    loads: int


def used() -> ColumnElement[bool]:
    """A use that opened the skill or read one of its files through the skill's own tool."""
    return or_(RunSkillUse.loaded.is_(True), RunSkillUse.resource_reads > 0)


async def record_uses(
    db: AsyncSession,
    records: Sequence[SkillUseRecord],
    *,
    organization_id: UUID,
    run_id: UUID,
    started_at: datetime,
) -> None:
    """Write a run's uses in one statement, adding to what an earlier segment of it wrote.

    A run that parked on an approval and resumed is one row finished twice, so a
    second write for the same agent and skill adds its counts rather than failing.
    """
    if not records:
        return
    statement = insert(RunSkillUse).values(
        [
            {
                "organization_id": organization_id,
                "run_id": run_id,
                "agent_id": record.agent_id,
                "skill_id": record.skill_id,
                "skill_version_id": record.skill_version_id,
                "projected": record.projected,
                "loaded": record.loaded,
                "resource_reads": record.resource_reads,
                "workspace_reads": record.workspace_reads,
                "created_at": started_at,
            }
            for record in records
        ]
    )
    await db.execute(
        statement.on_conflict_do_update(
            constraint="uq_run_skill_uses_run_agent_skill",
            set_={
                "loaded": RunSkillUse.loaded | statement.excluded.loaded,
                "resource_reads": RunSkillUse.resource_reads + statement.excluded.resource_reads,
                "workspace_reads": RunSkillUse.workspace_reads + statement.excluded.workspace_reads,
            },
        )
    )


async def mark_unrecorded(db: AsyncSession, *, organization_id: UUID, run_id: UUID) -> None:
    """Say a run's uses could not be written, so it reads as unknown rather than unused."""
    await db.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.organization_id == organization_id)
        .values(skill_uses_recorded=False)
    )


def _served(organization_id: UUID, skill_id: UUID, since: datetime) -> list[ColumnElement[bool]]:
    """One skill's uses in runs that served somebody - not an eval, not a Builder test."""
    return [
        RunSkillUse.organization_id == organization_id,
        RunSkillUse.skill_id == skill_id,
        RunSkillUse.created_at >= since,
        AgentRun.id == RunSkillUse.run_id,
        AgentRun.surface != RunSurface.EVAL.value,
        AgentRun.is_test.is_(False),
    ]


async def usage_by_agent(
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID, since: datetime
) -> list[AgentUsage]:
    """How often each agent used a skill since `since`, most used first.

    A run that only named a path in the skill's workspace folder counts under
    `workspace_reads` alone.
    """
    is_used = used()
    probable = and_(~is_used, RunSkillUse.workspace_reads > 0)
    loads = func.count(func.distinct(RunSkillUse.run_id)).filter(is_used)
    rows = await db.execute(
        select(
            RunSkillUse.agent_id,
            loads,
            func.coalesce(func.sum(RunSkillUse.resource_reads), 0),
            func.count(func.distinct(RunSkillUse.run_id)).filter(probable),
            func.max(RunSkillUse.created_at).filter(is_used),
        )
        .where(*_served(organization_id, skill_id, since))
        .group_by(RunSkillUse.agent_id)
        .order_by(loads.desc(), RunSkillUse.agent_id)
    )
    return [AgentUsage(*row) for row in rows.all()]


async def usage_by_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skill_id: UUID,
    since: datetime,
    agent_ids: Collection[UUID],
) -> list[VersionUsage]:
    """How many of those runs used each version of the skill, per agent."""
    if not agent_ids:
        return []
    rows = await db.execute(
        select(
            RunSkillUse.agent_id,
            RunSkillUse.skill_version_id,
            func.count(func.distinct(RunSkillUse.run_id)),
        )
        .where(*_served(organization_id, skill_id, since))
        .where(used(), RunSkillUse.agent_id.in_(list(agent_ids)))
        .group_by(RunSkillUse.agent_id, RunSkillUse.skill_version_id)
    )
    return [VersionUsage(*row) for row in rows.all()]
