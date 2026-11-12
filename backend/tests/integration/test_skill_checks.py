"""A skill change checked on every agent of its line, against a real database.

The skill, its versions and fork, the agents' bindings, datasets, the check's
rows and every decision are real. The eval runs are not: running a model is
not what is under test here, so `EvalRunService` answers each stage with a
result the test scripts per agent.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.skills import SkillBodyFile
from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AlreadyExistsError,
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.eval_run import EvalRun, EvalRunStatus
from app.db.models.skill import Skill
from app.db.models.skill_check import (
    AgentState,
    CheckOutcome,
    CheckSource,
    CheckStatus,
    CheckVerdict,
    SkillCheckAgent,
    UnknownReason,
)
from app.repositories import (
    dataset_repo,
    eval_run_repo,
    skill_check_repo,
    skill_proposal_repo,
    skill_usage_repo,
)
from app.schemas.resource_usage import ProposalDecision
from app.schemas.skill_check import (
    CandidateText,
    SkillCheckApply,
    SkillCheckFork,
    SkillCheckStart,
    SkillTestSetStart,
)
from app.schemas.skill_usage import SkillUseRecord
from app.schemas.skill_version import SkillForkCreate
from app.services import skill_check as skill_check_module
from app.services.eval_run import EvalRunService
from app.services.improvement_data import MIN_HOLDOUT_CASES
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


def _flips(outcome: Outcome, held_out: int) -> list[SimpleNamespace]:
    """The compared cases a stage's outcome amounts to, the rest unchanged."""
    flips = (
        ["fixed"] * outcome.fixed
        + ["regression"] * (outcome.broken + outcome.unconfirmed_broken)
        + ["incomplete"] * outcome.incomplete
    )
    return [SimpleNamespace(flip=flip) for flip in flips] + [
        SimpleNamespace(flip="unchanged") for _ in range(max(held_out - len(flips), 0))
    ]


@dataclass
class FakeEvals:
    """Eval runs that end at once with what the test scripted for their agent."""

    outcomes: dict[uuid.UUID, Outcome] = field(default_factory=dict)
    runs: dict[uuid.UUID, SimpleNamespace] = field(default_factory=dict)
    per_case: Decimal = Decimal("0.01")
    agent_left: Decimal | None = None
    org_left: Decimal | None = None
    refuse_start: set[uuid.UUID] = field(default_factory=set)
    start_refusal: dict[str, Any] | None = None
    """The details a refused start carries."""
    refuse_estimate: dict[uuid.UUID, str] = field(default_factory=dict)
    """The reason pricing a dataset's questions is refused with, by the dataset's id."""
    asked: int | None = None
    """How many questions a priced stage asks, when fewer than it names."""
    held_out: int = 5
    """The gradable held-out questions a stage's run compares when it asks a whole
    dataset; one asking named questions compares those."""
    started: list[tuple[uuid.UUID, Any]] = field(default_factory=list)
    served: list[Any] = field(default_factory=list)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = self

        async def estimate(_self, _ctx, agent_id, request, **_):
            if request.dataset_id in fake.refuse_estimate:
                raise BadRequestError(
                    message="Refused",
                    details={
                        "reason": fake.refuse_estimate[request.dataset_id],
                        "dataset_id": request.dataset_id,
                    },
                )
            cases = len(request.case_ids) if request.case_ids else 4
            total = fake.per_case * 2 * cases
            return SimpleNamespace(
                cases=cases if fake.asked is None else fake.asked,
                total_usd=total,
                rerun_ceiling_usd=total * 2,
                agent_remaining_usd=fake.agent_left,
                org_remaining_usd=fake.org_left,
            )

        async def start(_self, ctx, agent_id, request, *, candidate_skills=None, **_):
            if agent_id in fake.refuse_start:
                raise BadRequestError(message="Cannot start", details=fake.start_refusal)
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
                id=run_id,
                agent_id=agent_id,
                status=EvalRunStatus.RUNNING.value,
                held_out=len(request.case_ids) if request.case_ids else fake.held_out,
                dataset_id=dataset.id,
            )
            fake.started.append((agent_id, request))
            fake.served.append(candidate_skills)
            return SimpleNamespace(id=run_id)

        async def compare(_self, _ctx, run_id, *, holdout_minimum=True, **_):
            outcome = fake.outcomes.get(fake.runs[run_id].agent_id, Outcome())
            held_out = fake.runs[run_id].held_out
            too_few = holdout_minimum and held_out < MIN_HOLDOUT_CASES
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
                verdict="invalid" if too_few else "better",
                regressions_confirmed=outcome.broken,
                fixed_confirmed=outcome.fixed,
                fixed_unconfirmed=0,
                regressions_unconfirmed=outcome.unconfirmed_broken,
                compared=held_out,
                not_compared=0,
                changed=0,
                gradable_holdout=held_out,
                cases=_flips(outcome, held_out),
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


