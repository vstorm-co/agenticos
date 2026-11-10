"""The refusals and corners of a skill check: a stale or foreign proposal, agents a
person may not run or see, a run that has not settled, a line that gained an
agent, a pin nobody may publish, and the skill's questions taken from evidence."""

import asyncio
import contextlib
import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent_run import AgentRun
from app.db.models.background_job import BackgroundJob
from app.db.models.conversation import Conversation
from app.db.models.dataset import Dataset, DatasetCase
from app.db.models.eval_run import (
    ArmRole,
    ArmSource,
    EvalRun,
    EvalRunArm,
    EvalRunCase,
    EvalRunStatus,
)
from app.db.models.organization import OrganizationMember
from app.db.models.skill import Skill
from app.db.models.skill_check import (
    AgentState,
    CheckOutcome,
    CheckSource,
    CheckStatus,
    CheckVerdict,
    SkillCheck,
    SkillCheckAgent,
)
from app.repositories import (
    dataset_repo,
    eval_run_repo,
    skill_check_repo,
    skill_proposal_repo,
    skill_usage_repo,
    skill_version_repo,
)
from app.schemas.api_key import ApiKeyCreate
from app.schemas.authoring import ProposalCheck
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.schemas.resource_usage import ProposalDecision
from app.schemas.skill import SkillUpdate
from app.schemas.skill_check import (
    SkillCheckApply,
    SkillCheckFork,
    SkillCheckList,
    SkillCheckStart,
    SkillTestSetStart,
)
from app.schemas.skill_usage import SkillUseRecord
from app.schemas.skill_version import SkillVersionCreate
from app.services import skill_check as skill_check_module
from app.services.api_key import ApiKeyService
from app.services.authoring import AuthoringService
from app.services.dataset import DatasetService
from app.services.notifications import NotificationService
from app.services.skill_agents import SkillAgentService
from app.services.skill_check import SkillCheckService
from app.services.skill_proposal import SkillProposalService
from app.services.skill_versions import SkillVersionService
from app.services.skills import SkillService
from tests.integration.test_authoring import _owner
from tests.integration.test_skill_bindings import _serving, _with_specialist
from tests.integration.test_skill_checks import (
    NEW,
    FakeEvals,
    Lab,
    Outcome,
    _follow_publishes,
    _lab,
    _run_to_end,
    _start,
    _statuses,
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
    db: AsyncSession,
    lab: Lab,
    *,
    resources: dict[str, str] | None = None,
    source: str | None = None,
    **values: Any,
):
    proposal = await skill_proposal_repo.create(
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
    if source is not None:
        await skill_proposal_repo.annotate(db, proposal=proposal, values={"source": source})
    return proposal


async def _version(db: AsyncSession, lab: Lab, version_id: uuid.UUID):
    version = await skill_version_repo.get_version(
        db, version_id, organization_id=lab.ctx.organization_id, skill_id=lab.skill.id
    )
    assert version is not None
    return version


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

    async def test_a_check_the_organization_cannot_afford_is_refused(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals(org_left=Decimal("0.01")).install(monkeypatch)
        service = SkillCheckService(db)

        with pytest.raises(BadRequestError, match="budget"):
            await service.start(lab.ctx, lab.skill.id, _start())

    async def test_an_agent_and_its_specialist_on_one_line_are_one_agent_to_check(
        self, db, monkeypatch
    ):
        """An agent's eval answers through the agent and its specialists at once, so two
        readers of one line in one agent are checked, judged and decided as one."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        real = SkillAgentService.line_agents

        async def per_reader(self, skill, fork_id):
            found = await real(self, skill, fork_id)
            twice = [user for user in found if user.agent.id == lab.a.id]
            specialist = [replace(user, via_specialist="reader") for user in twice]
            return [*specialist, *found]

        monkeypatch.setattr(SkillAgentService, "line_agents", per_reader)
        service = SkillCheckService(db)

        check = await service.start(lab.ctx, lab.skill.id, _start())

        assert [row.agent.name for row in check.agents].count("A") == 1
        a = next(row for row in check.agents if row.agent.name == "A")
        assert a.via_specialist is None
        evals.outcomes = {lab.a.id: Outcome(fixed=1)}
        read = await _run_to_end(service, evals, lab, check.id)
        assert read.verdict is CheckVerdict.PASSED
        await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply())

    async def test_an_agent_only_a_specialist_of_reads_the_skill_through_is_checked_once(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        real = SkillAgentService.line_agents

        async def specialists_only(self, skill, fork_id):
            found = await real(self, skill, fork_id)
            return [
                replace(user, via_specialist=name)
                for user in found
                for name in ("reader", "writer")
            ]

        monkeypatch.setattr(SkillAgentService, "line_agents", specialists_only)

        estimate = await SkillCheckService(db).estimate(lab.ctx, lab.skill.id, _start())

        names = [row.agent.name for row in estimate.agents]
        assert sorted(names) == ["A", "B", "C"]
        assert {row.via_specialist for row in estimate.agents} == {"reader"}

    async def test_a_published_agent_and_its_specialist_are_reached_as_one_agent(
        self, db, monkeypatch
    ):
        """Read off real specs: an agent whose own binding and specialist both follow main
        is one agent reached through itself; one that delegates the skill is reached
        through its specialist."""
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        both = await _serving(
            db, lab.ctx, "Both", _with_specialist(dict(lab.a.draft_spec), lab.skill)
        )
        own = {**dict(lab.a.draft_spec), "skill_ids": [], "skill_bindings": []}
        delegates = await _serving(db, lab.ctx, "Delegates", _with_specialist(own, lab.skill))

        reached = await SkillAgentService(db).line_agents(lab.skill, None)
        estimate = await SkillCheckService(db).estimate(lab.ctx, lab.skill.id, _start())

        assert [user.via_specialist for user in reached if user.agent.id == both.id] == [None]
        assert [user.via_specialist for user in reached if user.agent.id == delegates.id] == [
            "billing"
        ]
        rows = {row.agent.name: row.via_specialist for row in estimate.agents}
        assert (rows["Both"], rows["Delegates"]) == (None, "billing")
        assert [row.agent.name for row in estimate.agents].count("Both") == 1

    async def test_only_the_agents_named_are_checked(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)

        check = await SkillCheckService(db).start(
            lab.ctx, lab.skill.id, _start(), source=CheckSource.SESSION, only=[lab.a.id]
        )

        assert [row.agent.name for row in check.agents] == ["A"]


@pytest.mark.anyio
async def test_a_fork_change_checked_on_one_agent_is_served_on_its_fork(db) -> None:
    """A change written for a fork names the fork, so the agent following that fork reads
    it in the candidate arm instead of its stored text."""
    lab = await _lab(db)
    fork = await skill_version_repo.get_fork(
        db, lab.fork_id, organization_id=lab.ctx.organization_id, skill_id=lab.skill.id
    )
    assert fork is not None
    proposal = await _proposal(db, lab, base_version_id=fork.base_version_id, fork_id=lab.fork_id)
    datasets = DatasetService(db)
    dataset = await datasets.create(lab.ctx, DatasetCreate(name="fork-cases"))
    await datasets.add_case(
        lab.ctx,
        dataset.id,
        DatasetCaseCreate(input="Q", checks=[{"type": "contains", "value": "x"}]),
    )

    started = await AuthoringService(db).check_skill(
        lab.ctx,
        lab.skill.id,
        ProposalCheck(dataset_id=dataset.id, agent_id=lab.on_fork.id, proposal_id=proposal.id),
    )

    [candidate] = [
        arm
        for arm in await eval_run_repo.list_arms(
            db, [started.id], organization_id=lab.ctx.organization_id
        )
        if arm.role == "candidate"
    ]
    assert candidate.skill_bodies is not None
    assert candidate.skill_bodies[str(lab.skill.id)]["fork_id"] == str(lab.fork_id)


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

    async def test_a_library_update_drops_the_files_the_bundle_no_longer_has(self, db, monkeypatch):
        """A library update's files are the bundled skill's whole set: the check serves
        that set, and applying it leaves no file behind that the bundle removed."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await _proposal(
            db, lab, resources={"limits.md": "Up to $500."}, source="library"
        )
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id))
        stored = await skill_check_repo.get(db, check.id, organization_id=lab.ctx.organization_id)
        assert stored is not None and stored.candidate_resources is not None
        assert set(stored.candidate_resources) == {"limits.md"}
        evals.outcomes = {lab.a.id: Outcome(fixed=1)}
        await _run_to_end(service, evals, lab, check.id)

        applied = await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply())

        assert await SkillVersionService(db).files_of(
            await _version(db, lab, applied.version.id)
        ) == {"limits.md": "Up to $500."}

    @pytest.mark.parametrize(
        ("bundled", "left"), [({}, {}), ({"a.md": "second"}, {"a.md": "second"})]
    )
    async def test_an_applied_library_update_leaves_exactly_the_bundles_files(
        self, db, monkeypatch, bundled: dict[str, str], left: dict[str, str]
    ):
        lab = await _lab(db)
        proposal = await _proposal(db, lab, resources=bundled, source="library")
        before = lab.skill.version

        await SkillProposalService(db).apply(
            lab.ctx, proposal.id, ProposalDecision(revision=proposal.revision), checked=True
        )

        await db.refresh(lab.skill)
        assert lab.skill.version == before + 1
        assert lab.skill.latest_version_id is not None
        version = await _version(db, lab, lab.skill.latest_version_id)
        assert await SkillVersionService(db).files_of(version) == left

    async def test_a_fork_of_a_library_update_holds_only_the_bundles_files(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await _proposal(db, lab, source="library")
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id))
        evals.outcomes = {lab.a.id: Outcome(fixed=1), lab.b.id: Outcome(broken=1)}
        await _run_to_end(service, evals, lab, check.id)

        forked = await service.fork(lab.ctx, lab.skill.id, check.id, SkillCheckFork(name="online"))

        assert forked.fork.latest is not None
        version = await _version(db, lab, forked.fork.latest.id)
        assert await SkillVersionService(db).files_of(version) == {}

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

    async def test_one_check_that_cannot_be_carried_on_does_not_hold_back_the_others(
        self, db, monkeypatch
    ):
        """The sweep queues one advance per check and does none of their work itself, so
        a check whose advance keeps failing fails only its own job."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        broken = await service.start(lab.ctx, lab.skill.id, _start())
        healthy = await service.start(lab.ctx, lab.skill.id, _start(fork_id=lab.fork_id))
        stale = await skill_check_repo.get(db, broken.id, organization_id=lab.ctx.organization_id)
        assert stale is not None
        stale.created_at = stale.created_at - timedelta(days=2)
        await db.flush()

        async def fail(_self, _check):
            raise RuntimeError("cannot settle")

        monkeypatch.setattr(SkillCheckService, "_expire", fail)

        assert await service.sweep() >= 2
        queued = {
            job.payload["check_id"]
            for job in (
                await db.execute(
                    select(BackgroundJob).where(BackgroundJob.kind == "advance-skill-check")
                )
            ).scalars()
        }
        assert {str(broken.id), str(healthy.id)} <= queued
        with pytest.raises(RuntimeError):
            await service.advance(broken.id, lab.ctx.organization_id)
        evals.finish_all()
        await service.advance(healthy.id, lab.ctx.organization_id)
        assert (await service.read(lab.ctx, lab.skill.id, healthy.id)).status is CheckStatus.DONE

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


def _record(into: list[object]):
    async def record(_self, run):
        into.append(run)

    return record


async def _live_runs(db: AsyncSession, check_id: uuid.UUID) -> list[str]:
    """The statuses of a check's eval runs that are still going, read from the table."""
    rows = await db.execute(
        select(EvalRun.status)
        .join(
            SkillCheckAgent,
            (SkillCheckAgent.skill_set_run_id == EvalRun.id)
            | (SkillCheckAgent.dataset_run_id == EvalRun.id),
        )
        .where(
            SkillCheckAgent.check_id == check_id,
            EvalRun.status.in_([EvalRunStatus.QUEUED.value, EvalRunStatus.RUNNING.value]),
        )
    )
    return list(rows.scalars())


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
        settled = await db.get(EvalRun, next(iter(evals.runs)))
        assert settled is not None
        settled.status = EvalRunStatus.COMPLETED.value
        await db.flush()

        await service.cancel(lab.ctx, lab.skill.id, check.id)

        assert (await _statuses(db, evals)).count("completed") == 1
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

    async def test_a_finished_check_the_line_moved_past_does_not_block_a_new_one(
        self, db, monkeypatch
    ):
        """A finished check that can still be decided is the change's check; one the line
        moved past can never be decided, so the change may be checked again."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await _proposal(db, lab)
        service, check = await _finished(
            db, lab, evals, {lab.a.id: Outcome(fixed=1)}, proposal=proposal
        )

        with pytest.raises(AlreadyExistsError):
            await service.start(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id))
        rows = await skill_check_repo.list_agents(
            db, [check.id], organization_id=lab.ctx.organization_id
        )
        moved = next(item for item in rows if item.agent_id == lab.c.id)
        moved.agent_version = (moved.agent_version or 0) + 3
        await db.flush()

        again = await service.start(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id))
        assert again.id != check.id

    async def test_a_change_decided_elsewhere_since_its_check_is_not_decided_again(
        self, db, monkeypatch
    ):
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
        await SkillProposalService(db).discard(
            lab.ctx, proposal.id, ProposalDecision(revision=proposal.revision)
        )

        with pytest.raises(ConcurrentChangeError, match="decided elsewhere"):
            await service.fork(lab.ctx, lab.skill.id, check.id, SkillCheckFork(name="x"))

    async def test_a_stale_check_whose_starter_lost_sight_of_the_runs_still_ends(
        self, db, monkeypatch
    ):
        """Ending a stale check is the platform stopping its own runs; a starter who may
        no longer read them cannot keep the check running."""
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        finished: list[object] = []
        monkeypatch.setattr(NotificationService, "eval_run_finished", _record(finished))
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        row = await skill_check_repo.get(db, check.id, organization_id=lab.ctx.organization_id)
        assert row is not None
        row.created_at = row.created_at - timedelta(days=2)
        member = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == lab.ctx.organization_id,
                OrganizationMember.user_id == lab.ctx.user_id,
            )
        )
        assert member is not None
        member.role = OrgRoleName.VIEWER.value
        await db.flush()

        await service.advance(check.id, lab.ctx.organization_id)

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert read.status is CheckStatus.DONE
        assert await _live_runs(db, check.id) == []
        assert len(finished) == 3

    async def test_a_check_running_for_a_day_is_ended_when_it_is_next_advanced(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        evals = FakeEvals(refuse_start={lab.c.id})
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        row = await skill_check_repo.get(db, check.id, organization_id=lab.ctx.organization_id)
        assert row is not None
        row.created_at = row.created_at - timedelta(days=2)
        await db.flush()

        await service.advance(check.id, lab.ctx.organization_id)

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert read.status is CheckStatus.DONE
        reasons = {item.agent.name: item.unknown_reason for item in read.agents}
        assert reasons == {"A": "failed", "B": "failed", "C": "failed"}
        assert await _live_runs(db, check.id) == []

    async def test_a_file_replaced_on_main_keeps_its_description_as_it_would_ship(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        base = await skill_version_repo.get_version(
            db,
            lab.skill.latest_version_id,
            organization_id=lab.ctx.organization_id,
            skill_id=lab.skill.id,
        )
        assert base is not None
        base.resources = {
            name: {**entry, "description": "How it is"} for name, entry in base.resources.items()
        }
        await db.flush()
        proposal = await _proposal(db, lab, resources={"a.md": "second"})

        check = await SkillCheckService(db).start(
            lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id)
        )

        stored = await skill_check_repo.get(db, check.id, organization_id=lab.ctx.organization_id)
        assert stored is not None and stored.candidate_resources == {
            "a.md": {"description": "How it is", "content": "second"}
        }

    async def test_a_withdrawn_proposals_running_check_is_stopped_and_a_finished_one_kept(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await _proposal(db, lab)
        service = SkillCheckService(db)
        running = await service.start(
            lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id)
        )

        await service.stop_for_proposal(lab.ctx, lab.skill.id, proposal.id)

        assert (await service.read(lab.ctx, lab.skill.id, running.id)).status is (
            CheckStatus.CANCELLED
        )
        other = await _proposal(db, lab)
        done = await service.start(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=other.id))
        await _run_to_end(service, evals, lab, done.id)
        await service.stop_for_proposal(lab.ctx, lab.skill.id, other.id)
        assert (await service.read(lab.ctx, lab.skill.id, done.id)).status is CheckStatus.DONE

    async def test_discarding_a_proposal_stops_its_running_check_and_runs(self, db, monkeypatch):
        """The result of a check on a discarded change can never be applied, so its runs
        stop spending the moment the change is discarded."""
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        proposal = await _proposal(db, lab)
        running = await SkillCheckService(db).start(
            lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id)
        )
        assert await _live_runs(db, running.id)

        await SkillProposalService(db).discard(
            lab.ctx, proposal.id, ProposalDecision(revision=proposal.revision)
        )

        read = await SkillCheckService(db).read(lab.ctx, lab.skill.id, running.id)
        assert read.status is CheckStatus.CANCELLED
        assert await _live_runs(db, running.id) == []

    async def test_an_agent_whose_own_dataset_is_deleted_is_not_judged_on_the_skill_set_alone(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        [own] = [
            item
            for item in await dataset_repo.for_agent(
                db, lab.a.id, organization_id=lab.ctx.organization_id
            )
            if item.skill_id is None
        ]
        own.latest_version = 1
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start(mode="thorough"))
        evals.outcomes = {lab.a.id: Outcome(fixed=1)}
        evals.finish_all()
        await service.advance(check.id, lab.ctx.organization_id)
        skill_id, own_id, a_id = lab.skill.id, own.id, lab.a.id
        await db.execute(delete(Dataset).where(Dataset.id == own_id))
        db.expire_all()

        evals.finish_all()
        await service.advance(check.id, lab.ctx.organization_id)

        read = await service.read(lab.ctx, skill_id, check.id)
        a = next(row for row in read.agents if row.agent.id == a_id)
        assert (a.state, a.unknown_reason) == (AgentState.UNKNOWN, "failed")

    async def test_a_check_whose_dataset_is_deleted_mid_stage_still_settles(self, db, monkeypatch):
        """Its eval runs go with the dataset; the agents running on it are unknown, and the
        check is decided on rather than waiting for runs that no longer exist."""
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        skill_id = lab.skill.id
        await db.execute(delete(Dataset).where(Dataset.skill_id == skill_id))
        db.expire_all()

        await service.advance(check.id, lab.ctx.organization_id)

        read = await service.read(lab.ctx, skill_id, check.id)
        assert read.status is CheckStatus.DONE
        assert {row.unknown_reason for row in read.agents} == {"failed"}

    async def test_the_second_stage_asks_the_dataset_version_the_check_planned(
        self, db, monkeypatch
    ):
        """An edit to the agent's dataset while the first stage runs does not change what
        the second asks: the sample and the price were taken from the planned version."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        [own] = [
            item
            for item in await dataset_repo.for_agent(
                db, lab.a.id, organization_id=lab.ctx.organization_id
            )
            if item.skill_id is None
        ]
        own.latest_version = planned = 3
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start(mode="thorough"))
        own.latest_version += 1
        await db.flush()

        evals.finish_all()
        await service.advance(check.id, lab.ctx.organization_id)

        [second] = [
            request
            for agent_id, request in evals.started
            if agent_id == lab.a.id and request.dataset_id == own.id
        ]
        assert second.dataset_version == planned

    @pytest.mark.security
    async def test_a_key_revoked_after_the_first_stage_runs_no_second(self, db, monkeypatch):
        """A check started with a key runs each later stage as that key stands then, never
        as the issuer's full role."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        keys = ApiKeyService(db)
        created = await keys.create(
            lab.ctx,
            ApiKeyCreate(
                name="assistant",
                scopes=[
                    Perm.RUNS_VIEW,
                    Perm.SKILLS_VIEW,
                    Perm.SKILLS_EDIT,
                    Perm.AGENTS_VIEW,
                    Perm.AGENTS_RUN,
                    Perm.DATASETS_VIEW,
                    Perm.DATASETS_RUN,
                ],
            ),
        )
        keyed = await keys.context_for_key(created.id, organization_id=lab.ctx.organization_id)
        service = SkillCheckService(db)
        check = await service.start(keyed, lab.skill.id, _start(mode="thorough"))
        first = len(evals.started)
        await keys.revoke(lab.ctx, created.id)
        monkeypatch.setattr(NotificationService, "eval_run_finished", AsyncMock())

        evals.finish_all()
        await service.advance(check.id, lab.ctx.organization_id)

        assert len(evals.started) == first
        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert {row.unknown_reason for row in read.agents} == {"failed"}
        assert await _live_runs(db, check.id) == []

    async def test_a_change_that_helped_nobody_may_still_be_forked(self, db, monkeypatch):
        """Whether a fork is worth having is the person's call: a blocked change offers it,
        and with nobody helped it moves nobody unless they pick."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(
            db, lab, evals, {lab.a.id: Outcome(broken=1), lab.b.id: Outcome(broken=1)}
        )

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        forked = await service.fork(
            lab.ctx, lab.skill.id, check.id, SkillCheckFork(name="x", acknowledge_unknown=True)
        )

        assert read.verdict is CheckVerdict.BLOCKED
        assert CheckOutcome.FORK_FOR_HELPED in read.outcomes
        assert forked.moved == [] and forked.draft_only == []
        assert forked.fork.name == "x"

    async def test_a_change_that_helped_nobody_is_forked_for_the_agents_picked(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(db, lab, evals, {lab.a.id: Outcome(broken=1)})

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        forked = await service.fork(
            lab.ctx,
            lab.skill.id,
            check.id,
            SkillCheckFork(name="x", acknowledge_unknown=True, agent_ids=[lab.b.id, lab.b.id]),
        )

        assert CheckOutcome.FORK_FOR_HELPED in read.outcomes
        assert [agent.name for agent in forked.moved] == ["B"]

    async def test_an_empty_pick_forks_without_moving_the_helped(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(db, lab, evals, {lab.a.id: Outcome(fixed=1)})

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        forked = await service.fork(
            lab.ctx,
            lab.skill.id,
            check.id,
            SkillCheckFork(name="x", acknowledge_unknown=True, agent_ids=[]),
        )

        assert read.verdict is not CheckVerdict.BLOCKED
        assert CheckOutcome.FORK_FOR_HELPED in read.outcomes
        assert forked.moved == [] and forked.draft_only == []

    async def test_a_pick_outside_the_check_is_refused(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(db, lab, evals, {lab.a.id: Outcome(fixed=1)})

        with pytest.raises(BadRequestError, match="Pick agents this check asked") as refused:
            await service.fork(
                lab.ctx,
                lab.skill.id,
                check.id,
                SkillCheckFork(name="x", acknowledge_unknown=True, agent_ids=[lab.pinned.id]),
            )
        assert refused.value.details["agent_ids"] == [lab.pinned.id]

    async def test_a_pick_the_caller_may_not_see_reads_as_outside_the_check(self, db, monkeypatch):
        """Refusing it as not editable would confirm a hidden agent was checked."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(
            db, lab, evals, {lab.a.id: Outcome(fixed=1), lab.b.id: Outcome(broken=1)}
        )
        _deny(monkeypatch, Perm.AGENTS_VIEW, lab.b.id)

        with pytest.raises(BadRequestError, match="Pick agents this check asked") as refused:
            await service.fork(
                lab.ctx,
                lab.skill.id,
                check.id,
                SkillCheckFork(name="x", acknowledge_unknown=True, agent_ids=[lab.b.id]),
            )
        assert refused.value.details["agent_ids"] == [lab.b.id]

    async def test_a_pick_the_caller_may_not_edit_is_refused(self, db, monkeypatch):
        """The default leaves a helped agent the caller may not edit on main; one they named
        themselves is refused rather than left behind without a word."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(
            db, lab, evals, {lab.a.id: Outcome(fixed=1), lab.b.id: Outcome(broken=1)}
        )
        _deny(monkeypatch, Perm.AGENTS_EDIT, lab.b.id)

        with pytest.raises(AuthorizationError) as refused:
            await service.fork(
                lab.ctx,
                lab.skill.id,
                check.id,
                SkillCheckFork(name="x", acknowledge_unknown=True, agent_ids=[lab.a.id, lab.b.id]),
            )
        assert refused.value.details == {"agent_ids": [lab.b.id], "agents": ["B"]}
        assert "You may not edit B" in refused.value.message

    async def test_an_agent_helped_through_a_specialist_is_moved_in_its_builder(
        self, db, monkeypatch
    ):
        """A fork moves only agents that bind the skill themselves: the default leaves one
        helped through a specialist where it is, and picking it is refused."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(
            db, lab, evals, {lab.a.id: Outcome(fixed=1), lab.b.id: Outcome(broken=1)}
        )
        rows = await skill_check_repo.list_agents(
            db, [check.id], organization_id=lab.ctx.organization_id
        )
        next(row for row in rows if row.agent_id == lab.a.id).via_specialist = "reader"
        await db.flush()

        with pytest.raises(BadRequestError, match="through a specialist") as refused:
            await service.fork(
                lab.ctx,
                lab.skill.id,
                check.id,
                SkillCheckFork(name="x", acknowledge_unknown=True, agent_ids=[lab.a.id]),
            )
        forked = await service.fork(
            lab.ctx, lab.skill.id, check.id, SkillCheckFork(name="x", acknowledge_unknown=True)
        )

        assert refused.value.details["agent_ids"] == [lab.a.id]
        assert forked.moved == [] and forked.draft_only == []

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
        await _follow_publishes(db, lab.b)
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


class TestATextWrittenAgainstAVersion:
    """The editor's text was written against the version it opened; a save made since must
    never be written over by applying a check of the older text."""

    async def test_a_text_written_against_an_older_version_is_not_checked(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        opened = lab.skill.latest_version_id
        await SkillService(db).update(
            lab.ctx, lab.skill.id, SkillUpdate(content="Saved meanwhile.")
        )

        with pytest.raises(ConcurrentChangeError) as refused:
            await SkillCheckService(db).start(
                lab.ctx, lab.skill.id, SkillCheckStart(candidate=NEW, base_version_id=opened)
            )

        assert refused.value.details == {"version": lab.skill.version}
        assert await SkillCheckService(db).list_checks(
            lab.ctx, lab.skill.id, fork_id=None, skip=0, limit=10
        ) == SkillCheckList(items=[], total=0)

    async def test_a_save_after_the_check_started_refuses_applying_it(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(
            lab.ctx,
            lab.skill.id,
            SkillCheckStart(candidate=NEW, base_version_id=lab.skill.latest_version_id),
        )
        evals.outcomes = {lab.a.id: Outcome(fixed=1)}
        await _run_to_end(service, evals, lab, check.id)
        await SkillService(db).update(
            lab.ctx, lab.skill.id, SkillUpdate(content="Saved meanwhile.")
        )
        saved = lab.skill.version

        with pytest.raises(ConcurrentChangeError) as refused:
            await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply())

        assert refused.value.details["version"] == saved
        await db.refresh(lab.skill)
        assert (lab.skill.version, lab.skill.content) == (saved, "Saved meanwhile.")


async def _answered(
    db: AsyncSession, lab: Lab, texts: Sequence[str], loads: Callable[[str], bool]
) -> tuple[Dataset, list[DatasetCase]]:
    """A dataset of these questions, every one held out, that agent A answered, with the
    skill loaded on the answers `loads` picks."""
    ctx = lab.ctx
    datasets = DatasetService(db)
    own = await datasets.create(
        ctx,
        DatasetCreate(name=f"a-{uuid.uuid4().hex[:6]}", improvement_holdout_share=Decimal(1)),
    )
    for text in texts:
        await datasets.add_case(ctx, own.id, DatasetCaseCreate(input=text, reference_answer="y"))
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
        if loads(case.input):
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
    return dataset, cases


class TestSampleAndTestSet:
    async def test_a_quick_check_asks_the_questions_whose_answers_loaded_the_skill(self, db):
        lab = await _lab(db)
        ctx = lab.ctx
        dataset, cases = await _answered(
            db,
            lab,
            ("Lost receipt, order 1", "Opening hours?", "Receipt gone, order 2"),
            lambda text: "eceipt" in text,
        )

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
        # A training question is never compared, so it is never sampled.
        trained = next(case for case in cases if case.case_id in one)
        trained.improvement_partition = "train"
        await db.flush()
        rest = await SkillCheckService(db)._sample(
            ctx, lab.skill, lab.a.id, dataset, {"receipt", "order"}
        )
        assert set(rest) == loaded - set(one)

    async def test_without_a_skill_set_a_quick_check_asks_enough_to_judge(self, db, monkeypatch):
        """Four questions alone are under the held-out minimum an agent's result needs, so
        an agent with no skill's questions beside them is asked five."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        texts = [f"Receipt question {index}" for index in range(6)]
        dataset, _ = await _answered(db, lab, texts, lambda _text: True)
        skill_id, a_id = lab.skill.id, lab.a.id
        await db.execute(
            delete(Dataset).where(
                (Dataset.skill_id == skill_id)
                | ((Dataset.agent_id == a_id) & (Dataset.id != dataset.id))
            )
        )
        db.expire_all()
        service = SkillCheckService(db)

        estimate = await service.estimate(lab.ctx, skill_id, _start())
        check = await service.start(
            lab.ctx, skill_id, _start(), source=CheckSource.SESSION, only=[a_id]
        )
        evals.outcomes = {a_id: Outcome(fixed=1)}
        for _ in range(3):
            evals.finish_all()
            await service.advance(check.id, lab.ctx.organization_id)
        read = await service.read(lab.ctx, skill_id, check.id)

        a = next(row for row in estimate.agents if row.agent.id == a_id)
        assert a.sample == "own_questions"
        assert [(stage.kind, stage.cases) for stage in a.stages] == [("dataset_sample", 5)]
        [checked] = read.agents
        assert checked.state is AgentState.BETTER

    async def test_a_quick_sample_never_picks_the_changes_own_evidence(self, db, monkeypatch):
        """The run leaves out the questions taken from the conversations the change
        learned from, so a sample of them would ask fewer questions than it picked."""
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        texts = [f"Receipt question {index}" for index in range(6)]
        dataset, cases = await _answered(db, lab, texts, lambda _text: True)
        evidence = Conversation(
            id=uuid.uuid4(),
            user_id=lab.ctx.user_id,
            organization_id=lab.ctx.organization_id,
            title="Evidence",
        )
        db.add(evidence)
        await db.flush()
        for case in cases[:4]:
            case.source_conversation_id = evidence.id
        await db.flush()
        kept = sorted((case.case_id for case in cases[4:]), key=str)
        evidence_id = evidence.id
        skill_id, a_id = lab.skill.id, lab.a.id
        await db.execute(
            delete(Dataset).where((Dataset.agent_id == a_id) & (Dataset.id != dataset.id))
        )
        db.expire_all()

        estimate = await SkillCheckService(db).estimate(
            lab.ctx, skill_id, _start(), exclude_conversations=[evidence_id]
        )

        a = next(row for row in estimate.agents if row.agent.id == a_id)
        [own] = [stage for stage in a.stages if stage.kind == "dataset_sample"]
        assert own.cases == 2
        skill = await db.get(Skill, skill_id)
        assert skill is not None
        picked = await SkillCheckService(db)._sample(
            lab.ctx, skill, a_id, dataset, set(), excluded=[evidence_id]
        )
        assert sorted(picked, key=str) == kept

    async def test_the_skills_test_questions_can_start_from_recent_answers(self, db, monkeypatch):
        """A person's rating outranks an answer that only failed, so it is the one a
        question shared by both keeps."""
        lab = await _lab(db)
        failed, good, bad = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        pack = SimpleNamespace(
            runs=[
                SimpleNamespace(run_id=failed, rating=0),
                SimpleNamespace(run_id=good, rating=1),
                SimpleNamespace(run_id=bad, rating=-1),
            ]
        )
        messages = {run_id: uuid.uuid4() for run_id in (failed, good, bad)}
        added: dict[str, Any] = {}

        async def for_skill(_self, _ctx, _skill_id, **_):
            return pack

        async def answers(_db, run_ids, *, organization_id):
            return {run_id: messages[run_id] for run_id in run_ids}

        async def add(_self, _ctx, dataset_id, message_ids, **kwargs):
            added.update(kwargs["answer_as"])
            added["order"] = message_ids
            added["one_per_question"] = kwargs["one_per_question"]
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

        created = await SkillCheckService(db).create_test_set(
            lab.ctx, lab.skill.id, SkillTestSetStart(from_evidence=True)
        )

        order = added.pop("order")
        one_per_question = added.pop("one_per_question")
        assert order == [messages[good], messages[bad], messages[failed]]
        assert one_per_question is True
        assert added == {
            messages[good]: "reference_answer",
            messages[bad]: "counter_example",
            messages[failed]: "counter_example",
        }
        assert created.scoring.judge.enabled and created.scoring.reference.enabled
        assert created.scoring.judge.criteria

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


@pytest.mark.security
async def test_a_caller_who_may_not_create_datasets_gets_no_test_questions(db):
    """A key for skills alone edits the skill, but the test set is a dataset."""
    lab = await _lab(db)
    test_set = await dataset_repo.for_skill(
        db, lab.skill.id, organization_id=lab.ctx.organization_id
    )
    assert test_set is not None
    test_set.skill_id = None
    await db.flush()
    key = AuthContext(
        user_id=lab.ctx.user_id,
        organization_id=lab.ctx.organization_id,
        role=OrgRoleName.OWNER,
        key_scopes=frozenset({Perm.SKILLS_VIEW, Perm.SKILLS_EDIT}),
    )

    with pytest.raises(AuthorizationError):
        await SkillCheckService(db).create_test_set(key, lab.skill.id, SkillTestSetStart())

    assert (
        await dataset_repo.for_skill(db, lab.skill.id, organization_id=lab.ctx.organization_id)
        is None
    )


def test_rows_say_what_they_are() -> None:
    check = SkillCheck(id=uuid.uuid4(), skill_id=uuid.uuid4(), fork_id=None, status="running")
    row = SkillCheckAgent(check_id=check.id, agent_id=uuid.uuid4(), state="better")

    assert "main" in repr(check) and "better" in repr(row)
    assert "fork=" in repr(SkillCheck(fork_id=uuid.uuid4()))


class TestStageCounts:
    """Each stage's counts are kept when the agent is judged, so a result with many agents
    reads them from the check rather than comparing every run again."""

    async def test_each_stage_counts_what_its_comparison_found(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(
            db,
            lab,
            evals,
            {lab.a.id: Outcome(fixed=2), lab.b.id: Outcome(broken=1)},
            mode="thorough",
        )

        read = await service.read(lab.ctx, lab.skill.id, check.id)

        a = next(row for row in read.agents if row.agent.id == lab.a.id)
        assert [stage.kind for stage in a.stages] == ["skill_set", "dataset"]
        for stage in a.stages:
            assert stage.counts is not None
            assert stage.eval_run_id is not None
            held = evals.runs[stage.eval_run_id].held_out
            assert stage.counts.model_dump() == {
                "compared": held,
                "fixed": 2,
                "broken": 0,
                "unchanged": held - 2,
                "unknown": 0,
            }
        assert sum(stage.counts.fixed for stage in a.stages if stage.counts) == a.fixed
        assert sum(stage.counts.compared for stage in a.stages if stage.counts) == a.held_out
        rows = await skill_check_repo.list_agents(
            db, [check.id], organization_id=lab.ctx.organization_id
        )
        stored = next(row for row in rows if row.agent_id == lab.a.id).stages
        assert [entry["dataset_id"] for entry in stored] == [
            str(stage.dataset_id) for stage in a.stages
        ]

    async def test_an_incomplete_question_is_unknown_and_never_compared(self, db, monkeypatch):
        """Every held-out question lands in exactly one count."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(
            db, lab, evals, {lab.a.id: Outcome(fixed=1, incomplete=1)}, mode="thorough"
        )

        read = await service.read(lab.ctx, lab.skill.id, check.id)

        a = next(row for row in read.agents if row.agent.id == lab.a.id)
        for stage in a.stages:
            assert stage.counts is not None and stage.eval_run_id is not None
            held = evals.runs[stage.eval_run_id].held_out
            assert stage.counts.unknown == 1
            assert stage.counts.compared == held - 1
            assert stage.counts.compared + stage.counts.unknown == held
            assert stage.counts.unchanged == held - 2
        assert a.held_out == sum(stage.counts.compared for stage in a.stages if stage.counts)

    async def test_an_agent_the_reader_may_not_see_shows_no_counts(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(
            db, lab, evals, {lab.a.id: Outcome(fixed=2), lab.b.id: Outcome(broken=1)}
        )
        _deny(monkeypatch, Perm.AGENTS_VIEW, lab.b.id)

        read = await service.read(lab.ctx, lab.skill.id, check.id)

        assert lab.b.id not in {row.agent.id for row in read.agents}
        assert read.hidden == 1

    async def test_a_dataset_the_reader_may_not_see_shows_no_counts(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(db, lab, evals, {lab.a.id: Outcome(fixed=2)})
        _deny_datasets(monkeypatch)

        read = await service.read(lab.ctx, lab.skill.id, check.id)

        assert {stage.counts for row in read.agents for stage in row.stages} == {None}

    async def test_an_agent_with_no_stage_run_keeps_none(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals(refuse_start={lab.c.id})
        evals.install(monkeypatch)
        service, check = await _finished(db, lab, evals, {lab.a.id: Outcome(fixed=2)})

        rows = await skill_check_repo.list_agents(
            db, [check.id], organization_id=lab.ctx.organization_id
        )

        c = next(row for row in rows if row.agent_id == lab.c.id)
        assert c.state == AgentState.UNKNOWN.value
        assert c.stages == []

    async def test_a_check_judged_before_counts_were_kept_reads_none(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service, check = await _finished(db, lab, evals, {lab.a.id: Outcome(fixed=2)})
        rows = await skill_check_repo.list_agents(
            db, [check.id], organization_id=lab.ctx.organization_id
        )
        for row in rows:
            row.stages = []
        await db.flush()

        read = await service.read(lab.ctx, lab.skill.id, check.id)

        stages = [stage for row in read.agents for stage in row.stages]
        assert stages and all(stage.eval_run_id is not None for stage in stages)
        assert {stage.counts for stage in stages} == {None}


class TestTwoSessionsOnOneProposal:
    async def test_the_second_start_waits_and_finds_the_first_check(
        self, db: AsyncSession, engine: AsyncEngine, monkeypatch
    ):
        """A double submit starts one check: the second start waits on the proposal and
        then sees the first's check, so the runs are paid for once."""
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        proposal = await _proposal(db, lab)
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def second() -> None:
            async with factory() as session:
                await SkillCheckService(session).start(
                    lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id)
                )

        task: asyncio.Task[None] | None = None
        async with factory() as first:
            try:
                await SkillCheckService(first).start(
                    lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id)
                )
                task = asyncio.create_task(second())
                await asyncio.sleep(0.4)
                assert not task.done()

                await first.commit()
                with pytest.raises(AlreadyExistsError, match="checked already"):
                    await asyncio.wait_for(task, 10)
                task = None
            finally:
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    async def test_discarding_a_proposal_does_not_wait_on_its_decided_check(
        self, db: AsyncSession, engine: AsyncEngine, monkeypatch
    ):
        """Applying a finished check holds the check and then claims the proposal, so a
        discard of the proposal must not wait on that check: it stops running checks only."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await _proposal(db, lab)
        _, check = await _finished(db, lab, evals, {lab.a.id: Outcome(fixed=1)}, proposal=proposal)
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as applying, factory() as discarding:
            await skill_check_repo.get(
                applying, check.id, organization_id=lab.ctx.organization_id, lock=True
            )
            await asyncio.wait_for(
                SkillProposalService(discarding).discard(
                    lab.ctx, proposal.id, ProposalDecision(revision=proposal.revision)
                ),
                5,
            )
            await discarding.commit()
            await applying.rollback()
