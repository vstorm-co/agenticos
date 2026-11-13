"""Catching up with main: who main has left behind, across an organization.

Against a real database, because "behind" is read off what each agent's
environments serve and off the version rows themselves.
"""

import asyncio
import contextlib
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentKind, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.resource_grant import Visibility
from app.db.models.skill import Skill
from app.repositories import agent_repo, skill_repo, skill_version_repo
from app.schemas.skill import SkillUpdate
from app.schemas.skill_version import ReturnToMain, SkillForkCreate, SkillVersionRestore
from app.services.skill_catch_up import SkillCatchUpService
from app.services.skill_versions import SkillVersionService
from app.services.skills import SkillService
from tests.integration.test_authoring import _member, _owner
from tests.integration.test_skill_bindings import (
    _fork,
    _runnable,
    _serving,
    _skill,
    _spec,
    _waiting_for_a_lock,
    _with_specialist,
)

pytestmark = pytest.mark.anyio


async def _main_moves_on(db: AsyncSession, ctx: AuthContext, skill: Skill) -> None:
    await SkillService(db).update(ctx, skill.id, SkillUpdate(content="v4 text"))


def _delegating(skill: Skill, **binding: Any) -> dict[str, Any]:
    """An agent that does not bind `skill` itself; its inline specialist does."""
    return {
        "name": "Desk",
        "capabilities": [
            {
                "id": "subagents",
                "config": {
                    "inline": [
                        {
                            "name": "billing",
                            "description": "Bills.",
                            "instructions": "Bill.",
                            "skill_ids": [str(skill.id)],
                            "skill_bindings": [{"skill_id": str(skill.id), **binding}],
                        }
                    ]
                },
            }
        ],
    }