async def _statuses(db: AsyncSession, evals: FakeEvals) -> list[str]:
    """The stored status of every eval run the check started."""
    statuses = []
    for run_id in evals.runs:
        run = await db.get(EvalRun, run_id)
        assert run is not None
        await db.refresh(run)
        statuses.append(run.status)
    return statuses


def _start(**values: Any) -> SkillCheckStart:
    return SkillCheckStart(candidate=NEW, **values)


async def _run_to_end(service: SkillCheckService, evals: FakeEvals, lab: Lab, check_id):
    for _ in range(3):
        evals.finish_all()
        await service.advance(check_id, lab.ctx.organization_id)
    return await service.read(lab.ctx, lab.skill.id, check_id)


async def _run_against(db: AsyncSession, lab: Lab, agent: Agent):
    """A dataset made in Datasets, for no agent, that `agent` finished an eval run on."""
    dataset = await _dataset(db, lab.ctx, "run-against")
    version = await dataset_repo.create_version(
        db,
        dataset_id=dataset.id,
        organization_id=lab.ctx.organization_id,
        number=1,
        case_count=dataset.case_count,
        change="add",
        changed_cases=0,
        created_by_user_id=lab.ctx.user_id,
    )
    dataset.latest_version = 1
    db.add(
        EvalRun(
            organization_id=lab.ctx.organization_id,
            agent_id=agent.id,
            dataset_id=dataset.id,
            dataset_version_id=version.id,
            created_by_user_id=lab.ctx.user_id,
            status=EvalRunStatus.COMPLETED.value,
            scoring={},
            scoring_hash="a" * 64,
            estimate_usd=Decimal("0.1"),
        )
    )
    await db.flush()
    return dataset


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

    async def test_a_dataset_the_agent_was_run_against_is_its_own_questions(self, db, monkeypatch):
        """A dataset made in Datasets names no agent; the one an agent's eval ran on is
        the agent's own questions all the same, as the Datasets list filtered by it says."""
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        dataset = await _run_against(db, lab, lab.c)
        picked = [uuid.uuid4()]

        async def sample(_self, _ctx, _skill, agent_id, asked, _words, _allowed=None, **_):
            return picked if asked.id == dataset.id else []

        monkeypatch.setattr(SkillCheckService, "_sample", sample)
        service = SkillCheckService(db)

        quick = await service.estimate(lab.ctx, lab.skill.id, _start())
        thorough = await service.estimate(lab.ctx, lab.skill.id, _start(mode="thorough"))

        c = next(row for row in quick.agents if row.agent.name == "C")
        assert c.sample == "own_questions"
        assert [(stage.kind, stage.dataset_id) for stage in c.stages][1:] == [
            ("dataset_sample", dataset.id)
        ]
        c = next(row for row in thorough.agents if row.agent.name == "C")
        assert [(stage.kind, stage.dataset_id) for stage in c.stages][1:] == [
            ("dataset", dataset.id)
        ]

    async def test_a_dataset_made_for_the_agent_comes_before_one_it_was_run_against(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        await _run_against(db, lab, lab.a)

        estimate = await SkillCheckService(db).estimate(
            lab.ctx, lab.skill.id, _start(mode="thorough")
        )

        a = next(row for row in estimate.agents if row.agent.name == "A")
        [own] = [stage for stage in a.stages if stage.kind == "dataset"]
        assert own.dataset_name is not None and own.dataset_name.startswith("a-own")

    async def test_a_dataset_the_starter_may_not_see_is_not_asked(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        hidden = await _run_against(db, lab, lab.c)
        real = skill_check_module.accessible_ids

        async def accessible(db, ctx, rows, wanted, **kwargs):
            found = await real(db, ctx, rows, wanted, **kwargs)
            return found - {hidden.id} if wanted is Perm.DATASETS_VIEW else found

        monkeypatch.setattr(skill_check_module, "accessible_ids", accessible)

        estimate = await SkillCheckService(db).estimate(
            lab.ctx, lab.skill.id, _start(mode="thorough")
        )

        c = next(row for row in estimate.agents if row.agent.name == "C")
        assert [stage.kind for stage in c.stages] == ["skill_set"]

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

        async def sample(_self, _ctx, _skill, agent_id, _dataset, _words, _allowed=None, **_):
            return picked if agent_id == lab.a.id else []

        monkeypatch.setattr(SkillCheckService, "_sample", sample)

        estimate = await SkillCheckService(db).estimate(lab.ctx, lab.skill.id, _start())

        a = next(row for row in estimate.agents if row.agent.name == "A")
        assert a.sample == "own_questions"
        assert [(stage.kind, stage.cases) for stage in a.stages] == [
            ("skill_set", 4),
            ("dataset_sample", 2),
        ]

    @pytest.mark.parametrize(
        ("outcomes", "states", "result"),
        [
            (
                {"a": Outcome(fixed=1), "b": Outcome(broken=2)},
                {"A": AgentState.BETTER, "B": AgentState.WORSE},
                CheckVerdict.BLOCKED,
            ),
            (
                {"a": Outcome(fixed=1)},
                {"A": AgentState.BETTER, "B": AgentState.NO_CHANGE},
                CheckVerdict.PASSED,
            ),
        ],
    )
    async def test_stages_too_small_alone_are_judged_together(
        self, db, monkeypatch, outcomes, states, result
    ):
        """Three held-out questions per stage are too few for any stage, and six for the
        agent are enough: a confirmed regression blocks, a confirmed fix passes."""
        lab = await _lab(db)
        evals = FakeEvals(held_out=3)
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(
            lab.ctx,
            lab.skill.id,
            _start(mode="thorough"),
            source=CheckSource.SESSION,
            only=[lab.a.id, lab.b.id],
        )
        evals.outcomes = {getattr(lab, key).id: value for key, value in outcomes.items()}

        read = await _run_to_end(service, evals, lab, check.id)

        assert {row.agent.name: row.state for row in read.agents} == states
        assert read.verdict is result

    async def test_one_stage_too_small_on_its_own_leaves_the_agent_unknown(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals(held_out=3)
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(
            lab.ctx, lab.skill.id, _start(), source=CheckSource.SESSION, only=[lab.c.id]
        )
        evals.outcomes = {lab.c.id: Outcome(fixed=1)}

        read = await _run_to_end(service, evals, lab, check.id)

        [c] = read.agents
        assert (c.state, c.unknown_reason) == (AgentState.UNKNOWN, UnknownReason.INCONCLUSIVE)

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
        assert read.candidate == NEW

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

    @pytest.mark.parametrize(("mode", "b_stages"), [("quick", 1), ("thorough", 2)])
    async def test_a_regression_in_the_skill_set_stops_only_a_quick_check_early(
        self, db, monkeypatch, mode: str, b_stages: int
    ):
        """A quick check is cheap and stops there; a thorough one is paid for in full and
        asks the agent's own questions too, so its row shows where the agent broke."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)

        async def sample(_self, _ctx, _skill, _agent_id, _dataset, _words, _allowed=None, **_):
            return [uuid.uuid4()]

        monkeypatch.setattr(SkillCheckService, "_sample", sample)
        service = SkillCheckService(db)
        check = await service.start(
            lab.ctx, lab.skill.id, SkillCheckStart(candidate=NEW, mode=mode)
        )
        evals.outcomes = {lab.b.id: Outcome(broken=1), lab.a.id: Outcome(fixed=1)}

        read = await _run_to_end(service, evals, lab, check.id)

        started = [agent for agent, _ in evals.started]
        assert started.count(lab.b.id) == b_stages
        assert started.count(lab.a.id) == 2
        assert read.verdict is CheckVerdict.BLOCKED

    async def test_a_quick_check_stops_at_a_regression_on_a_small_skill_set(self, db, monkeypatch):
        """A confirmed regression stops a quick check however few held-out questions found
        it, the rule the agent is judged by, so the agent's own sample is not paid for."""
        lab = await _lab(db)
        evals = FakeEvals(held_out=3)
        evals.install(monkeypatch)

        async def sample(_self, _ctx, _skill, _agent_id, _dataset, _words, _allowed=None, **_):
            return [uuid.uuid4()]

        monkeypatch.setattr(SkillCheckService, "_sample", sample)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.b.id: Outcome(broken=1), lab.a.id: Outcome(fixed=1)}

        read = await _run_to_end(service, evals, lab, check.id)

        assert [agent for agent, _ in evals.started].count(lab.b.id) == 1
        assert read.verdict is CheckVerdict.BLOCKED

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
        assert read.verdict is CheckVerdict.NEEDS_ACK


async def _stage_runs(db: AsyncSession, lab: Lab, check_id: uuid.UUID, agent: Agent):
    """The eval runs the check ran for `agent`, each stage it reached."""
    rows = await skill_check_repo.list_agents(
        db, [check_id], organization_id=lab.ctx.organization_id
    )
    [row] = [row for row in rows if row.agent_id == agent.id]
    return [run_id for run_id in (row.skill_set_run_id, row.dataset_run_id) if run_id]


class TestAPersonsVerdict:
    """A person's verdict on an answer a stage graded changes what the check says."""

    @pytest.mark.parametrize("source", [CheckSource.MANUAL, CheckSource.SESSION])
    async def test_a_regression_a_person_overturns_lets_the_change_pass(
        self, db, monkeypatch, source
    ):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start(), source=source)
        evals.outcomes = {lab.a.id: Outcome(fixed=2), lab.b.id: Outcome(broken=1)}
        assert (await _run_to_end(service, evals, lab, check.id)).verdict is CheckVerdict.BLOCKED

        evals.outcomes[lab.b.id] = Outcome()
        await service.recompute_after_review(
            lab.ctx.organization_id, await _stage_runs(db, lab, check.id, lab.b)
        )

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        states = {row.agent.name: row.state for row in read.agents}
        assert states == {"A": "better", "B": "no_change", "C": "no_change"}
        assert (read.status, read.verdict) == (CheckStatus.DONE, CheckVerdict.PASSED)

    async def test_a_verdict_on_a_run_no_check_asked_changes_nothing(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.b.id: Outcome(broken=1)}
        await _run_to_end(service, evals, lab, check.id)
        evals.outcomes = {}

        await service.recompute_after_review(lab.ctx.organization_id, [])
        await service.recompute_after_review(lab.ctx.organization_id, [uuid.uuid4()])

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert read.verdict is CheckVerdict.BLOCKED

    async def test_an_agent_whose_run_failed_stays_unknown(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        for run in evals.runs.values():
            run.status = EvalRunStatus.FAILED.value
        await service.advance(check.id, lab.ctx.organization_id)
        evals.outcomes = {lab.a.id: Outcome(fixed=2)}

        await service.recompute_after_review(lab.ctx.organization_id, list(evals.runs))

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert {row.unknown_reason for row in read.agents} == {"failed"}
        assert read.verdict is CheckVerdict.NEEDS_ACK

    @pytest.mark.security
    @pytest.mark.parametrize("starter", ["gone", "key_revoked"])
    async def test_a_check_nobody_may_read_any_more_is_left_as_it_was(
        self, db, monkeypatch, starter
    ):
        """The reviewer's own access never reads the agents of somebody else's check."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.b.id: Outcome(broken=1)}
        await _run_to_end(service, evals, lab, check.id)
        evals.outcomes = {}

        async def job_context(*_: Any, **__: Any) -> AuthContext | None:
            if starter == "key_revoked":
                raise AuthenticationError(message="Key gone")
            return None

        monkeypatch.setattr(skill_check_module, "job_context", job_context)
        await service.recompute_after_review(lab.ctx.organization_id, list(evals.runs))

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert read.verdict is CheckVerdict.BLOCKED

    async def test_an_agent_the_starter_may_no_longer_read_keeps_its_result(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.b.id: Outcome(broken=1)}
        await _run_to_end(service, evals, lab, check.id)
        evals.outcomes = {}

        async def refused(*_: Any, **__: Any) -> None:
            raise AuthorizationError(message="No access")

        monkeypatch.setattr(SkillCheckService, "_judge", refused)
        await service.recompute_after_review(lab.ctx.organization_id, list(evals.runs))

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert {row.agent.name: row.state for row in read.agents}["B"] == "worse"
        assert read.verdict is CheckVerdict.BLOCKED

    async def test_a_cancelled_check_is_left_as_it_was(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        await service.cancel(lab.ctx, lab.skill.id, check.id)

        await service.recompute_after_review(lab.ctx.organization_id, list(evals.runs))

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert (read.status, read.verdict) == (CheckStatus.CANCELLED, None)

    async def test_a_running_check_gets_its_verdict_when_its_last_agent_settles(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)

        async def sample(_self, _ctx, _skill, _agent_id, _dataset, _words, _allowed=None, **_):
            return [uuid.uuid4()]

        monkeypatch.setattr(SkillCheckService, "_sample", sample)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.a.id: Outcome(fixed=1), lab.b.id: Outcome(broken=1)}
        evals.finish_all()
        await service.advance(check.id, lab.ctx.organization_id)
        evals.outcomes[lab.b.id] = Outcome()

        await service.recompute_after_review(
            lab.ctx.organization_id, await _stage_runs(db, lab, check.id, lab.b)
        )

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert {row.agent.name: row.state for row in read.agents}["B"] == "unknown"
        assert (read.status, read.verdict) == (CheckStatus.RUNNING, None)
        read = await _run_to_end(service, evals, lab, check.id)
        assert read.verdict is CheckVerdict.NEEDS_ACK

    async def test_an_overturned_regression_whose_own_questions_went_unasked_is_unknown(
        self, db, monkeypatch
    ):
        """A quick check leaves an agent's own questions once the skill's make it worse;
        with that regression taken back, nothing it was asked says how it fares."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)

        async def sample(_self, _ctx, _skill, _agent_id, _dataset, _words, _allowed=None, **_):
            return [uuid.uuid4()]

        monkeypatch.setattr(SkillCheckService, "_sample", sample)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        evals.outcomes = {lab.a.id: Outcome(fixed=1), lab.b.id: Outcome(broken=1)}
        read = await _run_to_end(service, evals, lab, check.id)
        b = next(row for row in read.agents if row.agent.name == "B")
        assert (b.state, b.sample) == ("worse", "own_not_asked")
        assert [stage.kind for stage in b.stages] == ["skill_set"]

        evals.outcomes[lab.b.id] = Outcome()
        runs = await _stage_runs(db, lab, check.id, lab.b)
        await service.recompute_after_review(lab.ctx.organization_id, runs)

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        b = next(row for row in read.agents if row.agent.name == "B")
        assert (b.state, b.unknown_reason, b.sample) == (
            "unknown",
            "own_not_asked",
            "own_not_asked",
        )
        assert read.verdict is CheckVerdict.NEEDS_ACK

        evals.outcomes[lab.b.id] = Outcome(broken=1)
        await service.recompute_after_review(lab.ctx.organization_id, runs)

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert {row.agent.name: row.state for row in read.agents}["B"] == "worse"
        assert read.verdict is CheckVerdict.BLOCKED


class TestAStageThatCannotMeasure:
    """One stage's questions nothing can grade, or that all come from the change's own
    evidence, skip that stage - never the whole check."""

    @pytest.mark.parametrize(
        ("reason", "unknown"),
        [
            ("no_scorer", "unscorable"),
            ("all_evidence", "all_evidence"),
            ("only_anonymised", "no_questions"),
        ],
    )
    async def test_the_stage_is_skipped_and_the_rest_runs(self, db, monkeypatch, reason, unknown):
        lab = await _lab(db)
        test_set = await dataset_repo.for_skill(
            db, lab.skill.id, organization_id=lab.ctx.organization_id
        )
        assert test_set is not None
        evals = FakeEvals(refuse_estimate={test_set.id: reason})
        evals.install(monkeypatch)
        service = SkillCheckService(db)

        check = await service.start(lab.ctx, lab.skill.id, _start(mode="thorough"))

        rows = {row.agent.name: row for row in check.agents}
        assert [stage.kind for stage in rows["A"].stages] == ["dataset"]
        assert (rows["C"].state, rows["C"].unknown_reason) == ("unknown", unknown)
        assert rows["C"].stages == []
        evals.outcomes = {lab.a.id: Outcome(fixed=1)}
        read = await _run_to_end(service, evals, lab, check.id)
        assert {row.agent.name: row.state for row in read.agents} == {
            "A": "better",
            "B": "no_change",
            "C": "unknown",
        }
        assert read.verdict is CheckVerdict.NEEDS_ACK

    async def test_an_own_sample_nothing_can_grade_leaves_the_skill_set_alone(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        own = await _dataset(db, lab.ctx, "ungradable", agent=lab.c)
        FakeEvals(refuse_estimate={own.id: "no_scorer"}).install(monkeypatch)

        async def sample(_self, _ctx, _skill, _agent_id, asked, _words, _allowed=None, **_):
            return [uuid.uuid4()] if asked.id == own.id else []

        monkeypatch.setattr(SkillCheckService, "_sample", sample)

        estimate = await SkillCheckService(db).estimate(lab.ctx, lab.skill.id, _start())

        c = next(row for row in estimate.agents if row.agent.name == "C")
        assert (c.state, c.sample) == ("queued", "skill_set_only")
        assert [stage.kind for stage in c.stages] == ["skill_set"]

    async def test_any_other_refusal_still_refuses_the_check(self, db, monkeypatch):
        lab = await _lab(db)
        test_set = await dataset_repo.for_skill(
            db, lab.skill.id, organization_id=lab.ctx.organization_id
        )
        assert test_set is not None
        FakeEvals(refuse_estimate={test_set.id: "no_reruns"}).install(monkeypatch)

        with pytest.raises(BadRequestError):
            await SkillCheckService(db).start(lab.ctx, lab.skill.id, _start())

    async def test_a_sessions_check_of_its_own_evidence_alone_is_refused(self, db, monkeypatch):
        """An Improve session leaves out its evidence; when no agent has a question
        beyond it, the refusal names the dataset to add others to, before anything is
        paid for. A check by hand, with no evidence left out, waits for acknowledgement."""
        lab = await _lab(db)
        test_set = await dataset_repo.for_skill(
            db, lab.skill.id, organization_id=lab.ctx.organization_id
        )
        assert test_set is not None
        FakeEvals(refuse_estimate={test_set.id: "all_evidence"}).install(monkeypatch)
        service = SkillCheckService(db)
        evidence = [uuid.uuid4()]

        with pytest.raises(BadRequestError) as refused:
            await service.estimate(lab.ctx, lab.skill.id, _start(), exclude_conversations=evidence)
        with pytest.raises(BadRequestError):
            await service.start(
                lab.ctx,
                lab.skill.id,
                _start(),
                source=CheckSource.SESSION,
                exclude_conversations=evidence,
            )

        assert refused.value.details == {"reason": "all_evidence", "dataset_id": test_set.id}
        assert await skill_check_repo.list_for_skill(
            db,
            organization_id=lab.ctx.organization_id,
            skill_id=lab.skill.id,
            fork_id=None,
            skip=0,
            limit=5,
        ) == ([], 0)
        by_hand = await service.start(lab.ctx, lab.skill.id, _start())
        assert by_hand.verdict is CheckVerdict.NEEDS_ACK

    async def test_another_refusal_after_a_skipped_stage_still_refuses_the_check(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        test_set = await dataset_repo.for_skill(
            db, lab.skill.id, organization_id=lab.ctx.organization_id
        )
        own = await dataset_repo.testing_agent(
            db, lab.a.id, organization_id=lab.ctx.organization_id
        )
        assert test_set is not None and own
        FakeEvals(refuse_estimate={test_set.id: "no_scorer", own[0].id: "archived"}).install(
            monkeypatch
        )

        with pytest.raises(BadRequestError):
            await SkillCheckService(db).start(lab.ctx, lab.skill.id, _start(mode="thorough"))

    async def test_an_agent_asked_nothing_names_no_sample(self, db, monkeypatch):
        lab = await _lab(db)
        test_set = await dataset_repo.for_skill(
            db, lab.skill.id, organization_id=lab.ctx.organization_id
        )
        own = await _dataset(db, lab.ctx, "ungradable", agent=lab.c)
        assert test_set is not None
        FakeEvals(refuse_estimate={test_set.id: "no_scorer", own.id: "all_evidence"}).install(
            monkeypatch
        )

        async def sample(_self, _ctx, _skill, _agent_id, asked, _words, _allowed=None, **_):
            return [uuid.uuid4()] if asked.id == own.id else []

        monkeypatch.setattr(SkillCheckService, "_sample", sample)

        estimate = await SkillCheckService(db).estimate(lab.ctx, lab.skill.id, _start())

        c = next(row for row in estimate.agents if row.agent.name == "C")
        assert (c.state, c.unknown_reason, c.sample, c.stages) == (
            "unknown",
            "unscorable",
            None,
            [],
        )

    async def test_a_stage_refused_as_it_starts_says_why(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals(refuse_start={lab.c.id}, start_refusal={"reason": "all_evidence"}).install(
            monkeypatch
        )

        check = await SkillCheckService(db).start(lab.ctx, lab.skill.id, _start())

        c = next(row for row in check.agents if row.agent.name == "C")
        assert (c.state, c.unknown_reason) == ("unknown", "all_evidence")

    async def test_a_stage_counts_the_questions_it_asks(self, db, monkeypatch):
        """The questions taken from the change's own conversations are not asked, so
        they are not counted as asked either."""
        lab = await _lab(db)
        FakeEvals(asked=1).install(monkeypatch)

        estimate = await SkillCheckService(db).estimate(lab.ctx, lab.skill.id, _start())

        a = next(row for row in estimate.agents if row.agent.name == "A")
        assert [(stage.kind, stage.cases) for stage in a.stages] == [("skill_set", 1)]


class TestNothingToRun:
    async def test_a_line_nobody_reads_passes_at_once_and_applies(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        assert lab.skill.latest_version_id is not None
        empty = await SkillVersionService(db).create_fork(
            lab.ctx,
            lab.skill.id,
            SkillForkCreate(name="unread", from_version_id=lab.skill.latest_version_id),
        )
        service = SkillCheckService(db)

        check = await service.start(lab.ctx, lab.skill.id, _start(fork_id=empty.id))

        assert (check.status, check.verdict, check.agents, check.hidden) == (
            CheckStatus.DONE,
            CheckVerdict.PASSED,
            [],
            0,
        )
        assert check.no_readers and evals.started == []
        applied = await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply())
        assert (applied.version.fork_id, applied.version.content) == (empty.id, NEW.content)

    async def test_a_check_whose_agents_were_deleted_is_no_better(self, db, monkeypatch):
        """Deleting an agent deletes its row of the check: a check left with none was not
        one of a line nobody reads, and passes nothing."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        await db.execute(delete(SkillCheckAgent).where(SkillCheckAgent.check_id == check.id))

        await service.advance(check.id, lab.ctx.organization_id)

        read = await service.read(lab.ctx, lab.skill.id, check.id)
        assert (read.status, read.verdict, read.no_readers) == (
            CheckStatus.DONE,
            CheckVerdict.NO_BETTER,
            False,
        )

    async def test_a_line_none_of_whose_agents_can_be_checked_waits_for_an_acknowledgement(
        self, db, monkeypatch
    ):
        lab = await _lab(db)
        evals = FakeEvals(agent_left=Decimal("0.01"))
        evals.install(monkeypatch)
        service = SkillCheckService(db)

        check = await service.start(lab.ctx, lab.skill.id, _start())

        assert {row.unknown_reason for row in check.agents} == {"no_budget"}
        assert (check.status, check.verdict) == (CheckStatus.DONE, CheckVerdict.NEEDS_ACK)
        assert not check.no_readers and evals.started == []
        with pytest.raises(BadRequestError):
            await service.apply(lab.ctx, lab.skill.id, check.id, SkillCheckApply())
        applied = await service.apply(
            lab.ctx, lab.skill.id, check.id, SkillCheckApply(acknowledge_unknown=True)
        )
        assert applied.version.content == NEW.content


class TestStartingAndStopping:
    async def test_the_same_check_started_again_while_it_runs_is_that_check(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)

        first = await service.start(lab.ctx, lab.skill.id, _start())
        started = len(evals.started)
        again = await service.start(lab.ctx, lab.skill.id, _start())

        assert again.id == first.id and len(evals.started) == started
        other = CandidateText(description=NEW.description, content="Another text")
        thorough = await service.start(lab.ctx, lab.skill.id, _start(mode="thorough"))
        another = await service.start(lab.ctx, lab.skill.id, SkillCheckStart(candidate=other))
        assert len({first.id, thorough.id, another.id}) == 3
        await service.cancel(lab.ctx, lab.skill.id, first.id)
        assert (await service.start(lab.ctx, lab.skill.id, _start())).id != first.id

    async def test_a_cancelled_check_leaves_no_agent_running(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals(refuse_start={lab.c.id}).install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())

        read = await service.cancel(lab.ctx, lab.skill.id, check.id)

        assert {(row.agent.name, row.state, row.unknown_reason) for row in read.agents} == {
            ("A", "unknown", "cancelled"),
            ("B", "unknown", "cancelled"),
            ("C", "unknown", "failed"),
        }


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

    @pytest.mark.security
    async def test_an_agent_is_told_which_versions_its_own_answers_used(self, db):
        """A version an agent answered with before is not news to it; an eval's or a
        Builder test's answer does not count, and only a reader of runs learns either."""
        lab = await _lab(db)
        served = lab.skill.latest_version_id
        assert served is not None

        async def answered(agent: Agent, **run: Any) -> None:
            started = datetime.now(UTC)
            row = AgentRun(
                id=uuid.uuid4(),
                organization_id=lab.ctx.organization_id,
                agent_id=agent.id,
                status="completed",
                started_at=started,
                **{"surface": RunSurface.WEB.value, "is_test": False, **run},
            )
            db.add(row)
            await db.flush()
            await skill_usage_repo.record_uses(
                db,
                [
                    SkillUseRecord(
                        agent_id=agent.id,
                        skill_id=lab.skill.id,
                        skill_version_id=served,
                        loaded=True,
                    )
                ],
                organization_id=lab.ctx.organization_id,
                run_id=row.id,
                started_at=started,
            )

        await answered(lab.a)
        await answered(lab.b, surface=RunSurface.EVAL.value)
        await answered(lab.b, is_test=True)

        rows = {
            row.agent.name: row
            for row in (await SkillAgentService(db).agents(lab.ctx, lab.skill.id)).items
        }
        assert rows["A"].answered_with == [served]
        assert rows["B"].answered_with == []
        blind = replace(lab.ctx, key_scopes=frozenset(Perm) - {Perm.RUNS_VIEW})
        unseen = await SkillAgentService(db).agents(blind, lab.skill.id)
        assert all(row.answered_with == [] for row in unseen.items)

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
        assert await _statuses(db, evals) == [EvalRunStatus.CANCELLED.value] * len(evals.runs)
        discarded = await service.discard(lab.ctx, lab.skill.id, check.id)
        assert discarded.status is CheckStatus.DISCARDED

    @pytest.mark.security
    async def test_anyone_who_edits_the_skill_stops_a_check_whatever_runs_they_see(
        self, db, monkeypatch
    ):
        """Edit access to the skill is the authority: stopping needs no grant on each run."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        check = await SkillCheckService(db).start(lab.ctx, lab.skill.id, _start())
        # A key that edits the skill and reads runs, but sees none of the check's agents.
        key = replace(
            lab.ctx, key_scopes=frozenset({Perm.SKILLS_VIEW, Perm.SKILLS_EDIT, Perm.RUNS_VIEW})
        )

        cancelled = await SkillCheckService(db).cancel(key, lab.skill.id, check.id)

        assert cancelled.status is CheckStatus.CANCELLED
        assert await _statuses(db, evals) == [EvalRunStatus.CANCELLED.value] * len(evals.runs)


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
        assert [item.proposal_id for item in await service.awaiting(lab.ctx)] == [proposal.id]

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


class TestAwaiting:
    """What "Waiting for you" lists: checks a person started and has to come back to."""

    async def test_a_check_left_open_waits_until_it_is_decided(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())

        [running] = await service.awaiting(lab.ctx)
        assert (running.id, running.skill_name, running.line.name, running.agents) == (
            check.id,
            lab.skill.name,
            "main",
            3,
        )
        assert running.status is CheckStatus.RUNNING
        assert running.proposal_id is None
        evals.outcomes = {lab.a.id: Outcome(fixed=2), lab.b.id: Outcome(), lab.c.id: Outcome()}
        await _run_to_end(service, evals, lab, check.id)
        [done] = await service.awaiting(lab.ctx)
        assert (done.status, done.verdict) == (CheckStatus.DONE, CheckVerdict.PASSED)

        await service.discard(lab.ctx, lab.skill.id, check.id)
        assert await service.awaiting(lab.ctx) == []

    async def test_checks_on_main_and_a_fork_are_listed_by_line_newest_first(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        service = SkillCheckService(db)
        on_main = await service.start(lab.ctx, lab.skill.id, _start())
        on_fork = await service.start(lab.ctx, lab.skill.id, _start(fork_id=lab.fork_id))

        listed = await service.awaiting(lab.ctx)

        assert {item.id: item.line.name for item in listed} == {
            on_main.id: "main",
            on_fork.id: on_fork.line.name,
        }
        assert on_fork.line.name != "main"

    async def test_a_check_a_session_or_a_catch_up_decides_is_not_listed(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        service = SkillCheckService(db)
        check = await service.start(lab.ctx, lab.skill.id, _start())
        row = await skill_check_repo.get(db, check.id, organization_id=lab.ctx.organization_id)
        assert row is not None

        for source in ("session", "catch_up"):
            await skill_check_repo.update(db, row=row, values={"source": source})
            assert await service.awaiting(lab.ctx) == []

    @pytest.mark.security
    async def test_only_who_may_decide_it_sees_it(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        service = SkillCheckService(db)
        await service.start(lab.ctx, lab.skill.id, _start())
        operator = await _member(db, lab.ctx, OrgRoleName.OPERATOR)
        viewer = await _member(db, lab.ctx, OrgRoleName.VIEWER)

        assert await service.awaiting(operator) == []
        with pytest.raises(AuthorizationError):
            await service.awaiting(viewer)


class TestTestSet:
    async def test_a_skill_gets_one_set_of_test_questions(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx, name="tests-only")
        service = SkillCheckService(db)

        with pytest.raises(NotFoundError):
            await service.test_set(ctx, skill.id)
        created = await service.create_test_set(ctx, skill.id, SkillTestSetStart())

        assert (await service.test_set(ctx, skill.id)).id == created.id
        assert created.skill_id == skill.id
        # Every question it gets is held out: it measures changes, nothing learns from it.
        assert created.improvement_holdout_share == 1
        with pytest.raises(AlreadyExistsError):
            await service.create_test_set(ctx, skill.id, SkillTestSetStart())

    async def test_a_set_the_reader_may_not_open_is_said_apart_from_none(self, db):
        ctx = await _owner(db)
        skill = await _skill(db, ctx, name="tests-hidden")
        await SkillCheckService(db).create_test_set(ctx, skill.id, SkillTestSetStart())
        reader = replace(ctx, key_scopes=frozenset({Perm.SKILLS_VIEW}))

        with pytest.raises(AuthorizationError) as refused:
            await SkillCheckService(db).test_set(reader, skill.id)

        assert refused.value.details["reason"] == "test_set_hidden"


class TestAMergedText:
    async def test_its_files_are_the_whole_set_the_check_serves(self, db, monkeypatch):
        lab = await _lab(db)
        FakeEvals().install(monkeypatch)
        files = (SkillBodyFile(name="merged.md", description="Merged", content="both sides"),)

        read = await SkillCheckService(db).start(
            lab.ctx, lab.skill.id, _start(), source=CheckSource.SESSION, files=files
        )

        check = await skill_check_repo.get(db, read.id, organization_id=lab.ctx.organization_id)
        assert check is not None
        assert check.candidate_resources == {
            "merged.md": {"description": "Merged", "content": "both sides"}
        }


class TestASessionsDecision:
    async def test_only_a_finished_undecided_check_is_decided_by_its_session(self, db, monkeypatch):
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        read = await service.start(lab.ctx, lab.skill.id, _start(), source=CheckSource.SESSION)

        with pytest.raises(ConcurrentChangeError):
            await service.decidable_for_session(lab.ctx, lab.skill.id, read.id)
        await _run_to_end(service, evals, lab, read.id)
        check = await service.decidable_for_session(lab.ctx, lab.skill.id, read.id)
        await service.discard(lab.ctx, lab.skill.id, read.id, from_session=True)

        assert check.id == read.id
        with pytest.raises(AlreadyExistsError):
            await service.decidable_for_session(lab.ctx, lab.skill.id, read.id)

    async def test_a_check_its_session_moved_past_is_set_aside_and_offers_nothing(
        self, db, monkeypatch
    ):
        """Only its session decides it, and the session went on: nothing waits on it."""
        lab = await _lab(db)
        evals = FakeEvals()
        evals.install(monkeypatch)
        service = SkillCheckService(db)
        read = await service.start(lab.ctx, lab.skill.id, _start(), source=CheckSource.SESSION)
        await _run_to_end(service, evals, lab, read.id)
        check = await skill_check_repo.get(db, read.id, organization_id=lab.ctx.organization_id)
        assert check is not None

        await service.set_aside_for_session(check)

        after = await service.read(lab.ctx, lab.skill.id, read.id)
        assert (after.status, after.outcome, after.outcomes) == ("discarded", "discard", [])


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
