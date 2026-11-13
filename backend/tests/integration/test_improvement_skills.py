"""What an agent's Improve session found in its skills, and the seed it hands a skill's Improve."""

import uuid
from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.dataset import Dataset
from app.db.models.improvement import ImprovementRun
from app.db.models.skill import Skill
from app.repositories import authoring_repo, improvement_repo, personal_data_repo
from app.schemas.skill import SkillUpdate
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.skills import SkillService
from tests.integration.test_authoring import _member, _owner
from tests.integration.test_skill_bindings import (
    _fork,
    _serving,
    _skill,
    _spec,
    _with_specialist,
)

pytestmark = pytest.mark.anyio


async def _session(db: AsyncSession, ctx: AuthContext, agent: Agent) -> ImprovementRun:
    dataset = Dataset(
        id=uuid.uuid4(), organization_id=ctx.organization_id, name=f"d-{uuid.uuid4().hex[:6]}"
    )
    db.add(dataset)
    await db.flush()
    return await improvement_repo.create_run(
        db,
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        created_by_user_id=ctx.user_id,
        created_by_api_key_id=None,
        base_version_id=None,
        base_draft_hash="a" * 64,
        dataset_id=dataset.id,
        dataset_version=1,
        suite_id=None,
        suite_hash=None,
        scoring_hash="s" * 64,
        window_days=30,
        estimate_usd=Decimal("0.04"),
        budget_usd=Decimal("0.04"),
        max_iterations=3,
    )


async def _found(
    db: AsyncSession,
    ctx: AuthContext,
    run: ImprovementRun,
    skill: Skill,
    *problems: str,
    cited: uuid.UUID | None = None,
) -> uuid.UUID:
    """An attempt of the session whose improver found `problems` in `skill`; its cited run."""
    request = await authoring_repo.create_request(
        db,
        organization_id=ctx.organization_id,
        kind="improve",
        target="agent",
        agent_id=run.agent_id,
        skill_id=None,
        created_by_user_id=ctx.user_id,
        estimate_usd=Decimal("0.01"),
        window_days=30,
        improvement_run_id=run.id,
    )
    cited = cited or uuid.uuid4()
    request.report = {
        "skill_problems": [
            {
                "skill_id": str(skill.id),
                "skill_name": skill.name,
                "problem": problem,
                "evidence": [
                    {
                        "run_id": str(cited),
                        "quote": f"Quoted for {problem}",
                        "source": "conversation",
                        "number": 1,
                    }
                ],
                "evidence_dropped": 0,
            }
            for problem in problems
        ]
    }
    await db.flush()
    return cited


async def _moved_on(db: AsyncSession, ctx: AuthContext, skill: Skill) -> None:
    """Main gets a version past the one the fork started from."""
    await SkillService(db).update(ctx, skill.id, SkillUpdate(content="v4 text"))


