"""The refusals and corners of a skill check: a stale or foreign proposal, agents a
person may not run or see, a run that has not settled, a line that gained an
agent, a pin nobody may publish, and the skill's questions taken from evidence."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import Perm
from app.db.models.agent_run import AgentRun
from app.db.models.background_job import BackgroundJob
from app.db.models.eval_run import (
    ArmRole,
    ArmSource,
    EvalRun,
    EvalRunArm,
    EvalRunCase,
    EvalRunStatus,
)
from app.db.models.skill_check import (
    AgentState,
    CheckSource,
    CheckStatus,
    SkillCheck,
    SkillCheckAgent,
)
from app.repositories import (
    dataset_repo,
    skill_check_repo,
    skill_proposal_repo,
    skill_usage_repo,
    skill_version_repo,
)
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.schemas.resource_usage import ProposalDecision
from app.schemas.skill_check import (
    SkillCheckApply,
    SkillCheckFork,
    SkillCheckStart,
    SkillTestSetStart,
)
from app.schemas.skill_usage import SkillUseRecord
from app.schemas.skill_version import SkillVersionCreate
from app.services import skill_check as skill_check_module
from app.services.dataset import DatasetService
from app.services.skill_check import SkillCheckService
from app.services.skill_proposal import SkillProposalService
from app.services.skill_versions import SkillVersionService
from tests.integration.test_authoring import _owner
from tests.integration.test_skill_bindings import _serving
from tests.integration.test_skill_checks import (
    NEW,
    FakeEvals,
    Lab,
    Outcome,
    _lab,
    _run_to_end,
    _start,
)

pytestmark = pytest.mark.anyio


def _deny(monkeypatch: pytest.MonkeyPatch, perm: Perm, *agents: uuid.UUID) -> None:
    """The caller holds `perm` on every agent but these."""
    real = skill_check_module.accessible_ids

    async def accessible(db, ctx, rows, wanted, **kwargs):
        found = await real(db, ctx, rows, wanted, **kwargs)
        return found - set(agents) if wanted is perm else found

    monkeypatch.setattr(skill_check_module, "accessible_ids", accessible)


async def _proposal(
    db: AsyncSession, lab: Lab, *, resources: dict[str, str] | None = None, **values: Any
):
    return await skill_proposal_repo.create(
        db,
        organization_id=lab.ctx.organization_id,
        skill_id=lab.skill.id,
        agent_id=lab.a.id,
        conversation_id=None,
        name=lab.skill.name,
        description=lab.skill.description,
        content="An order number counts as a receipt.",
        resources=resources or {},
        base_version=lab.skill.version,
        base_version_id=values.pop("base_version_id", lab.skill.latest_version_id),
        fork_id=values.pop("fork_id", None),
    )


async def _finished(
    db, lab: Lab, evals: FakeEvals, outcomes: dict, *, proposal: Any = None, **start: Any
):
    service = SkillCheckService(db)
    begin = SkillCheckStart(proposal_id=proposal.id) if proposal is not None else _start(**start)
    check = await service.start(lab.ctx, lab.skill.id, begin)
    evals.outcomes = outcomes
    await _run_to_end(service, evals, lab, check.id)
    return service, check


class TestWhatCannotBeChecked:
    async def test_a_fork_the_skill_does_not_have_is_refused(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)

        with pytest.raises(BadRequestError):
            await SkillCheckService(db).estimate(
                lab.ctx, lab.skill.id, _start(fork_id=uuid.uuid4())
            )

    async def test_a_proposal_that_is_not_waiting_or_is_for_another_line(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        service = SkillCheckService(db)
        proposal = await _proposal(db, lab)

        with pytest.raises(NotFoundError):
            await service.estimate(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=uuid.uuid4()))
        with pytest.raises(BadRequestError):
            await service.estimate(
                lab.ctx,
                lab.skill.id,
                SkillCheckStart(proposal_id=proposal.id, fork_id=lab.fork_id),
            )

    async def test_a_proposal_written_against_an_older_version_is_refused(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        proposal = await _proposal(db, lab)
        await SkillVersionService(db).edit(
            lab.ctx,
            lab.skill.id,
            SkillVersionCreate(
                fork_id=None,
                base_version_id=lab.skill.latest_version_id,
                description=lab.skill.description,
                content="moved on",
            ),
        )

        with pytest.raises(ConcurrentChangeError):
            await SkillCheckService(db).estimate(
                lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id)
            )

    async def test_agents_the_caller_may_not_run_or_see(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        _deny(monkeypatch, Perm.AGENTS_RUN, lab.c.id)
        real = skill_check_module.accessible_ids

        async def accessible(db, ctx, rows, wanted, **kwargs):
            found = await real(db, ctx, rows, wanted, **kwargs)
            return found - {lab.b.id} if wanted is Perm.AGENTS_VIEW else found

        monkeypatch.setattr(skill_check_module, "accessible_ids", accessible)

        check = await SkillCheckService(db).start(lab.ctx, lab.skill.id, _start())

        rows = {row.agent.name: row for row in check.agents}
        assert rows["C"].unknown_reason == "no_access"
        assert "B" not in rows and check.hidden == 1
        assert lab.c.id not in [agent for agent, _ in evals.started]

    async def test_an_agent_with_no_questions_at_all_is_unknown(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        test_set = await dataset_repo.for_skill(
            db, lab.skill.id, organization_id=lab.ctx.organization_id
        )
        assert test_set is not None
        test_set.case_count = 0
        await db.flush()

        estimate = await SkillCheckService(db).estimate(lab.ctx, lab.skill.id, _start())

        rows = {row.agent.name: row for row in estimate.agents}
        assert rows["C"].unknown_reason == "no_questions"
        assert rows["A"].unknown_reason == "no_questions"

    async def test_an_estimate_the_eval_engine_refuses_is_no_access(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)

        async def refuse(_self, _ctx, agent_id, _request, **_):
            raise NotFoundError(message="Dataset not found")

        monkeypatch.setattr(skill_check_module.EvalRunService, "estimate", refuse)

        estimate = await SkillCheckService(db).estimate(lab.ctx, lab.skill.id, _start())

        assert {row.unknown_reason for row in estimate.agents} == {"no_access"}

    async def test_a_check_the_organization_cannot_afford_or_nobody_can_run(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals(org_left=Decimal("0.01")).install(monkeypatch)
        service = SkillCheckService(db)

        with pytest.raises(BadRequestError, match="budget"):
            await service.start(lab.ctx, lab.skill.id, _start())
        FakeEvals(agent_left=Decimal("0.01")).install(monkeypatch)
        with pytest.raises(BadRequestError, match="No agent"):
            await service.start(lab.ctx, lab.skill.id, _start())

    async def test_only_the_agents_named_are_checked(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)

        check = await SkillCheckService(db).start(
            lab.ctx, lab.skill.id, _start(), source=CheckSource.SESSION, only=[lab.a.id]
        )

        assert [row.agent.name for row in check.agents] == ["A"]


class TestRunning:
    async def test_a_proposals_files_are_measured_and_forked_as_they_would_ship(
        self, db, monkeypatch
    ):
        """A change's files replace or join the line's; the check serves that set, and a
        fork made from it holds the same set - nothing ships that was not measured."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await _proposal(db, lab, resources={"limits.md": "Up to $500."})
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id))
        stored = await skill_check_repo.get(db, check.id, organization_id=lab.ctx.organization_id)
        assert stored is not None and stored.candidate_resources is not None
        assert {name: item["content"] for name, item in stored.candidate_resources.items()} == {
            "a.md": "first",
            "limits.md": "Up to $500.",
        }
        evals.outcomes = {lab.a.id: Outcome(fixed=1), lab.b.id: Outcome(broken=1)}
        await _run_to_end(service, evals, lab, check.id)

        forked = await service.fork(lab.ctx, lab.skill.id, check.id, SkillCheckFork(name="online"))

        assert forked.fork.latest is not None
        version = await skill_version_repo.get_version(
            db,
            forked.fork.latest.id,
            organization_id=lab.ctx.organization_id,
            skill_id=lab.skill.id,
        )
        assert version is not None
        assert await SkillVersionService(db).files_of(version) == {
            "a.md": "first",
            "limits.md": "Up to $500.",
        }
        assert version.source == "workspace"

    async def test_a_run_still_going_leaves_its_agent_running(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())

        await service.advance(check.id, lab.ctx.organization_id)

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert read.status is CheckStatus.RUNNING
        assert {row.state for row in read.agents} == {AgentState.RUNNING}

    async def test_a_starter_who_may_no_longer_act_leaves_the_rest_unknown(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        row = await skill_check_repo.get(db, check.id, organization_id=lab.ctx.organization_id)
        assert row is not None
        row.created_by_user_id = None
        await db.flush()

        await service.advance(check.id, lab.ctx.organization_id)

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert {r.unknown_reason for r in read.agents} == {"failed"}

    async def test_a_dataset_gone_before_its_stage_is_judged_on_the_first(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(
            lab.ctx, lab.skill.id, SkillCheckStart(candidate=NEW, mode="thorough")
        )
        own = await dataset_repo.for_agent(db, lab.a.id, organization_id=lab.ctx.organization_id)
        monkeypatch.setattr(
            skill_check_module.dataset_repo,
            "get",
            _without(skill_check_module.dataset_repo.get, own[0].id),
        )
        evals.outcomes = {lab.a.id: Outcome(fixed=1)}

        read = await _run_to_end(service, evals, lab, check.id)

        assert next(row for row in read.agents if row.agent.name == "A").state == "better"

    async def test_the_sweep_and_a_settled_run_carry_a_check_on(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.finish_all()

        assert await service.sweep() >= 1
        run_id = next(iter(evals.runs))
        await service.after_run(lab.ctx.organization_id, run_id)
        await service.after_run(lab.ctx.organization_id, uuid.uuid4())

        queued = await db.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.kind == "advance-skill-check")
        )
        assert queued >= 1
        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert read.status is CheckStatus.RUNNING

    async def test_a_starter_who_lost_sight_of_the_runs_leaves_the_agent_unknown(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())

        async def refuse(_self, _ctx, _run_id, **_):
            raise AuthorizationError(message="Reading runs needs runs:view")

        monkeypatch.setattr(skill_check_module.EvalRunService, "compare", refuse)
        evals.finish_all()
        await service.advance(check.id, lab.ctx.organization_id)

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert {row.unknown_reason for row in read.agents} == {"no_access"}

    async def test_a_check_that_is_not_there(self, db, monkeypatch):
        lab = await _lab(db)

        with pytest.raises(NotFoundError):
            await SkillCheckService(db).read(lab.ctx, lab.skill.id, uuid.uuid4())

    async def test_a_lines_checks_are_listed_newest_first(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        service = SkillCheckService(db)
        first = await service.start(lab.ctx, lab.skill.id, _start())
        await service.cancel(lab.ctx, lab.skill.id, first.id)
        second = await service.start(lab.ctx, lab.skill.id, _start())
        await service.start(lab.ctx, lab.skill.id, _start(fork_id=lab.fork_id))

        listed = await service.list_checks(lab.ctx, lab.skill.id, fork_id=None, skip=0, limit=10)

        assert listed.total == 2
        assert {item.id for item in listed.items} == {first.id, second.id}


def _without(get, gone: uuid.UUID):
    async def lookup(db, dataset_id, *, organization_id):
        return (
            None
            if dataset_id == gone
            else await get(db, dataset_id, organization_id=organization_id)
        )

    return lookup


class TestDecidingRefusals:
    async def test_a_check_not_running_cannot_be_cancelled_and_one_settled_run_is_left(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        next(iter(evals.runs.values())).status = EvalRunStatus.COMPLETED.value

        await service.cancel(lab.ctx, lab.skill.id, check.id)

        assert [run.status for run in evals.runs.values()].count("completed") == 1
        with pytest.raises(AlreadyExistsError):
            await service.cancel(lab.ctx, lab.skill.id, check.id)

    async def test_a_running_or_decided_check_is_not_decided(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        running = await service.start(lab.ctx, lab.skill.id, _start())

        with pytest.raises(ConcurrentChangeError):
            await service.apply(lab.ctx, lab.skill.id, running.id, SkillCheckApply())
        evals.outcomes = {lab.a.id: Outcome(fixed=1)}
        await _run_to_end(service, evals, lab, running.id)
        await service.apply(lab.ctx, lab.skill.id, running.id, SkillCheckApply())
        with pytest.raises(AlreadyExistsError):
            await service.apply(lab.ctx, lab.skill.id, running.id, SkillCheckApply())

    async def test_a_change_that_helped_nobody_is_not_applied(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(db, lab, evals, {})

        with pytest.raises(BadRequestError):
            await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply())

    async def test_an_agent_that_joined_the_line_since_must_be_checked_too(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(db, lab, evals, {lab.a.id: Outcome(fixed=1)})
        await _serving(db, lab.ctx, "Newcomer", dict(lab.a.draft_spec))

        with pytest.raises(ConcurrentChangeError, match="changed since the check"):
            await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply())

    async def test_pinning_needs_publishing_the_worse_agents(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(
            db, lab, evals, {lab.a.id: Outcome(fixed=1), lab.b.id: Outcome(broken=1)}
        )
        _deny(monkeypatch, Perm.AGENTS_PUBLISH, lab.b.id)

        with pytest.raises(AuthorizationError) as refused:
            await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply(pin_worse=True))
        assert refused.value.details == {"agents": ["B"], "hidden": 0}

    async def test_a_worse_agent_reading_through_a_specialist_is_changed_in_the_builder(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(
            db, lab, evals, {lab.a.id: Outcome(fixed=1), lab.b.id: Outcome(broken=1)}
        )
        rows = await skill_check_repo.list_agents(
            db, [check.id], organization_id=lab.ctx.organization_id
        )
        worse = next(row for row in rows if row.agent_id == lab.b.id)
        worse.via_specialist = "reader"
        await db.flush()

        with pytest.raises(BadRequestError, match="specialist"):
            await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply(pin_worse=True))

    async def test_forking_moves_only_the_agents_the_caller_may_edit(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await _proposal(db, lab)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id))
        evals.outcomes = {
            lab.a.id: Outcome(fixed=1),
            lab.c.id: Outcome(fixed=1),
            lab.b.id: Outcome(broken=1),
        }
        await _run_to_end(service, evals, lab, check.id)
        _deny(monkeypatch, Perm.AGENTS_EDIT, lab.c.id)

        forked = await service.fork(lab.ctx, lab.skill.id, check.id, SkillCheckFork(name="online"))

        assert [agent.name for agent in forked.moved] == ["A"]
        await db.refresh(proposal)
        assert proposal.status == "applied"

    async def test_discarding_a_running_check_stops_it_and_its_proposal(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await _proposal(db, lab)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id))

        discarded = await service.discard(lab.ctx, lab.skill.id, check.id)

        assert discarded.status is CheckStatus.DISCARDED
        await db.refresh(proposal)
        assert proposal.status == "discarded"

    async def test_a_proposal_decided_elsewhere_is_left_alone(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await _proposal(db, lab)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id))
        await SkillProposalService(db).discard(
            lab.ctx, proposal.id, ProposalDecision(revision=proposal.revision)
        )

        discarded = await service.discard(lab.ctx, lab.skill.id, check.id)

        assert discarded.status is CheckStatus.DISCARDED

    async def test_the_gate_refuses_a_check_that_helped_nobody(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await _proposal(db, lab)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id))
        await _run_to_end(service, evals, lab, check.id)

        with pytest.raises(BadRequestError, match="does not allow"):
            await service.passed_for(lab.ctx, proposal, check.id)


