"""Moving an agent pinned to an older version of a skill up to main's newest, checked first.

The skill, its versions, the agents and their bindings, the check and the move are
real; the eval runs are scripted as in `test_skill_checks`.
"""

import uuid
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AlreadyExistsError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import Perm
from app.db.models.agent import Agent
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.skill_check import (
    AgentState,
    CheckMode,
    CheckOutcome,
    CheckSource,
    CheckStatus,
    CheckVerdict,
)
from app.repositories import agent_environment_repo, agent_repo, skill_check_repo
from app.schemas.skill import SkillUpdate
from app.schemas.skill_check import SkillCheckApply, SkillCheckFork, SkillUpdateCheck
from app.schemas.skill_version import SkillBindingChange
from app.services.agent_registry import AgentRegistryService
from app.services.skill_agents import SkillAgentService
from app.services.skill_check import SkillCheckService
from app.services.skills import SkillService
from tests.integration.test_authoring import _owner
from tests.integration.test_skill_bindings import _runnable, _serving, _skill, _with_specialist
from tests.integration.test_skill_checks import (
    FakeEvals,
    Lab,
    Outcome,
    _dataset,
    _lab,
    _run_to_end,
    _start,
)

pytestmark = pytest.mark.anyio

QUICK = SkillUpdateCheck()


def _to_main(check_id: Any, **values: Any) -> SkillBindingChange:
    return SkillBindingChange(state="main", check_id=check_id, **values)


async def _checked(db: AsyncSession, monkeypatch, outcomes: dict | None = None, **fake: Any):
    lab = await _lab(db)
    evals = FakeEvals(**fake)
    evals.install(monkeypatch)
    service = SkillCheckService(db)
    check = await service.start_update(lab.ctx, lab.skill.id, lab.pinned.id, QUICK)
    evals.outcomes = outcomes or {}
    read = await _run_to_end(service, evals, lab, check.id)
    return lab, service, read


async def _binding(db: AsyncSession, lab: Lab, agent: Agent) -> Any:
    listing = await SkillAgentService(db).agents(lab.ctx, lab.skill.id)
    return next(row for row in listing.items if row.agent.id == agent.id)


