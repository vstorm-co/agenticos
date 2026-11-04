"""Deleting a skill agents still use, by taking it out of them first, on a real database.

All or nothing: every agent loses the skill and the skill is gone, or a refusal names
the agents it could not be taken from and nothing changes.
"""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError, InUseError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.skill import Skill
from app.services.skills import SkillService
from tests.integration.test_authoring import _member, _owner, _published
from tests.integration.test_skill_bindings import (
    _runnable,
    _serving,
    _skill,
    _spec,
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