class TestWhatTheCheckMeasuredIsWhatShips:
    async def test_a_proposal_rewritten_after_its_check_is_not_applied(self, db, monkeypatch):
        """An agent's next turn rewrites its waiting change in place; the check
        measured the earlier text, so applying from it would ship an unchecked one."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await _proposal(db, lab)
        service, check = await _finished(
            db,
            lab,
            evals,
            {lab.a.id: Outcome(fixed=1), lab.b.id: Outcome(broken=1)},
            proposal=proposal,
        )
        proposal.content = "Refund everything, receipt or not."
        await db.flush()

        with pytest.raises(ConcurrentChangeError, match="rewritten"):
            await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply())
        with pytest.raises(ConcurrentChangeError, match="rewritten"):
            await service.fork(lab.ctx, lab.skill.id, check.id, SkillCheckFork(name="x"))

    async def test_a_check_of_the_same_text_is_not_a_check_of_the_proposal(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await _proposal(db, lab)
        service, check = await _finished(db, lab, evals, {lab.a.id: Outcome(fixed=1)})

        with pytest.raises(BadRequestError, match="Check this change"):
            await SkillProposalService(db).apply(
                lab.ctx,
                proposal.id,
                ProposalDecision(revision=proposal.revision, check_id=check.id),
            )
        await db.refresh(proposal)
        assert proposal.status == "pending"

    async def test_one_change_is_checked_once_at_a_time(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        proposal = await _proposal(db, lab)
        service = SkillCheckService(db)
        first = await service.start(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id))

        with pytest.raises(AlreadyExistsError) as again:
            await service.start(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id))
        assert again.value.details == {"check_id": first.id}
        proposal.content = "A rewritten change is a new one to check."
        await db.flush()
        second = await service.start(
            lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id)
        )
        assert second.id != first.id

    async def test_a_change_that_hurt_nobody_is_not_forked(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(db, lab, evals, {lab.a.id: Outcome(fixed=1)})

        with pytest.raises(BadRequestError, match="does not offer"):
            await service.fork(lab.ctx, lab.skill.id, check.id, SkillCheckFork(name="x"))

    async def test_an_agent_published_again_since_the_check_must_be_checked_again(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(db, lab, evals, {lab.a.id: Outcome(fixed=1)})
        rows = await skill_check_repo.list_agents(
            db, [check.id], organization_id=lab.ctx.organization_id
        )
        row = next(item for item in rows if item.agent_id == lab.b.id)
        row.agent_version = (row.agent_version or 0) + 7
        await db.flush()

        with pytest.raises(ConcurrentChangeError, match="published again") as refused:
            await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply())
        assert refused.value.details == {"agents": ["B"], "hidden": 0}

    async def test_a_failed_write_takes_the_pins_back_with_it(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(
            db, lab, evals, {lab.a.id: Outcome(fixed=1), lab.b.id: Outcome(broken=1)}
        )

        async def refuse(*_args, **_kwargs):
            raise ConcurrentChangeError(message="moved")

        monkeypatch.setattr(service.versions, "edit", refuse)
        with pytest.raises(ConcurrentChangeError):
            async with db.begin_nested():
                await service.apply(
                    lab.ctx, lab.skill.id, check.id, SkillCheckApply(pin_worse=True)
                )

        await db.refresh(lab.b)
        assert lab.b.draft_spec.get("skill_bindings", []) == []

    async def test_a_stranger_to_the_skill_learns_nothing_about_its_checks(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(
            db, lab, evals, {lab.a.id: Outcome(fixed=1), lab.b.id: Outcome(broken=1)}
        )
        stranger = await _owner(db)

        with pytest.raises(NotFoundError):
            await service.apply(stranger, lab.skill.id, check.id, SkillCheckApply())

    async def test_a_dataset_the_reader_may_not_see_is_not_named(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        _deny_datasets(monkeypatch)

        check = await SkillCheckService(db).start(lab.ctx, lab.skill.id, _start())

        assert {stage.dataset_name for row in check.agents for stage in row.stages} == {None}


def _deny_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    real = skill_check_module.accessible_ids

    async def accessible(db, ctx, rows, wanted, **kwargs):
        return (
            set() if wanted is Perm.DATASETS_VIEW else await real(db, ctx, rows, wanted, **kwargs)
        )

    monkeypatch.setattr(skill_check_module, "accessible_ids", accessible)


class TestSampleAndTestSet:
    async def test_a_quick_check_asks_the_questions_whose_answers_loaded_the_skill(self, db):
        lab = await _lab(db)
        ctx = lab.ctx
        datasets = DatasetService(db)
        own = await datasets.create(ctx, DatasetCreate(name=f"a-{uuid.uuid4().hex[:6]}"))
        for text in ("Lost receipt, order 1", "Opening hours?", "Receipt gone, order 2"):
            await datasets.add_case(
                ctx, own.id, DatasetCaseCreate(input=text, reference_answer="y")
            )
        dataset = await dataset_repo.get(db, own.id, organization_id=ctx.organization_id)
        assert dataset is not None
        version = await dataset_repo.get_version(
            db, dataset.id, dataset.latest_version, organization_id=ctx.organization_id
        )
        assert version is not None
        cases = await dataset_repo.list_cases(
            db, version.id, organization_id=ctx.organization_id, limit=None
        )
        run = EvalRun(
            organization_id=ctx.organization_id,
            agent_id=lab.a.id,
            dataset_id=dataset.id,
            dataset_version_id=version.id,
            created_by_user_id=ctx.user_id,
            status=EvalRunStatus.COMPLETED.value,
            scoring={},
            scoring_hash="a" * 64,
            estimate_usd=Decimal("0.1"),
        )
        db.add(run)
        await db.flush()
        arm = EvalRunArm(
            organization_id=ctx.organization_id,
            eval_run_id=run.id,
            role=ArmRole.CANDIDATE.value,
            position=0,
            source=ArmSource.VERSION.value,
            model_label="m",
            spec_hash="v",
        )
        db.add(arm)
        await db.flush()
        now = datetime.now(UTC)
        for index, case in enumerate(cases):
            answer = AgentRun(
                id=uuid.uuid4(),
                organization_id=ctx.organization_id,
                agent_id=lab.a.id,
                surface="eval",
                status="completed",
                started_at=now,
            )
            db.add(answer)
            await db.flush()
            db.add(
                EvalRunCase(
                    organization_id=ctx.organization_id,
                    eval_run_id=run.id,
                    arm_id=arm.id,
                    case_id=case.case_id,
                    case_revision_id=case.id,
                    position=index,
                    agent_run_id=answer.id,
                    ended_at=now - timedelta(minutes=index),
                )
            )
            if "eceipt" in case.input:
                await skill_usage_repo.record_uses(
                    db,
                    [
                        SkillUseRecord(
                            agent_id=lab.a.id,
                            skill_id=lab.skill.id,
                            skill_version_id=None,
                            loaded=True,
                            resource_reads=0,
                            workspace_reads=0,
                        )
                    ],
                    organization_id=ctx.organization_id,
                    run_id=answer.id,
                    started_at=now,
                )
        await db.flush()

        picked = await SkillCheckService(db)._sample(
            ctx, lab.skill, lab.a.id, dataset, {"receipt", "order"}
        )

        loaded = {case.case_id for case in cases if "eceipt" in case.input}
        assert set(picked) == loaded
        one = sorted(loaded, key=str)[:1]
        assert (
            await SkillCheckService(db)._sample(ctx, lab.skill, lab.a.id, dataset, {"receipt"}, one)
            == one
        )

    async def test_the_skills_test_questions_can_start_from_recent_answers(self, db, monkeypatch):
        lab = await _lab(db)
        good, bad = uuid.uuid4(), uuid.uuid4()
        pack = SimpleNamespace(
            runs=[SimpleNamespace(run_id=good, rating=1), SimpleNamespace(run_id=bad, rating=-1)]
        )
        added: dict[str, Any] = {}

        async def for_skill(_self, _ctx, _skill_id, **_):
            return pack

        async def answers(_db, run_ids, *, organization_id):
            return {run_id: uuid.uuid4() for run_id in run_ids}

        async def add(_self, _ctx, dataset_id, message_ids, **kwargs):
            added.update(kwargs["answer_as"])
            return None, len(message_ids)

        from app.services.authoring_evidence import EvidenceService

        monkeypatch.setattr(EvidenceService, "for_skill", for_skill)
        monkeypatch.setattr(skill_check_module.conversation_repo, "last_answers_of_runs", answers)
        monkeypatch.setattr(DatasetService, "add_from_messages", add)
        test_set = await dataset_repo.for_skill(
            db, lab.skill.id, organization_id=lab.ctx.organization_id
        )
        assert test_set is not None
        test_set.skill_id = None
        await db.flush()

        await SkillCheckService(db).create_test_set(
            lab.ctx, lab.skill.id, SkillTestSetStart(from_evidence=True)
        )

        assert sorted(added.values()) == ["counter_example", "reference_answer"]

    async def test_no_recent_answers_leave_the_test_questions_empty(self, db, monkeypatch):
        lab = await _lab(db)

        async def for_skill(_self, _ctx, _skill_id, **_):
            return SimpleNamespace(runs=[])

        from app.services.authoring_evidence import EvidenceService

        monkeypatch.setattr(EvidenceService, "for_skill", for_skill)
        test_set = await dataset_repo.for_skill(
            db, lab.skill.id, organization_id=lab.ctx.organization_id
        )
        assert test_set is not None
        test_set.skill_id = None
        await db.flush()

        created = await SkillCheckService(db).create_test_set(
            lab.ctx, lab.skill.id, SkillTestSetStart(from_evidence=True)
        )

        assert created.case_count == 0


def test_rows_say_what_they_are() -> None:
    check = SkillCheck(id=uuid.uuid4(), skill_id=uuid.uuid4(), fork_id=None, status="running")
    row = SkillCheckAgent(check_id=check.id, agent_id=uuid.uuid4(), state="better")

    assert "main" in repr(check) and "better" in repr(row)
    assert "fork=" in repr(SkillCheck(fork_id=uuid.uuid4()))
