"""A skill change checked on every agent of its line, against a real database.

The skill, its versions and fork, the agents' bindings, datasets, the check's
rows and every decision are real. The eval runs are not: running a model is
not what is under test here, so `EvalRunService` answers each stage with a
result the test scripts per agent.
"""

import uuid
from dataclasses import dataclass, field, replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.eval_run import EvalRun, EvalRunStatus
from app.db.models.skill import Skill
from app.db.models.skill_check import (
    AgentState,
    CheckOutcome,
    CheckSource,
    CheckStatus,
    CheckVerdict,
)
from app.repositories import dataset_repo, eval_run_repo, skill_check_repo, skill_proposal_repo
from app.schemas.resource_usage import ProposalDecision
from app.schemas.skill_check import (
    CandidateText,
    SkillCheckApply,
    SkillCheckFork,
    SkillCheckStart,
    SkillTestSetStart,
)
from app.services.eval_run import EvalRunService
from app.services.skill_agents import SkillAgentService
from app.services.skill_check import SkillCheckService
from app.services.skill_proposal import SkillProposalService
from app.services.skill_versions import SkillVersionService
from tests.integration.test_authoring import _member, _owner
from tests.integration.test_skill_bindings import _fork, _runnable, _serving, _skill

pytestmark = pytest.mark.anyio

NEW = CandidateText(description="How refunds work.", content="An order number counts as a receipt.")


@dataclass
class Outcome:
    """What one stage of one agent's check comes back with."""

    fixed: int = 0
    broken: int = 0
    unconfirmed_broken: int = 0
    incomplete: int = 0


@dataclass
class FakeEvals:
    """Eval runs that end at once with what the test scripted for their agent."""

    outcomes: dict[uuid.UUID, Outcome] = field(default_factory=dict)
    runs: dict[uuid.UUID, SimpleNamespace] = field(default_factory=dict)
    per_case: Decimal = Decimal("0.01")
    agent_left: Decimal | None = None
    org_left: Decimal | None = None
    refuse_start: set[uuid.UUID] = field(default_factory=set)
    started: list[tuple[uuid.UUID, Any]] = field(default_factory=list)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = self

        async def estimate(_self, _ctx, agent_id, request, **_):
            cases = len(request.case_ids) if request.case_ids else 4
            total = fake.per_case * 2 * cases
            return SimpleNamespace(
                total_usd=total,
                rerun_ceiling_usd=total * 2,
                agent_remaining_usd=fake.agent_left,
                org_remaining_usd=fake.org_left,
            )

        async def start(_self, ctx, agent_id, request, **_):
            if agent_id in fake.refuse_start:
                raise BadRequestError(message="Cannot start")
            dataset = await dataset_repo.get(
                _self.db, request.dataset_id, organization_id=ctx.organization_id
            )
            version = await dataset_repo.create_version(
                _self.db,
                dataset_id=dataset.id,
                organization_id=ctx.organization_id,
                number=dataset.latest_version + 1,
                case_count=dataset.case_count,
                change="add",
                changed_cases=0,
                created_by_user_id=ctx.user_id,
            )
            dataset.latest_version += 1
            row = EvalRun(
                organization_id=ctx.organization_id,
                agent_id=agent_id,
                dataset_id=dataset.id,
                dataset_version_id=version.id,
                created_by_user_id=ctx.user_id,
                status=EvalRunStatus.RUNNING.value,
                scoring={},
                scoring_hash="a" * 64,
                estimate_usd=Decimal("0.1"),
            )
            _self.db.add(row)
            await _self.db.flush()
            run_id = row.id
            fake.runs[run_id] = SimpleNamespace(
                id=run_id, agent_id=agent_id, status=EvalRunStatus.RUNNING.value
            )
            fake.started.append((agent_id, request))
            return SimpleNamespace(id=run_id)

        async def compare(_self, _ctx, run_id, **_):
            outcome = fake.outcomes.get(fake.runs[run_id].agent_id, Outcome())
            summary = SimpleNamespace(
                incomplete=outcome.incomplete, ungraded=0, crashed=0, pass_rate=0.5
            )
            better = SimpleNamespace(
                incomplete=0, ungraded=0, crashed=0, pass_rate=0.5 + 0.1 * outcome.fixed
            )
            return SimpleNamespace(
                candidate_summary=better if outcome.fixed else summary,
                baseline_summary=summary,
                baseline=object(),
                verdict="better",
                regressions_confirmed=outcome.broken,
                fixed_confirmed=outcome.fixed,
                fixed_unconfirmed=0,
                regressions_unconfirmed=outcome.unconfirmed_broken,
                compared=4,
            )

        async def cancel(_self, _ctx, run_id):
            fake.runs[run_id].status = EvalRunStatus.CANCELLED.value

        async def get(_db, run_id, *, organization_id):
            return fake.runs.get(run_id)

        monkeypatch.setattr(EvalRunService, "estimate", estimate)
        monkeypatch.setattr(EvalRunService, "start", start)
        monkeypatch.setattr(EvalRunService, "compare", compare)
        monkeypatch.setattr(EvalRunService, "cancel", cancel)
        monkeypatch.setattr(eval_run_repo, "get", get)

    def finish_all(self) -> None:
        for run in self.runs.values():
            if run.status == EvalRunStatus.RUNNING.value:
                run.status = EvalRunStatus.COMPLETED.value


