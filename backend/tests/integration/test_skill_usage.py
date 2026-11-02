"""Which skills runs used, against Postgres.

What only a database shows:

- a resumed run's second write adds to its first instead of failing;
- the statistics count the runs that opened a skill or read its files, per agent,
  inside a window, and never an eval or a Builder test;
- a run that only named the skill's workspace folder is counted apart;
- the caller sees agents it may see and a count of the rest, needs `runs:view`,
  and never reaches another organization's skill.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.organization import Organization
from app.db.models.skill import Skill
from app.db.models.skill_usage import RunSkillUse
from app.db.models.user import User
from app.repositories import skill_usage_repo
from app.schemas.skill_usage import SkillUseRecord
from app.services.skills import SkillService

pytestmark = pytest.mark.anyio


async def _org(db: AsyncSession) -> tuple[Organization, User]:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(), name="Lab", slug=f"lab-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id
    )
    db.add(org)
    await db.flush()
    return org, user


async def _agent(db: AsyncSession, org: Organization, user: User, name: str) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=user.id,
        visibility="org",
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        name=name,
        status="draft",
        draft_spec={"name": name},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _skill(db: AsyncSession, org: Organization, name: str = "returns-policy") -> Skill:
    skill = Skill(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=name,
        description="How returns work",
        content="# Returns",
        visibility="org",
    )
    db.add(skill)
    await db.flush()
    return skill


async def _run(
    db: AsyncSession,
    org: Organization,
    agent: Agent,
    *,
    surface: RunSurface = RunSurface.WEB,
    is_test: bool = False,
    started_at: datetime | None = None,
) -> AgentRun:
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        surface=surface.value,
        status="completed",
        is_test=is_test,
        started_at=started_at or datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    return run


async def _used(
    db: AsyncSession,
    run: AgentRun,
    skill: Skill,
    *,
    agent: Agent | None = None,
    loaded: bool = True,
    resource_reads: int = 0,
    workspace_reads: int = 0,
    version: uuid.UUID | None = None,
) -> None:
    await skill_usage_repo.record_uses(
        db,
        [
            SkillUseRecord(
                agent_id=(agent.id if agent else run.agent_id),
                skill_id=skill.id,
                skill_version_id=version,
                loaded=loaded,
                resource_reads=resource_reads,
                workspace_reads=workspace_reads,
            )
        ],
        organization_id=run.organization_id,
        run_id=run.id,
        started_at=run.started_at or datetime.now(UTC),
    )


def _builder(org: Organization, user: User, **kwargs: object) -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.BUILDER, **kwargs)


class TestRecording:
    async def test_a_resumed_runs_second_write_adds_to_the_first(self, db: AsyncSession):
        org, user = await _org(db)
        agent = await _agent(db, org, user, "Desk")
        skill = await _skill(db, org)
        run = await _run(db, org, agent)

        await _used(db, run, skill, loaded=False, resource_reads=1)
        await _used(db, run, skill, loaded=True, resource_reads=2, workspace_reads=1)

        [row] = (await db.execute(select(RunSkillUse))).scalars().all()
        assert (row.loaded, row.resource_reads, row.workspace_reads) == (True, 3, 1)
        assert row.created_at == run.started_at

    async def test_a_parent_and_its_delegate_keep_a_row_each(self, db: AsyncSession):
        org, user = await _org(db)
        parent = await _agent(db, org, user, "Desk")
        delegate = await _agent(db, org, user, "Specialist")
        skill = await _skill(db, org)
        run = await _run(db, org, parent)

        await _used(db, run, skill)
        await _used(db, run, skill, agent=delegate)

        rows = (await db.execute(select(RunSkillUse.agent_id))).scalars().all()
        assert sorted(rows) == sorted([parent.id, delegate.id])

    async def test_nothing_to_write_writes_nothing(self, db: AsyncSession):
        org, user = await _org(db)
        agent = await _agent(db, org, user, "Desk")
        run = await _run(db, org, agent)

        await skill_usage_repo.record_uses(
            db, [], organization_id=org.id, run_id=run.id, started_at=datetime.now(UTC)
        )

        assert (await db.execute(select(RunSkillUse))).scalars().all() == []

    async def test_a_lost_write_leaves_the_run_unknown(self, db: AsyncSession):
        org, user = await _org(db)
        other, _ = await _org(db)
        agent = await _agent(db, org, user, "Desk")
        run = await _run(db, org, agent)
        assert run.skill_uses_recorded is True

        await skill_usage_repo.mark_unrecorded(db, organization_id=other.id, run_id=run.id)
        await db.refresh(run)
        assert run.skill_uses_recorded is True

        await skill_usage_repo.mark_unrecorded(db, organization_id=org.id, run_id=run.id)
        await db.refresh(run)
        assert run.skill_uses_recorded is False


class TestStatistics:
    async def test_runs_that_used_the_skill_are_counted_per_agent(self, db: AsyncSession):
        org, user = await _org(db)
        desk = await _agent(db, org, user, "Desk")
        clerk = await _agent(db, org, user, "Clerk")
        skill = await _skill(db, org)
        other_skill = await _skill(db, org, "shipping")
        for _ in range(3):
            await _used(db, await _run(db, org, desk), skill)
        await _used(db, await _run(db, org, desk), skill, loaded=False, resource_reads=2)
        await _used(db, await _run(db, org, clerk), skill)
        await _used(db, await _run(db, org, clerk), skill, loaded=False, workspace_reads=1)
        await _used(db, await _run(db, org, clerk), other_skill)
        # Neither an eval, a Builder test, nor a run outside the window counts.
        await _used(db, await _run(db, org, clerk, surface=RunSurface.EVAL), skill)
        await _used(db, await _run(db, org, clerk, is_test=True), skill)
        await _used(
            db,
            await _run(db, org, clerk, started_at=datetime.now(UTC) - timedelta(days=45)),
            skill,
        )

        usage = await SkillService(db).usage(_builder(org, user), skill.id, days=30)

        assert [
            (a.agent_name, a.loads, a.resource_reads, a.workspace_reads) for a in usage.agents
        ] == [
            ("Desk", 4, 2, 0),
            ("Clerk", 1, 0, 1),
        ]
        assert usage.loads == 5
        assert (usage.hidden_agents, usage.hidden_loads) == (0, 0)
        assert usage.agents[0].last_loaded_at is not None
        assert [(v.skill_version_id, v.loads) for v in usage.agents[0].versions] == [(None, 4)]

    async def test_loads_are_split_by_the_version_served(self, db: AsyncSession):
        org, user = await _org(db)
        desk = await _agent(db, org, user, "Desk")
        skill = await _skill(db, org)
        v1, v2 = uuid.uuid4(), uuid.uuid4()
        await _used(db, await _run(db, org, desk), skill, version=v1)
        await _used(db, await _run(db, org, desk), skill, version=v2)
        await _used(db, await _run(db, org, desk), skill, version=v2)

        usage = await SkillService(db).usage(_builder(org, user), skill.id, days=30)

        assert sorted((v.skill_version_id, v.loads) for v in usage.agents[0].versions) == sorted(
            [(v1, 1), (v2, 2)]
        )

    async def test_an_agent_the_caller_cannot_see_is_only_counted(self, db: AsyncSession):
        org, user = await _org(db)
        desk = await _agent(db, org, user, "Desk")
        skill = await _skill(db, org)
        await _used(db, await _run(db, org, desk), skill)
        await _used(db, await _run(db, org, desk), skill)
        # A key issued for runs and skills, never for agents.
        key = _builder(org, user, key_scopes=frozenset({Perm.RUNS_VIEW, Perm.SKILLS_VIEW}))

        usage = await SkillService(db).usage(key, skill.id, days=30)

        assert usage.agents == []
        assert (usage.loads, usage.hidden_agents, usage.hidden_loads) == (0, 1, 2)

    async def test_a_caller_without_runs_view_is_refused(self, db: AsyncSession):
        org, user = await _org(db)
        skill = await _skill(db, org)
        member = AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.MEMBER)

        with pytest.raises(AuthorizationError):
            await SkillService(db).usage(member, skill.id, days=30)

    async def test_another_organizations_skill_is_not_found(self, db: AsyncSession):
        org, user = await _org(db)
        other, other_user = await _org(db)
        foreign = await _skill(db, other)
        await _used(db, await _run(db, other, await _agent(db, other, other_user, "Desk")), foreign)

        with pytest.raises(NotFoundError):
            await SkillService(db).usage(_builder(org, user), foreign.id, days=30)