class TestTheSessionsSkills:
    async def test_each_skill_shows_its_line_who_shares_it_and_what_was_found(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        quiet = await _skill(db, ctx, "shipping")
        fork = await _fork(db, ctx, skill, "fork text")
        await _moved_on(db, ctx, skill)
        pinned = await _serving(
            db,
            ctx,
            "Clerk",
            {
                "name": "Clerk",
                "skill_ids": [str(skill.id), str(quiet.id)],
                "skill_bindings": [{"skill_id": str(skill.id), "version": 1}],
            },
        )
        await _serving(db, ctx, "Desk", _spec(skill))
        await _serving(db, ctx, "Forked", _spec(skill, fork_id=str(fork.id)))
        run = await _session(db, ctx, pinned)
        await _found(db, ctx, run, skill, "It says ninety days")
        await _found(db, ctx, run, skill, "It says ninety days", "It skips the order number")

        read = await ImprovementPipelineService(db).skills(ctx, pinned.id, run.id)

        refunds, shipping = read.items
        assert (refunds.name, refunds.can_improve, refunds.hidden_agents) == ("refunds", True, 0)
        assert refunds.binding is not None and refunds.binding.state == "pinned"
        assert refunds.agents_on_line == 1
        assert [problem.problem for problem in refunds.problems] == [
            "It says ninety days",
            "It skips the order number",
        ]
        assert refunds.problems[0].evidence[0].quote == "Quoted for It says ninety days"
        assert refunds.update is not None
        assert (refunds.update.kind, refunds.update.to_version) == ("update_pinned", 4)
        assert (shipping.name, shipping.problems, shipping.update) == ("shipping", [], None)

    async def test_an_agent_reading_it_itself_and_through_a_specialist_counts_once(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        both = await _serving(db, ctx, "Desk", _with_specialist(_spec(skill), skill, version=1))
        run = await _session(db, ctx, both)

        [item] = (await ImprovementPipelineService(db).skills(ctx, both.id, run.id)).items

        assert item.binding is not None and item.binding.state == "main"
        assert item.agents_on_line == 1

    async def test_a_fork_behind_main_offers_to_catch_up_and_counts_its_own_agents(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill, "fork text")
        await _moved_on(db, ctx, skill)
        forked = await _serving(db, ctx, "Forked", _spec(skill, fork_id=str(fork.id)))
        await _serving(db, ctx, "Desk", _spec(skill))
        run = await _session(db, ctx, forked)

        [item] = (await ImprovementPipelineService(db).skills(ctx, forked.id, run.id)).items

        assert item.binding is not None and item.binding.state == "fork"
        assert item.agents_on_line == 1
        assert item.update is not None and item.update.kind == "catch_up_fork"

    async def test_a_skill_the_reader_cannot_see_is_left_out(self, db):
        owner = await _owner(db)
        skill = await _skill(db, owner)
        agent = await _serving(db, owner, "Desk", _spec(skill))
        # A skill deleted since the draft named it is left out rather than failing the read.
        agent.draft_spec = {
            **agent.draft_spec,
            "skill_ids": [*agent.draft_spec["skill_ids"], str(uuid.uuid4())],
        }
        run = await _session(db, owner, agent)
        await _found(db, owner, run, skill, "It says ninety days")
        blind = replace(
            owner, key_scopes=frozenset({Perm.AGENTS_VIEW, Perm.RUNS_VIEW, Perm.AGENTS_EDIT})
        )
        service = ImprovementPipelineService(db)

        assert (await service.skills(blind, agent.id, run.id)).items == []
        with pytest.raises(NotFoundError):
            await service.skill_seed(blind, run.id, skill.id)

    async def test_the_card_and_the_seed_read_the_served_line_not_the_draft(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill, "fork text")
        agent = await _serving(db, ctx, "Desk", _spec(skill))
        agent.draft_spec = _spec(skill, fork_id=str(fork.id))
        run = await _session(db, ctx, agent)
        await _found(db, ctx, run, skill, "It says ninety days")
        service = ImprovementPipelineService(db)

        [item] = (await service.skills(ctx, agent.id, run.id)).items
        seed = await service.skill_seed(ctx, run.id, skill.id)

        assert item.binding is not None and item.binding.state == "main"
        assert seed.fork_id is None

    async def test_reading_needs_runs_view_and_a_session_of_that_agent(self, db):
        owner = await _owner(db)
        skill = await _skill(db, owner)
        agent = await _serving(db, owner, "Desk", _spec(skill))
        other = await _serving(db, owner, "Other", _spec(skill))
        run = await _session(db, owner, agent)
        service = ImprovementPipelineService(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        no_runs = replace(member, key_scopes=frozenset({Perm.AGENTS_VIEW}))

        with pytest.raises(AuthorizationError):
            await service.skills(no_runs, agent.id, run.id)
        with pytest.raises(NotFoundError):
            await service.skills(owner, other.id, run.id)
        with pytest.raises(NotFoundError):
            await service.skills(await _owner(db), agent.id, run.id)


class TestTheSeed:
    async def test_it_carries_the_problems_their_runs_and_the_fork_the_agent_follows(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill, "fork text")
        agent = await _serving(db, ctx, "Forked", _spec(skill, fork_id=str(fork.id)))
        run = await _session(db, ctx, agent)
        cited = await _found(db, ctx, run, skill, "It says ninety days")

        seed = await ImprovementPipelineService(db).skill_seed(ctx, run.id, skill.id)

        assert (seed.agent_id, seed.fork_id, seed.run_ids) == (agent.id, fork.id, [cited])
        assert seed.problems == ["It says ninety days"]
        assert seed.quotes == ["Quoted for It says ninety days"]

    async def test_the_line_is_the_one_the_sessions_version_read_after_a_republish(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        fork = await _fork(db, ctx, skill, "fork text")
        agent = await _serving(db, ctx, "Forked", _spec(skill, fork_id=str(fork.id)))
        run = await _session(db, ctx, agent)
        run.base_version_id = agent.current_version_id
        onto_main = AgentVersion(
            agent_id=agent.id, organization_id=ctx.organization_id, version=2, spec=_spec(skill)
        )
        db.add(onto_main)
        await db.flush()
        environment = await db.scalar(
            select(AgentEnvironment).where(AgentEnvironment.agent_id == agent.id)
        )
        assert environment is not None
        agent.current_version_id = environment.version_id = onto_main.id
        agent.draft_spec = _spec(skill)
        await db.flush()
        await _found(db, ctx, run, skill, "It says ninety days")

        seed = await ImprovementPipelineService(db).skill_seed(ctx, run.id, skill.id)

        assert seed.fork_id == fork.id

    async def test_a_pinned_agent_hands_its_problems_to_main(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx)
        agent = await _serving(db, ctx, "Clerk", _spec(skill, version=1))
        run = await _session(db, ctx, agent)
        await _found(db, ctx, run, skill, "It says ninety days")

        seed = await ImprovementPipelineService(db).skill_seed(ctx, run.id, skill.id)

        assert seed.fork_id is None

    async def test_it_is_refused_without_problems_runs_view_or_the_session(self, db):
        owner = await _owner(db)
        skill = await _skill(db, owner)
        quiet = await _skill(db, owner, "shipping")
        agent = await _serving(db, owner, "Desk", _spec(skill))
        run = await _session(db, owner, agent)
        await _found(db, owner, run, skill, "It says ninety days")
        service = ImprovementPipelineService(db)

        with pytest.raises(BadRequestError):
            await service.skill_seed(owner, run.id, quiet.id)
        with pytest.raises(AuthorizationError):
            await service.skill_seed(
                replace(owner, key_scopes=frozenset({Perm.AGENTS_VIEW})), run.id, skill.id
            )
        with pytest.raises(NotFoundError):
            await service.skill_seed(owner, uuid.uuid4(), skill.id)
        with pytest.raises(NotFoundError):
            await service.skill_seed(await _owner(db), run.id, skill.id)


async def test_an_erased_persons_quotes_leave_the_problems_and_the_seed(db):
    ctx = await _owner(db)
    skill = await _skill(db, ctx)
    agent = await _serving(db, ctx, "Desk", _spec(skill))
    erased = await _member(db, ctx, OrgRoleName.MEMBER)
    asked = AgentRun(
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=erased.user_id,
        surface=RunSurface.WEB.value,
        status="completed",
    )
    db.add(asked)
    await db.flush()
    run = await _session(db, ctx, agent)
    await _found(db, ctx, run, skill, "It says ninety days", cited=asked.id)
    kept = await _found(db, ctx, run, skill, "It skips the order number")

    removed = await personal_data_repo.purge_evidence_of(db, erased.user_id, comments={})

    service = ImprovementPipelineService(db)
    [item] = (await service.skills(ctx, agent.id, run.id)).items
    assert removed == 1
    assert {problem.problem: len(problem.evidence) for problem in item.problems} == {
        "It says ninety days": 0,
        "It skips the order number": 1,
    }
    seed = await service.skill_seed(ctx, run.id, skill.id)
    assert (seed.run_ids, seed.quotes) == ([kept], ["Quoted for It skips the order number"])