async def _dataset(
    db: AsyncSession,
    ctx: AuthContext,
    name: str,
    *,
    agent: Agent | None = None,
    skill: Skill | None = None,
    cases: int = 4,
):
    dataset = await dataset_repo.create(
        db,
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name=f"{name}-{uuid.uuid4().hex[:6]}",
        description=None,
        visibility="org",
        agent_id=None if agent is None else agent.id,
        skill_id=None if skill is None else skill.id,
    )
    dataset.case_count = cases
    await db.flush()
    return dataset


@dataclass
class Lab:
    ctx: AuthContext
    skill: Skill
    a: Agent
    b: Agent
    c: Agent
    pinned: Agent
    on_fork: Agent
    fork_id: uuid.UUID


async def _lab(db: AsyncSession) -> Lab:
    """A on main with its own questions, B on main, C on main with none, one agent pinned to
    v1, one on a fork - and the skill's own test questions."""
    ctx = await _owner(db)
    skill = await _skill(db, ctx)
    fork = await _fork(db, ctx, skill, text="fork text")
    main = await _runnable(db, ctx, skill)

    def bound(**binding: Any) -> dict[str, Any]:
        return {**main, "skill_bindings": [{"skill_id": str(skill.id), **binding}]}

    a = await _serving(db, ctx, "A", main)
    b = await _serving(db, ctx, "B", main)
    c = await _serving(db, ctx, "C", main)
    pinned = await _serving(db, ctx, "Pinned", bound(version=1))
    on_fork = await _serving(db, ctx, "Forked", bound(fork_id=str(fork.id)))
    await _dataset(db, ctx, "skill-set", skill=skill)
    await _dataset(db, ctx, "a-own", agent=a)
    await _dataset(db, ctx, "b-own", agent=b)
    return Lab(ctx, skill, a, b, c, pinned, on_fork, fork.id)


async def _follow_publishes(db: AsyncSession, agent: Agent) -> None:
    """Have the agent's environments take each version it publishes."""
    for environment in (
        await db.scalars(select(AgentEnvironment).where(AgentEnvironment.agent_id == agent.id))
    ).all():
        environment.tracks_latest = True
    await db.flush()


def _start(**values: Any) -> SkillCheckStart:
    return SkillCheckStart(candidate=NEW, **values)


async def _run_to_end(service: SkillCheckService, evals: FakeEvals, lab: Lab, check_id):
    for _ in range(3):
        evals.finish_all()
        await service.advance(check_id, lab.ctx.organization_id)
    return await service.read(lab.ctx, lab.skill.id, check_id)


