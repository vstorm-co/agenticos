"""Catching up with main: who main has left behind, across an organization.

Against a real database, because "behind" is read off what each agent's
environments serve and off the version rows themselves.
"""

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.resource_grant import Visibility
from app.db.models.skill import Skill
from app.schemas.skill import SkillUpdate
from app.schemas.skill_version import SkillForkCreate
from app.services.skill_catch_up import SkillCatchUpService
from app.services.skill_versions import SkillVersionService
from app.services.skills import SkillService
from tests.integration.test_authoring import _member, _owner
from tests.integration.test_skill_bindings import _fork, _serving, _skill, _spec

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

        listed = await SkillCatchUpService(db).behind_main(ctx)

        assert (listed.total, listed.hidden) == (2, 0)
        pinned, forked = listed.items
        assert pinned.kind == "pinned" and pinned.agent is not None
        assert (pinned.agent.name, pinned.version.number, pinned.behind_main) == ("Pinned", 1, 3)
        assert (pinned.main_latest.number, pinned.agents, pinned.can_act) == (4, 1, True)
        assert forked.kind == "fork" and forked.fork is not None
        assert (forked.fork.id, forked.fork.base_number, forked.fork.changes) == (fork.id, 3, 0)
        assert (forked.agents, forked.behind_main, forked.can_act) == (2, 1, True)
        assert forked.version.id == fork.base.id

    async def test_a_specialists_pin_is_listed_under_its_agent(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        await _serving(db, ctx, "Desk", _delegating(skill, version=2))
        # The agent's own binding wins over its specialist's, as when it runs.
        await _serving(db, ctx, "Own", {**_delegating(skill, version=2), **_spec(skill)})

        [item] = (await SkillCatchUpService(db).behind_main(ctx)).items

        assert item.agent is not None
        assert (item.agent.name, item.via_specialist, item.behind_main) == ("Desk", "billing", 1)

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
