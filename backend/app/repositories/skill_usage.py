"""Which skills runs used: written by the runner, read for a skill's evidence and statistics."""

from collections.abc import Collection, Mapping, Sequence
from datetime import date, datetime
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.conversation import Message
from app.db.models.message_rating import MessageRating
from app.db.models.skill import Skill
from app.db.models.skill_usage import RunSkillUse
from app.db.models.skill_version import SkillFork, SkillVersion
from app.repositories.agent_run import served_runs
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


class RunUse(NamedTuple):
    skill_id: UUID
    name: str
    version: int | None
    fork: str | None
    loaded: bool


class DayUsage(NamedTuple):
    agent_id: UUID
    day: date
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
    The row keeps the version, and whether it was projected, that the first
    segment was served: there is one row per agent and skill, and a resumed segment
    served a newer version is credited to the older. The run's `skill_version_ids`
    names both.
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


async def mark_recorded(db: AsyncSession, *, organization_id: UUID, run_id: UUID) -> None:
    """Say a run's uses were written, so a run with none used no skill rather than unknown.

    A run one of whose segments could not be written stays unknown: what that
    segment used is lost, so a later segment's write does not make the run whole.
    """
    await db.execute(
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.organization_id == organization_id,
            AgentRun.skill_uses_recorded.is_not(False),
        )
        .values(skill_uses_recorded=True)
    )


async def mark_unrecorded(db: AsyncSession, *, organization_id: UUID, run_id: UUID) -> None:
    """Say part of a run's uses are lost, so the run stays unknown whatever is written later."""
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


async def answered_versions(
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID, agent_ids: Collection[UUID]
) -> list[tuple[UUID, UUID]]:
    """Each `(agent_id, skill_version_id)` an agent's served runs used, at any time."""
    if not agent_ids:
        return []
    rows = await db.execute(
        select(RunSkillUse.agent_id, RunSkillUse.skill_version_id)
        .distinct()
        .where(
            RunSkillUse.organization_id == organization_id,
            RunSkillUse.skill_id == skill_id,
            RunSkillUse.skill_version_id.is_not(None),
            RunSkillUse.agent_id.in_(list(agent_ids)),
            AgentRun.id == RunSkillUse.run_id,
            AgentRun.surface != RunSurface.EVAL.value,
            AgentRun.is_test.is_(False),
            used(),
        )
    )
    return [(agent_id, version_id) for agent_id, version_id in rows.all() if version_id is not None]


async def usage_by_day(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skill_id: UUID,
    since: datetime,
    agent_ids: Collection[UUID],
) -> list[DayUsage]:
    """How many of those runs used the skill on each UTC day, per agent; days with none
    are absent."""
    if not agent_ids:
        return []
    day = func.date(func.timezone("UTC", RunSkillUse.created_at))
    rows = await db.execute(
        select(RunSkillUse.agent_id, day, func.count(func.distinct(RunSkillUse.run_id)))
        .where(*_served(organization_id, skill_id, since))
        .where(used(), RunSkillUse.agent_id.in_(list(agent_ids)))
        .group_by(RunSkillUse.agent_id, day)
    )
    return [DayUsage(*row) for row in rows.all()]


async def uses_in_runs(
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID, run_ids: Collection[UUID]
) -> list[RunSkillUse]:
    """How each of these runs used the skill, one row per agent that used it."""
    if not run_ids:
        return []
    rows = await db.execute(
        select(RunSkillUse).where(
            RunSkillUse.organization_id == organization_id,
            RunSkillUse.skill_id == skill_id,
            RunSkillUse.run_id.in_(list(run_ids)),
        )
    )
    return list(rows.scalars().all())