class TestTheCheck:
    async def test_it_runs_main_newest_on_the_pinned_agent_alone(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)

        estimate = await service.estimate_update(lab.ctx, lab.skill.id, lab.pinned.id, QUICK)
        read = await service.start_update(lab.ctx, lab.skill.id, lab.pinned.id, QUICK)

        assert [row.agent.name for row in estimate.agents] == ["Pinned"]
        assert (estimate.line.name, estimate.base_version.number) == ("main", 1)
        assert estimate.mode is CheckMode.QUICK
        assert {agent_id for agent_id, _ in evals.started} == {lab.pinned.id}
        stored = await skill_check_repo.get(db, read.id, organization_id=lab.ctx.organization_id)
        assert stored is not None
        assert (stored.agent_id, stored.source) == (lab.pinned.id, CheckSource.CATCH_UP.value)
        assert stored.candidate_version_id == lab.skill.latest_version_id
        assert stored.candidate_content == "v3 text"

    async def test_the_candidate_is_main_newest_with_its_files_served_over_the_pin(
        self, db, monkeypatch
    ):
        """Its baseline is the agent as published, on its pinned version; the candidate is
        what moving it to main would leave it reading, which the pin alone would refuse."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)

        await SkillCheckService(db).start_update(lab.ctx, lab.skill.id, lab.pinned.id, QUICK)

        assert evals.served
        for bodies in evals.served:
            body = bodies[lab.skill.id]
            assert (body.content, body.fork_id, body.over_pin) == ("v3 text", None, True)
            assert [(item.name, item.content) for item in body.resources] == [("a.md", "first")]

    async def test_only_a_pinned_agent_behind_main_has_an_update_to_check(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        service = SkillCheckService(db)
        newest = await _serving(
            db,
            lab.ctx,
            "On v3",
            {**lab.a.draft_spec, "skill_bindings": [{"skill_id": str(lab.skill.id), "version": 3}]},
        )

        with pytest.raises(BadRequestError):
            await service.estimate_update(lab.ctx, lab.skill.id, lab.a.id, QUICK)
        with pytest.raises(BadRequestError):
            await service.start_update(lab.ctx, lab.skill.id, lab.on_fork.id, QUICK)
        with pytest.raises(AlreadyExistsError):
            await service.start_update(lab.ctx, lab.skill.id, newest.id, QUICK)
        unbound = await _serving(
            db, lab.ctx, "Unbound", {**lab.a.draft_spec, "skill_ids": [], "skill_bindings": []}
        )
        with pytest.raises(BadRequestError, match="is not pinned"):
            await service.start_update(lab.ctx, lab.skill.id, unbound.id, QUICK)

    async def test_another_organization_or_no_skill_edit_finds_nothing(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        service = SkillCheckService(db)
        member = replace(
            lab.ctx, key_scopes=frozenset({Perm.RUNS_VIEW, Perm.SKILLS_VIEW, Perm.AGENTS_VIEW})
        )

        with pytest.raises(NotFoundError):
            await service.start_update(await _owner(db), lab.skill.id, lab.pinned.id, QUICK)
        with pytest.raises(NotFoundError):
            await service.estimate_update(member, lab.skill.id, lab.pinned.id, QUICK)


class TestAccepting:
    async def test_a_not_worse_result_moves_the_agent_to_main_and_marks_it_checked(
        self, db, monkeypatch
    ):
        lab, service, read = await _checked(db, monkeypatch)

        assert read.outcomes == [CheckOutcome.APPLY, CheckOutcome.DISCARD]
        moved = await SkillAgentService(db).change_binding(
            lab.ctx, lab.skill.id, lab.pinned.id, _to_main(read.id)
        )

        assert moved.published is True
        newest = await agent_repo.newest_version(
            db, agent_id=lab.pinned.id, organization_id=lab.ctx.organization_id
        )
        assert newest is not None
        assert AgentSpec.model_validate(newest.spec).skill_bindings == []
        decided = await service.read(lab.ctx, lab.skill.id, read.id)
        assert (decided.status, decided.outcome) == (CheckStatus.APPLIED, CheckOutcome.APPLY)
        assert decided.applied_version_id == lab.skill.latest_version_id

    async def test_without_publish_the_draft_moves_and_the_live_version_stays(
        self, db, monkeypatch
    ):
        lab, _, read = await _checked(db, monkeypatch)
        editor = replace(
            lab.ctx,
            key_scopes=frozenset(
                {
                    Perm.SKILLS_VIEW,
                    Perm.SKILLS_EDIT,
                    Perm.AGENTS_VIEW,
                    Perm.AGENTS_EDIT,
                    Perm.AGENTS_RUN,
                    Perm.RUNS_VIEW,
                }
            ),
        )

        moved = await SkillAgentService(db).change_binding(
            editor, lab.skill.id, lab.pinned.id, _to_main(read.id)
        )

        assert moved.published is False
        await db.refresh(lab.pinned)
        assert AgentSpec.model_validate(lab.pinned.draft_spec).skill_bindings == []

    async def test_a_worse_result_offers_no_move(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start_update(lab.ctx, lab.skill.id, lab.pinned.id, QUICK)
        evals.outcomes = {lab.pinned.id: Outcome(broken=1)}
        read = await _run_to_end(service, evals, lab, check.id)

        assert read.verdict is CheckVerdict.BLOCKED
        assert read.outcomes == [CheckOutcome.DISCARD]
        with pytest.raises(BadRequestError):
            await SkillAgentService(db).change_binding(
                lab.ctx, lab.skill.id, lab.pinned.id, _to_main(read.id)
            )
        row = await _binding(db, lab, lab.pinned)
        assert row.binding.state == "pinned"

    async def test_an_unknown_result_moves_only_once_acknowledged(self, db, monkeypatch):
        service = SkillCheckService(db)
        lab = await _lab(db)
        refused = FakeEvals(refuse_start={lab.pinned.id})
        refused.install(monkeypatch)
        check = await service.start_update(lab.ctx, lab.skill.id, lab.pinned.id, QUICK)
        read = await _run_to_end(service, refused, lab, check.id)
        agents = SkillAgentService(db)

        assert read.agents[0].state is AgentState.UNKNOWN
        with pytest.raises(BadRequestError):
            await agents.change_binding(lab.ctx, lab.skill.id, lab.pinned.id, _to_main(read.id))
        moved = await agents.change_binding(
            lab.ctx,
            lab.skill.id,
            lab.pinned.id,
            _to_main(read.id, acknowledge_unknown=True),
        )
        assert moved.published is True


class TestRefusals:
    async def test_a_check_is_stale_once_main_moves_on(self, db, monkeypatch):
        lab, _, read = await _checked(db, monkeypatch)
        await SkillService(db).update(lab.ctx, lab.skill.id, SkillUpdate(content="v4 text"))

        with pytest.raises(ConcurrentChangeError):
            await SkillAgentService(db).change_binding(
                lab.ctx, lab.skill.id, lab.pinned.id, _to_main(read.id)
            )

    @pytest.mark.parametrize(
        ("moved", "promoted"),
        [
            ({"state": "pinned", "version": 2}, True),
            ({"state": "main"}, True),
            ({"state": "main"}, False),
        ],
        ids=["pinned elsewhere", "on main already", "published, not promoted"],
    )
    async def test_a_check_is_stale_once_the_agent_is_published_again(
        self, db, monkeypatch, moved, promoted
    ):
        """Accepting publishes from the agent's newest version, so a newer one than the
        measured version is stale even while its default environment still serves the old."""
        lab, _, read = await _checked(db, monkeypatch)
        agents = SkillAgentService(db)
        await agents.change_binding(
            lab.ctx, lab.skill.id, lab.pinned.id, SkillBindingChange(**moved)
        )
        if promoted:
            [environment] = await agent_environment_repo.list_for_agent(
                db, agent_id=lab.pinned.id, organization_id=lab.ctx.organization_id
            )
            newest = await agent_repo.newest_version(
                db, agent_id=lab.pinned.id, organization_id=lab.ctx.organization_id
            )
            assert newest is not None
            environment.version_id = newest.id
            await db.flush()

        with pytest.raises(ConcurrentChangeError):
            await agents.change_binding(lab.ctx, lab.skill.id, lab.pinned.id, _to_main(read.id))

    async def test_a_check_moves_only_the_agent_it_measured(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        update = await service.start_update(lab.ctx, lab.skill.id, lab.pinned.id, QUICK)
        line_check = await service.start(lab.ctx, lab.skill.id, _start())
        read = await _run_to_end(service, evals, lab, update.id)
        await _run_to_end(service, evals, lab, line_check.id)
        agents = SkillAgentService(db)

        with pytest.raises(BadRequestError):
            await agents.change_binding(lab.ctx, lab.skill.id, lab.on_fork.id, _to_main(read.id))
        with pytest.raises(BadRequestError):
            await agents.change_binding(
                lab.ctx, lab.skill.id, lab.pinned.id, _to_main(line_check.id)
            )

    async def test_an_update_check_never_changes_the_skill(self, db, monkeypatch):
        lab, service, read = await _checked(db, monkeypatch)

        assert (read.source, read.agent_id) == (CheckSource.CATCH_UP, lab.pinned.id)
        assert read.candidate_version_id == lab.skill.latest_version_id
        with pytest.raises(BadRequestError):
            await service.apply(lab.ctx, lab.skill.id, read.id, SkillCheckApply())
        with pytest.raises(BadRequestError):
            await service.fork(lab.ctx, lab.skill.id, read.id, SkillCheckFork(name="pinned"))
        with pytest.raises(ValidationError):
            SkillBindingChange(state="pinned", version=1, check_id=read.id)

    async def test_another_organizations_check_is_not_found(self, db, monkeypatch):
        lab, _, read = await _checked(db, monkeypatch)
        other = await _lab(db)

        with pytest.raises(NotFoundError):
            await SkillAgentService(db).change_binding(
                other.ctx, other.skill.id, other.pinned.id, _to_main(read.id)
            )


async def test_an_agent_served_on_main_twice_is_reached_once_at_its_defaults_version(db):
    ctx = await _owner(db)
    skill = await _skill(db, ctx)
    agent = await _serving(db, ctx, "Desk", await _runnable(db, ctx, skill))
    db.add(
        AgentEnvironment(
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            name="staging",
            version_id=agent.current_version_id,
            is_default=False,
        )
    )
    await db.flush()

    [reached] = await SkillAgentService(db).line_agents(skill, None)

    assert (reached.agent.id, reached.via_specialist) == (agent.id, None)


class TestOnce:
    async def test_a_check_moves_its_agent_once(self, db, monkeypatch):
        lab, _, read = await _checked(db, monkeypatch)
        agents = SkillAgentService(db)
        await agents.change_binding(lab.ctx, lab.skill.id, lab.pinned.id, _to_main(read.id))

        with pytest.raises(AlreadyExistsError):
            await agents.change_binding(lab.ctx, lab.skill.id, lab.pinned.id, _to_main(read.id))

    async def test_a_move_that_does_not_publish_leaves_the_check_open(self, db, monkeypatch):
        lab, service, read = await _checked(db, monkeypatch)
        refused = AsyncMock(side_effect=BadRequestError(message="Does not publish"))
        monkeypatch.setattr(AgentRegistryService, "publish_spec", refused)

        with pytest.raises(BadRequestError):
            async with db.begin_nested():
                await SkillAgentService(db).change_binding(
                    lab.ctx, lab.skill.id, lab.pinned.id, _to_main(read.id)
                )

        reread = await service.read(lab.ctx, lab.skill.id, read.id)
        assert (reread.status, reread.outcome) == (CheckStatus.DONE, None)

    async def test_an_agent_nobody_may_reach_is_not_found(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)

        with pytest.raises(NotFoundError):
            await SkillCheckService(db).start_update(lab.ctx, lab.skill.id, uuid.uuid4(), QUICK)
        with pytest.raises(NotFoundError):
            await SkillAgentService(db).change_binding(
                lab.ctx, lab.skill.id, uuid.uuid4(), _to_main(uuid.uuid4())
            )


async def test_an_agent_reading_a_line_itself_and_through_a_specialist_is_checked_once(
    db, monkeypatch
):
    ctx = await _owner(db)
    skill = await _skill(db, ctx)
    both = await _serving(db, ctx, "Desk", _with_specialist(await _runnable(db, ctx, skill), skill))
    await _dataset(db, ctx, "skill-set", skill=skill)
    FakeEvals().install(monkeypatch)

    [reached] = await SkillAgentService(db).line_agents(skill, None)
    started = await SkillCheckService(db).start(ctx, skill.id, _start())

    assert (reached.agent.id, reached.via_specialist) == (both.id, None)
    assert [row.agent.id for row in started.agents] == [both.id]


async def test_a_skill_pinned_only_in_a_specialist_names_it_and_the_builder(db, monkeypatch):
    ctx = await _owner(db)
    skill = await _skill(db, ctx)
    agent = await _serving(
        db, ctx, "Desk", _with_specialist(await _runnable(db, ctx, skill), skill, version=1)
    )
    FakeEvals().install(monkeypatch)

    with pytest.raises(BadRequestError, match="pinned in the specialist 'billing' of 'Desk'"):
        await SkillCheckService(db).start_update(ctx, skill.id, agent.id, QUICK)