class TestBehindMain:
    async def test_pinned_agents_and_forks_main_moved_past_are_listed_furthest_first(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        await _main_moves_on(db, ctx, skill)
        await _serving(db, ctx, "Pinned", _spec(skill, version=1))
        await _serving(db, ctx, "Main", _spec(skill))
        await _serving(db, ctx, "Current", _spec(skill, version=4))
        await _serving(db, ctx, "Returns A", _spec(skill, fork_id=str(fork.id)))
        await _serving(db, ctx, "Returns B", _spec(skill, fork_id=str(fork.id)))
        on_fork = str(fork.id)
        both = {**_delegating(skill, fork_id=on_fork), **_spec(skill, fork_id=on_fork)}
        await _serving(db, ctx, "Returns twice", both)

        listed = await SkillCatchUpService(db).behind_main(ctx)

        assert (listed.total, listed.hidden) == (2, 0)
        pinned, forked = listed.items
        assert pinned.kind == "pinned" and pinned.agent is not None
        assert (pinned.agent.name, pinned.version.number, pinned.behind_main) == ("Pinned", 1, 3)
        assert (pinned.main_latest.number, pinned.agents, pinned.can_act) == (4, 1, True)
        assert forked.kind == "fork" and forked.fork is not None
        assert (forked.fork.id, forked.fork.base_number, forked.fork.changes) == (fork.id, 3, 0)
        assert (forked.agents, forked.behind_main, forked.can_act) == (3, 1, True)
        assert forked.version.id == fork.base.id

    async def test_main_restoring_what_they_read_leaves_nobody_behind(self, db):
        """Behind main counts changes to what the skill says, as the skill page does."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        await _serving(db, ctx, "Pinned", _spec(skill, version=3))
        await _serving(db, ctx, "Forked", _spec(skill, fork_id=str(fork.id)))
        assert skill.latest_version_id is not None
        third = skill.latest_version_id
        await _main_moves_on(db, ctx, skill)
        assert [
            item.behind_main for item in (await SkillCatchUpService(db).behind_main(ctx)).items
        ] == [1, 1]

        assert skill.latest_version_id is not None
        await SkillVersionService(db).restore(
            ctx, skill.id, third, SkillVersionRestore(base_version_id=skill.latest_version_id)
        )

        listed = await SkillCatchUpService(db).behind_main(ctx)

        assert (skill.version, listed.items) == (5, [])

    async def test_a_specialists_pin_is_listed_under_its_agent(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        await _serving(db, ctx, "Desk", _delegating(skill, version=2))
        # The agent reads main itself and its specialist stays on v2: only the pin is behind.
        await _serving(db, ctx, "Own", {**_delegating(skill, version=2), **_spec(skill)})

        items = (await SkillCatchUpService(db).behind_main(ctx)).items

        assert [
            (item.agent.name if item.agent else None, item.via_specialist, item.behind_main)
            for item in items
        ] == [("Desk", "billing", 1), ("Own", "billing", 1)]
        # Changed in the agent's Builder, so nothing here offers to update it.
        assert [item.can_act for item in items] == [False, False]

    async def test_forks_nobody_reads_archived_or_already_on_main_are_not_behind(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        versions = SkillVersionService(db)
        assert skill.latest_version_id is not None
        unread = await versions.create_fork(
            ctx, skill.id, SkillForkCreate(name="eu", from_version_id=skill.latest_version_id)
        )
        archived = await versions.create_fork(
            ctx, skill.id, SkillForkCreate(name="old", from_version_id=skill.latest_version_id)
        )
        await versions.archive_fork(ctx, skill.id, archived.id)
        await _main_moves_on(db, ctx, skill)
        assert skill.latest_version_id is not None
        current = await versions.create_fork(
            ctx, skill.id, SkillForkCreate(name="new", from_version_id=skill.latest_version_id)
        )
        await _serving(db, ctx, "Archived", _spec(skill, fork_id=str(archived.id)))
        await _serving(db, ctx, "Current", _spec(skill, fork_id=str(current.id)))

        listed = await SkillCatchUpService(db).behind_main(ctx)

        assert listed.items == []
        assert unread.id not in {item.fork.id for item in listed.items if item.fork}

    async def test_the_default_environment_decides_and_archived_agents_are_gone(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        on_main = await _serving(db, ctx, "On main", _spec(skill))
        staging = AgentVersion(
            agent_id=on_main.id,
            organization_id=ctx.organization_id,
            version=2,
            spec=_spec(skill, version=1),
        )
        db.add(staging)
        await db.flush()
        db.add(
            AgentEnvironment(
                organization_id=ctx.organization_id,
                agent_id=on_main.id,
                name="staging",
                version_id=staging.id,
                is_default=False,
            )
        )
        retired = await _serving(db, ctx, "Retired", _spec(skill, version=1))
        retired.status = "archived"
        await db.flush()

        assert (await SkillCatchUpService(db).behind_main(ctx)).items == []

    async def test_specs_that_no_longer_read_and_pins_to_missing_versions_are_skipped(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        await _serving(db, ctx, "Broken", {"skill_bindings": [{"skill_id": str(skill.id)}]})
        await _serving(db, ctx, "Gone", _spec(skill, version=99))
        odd = _spec(skill, version=1)
        odd["capabilities"] = [{"id": "subagents", "config": {"inline": "nobody"}}]
        await _serving(db, ctx, "Odd delegation", odd)

        [item] = (await SkillCatchUpService(db).behind_main(ctx)).items

        assert item.agent is not None and item.agent.name == "Odd delegation"

    async def test_a_caller_sees_what_it_may_and_counts_the_agents_it_may_not(self, db):
        owner = await _owner(db)
        shared = await _skill(db, owner)
        private = await SkillService(db).create(
            owner,
            name="secrets",
            description="Kept to the owner.",
            content="v1 text",
            visibility=Visibility.PRIVATE,
        )
        await SkillService(db).update(owner, private.id, SkillUpdate(content="v2 text"))
        await _serving(db, owner, "Open", _spec(shared, version=1))
        hidden = await _serving(db, owner, "Hidden", _spec(shared, version=2))
        hidden.visibility = "private"
        await _serving(db, owner, "Secret", _spec(private, version=1))
        await db.flush()
        viewer = await _member(db, owner, OrgRoleName.VIEWER)

        listed = await SkillCatchUpService(db).behind_main(viewer)

        assert [(item.skill.name, item.can_act) for item in listed.items] == [("refunds", False)]
        assert listed.hidden == 1

    async def test_another_organizations_agents_are_not_this_ones(self, db):
        ours, theirs = await _owner(db), await _owner(db)
        skill = await _skill(db, theirs)
        await _serving(db, theirs, "Theirs", _spec(skill, version=1))

        assert (await SkillCatchUpService(db).behind_main(ours)).items == []


async def _following(db: AsyncSession, *agents: Agent) -> None:
    """Make each agent's environments follow its publishes, so a move goes live there."""
    await db.execute(
        update(AgentEnvironment)
        .where(AgentEnvironment.agent_id.in_([agent.id for agent in agents]))
        .values(tracks_latest=True)
    )


class TestReturnToMain:
    async def test_every_agent_moves_to_main_and_the_fork_is_archived(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        spec = await _runnable(db, ctx, skill, fork_id=str(fork.id))
        desk = await _serving(db, ctx, "Desk", spec)
        till = await _serving(db, ctx, "Till", spec)
        await _following(db, desk, till)

        returned = await SkillCatchUpService(db).return_to_main(
            ctx, skill.id, fork.id, ReturnToMain()
        )

        assert sorted((row.agent.name, row.published, row.refused) for row in returned.agents) == [
            ("Desk", True, None),
            ("Till", True, None),
        ]
        assert (returned.remaining, returned.archived, returned.hidden) == (0, True, 0)
        for agent in (desk, till):
            await db.refresh(agent)
            assert AgentSpec.model_validate(agent.draft_spec).skill_bindings == []

    async def test_only_the_agents_asked_for_move_and_the_fork_stays_while_read(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        spec = await _runnable(db, ctx, skill, fork_id=str(fork.id))
        desk = await _serving(db, ctx, "Desk", spec)
        till = await _serving(db, ctx, "Till", spec)
        await _following(db, desk, till)

        returned = await SkillCatchUpService(db).return_to_main(
            ctx, skill.id, fork.id, ReturnToMain(agent_ids=[desk.id])
        )

        assert [row.agent.name for row in returned.agents] == ["Desk"]
        assert (returned.remaining, returned.archived) == (1, False)

    async def test_an_agent_that_cannot_move_stays_with_the_reason(self, db):
        """A specialist's binding is the Builder's; a hidden agent is only counted."""
        owner = await _owner(db)
        skill = await _skill(db, owner)
        fork = await _fork(db, owner, skill)
        on_fork = str(fork.id)
        await _serving(
            db, owner, "Desk", _with_specialist({"name": "Desk"}, skill, fork_id=on_fork)
        )
        hidden = await _serving(db, owner, "Hidden", _spec(skill, fork_id=on_fork))
        hidden.visibility = "private"
        await db.flush()
        member = await _member(db, owner, OrgRoleName.MEMBER)

        returned = await SkillCatchUpService(db).return_to_main(
            member, skill.id, fork.id, ReturnToMain()
        )

        [desk] = returned.agents
        assert desk.agent.name == "Desk" and desk.published is False
        assert desk.refused is not None
        assert (returned.hidden, returned.remaining, returned.archived) == (1, 2, False)

    @pytest.mark.security
    async def test_a_system_agent_stays_with_its_reason_and_the_others_move(self, db):
        """Changing a system agent needs org:settings; that one refusal stops nobody else."""
        owner = await _owner(db)
        skill = await _skill(db, owner)
        fork = await _fork(db, owner, skill)
        spec = await _runnable(db, owner, skill, fork_id=str(fork.id))
        await _serving(db, owner, "Desk", spec)
        judge = await _serving(db, owner, "Judge", spec)
        judge.kind = AgentKind.JUDGE.value
        await db.flush()
        builder = await _member(db, owner, OrgRoleName.BUILDER)

        returned = await SkillCatchUpService(db).return_to_main(
            builder, skill.id, fork.id, ReturnToMain()
        )

        by_name = {row.agent.name: row for row in returned.agents}
        assert by_name["Desk"].refused is None
        assert by_name["Judge"].refused is not None and "system agent" in by_name["Judge"].refused

    async def test_a_move_an_environment_does_not_follow_leaves_the_fork_read(self, db):
        """Published, but production waits for a promotion: it still serves the fork."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        await _serving(db, ctx, "Desk", await _runnable(db, ctx, skill, fork_id=str(fork.id)))

        returned = await SkillCatchUpService(db).return_to_main(
            ctx, skill.id, fork.id, ReturnToMain()
        )

        [desk] = returned.agents
        assert (desk.published, returned.remaining, returned.archived) == (True, 1, False)

    async def test_a_move_that_waits_in_the_draft_leaves_the_fork_read(self, db):
        owner = await _owner(db)
        skill = await _skill(db, owner)
        fork = await _fork(db, owner, skill)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        await _serving(db, member, "Mine", await _runnable(db, member, skill, fork_id=str(fork.id)))

        returned = await SkillCatchUpService(db).return_to_main(
            member, skill.id, fork.id, ReturnToMain()
        )

        [mine] = returned.agents
        assert (mine.published, mine.refused) == (False, None)
        assert (returned.remaining, returned.archived) == (1, False)

    async def test_another_organizations_fork_is_not_found(self, db):
        ours, theirs = await _owner(db), await _owner(db)
        skill = await _skill(db, ours)
        stranger = await _skill(db, theirs, "invoices")
        their_fork = await _fork(db, theirs, stranger)

        with pytest.raises(NotFoundError):
            await SkillCatchUpService(db).return_to_main(
                ours, skill.id, their_fork.id, ReturnToMain()
            )

    async def test_a_fork_of_another_skill_is_not_found_and_nobody_moves(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        other = await _skill(db, ctx, "invoices")
        other_fork = await _fork(db, ctx, other)
        desk = await _serving(db, ctx, "Desk", _spec(other, fork_id=str(other_fork.id)))

        with pytest.raises(NotFoundError, match="Fork not found"):
            await SkillCatchUpService(db).return_to_main(
                ctx, skill.id, other_fork.id, ReturnToMain()
            )

        await db.refresh(desk)
        [binding] = AgentSpec.model_validate(desk.draft_spec).skill_bindings
        assert binding.fork_id == other_fork.id


class TestReturningBesideADecision:
    async def test_a_decision_holding_the_skill_lets_the_return_wait_its_turn(
        self, db: AsyncSession, engine: AsyncEngine
    ):
        """Deciding a fork's check locks the skill and then an agent; returning the fork's
        agents to main takes them in that order too, so it waits rather than deadlocking."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        desk = await _serving(
            db, ctx, "Desk", await _runnable(db, ctx, skill, fork_id=str(fork.id))
        )
        await _following(db, desk)
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def returning() -> None:
            async with factory() as session:
                await SkillCatchUpService(session).return_to_main(
                    ctx, skill.id, fork.id, ReturnToMain()
                )
                await session.commit()

        task: asyncio.Task[None] | None = None
        async with factory() as deciding:
            try:
                await skill_repo.lock(deciding, skill.id)
                task = asyncio.create_task(returning())
                await _waiting_for_a_lock(factory, task)

                await asyncio.wait_for(
                    agent_repo.get(
                        deciding, desk.id, organization_id=ctx.organization_id, for_update=True
                    ),
                    5,
                )
                await deciding.commit()
                await task
                task = None
            finally:
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

        async with factory() as reading:
            moved = await reading.get(Agent, desk.id)
            assert moved is not None
            assert AgentSpec.model_validate(moved.draft_spec).skill_bindings == []

    async def test_a_publish_reading_the_fork_lets_the_return_wait_its_turn(
        self, db: AsyncSession, engine: AsyncEngine
    ):
        """A publish locks its agent and then holds the forks it reads; returning the
        fork's agents holds the fork the same shared way until it archives it, so the
        two take turns on the agent rather than deadlocking."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill)
        desk = await _serving(
            db, ctx, "Desk", await _runnable(db, ctx, skill, fork_id=str(fork.id))
        )
        await _following(db, desk)
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def returning() -> None:
            async with factory() as session:
                await SkillCatchUpService(session).return_to_main(
                    ctx, skill.id, fork.id, ReturnToMain()
                )
                await session.commit()

        task: asyncio.Task[None] | None = None
        async with factory() as publishing:
            try:
                await agent_repo.get(
                    publishing, desk.id, organization_id=ctx.organization_id, for_update=True
                )
                task = asyncio.create_task(returning())
                await _waiting_for_a_lock(factory, task)

                await asyncio.wait_for(
                    skill_version_repo.hold_forks(
                        publishing, [fork.id], organization_id=ctx.organization_id
                    ),
                    5,
                )
                await publishing.commit()
                await task
                task = None
            finally:
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