async def skills_in_runs(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    run_ids: Collection[UUID],
    versions: Mapping[UUID, UUID | None] | None = None,
) -> dict[UUID, set[UUID]]:
    """For each skill the agent itself used in these runs, from a workspace path too, the runs.

    A delegate's use is the delegate's: it is not counted for the agent that delegated.
    With `versions`, a use counts only where the run was served the version named for
    its skill; a use whose version nobody recorded matches none.
    """
    if not run_ids:
        return {}
    rows = await db.execute(
        select(RunSkillUse.skill_id, RunSkillUse.run_id, RunSkillUse.skill_version_id).where(
            RunSkillUse.organization_id == organization_id,
            RunSkillUse.agent_id == agent_id,
            RunSkillUse.run_id.in_(list(run_ids)),
            or_(used(), RunSkillUse.workspace_reads > 0),
        )
    )
    found: dict[UUID, set[UUID]] = {}
    for skill_id, run_id, version_id in rows.tuples():
        if versions is not None and (version_id is None or versions.get(skill_id) != version_id):
            continue
        found.setdefault(skill_id, set()).add(run_id)
    return found


async def unknown_runs(
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID, since: datetime
) -> dict[UUID, int]:
    """Per agent, the rated-down or failed runs whose use of the skill nobody recorded.

    Runs from before uses were recorded, of an agent whose published version
    bound the skill - itself or through an inline specialist - with nothing copied
    from their transcripts either: they may have used it, and nothing says whether
    they did.
    """
    rated_down = (
        select(Message.id)
        .join(MessageRating, MessageRating.message_id == Message.id)
        .where(Message.run_id == AgentRun.id, MessageRating.rating < 0)
    )
    failed = AgentRun.status.in_(
        (RunStatus.FAILED.value, RunStatus.BUDGET_EXCEEDED.value, RunStatus.GUARDRAIL_BLOCKED.value)
    )
    recorded = select(RunSkillUse.id).where(
        RunSkillUse.run_id == AgentRun.id, RunSkillUse.skill_id == skill_id
    )
    rows = await db.execute(
        select(AgentRun.agent_id, func.count())
        .join(AgentVersion, AgentVersion.id == AgentRun.agent_version_id)
        .where(*served_runs(organization_id=organization_id, since=since))
        .where(
            AgentRun.skill_uses_recorded.is_not(True),
            or_(
                AgentVersion.spec["skill_ids"].contains([str(skill_id)]),
                AgentVersion.spec["capabilities"].contains(
                    [{"config": {"inline": [{"skill_ids": [str(skill_id)]}]}}]
                ),
            ),
            or_(rated_down.exists(), failed),
            ~recorded.exists(),
        )
        .group_by(AgentRun.agent_id)
    )
    return dict(rows.tuples().all())


async def agents_involved(
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID, since: datetime
) -> set[UUID]:
    """Every agent in a served run that used the skill: the run's own and any delegate."""
    rows = await db.execute(
        select(RunSkillUse.agent_id, AgentRun.agent_id)
        .join(AgentRun, AgentRun.id == RunSkillUse.run_id)
        .where(*served_runs(organization_id=organization_id, since=since))
        .where(RunSkillUse.skill_id == skill_id)
        .distinct()
    )
    return {agent_id for row in rows.all() for agent_id in row}


async def skills_of_run(db: AsyncSession, *, organization_id: UUID, run_id: UUID) -> list[RunUse]:
    """The skills one run used or read, each once per version it was served, by name.

    A delegate's use sits on the run under the delegate's own agent, so one skill can
    have a row per agent; they are one use here unless the versions differ.
    """
    rows = await db.execute(
        select(
            RunSkillUse.skill_id,
            Skill.name,
            SkillVersion.number,
            SkillFork.name,
            func.bool_or(RunSkillUse.loaded),
        )
        .join(Skill, Skill.id == RunSkillUse.skill_id)
        .outerjoin(SkillVersion, SkillVersion.id == RunSkillUse.skill_version_id)
        .outerjoin(SkillFork, SkillFork.id == SkillVersion.fork_id)
        .where(
            RunSkillUse.organization_id == organization_id,
            RunSkillUse.run_id == run_id,
            used(),
        )
        .group_by(RunSkillUse.skill_id, Skill.name, SkillVersion.number, SkillFork.name)
        .order_by(Skill.name, SkillVersion.number)
    )
    return [RunUse(*row) for row in rows.tuples().all()]
