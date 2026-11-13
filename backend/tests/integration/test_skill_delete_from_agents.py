"""Deleting a skill agents still use, by taking it out of them first, on a real database.

All or nothing: every agent loses the skill and the skill is gone, or a refusal names
the agents it could not be taken from and nothing changes.
"""

import asyncio
import contextlib
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError, InUseError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.skill import Skill
from app.repositories import agent_repo, promotion_gate_repo, skill_repo
from app.services.agent_registry import AgentRegistryService
from app.services.eval_suite import EvalSuiteService
from app.services.skills import SkillService
from tests.integration.test_authoring import _member, _owner, _published
from tests.integration.test_eval_suites import _dataset, _suite_data
from tests.integration.test_skill_bindings import (
    _runnable,
    _serving,
    _skill,
    _spec,
    _waiting_for_a_lock,
    _with_specialist,
)

pytestmark = pytest.mark.anyio


async def _environment(db: AsyncSession, agent: Agent) -> AgentEnvironment:
    found = await db.scalar(select(AgentEnvironment).where(AgentEnvironment.agent_id == agent.id))
    assert found is not None
    return found


async def _following(db: AsyncSession, ctx: AuthContext, name: str, spec: dict[str, Any]) -> Agent:
    """A published agent whose production follows publishes, serving `spec`."""
    agent = await _serving(db, ctx, name, spec)
    (await _environment(db, agent)).tracks_latest = True
    await db.flush()
    return agent


async def _gone(db: AsyncSession, skill: Skill) -> bool:
    db.expunge(skill)
    return await db.get(Skill, skill.id) is None


async def _delete(db: AsyncSession, ctx: AuthContext, skill: Skill) -> InUseError:
    with pytest.raises(InUseError) as refused:
        await SkillService(db).delete(ctx, skill.id, remove_from_agents=True)
    return refused.value


