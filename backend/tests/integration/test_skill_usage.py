"""Which skills runs used, against Postgres.

What only a database shows:

- a resumed run's second write adds to its first instead of failing;
- the statistics count the runs that opened a skill or read its files, per agent,
  inside a window, and never an eval or a Builder test;
- a run that only named the skill's workspace folder is counted apart;
- the caller sees agents it may see and a count of the rest, needs `runs:view`,
  and never reaches another organization's skill;
- a skill's evidence reads the runs that used it across agents, a delegate's
  too, counts the older runs nobody recorded as unknown, and withholds the text
  of a conversation the reader may not open.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.skills import ServedSkill, SkillUseLog
from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.conversation import Conversation, Message
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization
from app.db.models.skill import Skill
from app.db.models.skill_usage import RunSkillUse
from app.db.models.skill_version import SkillVersionSource
from app.db.models.user import User
from app.repositories import agent_run_repo, skill_usage_repo, skill_version_repo
from app.schemas.skill_usage import SkillUseRecord
from app.services.agent_runner import AgentRunnerService, PreparedRun
from app.services.authoring_evidence import EvidenceService
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


async def _version(db: AsyncSession, skill: Skill, number: int) -> uuid.UUID:
    version = await skill_version_repo.create_version(
        db,
        organization_id=skill.organization_id,
        skill_id=skill.id,
        fork_id=None,
        number=number,
        description=skill.description,
        content=skill.content,
        resources={},
        source=SkillVersionSource.EDIT,
        restored_from_id=None,
        proposal_id=None,
        library_fingerprint=None,
        created_by_user_id=None,
    )
    return version.id


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

        first, newer = await _version(db, skill, 1), await _version(db, skill, 2)

        await _used(db, run, skill, loaded=False, resource_reads=1, version=first)
        await _used(db, run, skill, loaded=True, resource_reads=2, workspace_reads=1, version=newer)

        [row] = (await db.execute(select(RunSkillUse))).scalars().all()
        assert (row.loaded, row.resource_reads, row.workspace_reads) == (True, 3, 1)
        assert row.created_at == run.started_at
        assert row.skill_version_id == first

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

    async def test_a_run_is_unknown_until_its_finish_records_what_it_used(self, db: AsyncSession):
        org, user = await _org(db)
        agent = await _agent(db, org, user, "Desk")
        skill = await _skill(db, org)

        async def started() -> AgentRun:
            return await agent_run_repo.create_run(
                db,
                organization_id=org.id,
                agent_id=agent.id,
                agent_version_id=None,
                user_id=user.id,
                conversation_id=None,
                surface=RunSurface.API.value,
                model_label=None,
                started_at=datetime.now(UTC),
            )

        kept, lost = await started(), await started()
        assert (kept.skill_uses_recorded, lost.skill_uses_recorded) == (None, None)
        service = AgentRunnerService(db)

        for run in (kept, lost):
            log = SkillUseLog(agent_id=agent.id, served={skill.name: ServedSkill(skill.id)})
            log.observe("load_capability", {"id": skill.name})
            prepared = PreparedRun(
                run=run,
                agent=agent,
                spec=AgentSpec(name="Desk"),
                built=MagicMock(),
                approvals=MagicMock(),
                skill_uses=log,
            )
            if run is kept:
                await service._write_skill_uses(prepared)
            else:
                with patch(
                    "app.services.agent_runner.skill_usage_repo.mark_recorded",
                    new=AsyncMock(side_effect=RuntimeError("connection lost")),
                ):
                    await service._write_skill_uses(prepared)

        await db.refresh(kept)
        await db.refresh(lost)
        assert (kept.skill_uses_recorded, lost.skill_uses_recorded) == (True, False)
        rows = (await db.execute(select(RunSkillUse.run_id))).scalars().all()
        # The failed savepoint took the use it had written with it.
        assert rows == [kept.id]

    async def test_marking_a_run_recorded_stays_inside_its_organization(self, db: AsyncSession):
        org, user = await _org(db)
        other, _ = await _org(db)
        agent = await _agent(db, org, user, "Desk")
        run = await _run(db, org, agent)
        run.skill_uses_recorded = None
        await db.flush()

        await skill_usage_repo.mark_recorded(db, organization_id=other.id, run_id=run.id)
        await skill_usage_repo.mark_unrecorded(db, organization_id=other.id, run_id=run.id)
        await db.refresh(run)
        assert run.skill_uses_recorded is None

        await skill_usage_repo.mark_recorded(db, organization_id=org.id, run_id=run.id)
        await db.refresh(run)
        assert run.skill_uses_recorded is True

    @pytest.mark.parametrize("failed_first", [True, False])
    async def test_a_segment_that_could_not_be_written_leaves_the_run_unknown(
        self, db: AsyncSession, failed_first: bool
    ):
        """A run parked on an approval is written once per segment, in either order."""
        org, user = await _org(db)
        agent = await _agent(db, org, user, "Desk")
        skill = await _skill(db, org)
        run = await _run(db, org, agent)
        run.skill_uses_recorded = None
        await db.flush()
        service = AgentRunnerService(db)

        async def segment(*, fails: bool) -> None:
            log = SkillUseLog(agent_id=agent.id, served={skill.name: ServedSkill(skill.id)})
            log.observe("load_capability", {"id": skill.name})
            prepared = PreparedRun(
                run=run,
                agent=agent,
                spec=AgentSpec(name="Desk"),
                built=MagicMock(),
                approvals=MagicMock(),
                skill_uses=log,
            )
            if not fails:
                await service._write_skill_uses(prepared)
                return
            with patch(
                "app.services.agent_runner.skill_usage_repo.record_uses",
                new=AsyncMock(side_effect=RuntimeError("connection lost")),
            ):
                await service._write_skill_uses(prepared)

        await segment(fails=failed_first)
        await segment(fails=not failed_first)

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

    async def test_a_run_names_the_skills_it_used_at_their_versions(self, db: AsyncSession):
        """By name and version, for the run's own page; a skill only offered, and one the
        reader may not see, are left out."""
        org, user = await _org(db)
        desk = await _agent(db, org, user, "Desk")
        clerk = await _agent(db, org, user, "Clerk")
        skill = await _skill(db, org)
        offered = await _skill(db, org, "shipping")
        _, stranger = await _org(db)
        hidden = await _skill(db, org, "payroll")
        hidden.visibility = "private"
        hidden.owner_user_id = stranger.id
        await db.flush()
        run = await _run(db, org, desk)
        version = await _version(db, skill, 2)
        await skill_usage_repo.record_uses(
            db,
            [
                SkillUseRecord(
                    agent_id=desk.id, skill_id=skill.id, skill_version_id=version, loaded=True
                ),
                SkillUseRecord(agent_id=desk.id, skill_id=offered.id, loaded=False),
                SkillUseRecord(agent_id=desk.id, skill_id=hidden.id, loaded=True),
                # A delegate that read the same version counts as the same use.
                SkillUseRecord(
                    agent_id=clerk.id,
                    skill_id=skill.id,
                    skill_version_id=version,
                    loaded=False,
                    resource_reads=1,
                ),
            ],
            organization_id=org.id,
            run_id=run.id,
            started_at=datetime.now(UTC),
        )

        viewer = AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.VIEWER)
        used = await SkillService(db).used_in_run(viewer, run.id)

        assert [(use.name, use.version, use.fork, use.loaded) for use in used] == [
            ("returns-policy", 2, None, True)
        ]

    async def test_the_gallery_names_the_copy_an_organization_installed(self, db: AsyncSession):
        org, user = await _org(db)
        installed = await _skill(db, org, "agenticos-guide")
        await _skill(db, org)

        gallery = await SkillService(db).gallery(_builder(org, user))

        found = {
            skill.name: skill.installed_id
            for industry in gallery.industries
            for skill in industry.skills
            if skill.installed
        }
        assert found == {"agenticos-guide": installed.id}

    async def test_loads_are_split_by_the_version_served(self, db: AsyncSession):
        org, user = await _org(db)
        desk = await _agent(db, org, user, "Desk")
        skill = await _skill(db, org)
        v1, v2 = await _version(db, skill, 1), await _version(db, skill, 2)
        await _used(db, await _run(db, org, desk), skill, version=v1)
        await _used(db, await _run(db, org, desk), skill, version=v2)
        await _used(db, await _run(db, org, desk), skill, version=v2)

        usage = await SkillService(db).usage(_builder(org, user), skill.id, days=30)

        assert sorted((v.skill_version_id, v.loads) for v in usage.agents[0].versions) == sorted(
            [(v1, 1), (v2, 2)]
        )

    async def test_loads_are_counted_per_utc_day_with_every_day_of_the_window(
        self, db: AsyncSession
    ):
        """A chart reads one point a day, so a day nobody used it is a zero, not a gap."""
        org, user = await _org(db)
        desk = await _agent(db, org, user, "Desk")
        desk.avatar_url, desk.avatar_color = "avatars/desk.png", 3
        skill = await _skill(db, org)
        now = datetime.now(UTC)
        earlier = now - timedelta(days=3)
        await _used(db, await _run(db, org, desk), skill)
        await _used(db, await _run(db, org, desk), skill)
        await _used(db, await _run(db, org, desk, started_at=earlier), skill)
        await _used(
            db, await _run(db, org, desk, surface=RunSurface.EVAL, started_at=earlier), skill
        )
        await _used(db, await _run(db, org, desk, is_test=True, started_at=earlier), skill)

        usage = await SkillService(db).usage(_builder(org, user), skill.id, days=7)

        [agent] = usage.agents
        assert (agent.slug, agent.has_avatar, agent.avatar_color) == (desk.slug, True, 3)
        assert [day.date for day in agent.daily] == [
            (now - timedelta(days=7 - offset)).date() for offset in range(8)
        ]
        assert {day.date: day.loads for day in agent.daily if day.loads} == {
            now.date(): 2,
            earlier.date(): 1,
        }

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


async def _answered(
    db: AsyncSession,
    org: Organization,
    agent: Agent,
    asker: User,
    *,
    rating: int = -1,
    status: str = "completed",
    version: AgentVersion | None = None,
    recorded: bool = True,
    surface: RunSurface = RunSurface.WEB,
) -> AgentRun:
    """A run in `asker`'s own conversation, its answer rated.

    An API run keeps its transcript in a conversation of its own as well; one
    with none is the HTTP API's default, where only the run holds the turns.
    """
    conversation = Conversation(id=uuid.uuid4(), organization_id=org.id, user_id=asker.id)
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=None if version is None else version.id,
        user_id=asker.id,
        conversation_id=None if surface is RunSurface.API else conversation.id,
        surface=surface.value,
        status=status,
        started_at=datetime.now(UTC),
        skill_uses_recorded=recorded,
    )
    db.add(run)
    await db.flush()
    db.add(
        Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            role="user",
            content="Can I return opened shoes?",
            run_id=run.id,
        )
    )
    answer = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role="assistant",
        content="Only unworn ones.",
        agent_id=agent.id,
        run_id=run.id,
    )
    db.add(answer)
    await db.flush()
    db.add(MessageRating(message_id=answer.id, user_id=asker.id, rating=rating))
    await db.flush()
    return run


async def _binding(db: AsyncSession, agent: Agent, skill: Skill) -> AgentVersion:
    version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        organization_id=agent.organization_id,
        version=1,
        spec={"name": agent.name, "skill_ids": [str(skill.id)]},
    )
    db.add(version)
    await db.flush()
    return version


class TestEvidence:
    async def test_runs_that_used_the_skill_across_agents_are_read_and_marked(
        self, db: AsyncSession
    ):
        org, user = await _org(db)
        desk = await _agent(db, org, user, "Desk")
        clerk = await _agent(db, org, user, "Clerk")
        specialist = await _agent(db, org, user, "Specialist")
        elsewhere = await _agent(db, org, user, "Elsewhere")
        skill = await _skill(db, org)
        other = await _skill(db, org, "shipping")
        opened = await _answered(db, org, desk, user)
        await _used(db, opened, skill)
        through_delegate = await _answered(db, org, clerk, user, status="failed")
        await _used(db, through_delegate, skill, agent=specialist)
        named_only = await _answered(db, org, clerk, user)
        await _used(db, named_only, skill, loaded=False, workspace_reads=1)
        await _used(db, await _answered(db, org, elsewhere, user), other)

        pack = await EvidenceService(db).for_skill(_builder(org, user), skill.id, window_days=30)

        by_run = {run.run_id: run for run in pack.runs}
        assert set(by_run) == {opened.id, through_delegate.id, named_only.id}
        assert (by_run[opened.id].skill_use, by_run[opened.id].via_delegate) == ("used", False)
        assert by_run[through_delegate.id].via_delegate is True
        assert by_run[named_only.id].skill_use == "probable"
        assert by_run[opened.id].prompt == "Can I return opened shoes?"
        assert "probable" in by_run[named_only.id].render()
        assert "delegated" in by_run[through_delegate.id].render()
        assert (pack.unknown_runs, pack.hidden_agents) == (0, 0)

    async def test_older_runs_of_an_agent_bound_to_the_skill_are_counted_as_unknown(
        self, db: AsyncSession
    ):
        org, user = await _org(db)
        desk = await _agent(db, org, user, "Desk")
        unbound = await _agent(db, org, user, "Unbound")
        skill = await _skill(db, org)
        bound = await _binding(db, desk, skill)
        await _answered(db, org, desk, user, version=bound, recorded=False)
        await _answered(db, org, desk, user, version=bound, recorded=False, status="failed")
        # Liked, so no evidence of a problem; and one whose transcript proved a load.
        await _answered(db, org, desk, user, version=bound, recorded=False, rating=1)
        proven = await _answered(db, org, desk, user, version=bound, recorded=False)
        await _used(db, proven, skill)
        await _answered(db, org, unbound, user, recorded=False)

        pack = await EvidenceService(db).for_skill(_builder(org, user), skill.id, window_days=30)

        assert [run.run_id for run in pack.runs] == [proven.id]
        assert pack.unknown_runs == 2

    async def test_a_line_reads_only_its_own_agents_uses_of_a_version_it_shares(
        self, db: AsyncSession
    ):
        """A fork with no version of its own serves its base, which main's agents read too."""
        org, user = await _org(db)
        on_fork = await _agent(db, org, user, "On fork")
        on_main = await _agent(db, org, user, "On main")
        skill = await _skill(db, org)
        base = await _version(db, skill, 1)
        mine = await _answered(db, org, on_fork, user)
        await _used(db, mine, skill, version=base)
        # Main's agent delegated to the fork's: the use that counts is the fork's.
        delegated = await _answered(db, org, on_main, user, status="failed")
        await _used(db, delegated, skill, agent=on_fork, version=base)
        await _used(db, await _answered(db, org, on_main, user), skill, version=base)
        main_version = await _binding(db, on_main, skill)
        await _answered(db, org, on_main, user, version=main_version, recorded=False)

        pack = await EvidenceService(db).for_skill(
            _builder(org, user), skill.id, window_days=30, versions=[base], readers=[on_fork.id]
        )

        assert {run.run_id for run in pack.runs} == {mine.id, delegated.id}
        assert (pack.unknown_runs, pack.hidden_agents) == (0, 0)

    async def test_an_agent_bound_only_through_a_specialist_is_counted_as_unknown(
        self, db: AsyncSession
    ):
        org, user = await _org(db)
        desk = await _agent(db, org, user, "Desk")
        skill = await _skill(db, org)
        version = AgentVersion(
            id=uuid.uuid4(),
            agent_id=desk.id,
            organization_id=org.id,
            version=1,
            spec={
                "name": desk.name,
                "capabilities": [
                    {
                        "id": "subagents",
                        "config": {"inline": [{"name": "billing", "skill_ids": [str(skill.id)]}]},
                    }
                ],
            },
        )
        db.add(version)
        await db.flush()
        await _answered(db, org, desk, user, version=version, recorded=False)

        pack = await EvidenceService(db).for_skill(_builder(org, user), skill.id, window_days=30)

        assert pack.unknown_runs == 1

    async def test_agents_the_reader_cannot_see_are_only_counted(self, db: AsyncSession):
        org, user = await _org(db)
        desk = await _agent(db, org, user, "Desk")
        skill = await _skill(db, org)
        await _used(db, await _answered(db, org, desk, user), skill)
        # An eval of another agent serves nobody, so it is not an agent hidden from them.
        evaluated = await _agent(db, org, user, "Evaluated")
        await _used(db, await _run(db, org, evaluated, surface=RunSurface.EVAL), skill)
        key = _builder(org, user, key_scopes=frozenset({Perm.RUNS_VIEW, Perm.SKILLS_VIEW}))

        pack = await EvidenceService(db).for_skill(key, skill.id, window_days=30)

        assert (pack.runs, pack.hidden_agents) == ([], 1)

    async def test_a_hidden_delegate_keeps_its_run_out(self, db: AsyncSession):
        org, user = await _org(db)
        desk = await _agent(db, org, user, "Desk")
        private = await _agent(db, org, user, "Private")
        private.visibility = "private"
        stranger = User(
            id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x"
        )
        db.add(stranger)
        await db.flush()
        private.owner_user_id = stranger.id
        await db.flush()
        skill = await _skill(db, org)
        run = await _answered(db, org, desk, user)
        await _used(db, run, skill, agent=private)
        member = AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.MEMBER)

        pack = await EvidenceService(db).for_skill(member, skill.id, window_days=30)

        assert (pack.runs, pack.hidden_agents) == ([], 1)

    async def test_a_conversation_the_reader_cannot_open_keeps_its_rating_and_loses_its_text(
        self, db: AsyncSession
    ):
        org, user = await _org(db)
        stranger = User(
            id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x"
        )
        db.add(stranger)
        await db.flush()
        desk = await _agent(db, org, user, "Desk")
        skill = await _skill(db, org)
        theirs = await _answered(db, org, desk, stranger)
        await _used(db, theirs, skill)
        mine = await _answered(db, org, desk, user)
        await _used(db, mine, skill)
        # Sees the agent, may not read runs, so only conversations it may open.
        member = AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.MEMBER)

        pack = await EvidenceService(db).for_skill(member, skill.id, window_days=30)

        by_run = {run.run_id: run for run in pack.runs}
        assert by_run[theirs.id].masked is True
        assert by_run[theirs.id].rating == -1
        assert "shoes" not in by_run[theirs.id].render()
        assert by_run[theirs.id].people == frozenset()
        assert by_run[mine.id].masked is False
        assert by_run[mine.id].prompt == "Can I return opened shoes?"

    async def test_a_run_with_no_conversation_is_read_with_runs_view_and_withheld_without(
        self, db: AsyncSession
    ):
        org, user = await _org(db)
        desk = await _agent(db, org, user, "Desk")
        skill = await _skill(db, org)
        api = await _answered(db, org, desk, user, surface=RunSurface.API)
        await _used(db, api, skill)
        assert api.conversation_id is None
        member = AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.MEMBER)

        [owned] = (
            await EvidenceService(db).for_skill(_builder(org, user), skill.id, window_days=30)
        ).runs
        [withheld] = (await EvidenceService(db).for_skill(member, skill.id, window_days=30)).runs

        assert (owned.masked, owned.prompt) == (False, "Can I return opened shoes?")
        assert (withheld.masked, withheld.rating) == (True, -1)
