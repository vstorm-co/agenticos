"""Binding an agent to main, a pinned version or a fork, against a real database.

What an agent reads, what publish refuses, which agents a change reaches, what the
skill page lists and what moving an agent publishes - each through the services,
on rows the database holds.
"""

import asyncio
import contextlib
import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.capabilities.skills import served_skills
from app.agents.spec import AgentSpec, SkillBindingSpec
from app.core.exceptions import BadRequestError, InUseError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.resource_grant import Visibility
from app.db.models.skill import Skill
from app.db.models.skill_version import SkillVersion
from app.schemas.agent_environment import EnvironmentUpdate
from app.schemas.skill import SkillUpdate
from app.schemas.skill_version import (
    SkillBindingChange,
    SkillForkCreate,
    SkillVersionCreate,
    SkillVersionRestore,
)
from app.services import proposal_reach
from app.services.agent_environment import AgentEnvironmentService
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import SPECIALIST_SKILLS_RESOURCE, AgentRunnerService, _served
from app.services.eval_suite import reads_skill_line
from app.services.resource_usage import agents_serving_skills
from app.services.skill_agents import SkillAgentService, lines_of
from app.services.skill_versions import SkillVersionService
from app.services.skills import SkillService
from tests.integration.test_authoring import _member, _owner, _published
from tests.integration.test_authoring_fields_flow import _profile

pytestmark = pytest.mark.anyio


async def _skill(db: AsyncSession, ctx: AuthContext, name: str = "refunds") -> Skill:
    skill = await SkillService(db).create(
        ctx,
        name=name,
        description="How refunds work.",
        content="v1 text",
        visibility=Visibility.ORG,
    )
    await SkillService(db).put_resources(ctx, skill.id, [("a.md", b"first")])
    await SkillService(db).update(ctx, skill.id, SkillUpdate(content="v3 text"))
    return skill


async def _fork(db: AsyncSession, ctx: AuthContext, skill: Skill, text: str | None = None):
    assert skill.latest_version_id is not None
    versions = SkillVersionService(db)
    read = await versions.create_fork(
        ctx, skill.id, SkillForkCreate(name="returns", from_version_id=skill.latest_version_id)
    )
    if text is not None:
        await versions.edit(
            ctx,
            skill.id,
            SkillVersionCreate(
                fork_id=read.id,
                base_version_id=read.base.id,
                description=skill.description,
                content=text,
            ),
        )
    return read


async def _serving(db: AsyncSession, ctx: AuthContext, name: str, spec: dict[str, Any]) -> Agent:
    """A published agent whose default environment serves `spec`."""
    agent = await _published(db, ctx, name=name, spec=spec)
    assert agent.current_version_id is not None
    db.add(
        AgentEnvironment(
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            name="production",
            version_id=agent.current_version_id,
            is_default=True,
        )
    )
    await db.flush()
    return agent


def _spec(skill: Skill, **binding: Any) -> dict[str, Any]:
    bindings = [{"skill_id": str(skill.id), **binding}] if binding else []
    return {"name": "Clerk", "skill_ids": [str(skill.id)], "skill_bindings": bindings}


def _with_specialist(spec: dict[str, Any], skill: Skill, **binding: Any) -> dict[str, Any]:
    """`spec` with an inline specialist, `billing`, that binds `skill` its own way."""
    bindings = [{"skill_id": str(skill.id), **binding}] if binding else []
    specialist = {
        "name": "billing",
        "description": "Bills.",
        "instructions": "Bill.",
        "skill_ids": [str(skill.id)],
        "skill_bindings": bindings,
    }
    return {**spec, "capabilities": [{"id": "subagents", "config": {"inline": [specialist]}}]}