class TestRemovingAndDeleting:
    async def test_every_agent_loses_the_skill_and_the_skill_is_deleted(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        spec = await _runnable(db, ctx, skill)
        clerk = await _following(db, ctx, "Clerk", spec)
        clerk.draft_spec = {**spec, "instructions": "Unfinished edit."}
        desk = await _published(
            db, ctx, name="Desk", spec=_with_specialist({"name": "Desk"}, skill)
        )
        await db.flush()

        await SkillService(db).delete(ctx, skill.id, remove_from_agents=True)

        assert await _gone(db, skill)
        await db.refresh(clerk)
        served = await db.get(AgentVersion, (await _environment(db, clerk)).version_id)
        assert served is not None and served.version == 2
        published = AgentSpec.model_validate(served.spec)
        assert published.skill_ids == [] and published.instructions == ""
        draft = AgentSpec.model_validate(clerk.draft_spec)
        assert draft.skill_ids == [] and draft.instructions == "Unfinished edit."
        await db.refresh(desk)
        specialist = desk.draft_spec["capabilities"][0]["config"]["inline"][0]
        assert specialist["skill_ids"] == [] and specialist["instructions"] == "Bill."

    async def test_without_a_served_version_using_it_only_the_draft_changes(self, db):
        """An agent may lose the skill from its draft without the right to publish."""
        owner = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        skill = await _skill(db, member)
        agent = await _serving(db, member, "Mine", {"name": "Mine"})
        agent.draft_spec = _spec(skill)
        await db.flush()

        await SkillService(db).delete(member, skill.id, remove_from_agents=True)

        assert await _gone(db, skill)
        await db.refresh(agent)
        assert AgentSpec.model_validate(agent.draft_spec).skill_ids == []
        assert agent.current_version_id == (await _environment(db, agent)).version_id

    async def test_another_organizations_agent_is_neither_counted_nor_touched(self, db):
        ctx = await _owner(db)
        other = await _owner(db)
        skill = await _skill(db, ctx)
        theirs = await _published(db, other, name="Theirs", spec=_spec(skill))

        await SkillService(db).delete(ctx, skill.id, remove_from_agents=True)

        assert await _gone(db, skill)
        await db.refresh(theirs)
        assert theirs.draft_spec == _spec(skill)

    async def test_an_unreadable_environment_that_never_named_it_does_not_stop_it(self, db):
        """Only a spec that names the skill can bind it; another one is not changed."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _serving(db, ctx, "Clerk", {"name": "Clerk"})
        agent.draft_spec = _spec(skill)
        broken = AgentVersion(
            agent_id=agent.id,
            organization_id=ctx.organization_id,
            version=2,
            spec={"name": "Clerk", "skill_ids": ["not-an-id"]},
        )
        db.add(broken)
        await db.flush()
        db.add(
            AgentEnvironment(
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                name="staging",
                version_id=broken.id,
            )
        )
        await db.flush()

        await SkillService(db).delete(ctx, skill.id, remove_from_agents=True)

        assert await _gone(db, skill)
        await db.refresh(agent)
        assert AgentSpec.model_validate(agent.draft_spec).skill_ids == []


class TestRefusingTheWholeDelete:
    async def test_an_agent_the_caller_cannot_change_refuses_it(self, db):
        owner = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        skill = await _skill(db, member)
        mine = await _published(db, member, name="Mine", spec=_spec(skill))
        await _published(db, owner, name="Theirs", spec=_spec(skill))

        refused = await _delete(db, member, skill)

        assert [agent["name"] for agent in refused.details["not_editable"]] == ["Theirs"]
        assert refused.details["hidden"] == 0
        assert "you cannot change 'Theirs'" in refused.message
        await db.refresh(mine)
        assert mine.draft_spec == _spec(skill)
        assert await db.get(Skill, skill.id) is not None

    async def test_an_agent_that_must_publish_without_the_right_to_is_refused(self, db):
        owner = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        skill = await _skill(db, member)
        await _following(db, member, "Mine", _spec(skill))

        refused = await _delete(db, member, skill)

        assert [agent["name"] for agent in refused.details["not_editable"]] == ["Mine"]

    async def test_a_hidden_agent_refuses_it_without_being_named(self, db):
        owner = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        skill = await _skill(db, member)
        secret = await _published(db, owner, name="Secret", spec=_spec(skill))
        secret.visibility = "private"
        await db.flush()

        refused = await _delete(db, member, skill)

        assert refused.details["hidden"] == 1
        assert refused.details["agents"] == []
        assert "Secret" not in refused.message

    async def test_an_environment_waiting_for_promotion_refuses_it(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _serving(db, ctx, "Clerk", _spec(skill))

        refused = await _delete(db, ctx, skill)

        assert refused.details["waiting"] == [
            {"id": agent.id, "name": "Clerk", "environments": ["production"]}
        ]
        assert "only a promotion moves" in refused.message
        await db.refresh(agent)
        assert agent.draft_spec == _spec(skill)

    async def test_a_following_environment_held_by_its_guards_refuses_it(self, db):
        """A publish does not move a follower its guard suites hold, so it waits like one
        that waits for promotion, and the refusal says so."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _following(db, ctx, "Clerk", _spec(skill))
        suite = await EvalSuiteService(db).create(
            ctx, agent.id, _suite_data(await _dataset(db, ctx))
        )
        await promotion_gate_repo.replace_guards(
            db, (await _environment(db, agent)).id, [suite.id], organization_id=ctx.organization_id
        )

        refused = await _delete(db, ctx, skill)

        assert refused.details["waiting"] == [
            {"id": agent.id, "name": "Clerk", "environments": ["production"]}
        ]
        assert "only a promotion moves" in refused.message

    @pytest.mark.parametrize("unreadable", ["draft", "served", "newest"])
    async def test_a_spec_that_no_longer_reads_refuses_it(self, db, unreadable):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _following(db, ctx, "Clerk", _spec(skill))
        broken = {"name": "Clerk", "skill_ids": [str(skill.id), "not-an-id"]}
        if unreadable == "draft":
            agent.draft_spec = broken
        elif unreadable == "served":
            served = await db.get(AgentVersion, agent.current_version_id)
            assert served is not None
            served.spec = broken
        else:
            db.add(
                AgentVersion(
                    agent_id=agent.id, organization_id=ctx.organization_id, version=2, spec=broken
                )
            )
        await db.flush()

        refused = await _delete(db, ctx, skill)

        assert [agent["name"] for agent in refused.details["not_editable"]] == ["Clerk"]

    async def test_an_agent_that_does_not_publish_without_it_is_named(self, db):
        """The request names no agent, so a publish refusal says which one to fix."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _following(db, ctx, "Clerk", _spec(skill))

        with pytest.raises(BadRequestError) as refused:
            await SkillService(db).delete(ctx, skill.id, remove_from_agents=True)

        assert refused.value.details is not None
        assert (refused.value.details["agent_id"], refused.value.details["agent_name"]) == (
            agent.id,
            "Clerk",
        )
        assert refused.value.details["problems"]
        assert refused.value.message.startswith("'Clerk' does not publish without 'refunds'")


class TestBesideAnotherWriter:
    """Two sessions on one skill: the delete and a draft save or a new binding."""

    async def test_a_draft_saved_meanwhile_waits_for_its_turn_instead_of_deadlocking(
        self, db: AsyncSession, engine: AsyncEngine
    ):
        """A save locks its agent, then holds the skill; the delete takes them in that order."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _published(db, ctx, name="Clerk", spec=_spec(skill))
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def delete() -> None:
            async with factory() as session:
                await SkillService(session).delete(ctx, skill.id, remove_from_agents=True)
                await session.commit()

        task: asyncio.Task[None] | None = None
        async with factory() as saving:
            try:
                await agent_repo.get(
                    saving, agent.id, organization_id=ctx.organization_id, for_update=True
                )
                task = asyncio.create_task(delete())
                await asyncio.sleep(0.4)
                assert not task.done()

                await asyncio.wait_for(
                    skill_repo.hold(saving, [skill.id], organization_id=ctx.organization_id), 5
                )
                await saving.commit()
                await task
                task = None
            finally:
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

        async with factory() as reading:
            assert await reading.get(Skill, skill.id) is None
            after = await reading.get(Agent, agent.id)
            assert after is not None and AgentSpec.model_validate(after.draft_spec).skill_ids == []

    async def test_a_check_decision_holding_the_skill_lets_the_delete_wait_its_turn(
        self, db: AsyncSession, engine: AsyncEngine
    ):
        """Deciding a check locks the skill and then an agent it pins or moves; the delete
        takes them in that order too, so it waits rather than deadlocking."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _published(db, ctx, name="Clerk", spec=_spec(skill))
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def delete() -> None:
            async with factory() as session:
                await SkillService(session).delete(ctx, skill.id, remove_from_agents=True)
                await session.commit()

        task: asyncio.Task[None] | None = None
        async with factory() as deciding:
            try:
                await skill_repo.lock(deciding, skill.id)
                task = asyncio.create_task(delete())
                await _waiting_for_a_lock(factory, task)

                await asyncio.wait_for(
                    agent_repo.get(
                        deciding, agent.id, organization_id=ctx.organization_id, for_update=True
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
            assert await reading.get(Skill, skill.id) is None

    async def test_an_agent_created_with_it_meanwhile_refuses_the_delete(
        self, db: AsyncSession, engine: AsyncEngine
    ):
        """Creating an agent holds the skills it binds, as a draft save does, so the delete
        waits for it and then sees it."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def delete() -> None:
            async with factory() as session:
                await SkillService(session).delete(ctx, skill.id)

        task: asyncio.Task[None] | None = None
        async with factory() as creating:
            try:
                await AgentRegistryService(creating).create(
                    ctx, AgentSpec.model_validate(_spec(skill))
                )
                task = asyncio.create_task(delete())
                await _waiting_for_a_lock(factory, task)

                await creating.commit()
                with pytest.raises(InUseError):
                    await task
                task = None
            finally:
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    async def test_an_agent_that_starts_using_it_meanwhile_refuses_the_delete(
        self, db: AsyncSession, engine: AsyncEngine
    ):
        """It was not locked with the others, so nothing is removed and nothing deleted."""
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        clerk = await _published(db, ctx, name="Clerk", spec=_spec(skill))
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def delete() -> None:
            async with factory() as session:
                await SkillService(session).delete(ctx, skill.id, remove_from_agents=True)

        task: asyncio.Task[None] | None = None
        async with factory() as binding:
            try:
                await skill_repo.hold(binding, [skill.id], organization_id=ctx.organization_id)
                await _published(binding, ctx, name="Desk", spec=_spec(skill))
                task = asyncio.create_task(delete())
                await _waiting_for_a_lock(factory, task)
                assert not task.done()

                await binding.commit()
                with pytest.raises(InUseError) as refused:
                    await task
                task = None
            finally:
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

        assert refused.value.details == {"reason": "agents_changed"}
        async with factory() as reading:
            assert await reading.get(Skill, skill.id) is not None
            after = await reading.get(Agent, clerk.id)
            assert after is not None and after.draft_spec == _spec(skill)