class TestWhoIsChecked:
    async def test_a_main_change_runs_mains_agents_and_nobody_pinned_or_forked(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)

        estimate = await SkillCheckService(db).estimate(lab.ctx, lab.skill.id, _start())

        assert {row.agent.name for row in estimate.agents} == {"A", "B", "C"}
        assert estimate.line.name == "main"
        assert estimate.hidden == 0

    async def test_a_fork_change_runs_only_the_forks_agents(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)

        estimate = await SkillCheckService(db).estimate(
            lab.ctx, lab.skill.id, _start(fork_id=lab.fork_id)
        )

        assert [row.agent.name for row in estimate.agents] == ["Forked"]
        assert estimate.line.fork_id == lab.fork_id

    async def test_a_quick_check_without_loaded_questions_falls_back_to_the_skill_set(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)

        estimate = await SkillCheckService(db).estimate(lab.ctx, lab.skill.id, _start())

        rows = {row.agent.name: row for row in estimate.agents}
        assert rows["A"].sample == "skill_set_only"
        assert [stage.kind for stage in rows["A"].stages] == ["skill_set"]

    async def test_a_quick_check_asks_the_questions_that_loaded_the_skill(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        picked = [uuid.uuid4(), uuid.uuid4()]

        async def sample(_self, _ctx, _skill, agent_id, _dataset, _words, _allowed=None):
            return picked if agent_id == lab.a.id else []

        monkeypatch.setattr(SkillCheckService, "_sample", sample)

        estimate = await SkillCheckService(db).estimate(lab.ctx, lab.skill.id, _start())

        a = next(row for row in estimate.agents if row.agent.name == "A")
        assert a.sample == "own_questions"
        assert [(stage.kind, stage.cases) for stage in a.stages] == [
            ("skill_set", 4),
            ("dataset_sample", 2),
        ]

    async def test_a_changed_description_is_always_checked_thoroughly(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)

        estimate = await SkillCheckService(db).estimate(
            lab.ctx,
            lab.skill.id,
            SkillCheckStart(
                candidate=CandidateText(description="When to refund.", content="x"), mode="quick"
            ),
        )

        assert (estimate.mode, estimate.description_changed) == ("thorough", True)
        a = next(row for row in estimate.agents if row.agent.name == "A")
        assert [stage.kind for stage in a.stages] == ["skill_set", "dataset"]

    @pytest.mark.security
    async def test_an_agent_without_budget_is_named_before_the_start(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals(agent_left=Decimal("0.01")).install(monkeypatch)

        estimate = await SkillCheckService(db).estimate(lab.ctx, lab.skill.id, _start())

        assert {row.unknown_reason for row in estimate.agents} == {"no_budget"}
        assert estimate.expected_usd == Decimal(0)

    async def test_checking_needs_runs_view_and_starts_nothing_without(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        member = await _member(db, lab.ctx, OrgRoleName.VIEWER)

        with pytest.raises(AuthorizationError):
            await SkillCheckService(db).start(member, lab.skill.id, _start())
        assert evals.started == []


class TestASessionsDraw:
    """A skill session measures on the questions it kept aside, and never on the
    ones its change was learned from."""

    async def test_the_held_out_questions_are_the_only_ones_asked(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        test_set = await dataset_repo.for_skill(
            db, lab.skill.id, organization_id=lab.ctx.organization_id
        )
        own = await dataset_repo.for_agent(db, lab.a.id, organization_id=lab.ctx.organization_id)
        b_own = await dataset_repo.for_agent(db, lab.b.id, organization_id=lab.ctx.organization_id)
        assert test_set is not None
        kept = [uuid.uuid4(), uuid.uuid4()]
        learned_from = [uuid.uuid4()]

        check = await SkillCheckService(db).start(
            lab.ctx,
            lab.skill.id,
            SkillCheckStart(candidate=NEW, mode="thorough"),
            holdout={test_set.id: kept, own[0].id: kept[:1], b_own[0].id: []},
            exclude_conversations=learned_from,
        )

        rows = {row.agent.name: row for row in check.agents}
        assert [(stage.kind, stage.cases) for stage in rows["A"].stages] == [
            ("skill_set", 2),
            ("dataset", 1),
        ]
        assert [stage.kind for stage in rows["B"].stages] == ["skill_set"]
        assert {tuple(request.case_ids) for _, request in evals.started} == {
            tuple(sorted(kept, key=str))
        }
        stored = await skill_check_repo.get(db, check.id, organization_id=lab.ctx.organization_id)
        assert stored is not None and stored.excluded_conversation_ids == learned_from

    async def test_an_empty_draw_for_the_skills_questions_skips_them(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        test_set = await dataset_repo.for_skill(
            db, lab.skill.id, organization_id=lab.ctx.organization_id
        )
        assert test_set is not None

        estimate = await SkillCheckService(db).estimate(
            lab.ctx, lab.skill.id, _start(), holdout={test_set.id: []}
        )

        assert {row.unknown_reason for row in estimate.agents} == {"no_questions"}


class TestTheRule:
    async def test_a_change_that_helps_and_breaks_nobody_passes(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.a.id: Outcome(fixed=2), lab.b.id: Outcome(), lab.c.id: Outcome()}

        read = await _run_to_end(service, evals, lab, check.id)

        states = {row.agent.name: row.state for row in read.agents}
        assert states == {"A": "better", "B": "no_change", "C": "no_change"}
        assert (read.status, read.verdict) == (CheckStatus.DONE, CheckVerdict.PASSED)
        assert read.outcomes[0] is CheckOutcome.APPLY

    async def test_one_agent_worse_blocks_and_offers_the_four_ways(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.a.id: Outcome(fixed=2), lab.b.id: Outcome(broken=1)}

        read = await _run_to_end(service, evals, lab, check.id)

        assert read.verdict is CheckVerdict.BLOCKED
        assert read.outcomes == [
            CheckOutcome.IMPROVE_FURTHER,
            CheckOutcome.APPLY_AND_PIN,
            CheckOutcome.FORK_FOR_HELPED,
            CheckOutcome.DISCARD,
        ]

    async def test_a_regression_in_the_skill_set_stops_that_agent_early(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(
            lab.ctx, lab.skill.id, SkillCheckStart(candidate=NEW, mode="thorough")
        )
        evals.outcomes = {lab.b.id: Outcome(broken=1), lab.a.id: Outcome(fixed=1)}

        await _run_to_end(service, evals, lab, check.id)

        datasets_run = [agent for agent, request in evals.started if request.case_ids is None]
        assert datasets_run.count(lab.b.id) == 1
        assert datasets_run.count(lab.a.id) == 2

    async def test_unconfirmed_regressions_are_a_warning(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.a.id: Outcome(fixed=2), lab.b.id: Outcome(unconfirmed_broken=1)}

        read = await _run_to_end(service, evals, lab, check.id)

        assert read.verdict is CheckVerdict.PASSED
        assert read.warnings == ["within_noise"]

    async def test_an_agent_whose_run_cannot_start_needs_an_acknowledgement(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals(refuse_start={lab.c.id})
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.a.id: Outcome(fixed=1)}

        read = await _run_to_end(service, evals, lab, check.id)

        assert read.verdict is CheckVerdict.NEEDS_ACK
        with pytest.raises(BadRequestError):
            await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply())
        applied = await service.apply(
            lab.ctx, lab.skill.id, check.id, SkillCheckApply(acknowledge_unknown=True)
        )
        assert applied.version.content == NEW.content
        listing = await SkillAgentService(db).agents(lab.ctx, lab.skill.id)
        rows = {row.agent.name: row for row in listing.items}
        assert rows["C"].checked is None and rows["C"].checked_versions == []
        assert rows["A"].checked is not None and rows["A"].checked.sample == "skill_set_only"

    async def test_a_failed_run_is_unknown(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        for run in evals.runs.values():
            run.status = EvalRunStatus.FAILED.value

        await service.advance(check.id, lab.ctx.organization_id)

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert {row.unknown_reason for row in read.agents} == {"failed"}
        assert read.verdict is CheckVerdict.NO_BETTER


class TestDeciding:
    async def test_apply_and_pin_keeps_the_worse_agent_on_its_version(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.a.id: Outcome(fixed=2), lab.b.id: Outcome(broken=1)}
        await _run_to_end(service, evals, lab, check.id)
        before = lab.skill.version

        with pytest.raises(BadRequestError):
            await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply())
        await _follow_publishes(db, lab.b)
        applied = await service.apply(
            lab.ctx, lab.skill.id, check.id, SkillCheckApply(pin_worse=True)
        )

        assert [agent.name for agent in applied.pinned] == ["B"]
        assert applied.version.number == before + 1
        await db.refresh(lab.b)
        bindings = AgentSpec.model_validate(lab.b.draft_spec).skill_bindings
        assert [(item.skill_id, item.version) for item in bindings] == [(lab.skill.id, before)]
        with pytest.raises(AlreadyExistsError):
            await service.discard(lab.ctx, lab.skill.id, check.id)

    @pytest.mark.security
    async def test_an_agent_is_told_which_versions_were_checked_on_it(self, db, monkeypatch):
        """Change version asks whether a version was checked on that agent; a version
        that came out of a check says so, one written by hand does not. Only a caller who
        may read eval results learns either."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.a.id: Outcome(fixed=2)}
        await _run_to_end(service, evals, lab, check.id)

        applied = await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply())

        listing = await SkillAgentService(db).agents(lab.ctx, lab.skill.id)
        rows = {row.agent.name: row for row in listing.items}
        assert rows["A"].checked is not None
        assert (rows["A"].checked.version_id, rows["A"].checked.state) == (
            applied.version.id,
            AgentState.BETTER,
        )
        assert [ref.check_id for ref in rows["B"].checked_versions] == [check.id]
        assert rows["Pinned"].checked is None and rows["Pinned"].checked_versions == []

        blind = replace(lab.ctx, key_scopes=frozenset(Perm) - {Perm.RUNS_VIEW})
        unseen = await SkillAgentService(db).agents(blind, lab.skill.id)
        assert unseen.items and all(
            row.checked is None and row.checked_versions == [] for row in unseen.items
        )

    async def test_fork_for_the_helped_moves_them_and_leaves_main(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.a.id: Outcome(fixed=2), lab.b.id: Outcome(broken=1)}
        await _run_to_end(service, evals, lab, check.id)
        before = lab.skill.version

        forked = await service.fork(lab.ctx, lab.skill.id, check.id, SkillCheckFork(name="online"))

        assert [agent.name for agent in forked.moved] == ["A"]
        assert forked.fork.name == "online" and forked.fork.changes == 1
        await db.refresh(lab.skill)
        assert lab.skill.version == before
        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert read.status is CheckStatus.FORKED

    async def test_a_line_that_moved_since_the_check_refuses_it(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.a.id: Outcome(fixed=2)}
        await _run_to_end(service, evals, lab, check.id)
        from app.schemas.skill_version import SkillVersionCreate

        await SkillVersionService(db).edit(
            lab.ctx,
            lab.skill.id,
            SkillVersionCreate(
                fork_id=None,
                base_version_id=lab.skill.latest_version_id,
                description=lab.skill.description,
                content="somebody else's edit",
            ),
        )

        with pytest.raises(ConcurrentChangeError):
            await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply())

    async def test_a_worse_agent_whose_environment_waits_for_promotion_is_not_pinned(
        self, db, monkeypatch
    ):
        """Pinning publishes a new agent version; an environment that waits for promotion
        keeps the old one, which follows main and would serve the change at once."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.a.id: Outcome(fixed=2), lab.b.id: Outcome(broken=1)}
        await _run_to_end(service, evals, lab, check.id)

        with pytest.raises(BadRequestError, match="waits for promotion") as refused:
            await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply(pin_worse=True))

        assert refused.value.details == {"agents": ["B"]}

    async def test_a_fork_line_never_offers_pin_or_fork(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start(fork_id=lab.fork_id))
        evals.outcomes = {lab.on_fork.id: Outcome(broken=1)}

        read = await _run_to_end(service, evals, lab, check.id)

        assert read.outcomes == [CheckOutcome.IMPROVE_FURTHER, CheckOutcome.DISCARD]
        with pytest.raises(BadRequestError):
            await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply(pin_worse=True))

    async def test_discard_and_cancel(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())

        cancelled = await service.cancel(lab.ctx, lab.skill.id, check.id)

        assert cancelled.status is CheckStatus.CANCELLED
        assert all(run.status == EvalRunStatus.CANCELLED.value for run in evals.runs.values())
        discarded = await service.discard(lab.ctx, lab.skill.id, check.id)
        assert discarded.status is CheckStatus.DISCARDED


class TestAProposalGoesLiveOnlyThroughItsCheck:
    async def _proposal(self, db, lab: Lab):
        return await skill_proposal_repo.create(
            db,
            organization_id=lab.ctx.organization_id,
            agent_id=lab.a.id,
            skill_id=lab.skill.id,
            name=lab.skill.name,
            description=lab.skill.description,
            content="An order number counts as a receipt.",
            resources={},
            base_version=lab.skill.version,
            base_version_id=lab.skill.latest_version_id,
            conversation_id=None,
            fork_id=None,
        )

    async def test_applying_without_a_check_is_refused(self, db, monkeypatch):
        lab = await _lab(db)
        proposal = await self._proposal(db, lab)

        with pytest.raises(BadRequestError, match="Check this change"):
            await SkillProposalService(db).apply(
                lab.ctx, proposal.id, ProposalDecision(revision=proposal.revision)
            )

    async def test_a_passed_check_applies_the_proposal(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await self._proposal(db, lab)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id))
        evals.outcomes = {lab.a.id: Outcome(fixed=1)}
        await _run_to_end(service, evals, lab, check.id)

        decided = await SkillProposalService(db).apply(
            lab.ctx, proposal.id, ProposalDecision(revision=proposal.revision, check_id=check.id)
        )

        assert decided.status == "applied"
        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert read.status is CheckStatus.APPLIED

    async def test_a_check_of_another_text_does_not_open_the_gate(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        proposal = await self._proposal(db, lab)
        service = SkillCheckService(db)
        other = CandidateText(description=NEW.description, content="Something else entirely.")
        check = await service.start(lab.ctx, lab.skill.id, SkillCheckStart(candidate=other))
        evals.outcomes = {lab.a.id: Outcome(fixed=1)}
        await _run_to_end(service, evals, lab, check.id)

        with pytest.raises(BadRequestError):
            await SkillProposalService(db).apply(
                lab.ctx,
                proposal.id,
                ProposalDecision(revision=proposal.revision, check_id=check.id),
            )


class TestIsolation:
    async def test_another_organizations_check_is_not_found(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        stranger = await _owner(db)

        with pytest.raises(NotFoundError):
            await service.read(stranger, lab.skill.id, check.id)
        assert (
            await skill_check_repo.get(db, check.id, organization_id=stranger.organization_id)
            is None
        )

    async def test_reading_needs_runs_view(self, db, monkeypatch):
        lab = await _lab(db)
        member = await _member(db, lab.ctx, OrgRoleName.VIEWER)

        with pytest.raises(AuthorizationError):
            await SkillCheckService(db).list_checks(
                member, lab.skill.id, fork_id=None, skip=0, limit=10
            )


class TestTestSet:
    async def test_a_skill_gets_one_set_of_test_questions(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx, name="tests-only")
        service = SkillCheckService(db)

        with pytest.raises(NotFoundError):
            await service.test_set(ctx, skill.id)
        created = await service.create_test_set(ctx, skill.id, SkillTestSetStart())

        assert (await service.test_set(ctx, skill.id)).id == created.id
        with pytest.raises(AlreadyExistsError):
            await service.create_test_set(ctx, skill.id, SkillTestSetStart())


class TestASessionsCheckStops:
    async def test_the_session_stops_its_check_and_every_run_it_started(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        service = SkillCheckService(db)
        read = await service.start(lab.ctx, lab.skill.id, _start(), source=CheckSource.SESSION)
        check = await skill_check_repo.get(db, read.id, organization_id=lab.ctx.organization_id)
        assert check is not None
        runs = [
            run_id
            for row in await skill_check_repo.list_agents(
                db, [check.id], organization_id=lab.ctx.organization_id
            )
            for run_id in (row.skill_set_run_id, row.dataset_run_id)
            if run_id is not None
        ]

        await service.stop_for_session(check)

        assert runs and check.status == "cancelled"
        for run_id in runs:
            run = await db.get(EvalRun, run_id)
            assert run is not None
            await db.refresh(run)
            assert run.status == "cancelled"