async def _waiting_for_a_lock(
    factory: async_sessionmaker[AsyncSession], task: asyncio.Task[None]
) -> None:
    """Return once some session of this database waits for a lock.

    A loaded runner can take seconds to reach the lock, so the bound is generous;
    a delete that finishes instead of waiting is awaited, so its own error, not a
    timeout, is what fails the test.
    """
    async with factory() as session:
        for _ in range(600):
            if task.done():
                await task
                raise AssertionError("the delete finished without waiting for a lock")
            waiting = await session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND datname = current_database()"
                )
            )
            if waiting:
                return
            # pg_stat_activity is read once per transaction and repeated until it ends.
            await session.rollback()
            await asyncio.sleep(0.1)
    raise AssertionError("nothing waited for a lock within 60s")


class TestWhatAnAgentReads:
    async def test_main_pinned_and_fork_each_serve_their_own_text_and_files(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill, "fork text")
        service = SkillService(db)

        [main] = await service.resolve_for_agent(ctx, [skill.id])
        [pinned] = await service.resolve_for_agent(
            ctx, [skill.id], bindings=[SkillBindingSpec(skill_id=skill.id, version=1)]
        )
        [forked] = await service.resolve_for_agent(
            ctx, [skill.id], bindings=[SkillBindingSpec(skill_id=skill.id, fork_id=fork.id)]
        )

        assert (main.content, main.version) == ("v3 text", 3)
        assert (pinned.content, pinned.version, pinned.resources) == ("v1 text", 1, [])
        assert forked.content == "fork text"
        assert [(file.name, file.content) for file in forked.resources] == [("a.md", "first")]
        assert (
            len({main.latest_version_id, pinned.latest_version_id, forked.latest_version_id}) == 3
        )

    async def test_a_version_the_skill_does_not_have_is_skipped_not_served(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)

        resolved = await SkillService(db).resolve_for_agent(
            ctx,
            [skill.id],
            bindings=[SkillBindingSpec(skill_id=skill.id, fork_id=uuid.uuid4())],
        )

        assert resolved == []

    async def test_a_pinned_agents_skill_uses_name_the_version_it_reads(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        [pinned] = await SkillService(db).resolve_for_agent(
            ctx, [skill.id], bindings=[SkillBindingSpec(skill_id=skill.id, version=1)]
        )

        served = served_skills([pinned], {})

        v1 = await db.scalar(
            select(SkillVersion.id).where(
                SkillVersion.skill_id == skill.id,
                SkillVersion.fork_id.is_(None),
                SkillVersion.number == 1,
            )
        )
        await db.refresh(skill)
        assert served[skill.name].version_id == v1 != skill.latest_version_id

    async def test_a_run_records_the_versions_it_and_its_specialists_serve(self, db):
        ctx = await _owner(db)
        skill, other = await _skill(db, ctx), await _skill(db, ctx, "invoices")
        spec = AgentSpec.model_validate(_spec(skill, version=1))
        runner = AgentRunnerService(db)
        own = await runner.skills.resolve_for_agent(
            ctx, spec.skill_ids, bindings=spec.skill_bindings
        )
        resources: dict[str, Any] = {SPECIALIST_SKILLS_RESOURCE: []}

        await runner._delegate_resources(
            ctx,
            AgentSpec(name="billing", skill_ids=[other.id]),
            agent_id=None,
            shared=[],
            parent_resources=resources,
            person_id=None,
        )

        served = _served([*own, *resources[SPECIALIST_SKILLS_RESOURCE]])
        pinned = await SkillService(db).resolve_for_agent(
            ctx, [skill.id], bindings=spec.skill_bindings
        )
        assert served == [pinned[0].latest_version_id, other.latest_version_id]
        assert pinned[0].latest_version_id != skill.latest_version_id


class TestPublishRefuses:
    async def _problems(self, db, ctx, spec: dict[str, Any]) -> list[str]:
        registry = AgentRegistryService(db)
        parsed = AgentSpec.model_validate(spec)
        return await registry.skill_problems(ctx, parsed.skill_ids, parsed.skill_bindings)

    async def test_a_version_or_fork_the_skill_does_not_have(self, db):
        ctx = await _owner(db)
        skill, other = await _skill(db, ctx), await _skill(db, ctx, "invoices")
        foreign = await _fork(db, ctx, other)

        assert await self._problems(db, ctx, _spec(skill, version=9)) == [
            "Skill 'refunds' has no version 9"
        ]
        assert await self._problems(db, ctx, _spec(skill, fork_id=str(foreign.id))) == [
            f"Skill fork not found: {foreign.id}"
        ]
        assert await self._problems(db, ctx, _spec(skill, version=3)) == []

    async def test_an_archived_fork(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        await SkillVersionService(db).archive_fork(ctx, skill.id, fork.id)

        assert await self._problems(db, ctx, _spec(skill, fork_id=str(fork.id))) == [
            f"Skill fork not found: {fork.id}"
        ]

    async def test_another_organizations_fork(self, db):
        ctx, stranger = await _owner(db), await _owner(db)
        skill = await _skill(db, ctx)
        theirs = await _fork(db, stranger, await _skill(db, stranger))

        assert await self._problems(db, ctx, _spec(skill, fork_id=str(theirs.id))) == [
            f"Skill fork not found: {theirs.id}"
        ]

    async def test_nothing_is_said_about_the_versions_of_a_skill_the_publisher_cannot_read(
        self, db
    ):
        owner = await _owner(db)
        skill = await SkillService(db).create(
            owner, name="private", description="d", content="c", visibility=Visibility.PRIVATE
        )
        member = await _member(db, owner, OrgRoleName.MEMBER)

        assert await self._problems(db, member, _spec(skill, version=9)) == [
            f"Skill not found: {skill.id}"
        ]


class TestAChangeReachesItsLine:
    async def test_main_reaches_main_agents_and_a_fork_its_own(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        on_main = await _serving(db, ctx, "Main", _spec(skill))
        await _serving(db, ctx, "Pinned", _spec(skill, version=1))
        on_fork = await _serving(db, ctx, "Fork", _spec(skill, fork_id=str(fork.id)))

        main = await proposal_reach.reach(
            db, organization_id=ctx.organization_id, kind="skill", resource_ids=[skill.id]
        )
        forked = await proposal_reach.reach(
            db,
            organization_id=ctx.organization_id,
            kind="skill",
            resource_ids=[skill.id],
            fork_id=fork.id,
        )

        assert [item.agent.id for item in main[skill.id]] == [on_main.id]
        assert [item.agent.id for item in forked[skill.id]] == [on_fork.id]

    def test_a_specialist_reads_a_line_as_its_agent_does(self):
        skill, fork = uuid.uuid4(), uuid.uuid4()
        spec = AgentSpec.model_validate(
            {
                "name": "Clerk",
                "capabilities": [
                    {
                        "id": "subagents",
                        "config": {
                            "inline": [
                                {
                                    "name": "returns",
                                    "description": "d",
                                    "instructions": "i",
                                    "skill_ids": [str(skill)],
                                    "skill_bindings": [
                                        {"skill_id": str(skill), "fork_id": str(fork)}
                                    ],
                                }
                            ]
                        },
                    }
                ],
            }
        )

        assert reads_skill_line(spec, skill, fork) is True
        assert reads_skill_line(spec, skill, None) is False
        assert reads_skill_line(AgentSpec(name="x"), skill, None) is False


class TestTheSkillsAgents:
    async def test_a_pinned_agent_is_behind_by_changes_not_by_versions(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        await _serving(db, ctx, "Clerk", _spec(skill, version=3))
        versions = SkillVersionService(db)
        for _ in range(2):
            assert skill.latest_version_id is not None
            await versions.restore(
                ctx,
                skill.id,
                skill.latest_version_id,
                SkillVersionRestore(base_version_id=skill.latest_version_id),
            )

        [row] = (await SkillAgentService(db).agents(ctx, skill.id)).items

        assert (skill.version, row.binding.state, row.binding.behind_main) == (5, "pinned", 0)

    async def test_each_agent_shows_the_version_it_reads_and_how_far_behind(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill, "fork text")
        await _serving(db, ctx, "A main", _spec(skill))
        await _serving(db, ctx, "B pinned", _spec(skill, version=1))
        await _serving(db, ctx, "C fork", _spec(skill, fork_id=str(fork.id)))
        await _published(db, ctx, name="D draft", spec=_spec(skill))

        listed = await SkillAgentService(db).agents(ctx, skill.id)

        rows = {row.agent.name: row for row in listed.items}
        assert listed.main_latest.number == 3 and listed.hidden == 0
        assert (rows["A main"].binding.state, rows["A main"].binding.behind_main) == ("main", 0)
        assert (rows["B pinned"].binding.version.number, rows["B pinned"].binding.behind_main) == (
            1,
            2,
        )
        fork_row = rows["C fork"].binding
        assert fork_row.state == "fork" and fork_row.fork is not None
        assert (fork_row.fork.name, fork_row.fork.changes, fork_row.behind_main) == (
            "returns",
            1,
            0,
        )
        assert rows["D draft"].draft_only is True and rows["D draft"].agent_version is None
        assert all(row.can_change and row.can_publish for row in listed.items)

    async def test_an_environment_reading_differently_is_listed_beside_the_default(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        agent = await _serving(db, ctx, "Clerk", _spec(skill))
        staging = AgentVersion(
            agent_id=agent.id,
            organization_id=ctx.organization_id,
            version=2,
            spec=_spec(skill, fork_id=str(fork.id)),
        )
        db.add(staging)
        await db.flush()
        db.add(
            AgentEnvironment(
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                name="staging",
                version_id=staging.id,
                is_default=False,
            )
        )
        await db.flush()

        agents = SkillAgentService(db)
        [row] = (await agents.agents(ctx, skill.id)).items
        by_version, by_fork = await agents.counts(skill)

        assert row.binding.state == "main"
        assert [(env.name, env.binding.state, env.agent_version) for env in row.environments] == [
            ("staging", "fork", 2)
        ]
        assert by_fork[fork.id] == 1
        assert skill.latest_version_id is not None and by_version[skill.latest_version_id] == 1

    async def test_a_reader_outside_the_default_environment_gets_its_own_row(self, db):
        """A specialist that only another environment serves, or only the draft names."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        agent = await _serving(db, ctx, "Clerk", _spec(skill))
        staging = AgentVersion(
            agent_id=agent.id,
            organization_id=ctx.organization_id,
            version=2,
            spec=_with_specialist(_spec(skill), skill, fork_id=str(fork.id)),
        )
        db.add(staging)
        await db.flush()
        db.add(
            AgentEnvironment(
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                name="staging",
                version_id=staging.id,
                is_default=False,
            )
        )
        agent.draft_spec = _with_specialist(_spec(skill), skill, version=1)
        await db.flush()

        rows = (await SkillAgentService(db).agents(ctx, skill.id)).items

        assert [
            (row.via_specialist, row.binding.state, row.agent_version, row.draft_only)
            for row in rows
        ] == [(None, "main", 1, False), ("billing", "fork", 2, False)]
        assert rows[1].draft_differs is True

    async def test_agents_the_caller_cannot_see_are_only_counted(self, db):
        owner = await _owner(db)
        skill = await _skill(db, owner)
        hidden = await _serving(db, owner, "Private", _spec(skill))
        hidden.visibility = "private"
        await db.flush()
        member = await _member(db, owner, OrgRoleName.MEMBER)

        listed = await SkillAgentService(db).agents(member, skill.id)

        assert (listed.items, listed.hidden) == ([], 1)

    async def test_counts_and_cards_follow_what_is_served(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        await _serving(db, ctx, "Main", _spec(skill))
        await _serving(db, ctx, "Fork", _spec(skill, fork_id=str(fork.id)))
        await _published(db, ctx, name="Draft", spec=_spec(skill))
        versions = SkillVersionService(db)

        history = {
            item.number: item.agents
            for item in (await versions.list_versions(ctx, skill.id, fork_id=None)).items
        }
        [listed_fork] = (await versions.list_forks(ctx, skill.id)).items
        cards = await agents_serving_skills(db, ctx, skill_ids=[skill.id])

        assert history[3] == 2
        assert listed_fork.agents == 1 and listed_fork.archive_candidate is False
        assert sorted(agent.name for agent in cards[skill.id]) == ["Fork", "Main"]

    async def test_a_card_names_the_agents_that_only_drafted_it_apart(self, db):
        """An agent the skill was just added to, not yet published with it, is named as
        a draft rather than left out as if nothing used the skill."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        await _serving(db, ctx, "Main", _spec(skill))
        await _published(db, ctx, name="Draft", spec=_spec(skill))

        [card] = (await SkillService(db).list_readable(ctx)).items

        assert [agent.name for agent in card.used_by] == ["Main"]
        assert [agent.name for agent in card.drafted_by] == ["Draft"]

    async def test_specs_that_name_the_skill_without_a_readable_binding_are_left_out(self, db):
        """A version or fork that is gone, a mention in the instructions, a spec that no
        longer parses: none is an agent of the skill, and none breaks the listing."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        await _serving(db, ctx, "Unrelated", {"name": "Unrelated"})
        await _serving(db, ctx, "Gone version", _spec(skill, version=9))
        await _serving(db, ctx, "Gone fork", _spec(skill, fork_id=str(uuid.uuid4())))
        await _serving(db, ctx, "Mentions", {"name": "Mentions", "instructions": str(skill.id)})
        await _serving(db, ctx, "Broken", {"skill_ids": [str(skill.id)], "no_such_field": 1})
        specialist = {
            "name": "Delegates",
            "capabilities": [
                {
                    "id": "subagents",
                    "config": {
                        "inline": [
                            {
                                "name": "returns",
                                "description": "d",
                                "instructions": "i",
                                "skill_ids": [str(skill.id)],
                            }
                        ]
                    },
                }
            ],
        }
        await _serving(db, ctx, "Delegates", specialist)

        listed = await SkillAgentService(db).agents(ctx, skill.id)
        by_version, _ = await SkillAgentService(db).counts(skill)
        cards = await agents_serving_skills(db, ctx, skill_ids=[skill.id])

        assert [(row.agent.name, row.via_specialist) for row in listed.items] == [
            ("Delegates", "returns")
        ]
        assert listed.hidden == 0
        assert sum(by_version.values()) == 1
        assert sorted(agent.name for agent in cards[skill.id]) == [
            "Delegates",
            "Gone fork",
            "Gone version",
        ]

    def test_a_delegation_whose_config_no_longer_reads_binds_nothing(self):
        skill = uuid.uuid4()
        spec = {
            "name": "x",
            "capabilities": [
                {"id": "subagents", "config": {"inline": "not a list", "x": str(skill)}}
            ],
        }

        assert lines_of(spec, skill) == []
        assert reads_skill_line(AgentSpec.model_validate(spec), skill, None) is False

    def test_a_spec_that_does_not_name_the_skill_reads_nothing(self):
        skill = uuid.uuid4()

        assert lines_of({"name": "x"}, skill) == []
        assert lines_of({"skill_ids": [str(skill)], "bad": 1}, skill) == []


async def _runnable(db: AsyncSession, ctx: AuthContext, skill: Skill, **binding: Any):
    """A spec that publishes: it names a model of the organization's."""
    profile = await _profile(db, ctx, "gpt-4o-mini")
    return {**_spec(skill, **binding), "model_profile_id": str(profile.id)}


class TestMovingAnAgent:
    async def test_publishing_moves_only_the_binding_and_the_draft_keeps_its_edits(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        spec = await _runnable(db, ctx, skill)
        agent = await _serving(db, ctx, "Clerk", spec)
        agent.draft_spec = {**spec, "instructions": "Unfinished edit."}
        production = await db.scalar(
            select(AgentEnvironment).where(AgentEnvironment.agent_id == agent.id)
        )
        assert production is not None
        production.tracks_latest = True
        await db.flush()

        moved = await SkillAgentService(db).change_binding(
            ctx, skill.id, agent.id, SkillBindingChange(state="pinned", version=1)
        )

        assert moved.published is True and moved.agent_version == 2
        assert moved.environments == ["production"]
        assert moved.usage is not None and moved.usage.binding.version.number == 1
        await db.refresh(agent)
        new = await db.get(AgentVersion, agent.current_version_id)
        assert new is not None
        published = AgentSpec.model_validate(new.spec)
        assert published.instructions == ""
        assert published.skill_bindings == [SkillBindingSpec(skill_id=skill.id, version=1)]
        draft = AgentSpec.model_validate(agent.draft_spec)
        assert draft.instructions == "Unfinished edit."
        assert draft.skill_bindings == published.skill_bindings

    async def test_without_publish_only_the_draft_changes(self, db):
        owner = await _owner(db)
        skill = await _skill(db, owner)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        agent = await _serving(db, member, "Mine", await _runnable(db, member, skill))
        fork = await _fork(db, owner, skill)

        moved = await SkillAgentService(db).change_binding(
            member, skill.id, agent.id, SkillBindingChange(state="fork", fork_id=fork.id)
        )

        await db.refresh(agent)
        assert moved.published is False
        assert AgentSpec.model_validate(agent.draft_spec).skill_bindings == [
            SkillBindingSpec(skill_id=skill.id, fork_id=fork.id)
        ]

    async def test_back_to_main_drops_the_pin(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _serving(db, ctx, "Clerk", await _runnable(db, ctx, skill, version=1))

        await SkillAgentService(db).change_binding(
            ctx, skill.id, agent.id, SkillBindingChange(state="main")
        )

        await db.refresh(agent)
        assert AgentSpec.model_validate(agent.draft_spec).skill_bindings == []

    async def test_a_version_the_skill_does_not_have_does_not_publish(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _serving(db, ctx, "Clerk", _spec(skill))

        with pytest.raises(BadRequestError):
            await SkillAgentService(db).change_binding(
                ctx, skill.id, agent.id, SkillBindingChange(state="pinned", version=9)
            )

    async def test_a_skill_only_a_specialist_uses_is_changed_in_the_builder(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        spec = _with_specialist({"name": "Clerk"}, skill, version=1)
        agent = await _serving(db, ctx, "Clerk", spec)

        with pytest.raises(BadRequestError, match="Builder"):
            await SkillAgentService(db).change_binding(
                ctx, skill.id, agent.id, SkillBindingChange(state="main")
            )

    async def test_an_agent_whose_draft_does_not_use_the_skill_is_refused(self, db):
        """The draft decides, as the Builder shows it: published but unticked is not used."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _serving(db, ctx, "Clerk", _spec(skill))
        agent.draft_spec = {"name": "Clerk"}
        await db.flush()

        with pytest.raises(BadRequestError, match="does not use 'refunds'"):
            await SkillAgentService(db).change_binding(
                ctx, skill.id, agent.id, SkillBindingChange(state="pinned", version=1)
            )

    async def test_a_move_publishes_from_the_newest_version_not_the_default_environments(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        spec = await _runnable(db, ctx, skill)
        agent = await _serving(db, ctx, "Clerk", spec)
        production_version = agent.current_version_id
        newer = AgentVersion(
            agent_id=agent.id,
            organization_id=ctx.organization_id,
            version=2,
            spec={**spec, "instructions": "From v2."},
        )
        db.add(newer)
        await db.flush()
        dev = AgentEnvironment(
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            name="dev",
            version_id=newer.id,
            is_default=False,
            tracks_latest=True,
        )
        db.add(dev)
        await db.flush()

        moved = await SkillAgentService(db).change_binding(
            ctx, skill.id, agent.id, SkillBindingChange(state="pinned", version=1)
        )

        assert (moved.published, moved.agent_version, moved.environments) == (True, 3, ["dev"])
        await db.refresh(dev)
        await db.refresh(agent)
        third = await db.get(AgentVersion, dev.version_id)
        assert third is not None and third.version == 3
        published = AgentSpec.model_validate(third.spec)
        assert published.instructions == "From v2."
        assert published.skill_bindings == [SkillBindingSpec(skill_id=skill.id, version=1)]
        assert agent.current_version_id == production_version

    async def test_without_publish_an_unfinished_draft_still_takes_the_move(self, db):
        """Only the binding is checked: a draft is allowed to be unfinished."""
        owner = await _owner(db)
        skill = await _skill(db, owner)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        spec = await _runnable(db, member, skill)
        agent = await _serving(db, member, "Mine", spec)
        gone = str(uuid.uuid4())
        agent.draft_spec = {**spec, "collection_ids": [gone]}
        await db.flush()

        moved = await SkillAgentService(db).change_binding(
            member, skill.id, agent.id, SkillBindingChange(state="pinned", version=1)
        )

        await db.refresh(agent)
        assert moved.published is False
        draft = AgentSpec.model_validate(agent.draft_spec)
        assert [str(collection) for collection in draft.collection_ids] == [gone]
        assert draft.skill_bindings == [SkillBindingSpec(skill_id=skill.id, version=1)]
        with pytest.raises(BadRequestError) as refused:
            await SkillAgentService(db).change_binding(
                member, skill.id, agent.id, SkillBindingChange(state="pinned", version=9)
            )
        assert refused.value.details["problems"] == ["Skill 'refunds' has no version 9"]

    async def test_a_skill_not_published_yet_or_an_agent_never_published_moves_the_draft(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        published = await _serving(db, ctx, "Published", await _runnable(db, ctx, skill))
        published.draft_spec = _spec(skill)
        published_spec = await db.get(AgentVersion, published.current_version_id)
        assert published_spec is not None
        published_spec.spec = {"name": "Clerk"}
        never = Agent(
            organization_id=ctx.organization_id,
            owner_user_id=ctx.user_id,
            visibility="org",
            slug=f"never-{uuid.uuid4().hex[:6]}",
            name="Never",
            status="draft",
            draft_spec=_spec(skill),
        )
        db.add(never)
        await db.flush()

        for agent in (published, never):
            moved = await SkillAgentService(db).change_binding(
                ctx, skill.id, agent.id, SkillBindingChange(state="pinned", version=1)
            )

            await db.refresh(agent)
            assert moved.published is False
            assert AgentSpec.model_validate(agent.draft_spec).skill_bindings == [
                SkillBindingSpec(skill_id=skill.id, version=1)
            ]

    async def test_a_caller_without_edit_or_without_the_skill_is_not_found(self, db):
        owner = await _owner(db)
        skill = await _skill(db, owner)
        secret = await SkillService(db).create(
            owner, name="secret", description="d", content="c", visibility=Visibility.PRIVATE
        )
        agent = await _serving(db, owner, "Clerk", _spec(skill))
        viewer = await _member(db, owner, OrgRoleName.VIEWER)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        own = await _serving(db, member, "Mine", _spec(skill))

        with pytest.raises(NotFoundError):
            await SkillAgentService(db).change_binding(
                viewer, skill.id, agent.id, SkillBindingChange(state="main")
            )
        with pytest.raises(NotFoundError):
            await SkillAgentService(db).change_binding(
                member, secret.id, own.id, SkillBindingChange(state="main")
            )

    async def test_another_organizations_agent_is_not_found(self, db):
        ctx, stranger = await _owner(db), await _owner(db)
        skill = await _skill(db, ctx)
        theirs = await _serving(db, stranger, "Theirs", {"name": "Theirs"})

        with pytest.raises(NotFoundError):
            await SkillAgentService(db).change_binding(
                ctx, skill.id, theirs.id, SkillBindingChange(state="main")
            )


class TestArchivingAFork:
    async def test_an_older_version_reading_an_archived_fork_is_not_promoted(self, db):
        """Archiving only waits for what is read now; the version before is refused later."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        agent = await _serving(
            db, ctx, "Clerk", await _runnable(db, ctx, skill, fork_id=str(fork.id))
        )
        on_fork = agent.current_version_id
        production = await db.scalar(
            select(AgentEnvironment).where(AgentEnvironment.agent_id == agent.id)
        )
        assert production is not None and on_fork is not None
        production.tracks_latest = False
        await db.flush()
        await SkillAgentService(db).change_binding(
            ctx, skill.id, agent.id, SkillBindingChange(state="main")
        )
        await AgentEnvironmentService(db).update(
            ctx, agent.id, production.id, EnvironmentUpdate(tracks_latest=True)
        )
        await SkillVersionService(db).archive_fork(ctx, skill.id, fork.id)

        with pytest.raises(BadRequestError, match="archived skill fork 'returns'"):
            await AgentEnvironmentService(db).update(
                ctx,
                agent.id,
                production.id,
                EnvironmentUpdate(tracks_latest=False, version_id=on_fork),
            )

    async def test_an_environment_moved_onto_the_fork_meanwhile_refuses_the_archive(
        self, db: AsyncSession, engine: AsyncEngine
    ):
        """The archive waits for an environment being moved onto a version that reads the
        fork, and then sees it, rather than archiving a fork that is about to be served."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        agent = await _serving(
            db, ctx, "Clerk", await _runnable(db, ctx, skill, fork_id=str(fork.id))
        )
        on_fork = agent.current_version_id
        production = await db.scalar(
            select(AgentEnvironment).where(AgentEnvironment.agent_id == agent.id)
        )
        assert production is not None and on_fork is not None
        production.tracks_latest = False
        await db.flush()
        await SkillAgentService(db).change_binding(
            ctx, skill.id, agent.id, SkillBindingChange(state="main")
        )
        await AgentEnvironmentService(db).update(
            ctx, agent.id, production.id, EnvironmentUpdate(tracks_latest=True)
        )
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def archive() -> None:
            async with factory() as session:
                await SkillVersionService(session).archive_fork(ctx, skill.id, fork.id)
                await session.commit()

        task: asyncio.Task[None] | None = None
        async with factory() as moving:
            try:
                await AgentEnvironmentService(moving).update(
                    ctx,
                    agent.id,
                    production.id,
                    EnvironmentUpdate(tracks_latest=False, version_id=on_fork),
                )
                task = asyncio.create_task(archive())
                await _waiting_for_a_lock(factory, task)

                await moving.commit()
                with pytest.raises(InUseError):
                    await task
                task = None
            finally:
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    async def test_a_fork_an_agent_reads_is_not_archived(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        await _published(db, ctx, name="Draft", spec=_spec(skill, fork_id=str(fork.id)))

        with pytest.raises(InUseError) as refused:
            await SkillVersionService(db).archive_fork(ctx, skill.id, fork.id)

        assert refused.value.details["agents"][0]["name"] == "Draft"

    async def test_a_hidden_agent_refuses_the_archive_without_being_named(self, db):
        owner = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        skill = await _skill(db, member)
        fork = await _fork(db, member, skill)
        secret = await _published(db, owner, name="Secret", spec=_spec(skill, fork_id=str(fork.id)))
        secret.visibility = "private"
        await db.flush()

        with pytest.raises(InUseError) as refused:
            await SkillVersionService(db).archive_fork(member, skill.id, fork.id)

        assert refused.value.details["hidden"] == 1
        assert refused.value.details["agents"] == []
        assert "Secret" not in refused.value.message
        assert "Secret" not in str(refused.value.details)

    async def test_a_fork_only_a_specialist_reads_is_read_counted_and_listed(self, db):
        """The agent reads main itself and the fork through its specialist: both count."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        await _serving(db, ctx, "Desk", _with_specialist(_spec(skill), skill, fork_id=str(fork.id)))
        agents = SkillAgentService(db)

        with pytest.raises(InUseError):
            await SkillVersionService(db).archive_fork(ctx, skill.id, fork.id)
        _, by_fork = await agents.counts(skill)
        listed = await agents.agents(ctx, skill.id)

        assert by_fork[fork.id] == 1
        assert [
            (row.via_specialist, row.binding.state, row.can_change) for row in listed.items
        ] == [(None, "main", True), ("billing", "fork", False)]
        assert listed.hidden == 0
