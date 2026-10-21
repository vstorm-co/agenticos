"""Eval runs end to end against Postgres, with the model replaced by a scripted answer.

The runner's own behaviour - isolation, budgets before each request, version
attribution - is covered where it lives. What only a database shows is here:

- a 20-case run of a draft is twenty eval runs, none attributed to a version;
- a run past the budget is refused before anything is written or called, and
  a cancelled run or one that ran out of budget starts no further case;
- a case that passed on v6 and fails on v7 is a regression, confirmed by
  reruns, and one flip is reported as too small a sample to be a verdict;
- a baseline in the same run is reused when everything matches;
- one run over two models reports each;
- nothing crosses organizations, and access is the dataset's and the agent's.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.isolation import ToolRecording
from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
    NothingToScoreError,
    PaymentRequiredError,
)
from app.core.permissions import ROLE_PERMS, AuthContext, OrgRoleName, Perm, Scope
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.case_score import CaseScore
from app.db.models.conversation import Conversation
from app.db.models.credential import ModelProfile
from app.db.models.dataset import Dataset, DatasetCase
from app.db.models.eval_run import EvalRun, EvalRunArm, EvalRunCase, EvalRunPurpose, EvalRunStatus
from app.db.models.intercepted_tool_call import InterceptedToolCall
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, ResourceGrant
from app.db.models.user import User
from app.repositories import eval_run_repo
from app.schemas.agent_environment import EnvironmentCreate
from app.schemas.dataset import DatasetCaseCreate, DatasetCaseUpdate, DatasetCreate
from app.schemas.eval_run import EvalRunRequest
from app.schemas.scoring import CaseVerdict, RescoreRequest
from app.services.agent_environment import AgentEnvironmentService
from app.services.agent_registry import (
    AgentRegistryService,
    PublishedCandidate,
    UnpublishedCandidate,
)
from app.services.agent_runner import AgentRunnerService
from app.services.dataset import DatasetService
from app.services.eval_run import EvalRunService
from app.services.eval_run_worker import EvalRunWorker
from app.services.model_profile import ModelProfileService
from app.services.scorers import JUDGE_PROMPT_VERSION
from app.services.scoring import ScoringService
from app.services.transcript import RecordedToolCall

pytestmark = pytest.mark.anyio

_PASS = "You have 30 days to return it."
_FAIL = "You have 90 days."


async def _user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _owner(db: AsyncSession) -> AuthContext:
    user = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="owner")
    )
    await db.flush()
    return AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER.value)


async def _member(db: AsyncSession, ctx: AuthContext, role: OrgRoleName) -> AuthContext:
    user = await _user(db)
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=ctx.organization_id, user_id=user.id, role=role.value
        )
    )
    await db.flush()
    return AuthContext(user_id=user.id, organization_id=ctx.organization_id, role=role.value)


async def _agent(db: AsyncSession, ctx: AuthContext) -> tuple[Agent, dict[int, AgentVersion]]:
    """An agent published twice - v6 and v7 - visible to the organization."""
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility="org",
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        status="published",
        draft_spec={"name": "Clerk", "instructions": "Being edited"},
    )
    db.add(agent)
    await db.flush()
    versions = {}
    for number in (6, 7):
        versions[number] = AgentVersion(
            id=uuid.uuid4(),
            agent_id=agent.id,
            organization_id=ctx.organization_id,
            version=number,
            spec={"name": "Clerk", "instructions": f"v{number}"},
        )
        db.add(versions[number])
    await db.flush()
    agent.current_version_id = versions[7].id
    await db.flush()
    return agent, versions


async def _dataset(db: AsyncSession, ctx: AuthContext, *, cases: int) -> Dataset:
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name=f"refunds-{uuid.uuid4().hex[:6]}"))
    for index in range(cases):
        await service.add_case(
            ctx,
            dataset.id,
            DatasetCaseCreate(
                input=f"Question {index}",
                checks=[{"type": "contains", "value": "30 days"}],
                tags=["refunds"] if index % 2 == 0 else [],
            ),
        )
    stored = await db.get(Dataset, dataset.id)
    assert stored is not None
    return stored


async def _profile(db: AsyncSession, ctx: AuthContext, label: str) -> ModelProfile:
    profile = ModelProfile(
        organization_id=ctx.organization_id, label=label, provider="openai", model=label
    )
    db.add(profile)
    await db.flush()
    return profile


class Model:
    """Stands in for the runner: answers from a script, and writes the run row a real run would.

    `answer(prompt, call)` decides the text; `status(call)` the run's ending;
    `before(call)` runs first, as a person acting mid-run would.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        answer: Any = lambda prompt, call: _PASS,
        status: Any = lambda call: "completed",
        before: Any = None,
        tools: Any = lambda call: [],
        raises: Any = lambda call: None,
    ) -> None:
        self.db = db
        self.answer = answer
        self.status = status
        self.before = before
        self.tools = tools
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    async def execute(self, runner: AgentRunnerService, ctx: AuthContext, agent_id, prompt, **kw):
        call = len(self.calls)
        self.calls.append({"prompt": prompt, **kw})
        if self.before is not None:
            await self.before(call)
        failure = self.raises(call)
        if failure is not None:
            raise failure
        candidate = kw["candidate"]
        started = datetime.now(UTC)
        run = AgentRun(
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            agent_version_id=(
                candidate.version_id if isinstance(candidate, PublishedCandidate) else None
            ),
            user_id=ctx.user_id,
            surface=kw["surface"].value,
            status=self.status(call),
            model_label="gpt-test",
            cost_usd=Decimal("0.01"),
            input_tokens=100,
            output_tokens=20,
            started_at=started,
            # A run that did not complete may never have recorded its end.
            ended_at=started + timedelta(milliseconds=500)
            if self.status(call) == "completed"
            else None,
        )
        self.db.add(run)
        await self.db.flush()
        for index, (tool, args, held) in enumerate(self.tools(call)):
            kw["tool_calls"].append(
                RecordedToolCall(tool_call_id=f"call-{index}", tool_name=tool, args=args)
            )
            if held:
                self.db.add(
                    InterceptedToolCall(
                        organization_id=ctx.organization_id,
                        run_id=run.id,
                        agent_id=agent_id,
                        sequence=index,
                        tool_call_id=f"call-{index}",
                        tool_name=tool,
                        tool_id=f"tool:{tool}",
                        args=args,
                        outcome="blocked",
                        reason="writes",
                    )
                )
        await self.db.flush()
        return self.answer(prompt, call), run


def _sessions(db: AsyncSession):
    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    return session


@pytest.fixture(autouse=True)
def _environment():
    """No real model, no dispatch, one drainer - the session is shared, so serial."""

    def dropped(_db, coro, *, name):
        coro.close()

    with (
        patch.object(
            ModelProfileService,
            "resolve",
            new=AsyncMock(
                return_value=SimpleNamespace(label="gpt-test", model="gpt-test", provider="openai")
            ),
        ),
        patch.object(AgentRegistryService, "validate_spec", new=AsyncMock()),
        patch("app.services.eval_run.spawn_after_commit", side_effect=dropped),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
        patch("app.services.eval_run.settings.EVAL_FALLBACK_CASE_COST_USD", Decimal("0.05")),
    ):
        yield


async def _run_to_end(db: AsyncSession, model: Model, run_id, ctx: AuthContext) -> None:
    async def execute(runner, *args, **kwargs):
        return await model.execute(runner, *args, **kwargs)

    with patch.object(AgentRunnerService, "execute", new=execute):
        await EvalRunWorker(
            run_id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
        ).run()


async def test_a_draft_run_is_twenty_eval_runs_none_attributed_to_a_version(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=20)
    service = EvalRunService(db)
    model = Model(db)

    started = await service.start(
        ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, candidate="draft")
    )
    await _run_to_end(db, model, started.id, ctx)

    assert len(model.calls) == 20
    assert all(isinstance(call["candidate"], UnpublishedCandidate) for call in model.calls)
    assert {call["surface"] for call in model.calls} == {RunSurface.EVAL}
    runs = (await db.execute(select(AgentRun).where(AgentRun.agent_id == agent.id))).scalars().all()
    assert len(runs) == 20
    assert {run.surface for run in runs} == {"eval"}
    assert {run.agent_version_id for run in runs} == {None}

    read = await service.get(ctx, started.id)
    assert read.status == "completed"
    assert (read.attempts_done, read.attempts_total) == (20, 20)
    summary = read.arms[0].summary
    assert (summary.passed, summary.pass_rate) == (20, 1.0)
    assert summary.cost_usd == Decimal("0.20")
    assert set(read.arms[0].by_tag) == {"refunds"}
    assert read.arms[0].source == "draft"


@pytest.mark.security
async def test_a_run_past_the_budget_is_refused_before_anything_is_written(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=20)
    org = await db.get(Organization, ctx.organization_id)
    assert org is not None
    org.monthly_budget_usd = Decimal("0.50")
    await db.flush()
    service = EvalRunService(db)
    request = EvalRunRequest(dataset_id=dataset.id)

    estimate = await service.estimate(ctx, agent.id, request)
    with pytest.raises(PaymentRequiredError):
        await service.start(ctx, agent.id, request)

    assert estimate.total_usd == Decimal("1.00")
    assert estimate.arms[0].basis == "fallback"
    assert not estimate.affordable
    assert estimate.org_after_usd == Decimal("-0.50")
    assert await db.scalar(select(func.count()).select_from(EvalRun)) == 0


async def test_a_run_on_an_older_version_asks_exactly_what_it_held(db) -> None:
    """Edits after a version leave what a run started on it is asked unchanged."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=3)
    datasets = DatasetService(db)
    held = (await datasets.list_cases(ctx, dataset.id)).items
    await datasets.update_case(
        ctx, dataset.id, held[0].case_id, DatasetCaseUpdate(input="Question 0, reworded")
    )
    await datasets.remove_case(ctx, dataset.id, held[1].case_id)

    started = await EvalRunService(db).start(
        ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, dataset_version=3)
    )

    asked = (
        (
            await db.execute(
                select(EvalRunCase.case_revision_id)
                .where(EvalRunCase.eval_run_id == started.id)
                .order_by(EvalRunCase.position)
            )
        )
        .scalars()
        .all()
    )
    assert asked == [case.id for case in held]


async def test_a_cancelled_run_starts_no_further_case(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=6)
    service = EvalRunService(db)
    started = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))

    async def cancel_on_the_second(call: int) -> None:
        if call == 1:
            await service.cancel(ctx, started.id)

    model = Model(db, before=cancel_on_the_second)
    await _run_to_end(db, model, started.id, ctx)

    read = await service.get(ctx, started.id)
    assert len(model.calls) == 2
    assert read.status == "cancelled"
    # The case that was already running when the person cancelled finished.
    assert (read.attempts_done, read.attempts_total) == (2, 6)


@pytest.mark.security
async def test_a_case_that_runs_out_of_budget_stops_the_run(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=5)
    service = EvalRunService(db)
    started = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))

    model = Model(db, status=lambda call: "budget_exceeded" if call == 2 else "completed")
    await _run_to_end(db, model, started.id, ctx)

    read = await service.get(ctx, started.id)
    assert len(model.calls) == 3
    assert read.status == "budget_exceeded"
    # The cases left unanswered still count, so progress reads 3 of 5.
    assert (read.attempts_done, read.attempts_total) == (3, 5)


async def test_a_case_that_passed_on_v6_and_fails_on_v7_is_a_confirmed_regression(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=4)
    service = EvalRunService(db)

    v6 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    await _run_to_end(db, Model(db), v6.id, ctx)
    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    model = Model(db, answer=lambda prompt, call: _FAIL if prompt == "Question 0" else _PASS)
    await _run_to_end(db, model, v7.id, ctx)

    # Four answers, then the one flipped case twice more.
    assert len(model.calls) == 6
    comparison = await service.compare(ctx, v7.id)
    assert comparison.baseline is not None and comparison.baseline.run_id == v6.id
    assert comparison.baseline.version_number == 6
    assert not comparison.paired
    assert comparison.regressions_confirmed == 1
    regression = next(case for case in comparison.cases if case.flip == "regression")
    assert regression.candidate_reruns == [False, False]
    assert regression.input == "Question 0"
    # A case that breaks every time makes it worse; one flip says nothing overall.
    assert (comparison.verdict, comparison.overall) == ("worse", None)
    assert comparison.compared == 4
    assert comparison.flips_by_tag["refunds"]["regression"] == 1

    failed = await service.cases(ctx, v7.id, outcome="failed")
    with pytest.raises(NotFoundError, match="Arm not found"):
        await service.cases(ctx, v7.id, arm_id=uuid.uuid4(), outcome="failed")
    assert [case.input for case in failed.items] == ["Question 0"]
    assert [attempt.attempt for attempt in failed.items[0].attempts] == [0, 1, 2]


async def test_a_flip_its_reruns_undo_counts_as_it_settled(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=4)
    service = EvalRunService(db)
    v6 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    await _run_to_end(db, Model(db), v6.id, ctx)
    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    asked: list[str] = []

    def answer(prompt: str, call: int) -> str:
        asked.append(prompt)
        return _FAIL if asked.count("Question 0") == 1 and prompt == "Question 0" else _PASS

    await _run_to_end(db, Model(db, answer=answer), v7.id, ctx)

    comparison = await service.compare(ctx, v7.id)
    assert (comparison.verdict, comparison.regressions_unconfirmed) == ("no_difference", 1)
    summary = comparison.candidate_summary
    assert (summary.pass_rate, summary.first_pass_rate) == (1.0, 0.75)
    read = await service.get(ctx, v7.id)
    assert read.outcome is not None
    assert (read.outcome.candidate_pass_rate, read.outcome.candidate_first_pass_rate) == (
        1.0,
        0.75,
    )
    assert read.arms[0].summary.pass_rate == 1.0


async def test_a_baseline_in_the_same_run_is_reused_when_everything_matches(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=3)
    service = EvalRunService(db)
    request = EvalRunRequest(dataset_id=dataset.id, candidate="draft", paired_baseline=True)

    first = await service.start(ctx, agent.id, request)
    model = Model(db)
    await _run_to_end(db, model, first.id, ctx)
    assert len(model.calls) == 6
    assert {type(call["candidate"]) for call in model.calls} == {
        UnpublishedCandidate,
        PublishedCandidate,
    }

    estimate = await service.estimate(ctx, agent.id, request)
    baseline = next(arm for arm in estimate.arms if arm.role == "baseline")
    assert (baseline.basis, baseline.cached_from_run_id) == ("cached", first.id)
    # Its first answers are free, but a case that flips is asked of it again.
    candidate = next(arm for arm in estimate.arms if arm.role == "candidate")
    assert estimate.rerun_ceiling_usd == candidate.cost_per_case_usd * 2 * 3 * 2

    second = await service.start(ctx, agent.id, request)
    again = Model(db)
    await _run_to_end(db, again, second.id, ctx)
    assert len(again.calls) == 3
    comparison = await service.compare(ctx, second.id)
    # The comparison names the run the baseline was answered in, and when.
    assert not comparison.paired
    assert comparison.baseline is not None
    assert comparison.baseline.run_id == first.id
    assert comparison.baseline.finished_at is not None
    assert comparison.verdict == "no_difference"
    read = await service.get(ctx, second.id)
    reused = next(arm for arm in read.arms if arm.role == "baseline")
    assert reused.reused_from_arm_id is not None
    assert reused.summary.passed == 3


async def test_one_run_over_two_models_reports_each(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=3)
    cheap, strong = await _profile(db, ctx, "cheap"), await _profile(db, ctx, "strong")
    service = EvalRunService(db)

    started = await service.start(
        ctx,
        agent.id,
        EvalRunRequest(dataset_id=dataset.id, model_profile_ids=[cheap.id, strong.id]),
    )
    model = Model(
        db,
        answer=lambda prompt, call: _PASS if call % 2 else _FAIL,
    )
    await _run_to_end(db, model, started.id, ctx)

    read = await service.get(ctx, started.id)
    assert [arm.model_profile_id for arm in read.arms] == [cheap.id, strong.id]
    assert {call["model_profile_id"] for call in model.calls} == {cheap.id, strong.id}
    rates = sorted(arm.summary.pass_rate for arm in read.arms if arm.summary.pass_rate is not None)
    assert sum(arm.summary.cases for arm in read.arms) == 6
    assert all(arm.summary.p50_ms == 500 for arm in read.arms)
    assert len(rates) == 2


@pytest.mark.security
async def test_nothing_crosses_organizations(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)
    started = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))

    stranger = await _owner(db)
    their_agent, _ = await _agent(db, stranger)
    their_dataset = await _dataset(db, stranger, cases=2)

    with pytest.raises(NotFoundError):
        await service.estimate(stranger, their_agent.id, EvalRunRequest(dataset_id=dataset.id))
    with pytest.raises(NotFoundError):
        await service.estimate(stranger, agent.id, EvalRunRequest(dataset_id=their_dataset.id))
    with pytest.raises(NotFoundError):
        await service.get(stranger, started.id)
    with pytest.raises(NotFoundError):
        await service.cancel(stranger, started.id)
    assert (await service.recent(stranger)).items == []


@pytest.mark.security
async def test_running_the_draft_needs_edit_access_to_the_agent(db) -> None:
    owner = await _owner(db)
    agent, _ = await _agent(db, owner)
    dataset = await _dataset(db, owner, cases=2)
    operator = await _member(db, owner, OrgRoleName.OPERATOR)
    service = EvalRunService(db)

    with pytest.raises(AuthorizationError):
        await service.estimate(
            operator, agent.id, EvalRunRequest(dataset_id=dataset.id, candidate="draft")
        )
    estimate = await service.estimate(operator, agent.id, EvalRunRequest(dataset_id=dataset.id))
    assert estimate.cases == 2


@pytest.mark.security
async def test_a_grant_on_the_dataset_lets_a_member_run_it(db) -> None:
    owner = await _owner(db)
    agent, _ = await _agent(db, owner)
    dataset = await _dataset(db, owner, cases=2)
    dataset.visibility = "private"
    await db.flush()
    member = await _member(db, owner, OrgRoleName.MEMBER)
    service = EvalRunService(db)
    request = EvalRunRequest(dataset_id=dataset.id)

    with pytest.raises(NotFoundError):
        await service.estimate(member, agent.id, request)
    db.add(
        ResourceGrant(
            organization_id=owner.organization_id,
            subject_user_id=member.user_id,
            resource_type="dataset",
            resource_id=dataset.id,
            level=GrantLevel.USE.value,
        )
    )
    await db.flush()
    assert (await service.estimate(member, agent.id, request)).cases == 2


@pytest.mark.security
async def test_reading_runs_needs_runs_view(db) -> None:
    owner = await _owner(db)
    agent, _ = await _agent(db, owner)
    dataset = await _dataset(db, owner, cases=1)
    service = EvalRunService(db)
    started = await service.start(owner, agent.id, EvalRunRequest(dataset_id=dataset.id))
    viewer = await _member(db, owner, OrgRoleName.VIEWER)

    with pytest.raises(AuthorizationError):
        await service.get(viewer, started.id)
    with pytest.raises(AuthorizationError):
        await service.list_for_agent(viewer, agent.id)
    assert (await service.recent(viewer)).items == []
    listed = await service.list_for_agent(owner, agent.id)
    assert [run.id for run in listed.items] == [started.id]


async def test_a_different_scoring_makes_the_comparison_invalid(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)

    v6 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    await _run_to_end(db, Model(db), v6.id, ctx)
    dataset.scoring = {"review": {"select": "all"}}
    await db.flush()
    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db), v7.id, ctx)

    comparison = await service.compare(ctx, v7.id)
    assert comparison.verdict == "invalid"
    assert comparison.invalid_reason is not None


async def test_a_dataset_that_decides_nothing_is_refused(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await DatasetService(db).create(ctx, DatasetCreate(name="empty"))
    service = EvalRunService(db)

    with pytest.raises(BadRequestError, match="has no cases"):
        await service.estimate(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    with pytest.raises(BadRequestError, match="no earlier version"):
        await service.estimate(
            ctx,
            agent.id,
            EvalRunRequest(
                dataset_id=(await _dataset(db, ctx, cases=1)).id,
                version=6,
                paired_baseline=True,
            ),
        )


async def test_every_call_is_kept_and_a_held_write_counts_as_blocked(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    service = EvalRunService(db)
    started = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    model = Model(
        db,
        tools=lambda call: [
            ("lookup_order", {"order": 4512}, False),
            ("send_email", {"to": "customer@example.com"}, True),
        ],
    )
    seen: list[dict[str, Any]] = []
    real = ScoringService.score_case

    async def score_case(self, ctx, **kwargs):
        seen.append(kwargs)
        return await real(self, ctx, **kwargs)

    with patch.object(ScoringService, "score_case", new=score_case):
        await _run_to_end(db, model, started.id, ctx)

    cases = await service.cases(ctx, started.id)
    calls = cases.items[0].attempts[0].calls
    assert [(c.tool, c.outcome) for c in calls] == [
        ("lookup_order", "executed"),
        ("send_email", "blocked"),
    ]
    assert calls[0].args == {"order": 4512}
    answer = seen[0]["answer"]
    assert [(c.tool, c.blocked) for c in answer.calls] == [
        ("lookup_order", False),
        ("send_email", True),
    ]
    assert seen[0]["eval_run_id"] == started.id


async def test_a_case_that_breaks_is_kept_as_failed_and_the_run_goes_on(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=3)
    service = EvalRunService(db)
    started = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    model = Model(
        db,
        raises=lambda call: RuntimeError("provider exploded") if call == 0 else None,
        status=lambda call: "failed" if call == 1 else "completed",
    )

    await _run_to_end(db, model, started.id, ctx)

    read = await service.get(ctx, started.id)
    statuses = [
        attempt.status
        for case in (await service.cases(ctx, started.id)).items
        for attempt in case.attempts
    ]
    assert read.status == "completed"
    assert statuses == ["failed", "failed", "done"]
    assert read.arms[0].summary.incomplete == 2


async def test_a_case_nothing_scores_is_undecided_and_a_scoring_crash_is_a_failure(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)
    started = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    outcomes = iter([NothingToScoreError(case_id=uuid.uuid4()), RuntimeError("scorer bug")])

    async def score_case(self, ctx, **kwargs):
        raise next(outcomes)

    with patch.object(ScoringService, "score_case", new=score_case):
        await _run_to_end(db, Model(db), started.id, ctx)

    attempts = [case.attempts[0] for case in (await service.cases(ctx, started.id)).items]
    assert [(a.status, a.outcome) for a in attempts] == [("done", None), ("failed", None)]
    assert attempts[0].answer == _PASS
    assert attempts[0].error is not None


async def test_a_worker_never_starts_a_finished_run_or_one_whose_starter_left(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)

    cancelled = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await service.cancel(ctx, cancelled.id)
    model = Model(db)
    await _run_to_end(db, model, cancelled.id, ctx)
    assert model.calls == []

    member = await _member(db, ctx, OrgRoleName.ADMIN)
    orphaned = await service.start(member, agent.id, EvalRunRequest(dataset_id=dataset.id))
    membership = await db.scalar(
        select(OrganizationMember).where(OrganizationMember.user_id == member.user_id)
    )
    await db.delete(membership)
    await db.flush()
    await _run_to_end(db, model, orphaned.id, ctx)

    read = await service.get(ctx, orphaned.id)
    assert model.calls == []
    assert read.status == "failed"
    assert read.error == "Whoever started this eval is no longer a member."
    assert (read.attempts_done, read.attempts_total) == (0, 2)


async def test_a_full_organization_waits_for_a_free_slot(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    service = EvalRunService(db)
    started = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    model = Model(db)

    async def give_up(_seconds: float) -> None:
        await service.cancel(ctx, started.id)

    async def execute(runner, *args, **kwargs):
        return await model.execute(runner, *args, **kwargs)

    with (
        patch("app.services.eval_run_worker.settings.EVAL_ORG_CONCURRENCY", 0),
        patch.object(AgentRunnerService, "execute", new=execute),
    ):
        await EvalRunWorker(
            started.id, ctx.organization_id, sessions=_sessions(db), sleep=give_up
        ).run()

    assert model.calls == []
    assert (await service.get(ctx, started.id)).status == "cancelled"


async def test_a_case_from_a_conversation_is_answered_from_its_recording(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    source = AgentRun(
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=ctx.user_id,
        status="completed",
        model_label="gpt-test",
        started_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()
    revisions = (
        (
            await db.execute(
                select(DatasetCase)
                .where(DatasetCase.dataset_id == dataset.id)
                .order_by(DatasetCase.input)
            )
        )
        .scalars()
        .all()
    )
    for revision in revisions:
        revision.source_run_id = source.id
    await db.flush()
    service = EvalRunService(db)
    started = await service.start(
        ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, from_recordings=True)
    )
    recording = ToolRecording([])
    answers = iter([recording, BadRequestError(message="no manifest", details={})])

    async def tool_recording(self, ctx, run_id):
        found = next(answers)
        if isinstance(found, Exception):
            raise found
        return found

    model = Model(db)
    with patch.object(AgentRunnerService, "tool_recording", new=tool_recording):
        await _run_to_end(db, model, started.id, ctx)

    assert [call["isolation"].recording for call in model.calls] == [recording, None]


@pytest.mark.security
async def test_who_may_stop_a_run(db) -> None:
    owner = await _owner(db)
    agent, _ = await _agent(db, owner)
    dataset = await _dataset(db, owner, cases=2)
    service = EvalRunService(db)
    started = await service.start(owner, agent.id, EvalRunRequest(dataset_id=dataset.id))
    operator = await _member(db, owner, OrgRoleName.OPERATOR)
    admin = await _member(db, owner, OrgRoleName.ADMIN)

    with pytest.raises(AuthorizationError):
        await service.cancel(operator, started.id)
    stopped = await service.cancel(admin, started.id)
    again = await service.cancel(owner, started.id)

    assert stopped.status == again.status == "cancelled"
    assert again.ended_at == stopped.ended_at


@pytest.mark.security
async def test_a_run_whose_agent_the_reader_cannot_see_is_not_found(db) -> None:
    owner = await _owner(db)
    agent, _ = await _agent(db, owner)
    dataset = await _dataset(db, owner, cases=1)
    service = EvalRunService(db)
    started = await service.start(owner, agent.id, EvalRunRequest(dataset_id=dataset.id))

    hidden = NotFoundError(message="Agent not found", details={})
    with (
        patch.object(AgentRegistryService, "get", new=AsyncMock(side_effect=hidden)),
        pytest.raises(NotFoundError, match="Eval run not found"),
    ):
        await service.get(owner, started.id)


async def test_comparison_edges(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    other = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)

    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db), v7.id, ctx)
    alone = await service.compare(ctx, v7.id)
    assert alone.baseline is None and alone.verdict is None
    assert alone.not_compared == 2

    with pytest.raises(NotFoundError, match="Arm not found"):
        await service.compare(ctx, v7.id, arm_id=uuid.uuid4())

    again = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db), again.id, ctx)
    named = await service.compare(ctx, again.id, baseline_run_id=v7.id)
    assert named.baseline is not None and named.baseline.run_id == v7.id
    assert named.verdict == "no_difference"

    elsewhere = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=other.id))
    with pytest.raises(BadRequestError, match="same agent on the same dataset"):
        await service.compare(ctx, again.id, baseline_run_id=elsewhere.id)


async def test_a_baseline_graded_by_another_judge_is_not_compared(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)

    v6 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    await _run_to_end(db, Model(db), v6.id, ctx)
    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db), v7.id, ctx)
    for score in (
        await db.execute(select(CaseScore).where(CaseScore.eval_run_id == v6.id))
    ).scalars():
        score.judge = {"model_profile_id": None, "agent_version_id": None, "rubric_hash": "a"}
    for score in (
        await db.execute(select(CaseScore).where(CaseScore.eval_run_id == v7.id))
    ).scalars():
        score.judge = {"model_profile_id": None, "agent_version_id": None, "rubric_hash": "b"}
    await db.flush()

    comparison = await service.compare(ctx, v7.id)
    assert comparison.verdict == "invalid"
    assert "different judge" in (comparison.invalid_reason or "")


async def test_a_baseline_graded_by_the_judge_s_older_prompt_says_so(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    service = EvalRunService(db)
    v6 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    await _run_to_end(db, Model(db), v6.id, ctx)
    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db), v7.id, ctx)
    pin = {"agent_version_id": None, "rubric_hash": "a"}
    await _pin(db, v6.id, pin)
    await _pin(db, v7.id, {**pin, "prompt_version": 1})
    assert (await service.compare(ctx, v7.id)).verdict == "no_difference"

    await _pin(db, v7.id, {**pin, "prompt_version": 2})

    comparison = await service.compare(ctx, v7.id)
    assert comparison.verdict == "invalid"
    assert "instructions changed" in (comparison.invalid_reason or "")
    # A run names the model its judge graded on, for a reader to set beside its own.
    assert (await service.get(ctx, v7.id)).judge_model_profile_id is None
    profile = uuid.uuid4()
    await _pin(db, v6.id, {**pin, "model_profile_id": str(profile)})
    assert (await service.get(ctx, v6.id)).judge_model_profile_id == profile


async def test_a_judge_that_graded_nothing_leaves_the_comparison_standing(db) -> None:
    """Its pin is kept for refusing to grade again, and may name a judge that
    differs from the one that graded everything else."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)
    v6 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    await _run_to_end(db, Model(db), v6.id, ctx)
    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db), v7.id, ctx)
    pin = {"agent_version_id": None, "rubric_hash": "a", "prompt_version": JUDGE_PROMPT_VERSION}
    await _pin(db, v6.id, pin)
    await _pin(db, v7.id, pin)
    failed = await _errored(db, v7.id, scorer="judge", reason_code="judge_output_invalid")
    failed.judge = {**pin, "agent_version_id": str(uuid.uuid4()), "rubric_hash": None}
    await db.flush()

    comparison = await service.compare(ctx, v7.id)
    assert comparison.verdict == "no_difference"
    assert comparison.invalid_reason is None

    # One criterion it did grade is a grade by that judge.
    failed.results = [*failed.results, {**failed.results[0], "status": "pass"}]
    await db.flush()
    assert (await service.compare(ctx, v7.id)).verdict == "invalid"


async def test_cases_with_their_own_judge_checks_still_compare(db) -> None:
    """A rubric fingerprint covers a case's own judge checks, so two cases of one
    side are pinned differently; only the same case on the two sides must match."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)
    started = await service.start(
        ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, paired_baseline=True, reruns=0)
    )
    await _run_to_end(db, Model(db), started.id, ctx)
    attempts = (
        (await db.execute(select(EvalRunCase).where(EvalRunCase.eval_run_id == started.id)))
        .scalars()
        .all()
    )
    rubric = {case_id: uuid.uuid4().hex for case_id in {a.case_id for a in attempts}}
    for attempt in attempts:
        score = await db.get(CaseScore, attempt.case_score_id)
        assert score is not None
        score.judge = {"agent_version_id": None, "rubric_hash": rubric[attempt.case_id]}
    await db.flush()

    comparison = await service.compare(ctx, started.id)
    assert comparison.verdict == "no_difference"
    assert comparison.invalid_reason is None

    # The same case graded under another rubric on one side does not compare.
    one = next(a for a in attempts if a.arm_id == comparison.baseline.arm_id)
    score = await db.get(CaseScore, one.case_score_id)
    assert score is not None
    score.judge = {"agent_version_id": None, "rubric_hash": "other"}
    await db.flush()
    assert (await service.compare(ctx, started.id)).verdict == "invalid"


async def test_a_case_added_since_the_baseline_is_not_compared(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)

    v6 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    await _run_to_end(db, Model(db), v6.id, ctx)
    await DatasetService(db).add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(input="New question", checks=[{"type": "contains", "value": "x"}]),
    )
    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    model = Model(db, answer=lambda prompt, call: _FAIL if prompt == "New question" else _PASS)
    await _run_to_end(db, model, v7.id, ctx)

    comparison = await service.compare(ctx, v7.id)
    # The new case failed but has nothing to flip from, so it is not rerun.
    assert len(model.calls) == 3
    assert (comparison.compared, comparison.not_compared) == (2, 1)
    assert comparison.baseline is not None and comparison.baseline.dataset_version == 2
    assert comparison.candidate.dataset_version == 3


async def test_a_flip_against_a_baseline_in_the_same_run_reruns_both_sides(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)
    started = await service.start(
        ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, paired_baseline=True, reruns=1)
    )

    def answer(prompt: str, call: int) -> str:
        current = model.calls[call]["candidate"]
        regressed = current.version_id == agent.current_version_id and prompt == "Question 0"
        return _FAIL if regressed else _PASS

    model = Model(db, answer=answer)
    await _run_to_end(db, model, started.id, ctx)

    comparison = await service.compare(ctx, started.id)
    assert comparison.paired
    assert comparison.baseline is not None and comparison.baseline.version_number == 6
    assert comparison.regressions_confirmed == 1
    # Two arms of two cases, then the flipped case once more on each arm.
    assert len(model.calls) == 6
    case = next(c for c in comparison.cases if c.flip == "regression")
    assert (case.baseline_reruns, case.candidate_reruns) == ([True], [False])

    # The judge republished between a case's first answers and its reruns: both
    # sides hold both judges' grades, in opposite proportions, and do not compare.
    old = {"agent_version_id": None, "rubric_hash": "a"}
    new = {"agent_version_id": str(uuid.uuid4()), "rubric_hash": "a"}
    tries = await db.execute(
        select(EvalRunCase, EvalRunArm.role)
        .join(EvalRunArm, EvalRunArm.id == EvalRunCase.arm_id)
        .where(EvalRunCase.eval_run_id == started.id)
    )
    for attempt, role in tries.all():
        score = await db.get(CaseScore, attempt.case_score_id)
        assert score is not None
        first = attempt.attempt == 0
        score.judge = old if first == (role == "candidate") else new
    await db.flush()
    mixed = await service.compare(ctx, started.id)
    assert mixed.verdict == "invalid"
    assert "judge changed while" in (mixed.invalid_reason or "")


async def test_the_estimate_counts_the_judge_and_the_agents_own_cap(db) -> None:
    ctx = await _owner(db)
    await _assist(db, ctx, on=True)
    agent, versions = await _agent(db, ctx)
    versions[7].spec = {"name": "Clerk", "budget": {"monthly_usd": 2}}
    dataset = await _dataset(db, ctx, cases=4)
    dataset.scoring = {
        "judge": {"enabled": True, "criteria": [{"name": "Tone", "description": "Polite"}]}
    }
    await db.flush()
    service = EvalRunService(db)

    estimate = await service.estimate(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))

    assert estimate.judge_usd == Decimal("0.20")
    assert estimate.total_usd == Decimal("0.40")
    assert estimate.agent_remaining_usd == Decimal("2")
    # The judge bills to its own agent; the evaluated agent keeps $2 - $0.20.
    assert estimate.agent_after_usd == Decimal("1.80")
    assert estimate.rerun_ceiling_usd == Decimal("0.80")

    # A draft with a looser cap against v7: v7 stops first, so its cap decides.
    agent.draft_spec = {**agent.draft_spec, "budget": {"monthly_usd": 5}}
    await db.flush()
    paired = await service.estimate(
        ctx,
        agent.id,
        EvalRunRequest(dataset_id=dataset.id, candidate="draft", paired_baseline=True),
    )
    assert paired.agent_remaining_usd == Decimal("2")


async def test_a_model_with_no_history_is_priced_at_its_own_price(db) -> None:
    """A typical case at the model's price, not a flat guess eighty times too high."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=10)
    nano = await _profile(db, ctx, "gpt-4.1-nano")
    priced = SimpleNamespace(label="nano", model="gpt-4.1-nano", provider="openai")

    with patch.object(ModelProfileService, "resolve", new=AsyncMock(return_value=priced)):
        estimate = await EvalRunService(db).estimate(
            ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, model_profile_ids=[nano.id])
        )

    [arm] = estimate.arms
    # 2000 tokens in at $0.10/1M and 400 out at $0.40/1M.
    assert (arm.basis, arm.cost_per_case_usd) == ("fallback", Decimal("0.00036"))
    assert arm.cost_usd == Decimal("0.0036")


async def _assist(db: AsyncSession, ctx: AuthContext, *, on: bool) -> None:
    org = await db.get(Organization, ctx.organization_id)
    assert org is not None
    org.ai_assistance_enabled = on
    await db.flush()


async def _pin(db: AsyncSession, run_id, judge: dict[str, Any] | None) -> None:
    for score in (
        await db.execute(select(CaseScore).where(CaseScore.eval_run_id == run_id))
    ).scalars():
        score.judge = judge
    await db.flush()


async def test_a_cached_baseline_must_have_been_graded_by_the_judge_that_grades_now(db) -> None:
    ctx = await _owner(db)
    await _assist(db, ctx, on=True)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    dataset.scoring = {
        "judge": {"enabled": True, "criteria": [{"name": "Tone", "description": "Polite"}]}
    }
    await db.flush()
    service = EvalRunService(db)
    request = EvalRunRequest(dataset_id=dataset.id, candidate="draft", paired_baseline=True)
    first = await service.start(ctx, agent.id, request)
    await _run_to_end(db, Model(db), first.id, ctx)

    async def baseline_basis() -> str:
        estimate = await service.estimate(ctx, agent.id, request)
        return next(arm.basis for arm in estimate.arms if arm.role == "baseline")

    for score in (
        await db.execute(select(CaseScore).where(CaseScore.eval_run_id == first.id))
    ).scalars():
        score.results = [
            {**r, "status": "pass"} if r["scorer"] == "judge" else r for r in score.results
        ]
    # No judge is published in this organization, so that is the judge now.
    now = {"agent_version_id": None, "rubric_hash": "a", "prompt_version": JUDGE_PROMPT_VERSION}
    await _pin(db, first.id, now)
    assert await baseline_basis() == "cached"
    # A first answer that never came in would never be asked again.
    hole = await db.scalar(
        select(EvalRunCase)
        .join(EvalRunArm, EvalRunArm.id == EvalRunCase.arm_id)
        .where(EvalRunArm.eval_run_id == first.id, EvalRunArm.role == "baseline")
        .limit(1)
    )
    assert hole is not None
    hole.status = "failed"
    await db.flush()
    assert await baseline_basis() == "history"
    hole.status = "done"
    await db.flush()
    # Graded before the judge's prompt changed.
    await _pin(db, first.id, {"agent_version_id": None, "rubric_hash": "a"})
    assert await baseline_basis() == "history"
    await _pin(db, first.id, {**now, "agent_version_id": str(uuid.uuid4())})
    assert await baseline_basis() == "history"
    # A judge that graded nothing on one answer does not stand for the run's judge.
    await _pin(db, first.id, now)
    baseline = (
        await db.execute(
            select(CaseScore)
            .join(EvalRunCase, EvalRunCase.case_score_id == CaseScore.id)
            .join(EvalRunArm, EvalRunArm.id == EvalRunCase.arm_id)
            .where(EvalRunArm.eval_run_id == first.id, EvalRunArm.role == "baseline")
            .limit(1)
        )
    ).scalar_one()
    baseline.results = [
        {**r, "scorer": "judge", "status": "error", "reason_code": "judge_output_invalid"}
        for r in baseline.results
    ]
    baseline.judge = {**now, "agent_version_id": str(uuid.uuid4())}
    await db.flush()
    assert await baseline_basis() == "cached"
    # Graded by no judge at all, where a judge would grade now.
    await _pin(db, first.id, None)
    assert await baseline_basis() == "history"

    # With AI assistance off no judge grades now, so only an ungraded arm stands in.
    await _assist(db, ctx, on=False)
    assert await baseline_basis() == "cached"
    await _pin(db, first.id, {"agent_version_id": None, "rubric_hash": "a"})
    assert await baseline_basis() == "history"


async def test_with_ai_assistance_off_the_estimate_has_no_judge(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=4)
    dataset.scoring = {
        "judge": {"enabled": True, "criteria": [{"name": "Tone", "description": "Polite"}]}
    }
    await db.flush()

    estimate = await EvalRunService(db).estimate(
        ctx, agent.id, EvalRunRequest(dataset_id=dataset.id)
    )

    assert estimate.judge_usd == Decimal(0)
    assert estimate.total_usd == Decimal("0.20")


async def test_what_cannot_run_is_refused_before_anything_is_estimated(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    unchecked = await DatasetService(db).create(ctx, DatasetCreate(name="unchecked"))
    await DatasetService(db).add_case(
        ctx, unchecked.id, DatasetCaseCreate(input="Hi", reference_answer="Hello")
    )
    service = EvalRunService(db)

    with pytest.raises(BadRequestError, match="no version 9"):
        await service.estimate(
            ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, dataset_version=9)
        )
    with pytest.raises(BadRequestError, match="Nothing in this dataset's scoring"):
        await service.estimate(ctx, agent.id, EvalRunRequest(dataset_id=unchecked.id))
    with pytest.raises(BadRequestError, match="has no version 3"):
        await service.estimate(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=3))

    agent.current_version_id = None
    await db.flush()
    with pytest.raises(BadRequestError, match="run its draft instead"):
        await service.estimate(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    named = await service.estimate(
        ctx,
        agent.id,
        EvalRunRequest(
            dataset_id=dataset.id, candidate="draft", paired_baseline=True, baseline_version=6
        ),
    )
    assert [arm.version_number for arm in named.arms] == [None, 6]

    agent.status = "archived"
    await db.flush()
    with pytest.raises(BadRequestError, match="archived"):
        await service.estimate(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))


async def test_a_spec_handed_over_by_a_caller_runs_as_an_explicit_arm(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)

    estimate = await EvalRunService(db).estimate(
        ctx,
        agent.id,
        EvalRunRequest(dataset_id=dataset.id),
        candidate_spec=AgentSpec(name="Clerk", instructions="Proposed"),
    )

    assert [(arm.source, arm.version_number) for arm in estimate.arms] == [("explicit", None)]


async def test_cases_narrow_by_tag(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=3)
    service = EvalRunService(db)
    started = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db), started.id, ctx)

    tagged = await service.cases(ctx, started.id, tag="refunds")
    passed = await service.cases(ctx, started.id, outcome="passed", limit=1)

    assert [case.input for case in tagged.items] == ["Question 0", "Question 2"]
    assert (passed.total, len(passed.items)) == (3, 1)


@pytest.mark.security
async def test_a_budget_stop_leaves_a_run_another_worker_already_ended(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    service = EvalRunService(db)
    started = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await service.cancel(ctx, started.id)

    worker = EvalRunWorker(started.id, ctx.organization_id, sessions=_sessions(db))
    await worker._stop_for_budget(db)

    assert (await service.get(ctx, started.id)).status == EvalRunStatus.CANCELLED.value


async def test_a_version_whose_last_case_was_removed_is_refused(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    datasets = DatasetService(db)
    only = (await datasets.list_cases(ctx, dataset.id)).items[0]
    await datasets.remove_case(ctx, dataset.id, only.case_id)

    with pytest.raises(BadRequestError, match="holds no cases"):
        await EvalRunService(db).estimate(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))


async def test_a_working_run_says_it_is_alive(db) -> None:
    ctx = await _owner(db)
    run_id = uuid.uuid4()
    worker = EvalRunWorker(run_id, ctx.organization_id, sessions=_sessions(db), heartbeat=0)
    twice = asyncio.Event()

    async def beaten(*_args: object, **_kwargs: object) -> None:
        if beat.await_count >= 2:
            twice.set()

    beat = AsyncMock(side_effect=beaten)

    with patch("app.services.eval_run_worker.eval_run_repo.heartbeat", new=beat):
        beating = asyncio.create_task(worker._beat())
        await asyncio.wait_for(twice.wait(), timeout=5)
        beating.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beating

    assert beat.await_args.args[1] == run_id
    assert beat.await_args.kwargs["organization_id"] == ctx.organization_id


async def test_a_run_its_worker_cannot_finish_ends_failed_at_once(db) -> None:
    """The database lost mid-run: the run is failed by its worker, not left live for the sweep."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=3)
    service = EvalRunService(db)
    started = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    attempts = list(
        await db.scalars(select(EvalRunCase).where(EvalRunCase.eval_run_id == started.id))
    )
    attempts[0].status = "running"
    await db.flush()
    worker = EvalRunWorker(started.id, ctx.organization_id, sessions=_sessions(db))

    with (
        patch.object(EvalRunWorker, "_wave", new=AsyncMock(side_effect=TimeoutError())),
        pytest.raises(TimeoutError),
    ):
        await worker.run()

    run = await service.get(ctx, started.id)
    assert run.status == EvalRunStatus.FAILED.value
    assert run.error == "This eval stopped on an error before it finished. Run it again."
    statuses = await db.scalars(
        select(EvalRunCase.status).where(EvalRunCase.eval_run_id == started.id)
    )
    assert sorted(statuses) == ["failed", "skipped", "skipped"]


async def test_a_drainer_that_fails_stops_the_others_before_the_run_is_failed(db) -> None:
    """A sibling left running would write answers to attempts the run already failed."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    started = await EvalRunService(db).start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    worker = EvalRunWorker(started.id, ctx.organization_id, sessions=_sessions(db))
    events: list[str] = []
    busy = asyncio.Event()

    async def drain(_ctx: AuthContext) -> None:
        if not busy.is_set():
            busy.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                events.append("sibling stopped")
                raise
        await busy.wait()
        raise TimeoutError

    fail_live = eval_run_repo.fail_live

    async def failing(*args: object, **kwargs: Any) -> bool:
        events.append("run failed")
        return await fail_live(*args, **kwargs)

    with (
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 2),
        patch.object(EvalRunWorker, "_drain", new=AsyncMock(side_effect=drain)),
        patch("app.services.eval_run_worker.eval_run_repo.fail_live", new=failing),
        pytest.raises(TimeoutError),
    ):
        await worker.run()

    assert events == ["sibling stopped", "run failed"]


async def test_a_run_the_worker_cannot_close_either_is_left_to_the_sweep(db, caplog) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    service = EvalRunService(db)
    started = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    worker = EvalRunWorker(started.id, ctx.organization_id, sessions=_sessions(db))

    with (
        patch.object(EvalRunWorker, "_wave", new=AsyncMock(side_effect=TimeoutError())),
        patch(
            "app.services.eval_run_worker.eval_run_repo.fail_live",
            new=AsyncMock(side_effect=ConnectionError()),
        ),
        caplog.at_level("ERROR", logger="app.services.eval_run_worker"),
        pytest.raises(TimeoutError),
    ):
        await worker.run()

    assert (await service.get(ctx, started.id)).status == EvalRunStatus.RUNNING.value
    assert any(record.message == "eval_run_not_closed" for record in caplog.records)


async def test_a_heartbeat_that_fails_is_not_the_last(db, caplog) -> None:
    """A worker silent after one dropped connection would be reaped while it still works."""
    ctx = await _owner(db)
    worker = EvalRunWorker(uuid.uuid4(), ctx.organization_id, sessions=_sessions(db), heartbeat=0)
    again = asyncio.Event()

    async def beaten(*_args: object, **_kwargs: object) -> None:
        if beat.await_count == 1:
            raise TimeoutError
        again.set()

    beat = AsyncMock(side_effect=beaten)

    with (
        patch("app.services.eval_run_worker.eval_run_repo.heartbeat", new=beat),
        caplog.at_level("WARNING", logger="app.services.eval_run_worker"),
    ):
        beating = asyncio.create_task(worker._beat())
        await asyncio.wait_for(again.wait(), timeout=5)
        beating.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beating

    assert any(record.message == "eval_heartbeat_failed" for record in caplog.records)


async def test_an_attempt_gone_with_its_run_stops_the_drainer(db) -> None:
    ctx = await _owner(db)
    worker = EvalRunWorker(uuid.uuid4(), ctx.organization_id, sessions=_sessions(db))

    assert await worker._answer(ctx, uuid.uuid4()) is True


async def _decide(db: AsyncSession, run_id, prompt: str, *, passed: bool) -> None:
    """A person's verdict on a case's first answer, given now."""
    revision = await db.scalar(select(DatasetCase).where(DatasetCase.input == prompt))
    assert revision is not None
    attempt = await db.scalar(
        select(EvalRunCase).where(
            EvalRunCase.eval_run_id == run_id,
            EvalRunCase.case_id == revision.case_id,
            EvalRunCase.attempt == 0,
        )
    )
    assert attempt is not None
    score = await db.get(CaseScore, attempt.case_score_id)
    assert score is not None
    score.human_passed = passed
    score.review_state = "done"
    score.reviewed_at = datetime.now(UTC) + timedelta(seconds=1)
    await db.flush()


async def test_a_finished_run_keeps_its_verdict_until_a_person_decides_a_score(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=4)
    service = EvalRunService(db)
    v6 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    assert v6.outcome is None
    await _run_to_end(db, Model(db), v6.id, ctx)
    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    model = Model(db, answer=lambda prompt, call: _FAIL if prompt == "Question 0" else _PASS)
    await _run_to_end(db, model, v7.id, ctx)

    listed = {run.id: run for run in (await service.list_for_agent(ctx, agent.id)).items}
    first = listed[v6.id].outcome
    # Nothing ran before v6 on this dataset, so it is the first result.
    assert first is not None and first.verdict is None and first.baseline is None
    assert first.candidate_pass_rate == 1.0
    outcome = listed[v7.id].outcome
    assert outcome is not None
    assert (outcome.verdict, outcome.overall) == ("worse", None)
    assert outcome.baseline is not None and outcome.baseline.run_id == v6.id
    assert outcome.regressions_confirmed == 1
    assert (outcome.candidate_pass_rate, outcome.baseline_pass_rate) == (0.75, 1.0)
    assert (outcome.candidate_first_pass_rate, outcome.baseline_first_pass_rate) == (0.75, 1.0)
    read = await service.get(ctx, v7.id)
    assert (read.cases, read.first_done, read.first_total, read.attempts_total) == (4, 4, 4, 6)
    assert read.rerun_ceiling_usd == Decimal("0.08")

    # Read again, the verdict is the one kept rather than compared anew.
    stored = await db.get(EvalRun, v7.id)
    assert stored is not None and stored.outcome_at is not None
    kept_at = stored.outcome_at
    await service.get(ctx, v7.id)
    assert stored.outcome_at == kept_at

    # A kept verdict in a shape this build no longer reads is compared afresh.
    stored.outcome = {"verdict": "worse"}
    await db.flush()
    assert (await service.get(ctx, v7.id)).outcome == outcome
    kept_at = stored.outcome_at

    # A person passes the case that broke: the regression is gone from the listing.
    await _decide(db, v7.id, "Question 0", passed=True)
    decided = await service.get(ctx, v7.id)
    assert decided.outcome is not None
    assert decided.outcome.regressions_confirmed == 0
    assert decided.outcome.candidate_pass_rate == 1.0
    assert stored.outcome_at > kept_at

    # Withdrawn, the verdict is gone and the regression is back.
    revision = await db.scalar(select(DatasetCase).where(DatasetCase.input == "Question 0"))
    assert revision is not None
    attempt = await db.scalar(
        select(EvalRunCase).where(
            EvalRunCase.eval_run_id == v7.id,
            EvalRunCase.case_id == revision.case_id,
            EvalRunCase.attempt == 0,
        )
    )
    assert attempt is not None and attempt.case_score_id is not None
    await ScoringService(db).set_verdict(
        ctx, dataset.id, attempt.case_score_id, CaseVerdict(passed=None)
    )
    withdrawn = await service.get(ctx, v7.id)
    assert withdrawn.outcome is not None
    assert withdrawn.outcome.regressions_confirmed == 1


async def test_runs_of_the_draft_as_it_stands_now(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    service = EvalRunService(db)
    version_run = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    draft_run = await service.start(
        ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, candidate="draft")
    )

    tested = await service.list_for_agent(ctx, agent.id, draft=True)
    assert [run.id for run in tested.items] == [draft_run.id]
    assert version_run.id not in [run.id for run in tested.items]

    # The same draft stored with its keys in another order is the same draft.
    agent.draft_spec = dict(reversed(list(agent.draft_spec.items())))
    await db.flush()
    assert (await service.list_for_agent(ctx, agent.id, draft=True)).total == 1

    agent.draft_spec = {**agent.draft_spec, "instructions": "Edited since"}
    await db.flush()
    assert (await service.list_for_agent(ctx, agent.id, draft=True)).items == []


@pytest.mark.security
async def test_a_datasets_runs_are_read_over_the_agents_and_dataset_the_reader_may_see(
    db,
) -> None:
    owner = await _owner(db)
    shared, _ = await _agent(db, owner)
    private, _ = await _agent(db, owner)
    private.visibility = "private"
    dataset = await _dataset(db, owner, cases=1)
    dataset.visibility = "private"
    await db.flush()
    service = EvalRunService(db)
    seen = await service.start(owner, shared.id, EvalRunRequest(dataset_id=dataset.id))
    unseen = await service.start(owner, private.id, EvalRunRequest(dataset_id=dataset.id))

    listed = await service.list_for_dataset(owner, dataset.id)
    assert {run.id for run in listed.items} == {seen.id, unseen.id}
    assert listed.total == 2

    with patch.dict(
        ROLE_PERMS,
        {
            "analyst": {
                Perm.RUNS_VIEW: Scope.ALL,
                Perm.AGENTS_VIEW: Scope.SHARED,
                Perm.DATASETS_VIEW: Scope.SHARED,
            }
        },
    ):
        user = await _user(db)
        db.add(
            OrganizationMember(
                id=uuid.uuid4(),
                organization_id=owner.organization_id,
                user_id=user.id,
                role="analyst",
            )
        )
        await db.flush()
        analyst = AuthContext(
            user_id=user.id, organization_id=owner.organization_id, role="analyst"
        )
        # The dataset is its owner's alone until it is shared.
        with pytest.raises(NotFoundError):
            await service.list_for_dataset(analyst, dataset.id)
        dataset.visibility = "org"
        await db.flush()
        visible = await service.list_for_dataset(analyst, dataset.id)
        assert [run.id for run in visible.items] == [seen.id]
        assert visible.total == 1

    viewer = await _member(db, owner, OrgRoleName.VIEWER)
    with pytest.raises(AuthorizationError):
        await service.list_for_dataset(viewer, dataset.id)
    stranger = await _owner(db)
    with pytest.raises(NotFoundError):
        await service.list_for_dataset(stranger, dataset.id)


async def test_cases_narrow_to_the_ones_named(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=3)
    service = EvalRunService(db)
    run = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    everything = await service.cases(ctx, run.id)

    named = await service.cases(ctx, run.id, case_ids=[everything.items[1].case_id])

    assert [case.case_id for case in named.items] == [everything.items[1].case_id]
    assert named.total == 1
    expectation = named.items[0].expectation
    assert expectation is not None
    assert [check.model_dump()["value"] for check in expectation.checks] == ["30 days"]


@pytest.mark.security
async def test_an_eval_run_names_its_case_to_who_may_see_the_dataset(db) -> None:
    owner = await _owner(db)
    agent, _ = await _agent(db, owner)
    dataset = await _dataset(db, owner, cases=1)
    service = EvalRunService(db)
    run = await service.start(owner, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db), run.id, owner)
    attempt = await db.scalar(select(EvalRunCase).where(EvalRunCase.eval_run_id == run.id))
    assert attempt is not None and attempt.agent_run_id is not None

    link = await service.case_link(owner, attempt.agent_run_id)

    assert link is not None
    assert (link.eval_run_id, link.agent_id, link.case_id) == (run.id, agent.id, attempt.case_id)
    assert (link.dataset_name, link.case_input) == (dataset.name, "Question 0")
    # A private dataset is its owner's: a colleague reading the run history
    # learns neither its name nor its question from it.
    dataset.visibility = "private"
    await db.flush()
    member = await _member(db, owner, OrgRoleName.MEMBER)
    assert await service.case_link(member, attempt.agent_run_id) is None
    assert await service.case_link(owner, uuid.uuid4()) is None


async def test_an_eval_run_puts_nothing_in_the_review_queue_itself(db) -> None:
    """A run's failures go to review only when a person sends them there."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    dataset.scoring = {**dataset.scoring, "review": {"select": "all"}}
    await db.flush()
    service = EvalRunService(db)
    run = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db, answer=lambda prompt, call: _FAIL), run.id, ctx)

    states = (
        await db.scalars(select(CaseScore.review_state).where(CaseScore.eval_run_id == run.id))
    ).all()

    assert states and set(states) == {"none"}


async def test_the_estimate_prices_the_judge_the_dataset_names(db) -> None:
    ctx = await _owner(db)
    await _assist(db, ctx, on=True)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=4)
    judge = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility="org",
        slug=f"strict-{uuid.uuid4().hex[:8]}",
        name="Strict judge",
        status="published",
        kind="judge",
        draft_spec={"name": "Strict judge"},
    )
    db.add(judge)
    await db.flush()
    db.add(
        AgentRun(
            organization_id=ctx.organization_id,
            agent_id=judge.id,
            surface=RunSurface.EVAL.value,
            status="completed",
            model_label="gpt-test",
            cost_usd=Decimal("0.02"),
            started_at=datetime.now(UTC),
        )
    )
    dataset.scoring = {
        "judge": {
            "enabled": True,
            "agent_id": str(judge.id),
            "criteria": [{"name": "Tone", "description": "Polite"}],
        }
    }
    await db.flush()

    estimate = await EvalRunService(db).estimate(
        ctx, agent.id, EvalRunRequest(dataset_id=dataset.id)
    )

    # Its own history, not the default judge's guess.
    assert estimate.judge_usd == Decimal("0.08")


async def test_a_run_of_the_draft_says_when_the_draft_moved_on(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    service = EvalRunService(db)
    draft_run = await service.start(
        ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, candidate="draft")
    )
    version_run = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))

    assert (await service.get(ctx, draft_run.id)).draft_changed is False
    assert (await service.get(ctx, version_run.id)).draft_changed is None
    agent.draft_spec = {**agent.draft_spec, "instructions": "Edited since"}
    await db.flush()
    assert (await service.get(ctx, draft_run.id)).draft_changed is True


@pytest.mark.security
async def test_what_a_run_tested_is_read_by_who_may_edit_the_agent(db) -> None:
    owner = await _owner(db)
    agent, _ = await _agent(db, owner)
    dataset = await _dataset(db, owner, cases=1)
    service = EvalRunService(db)
    run = await service.start(
        owner,
        agent.id,
        EvalRunRequest(dataset_id=dataset.id, candidate="draft", paired_baseline=True),
    )
    draft, baseline = sorted(run.arms, key=lambda arm: arm.position)

    assert (await service.arm_spec(owner, run.id, draft.id)).instructions == "Being edited"
    assert (await service.arm_spec(owner, run.id, baseline.id)).instructions == "v7"
    with pytest.raises(NotFoundError):
        await service.arm_spec(owner, run.id, uuid.uuid4())
    operator = await _member(db, owner, OrgRoleName.OPERATOR)
    with pytest.raises(AuthorizationError):
        await service.arm_spec(operator, run.id, draft.id)


async def test_what_a_run_tested_is_gone_with_its_version(db) -> None:
    ctx = await _owner(db)
    agent, versions = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    service = EvalRunService(db)
    run = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    [arm] = run.arms
    stored = await db.get(EvalRunArm, arm.id)
    assert stored is not None
    stored.agent_version_id = None
    await db.flush()

    with pytest.raises(NotFoundError, match="version this side ran is gone"):
        await service.arm_spec(ctx, run.id, arm.id)


async def test_a_judge_with_no_history_is_priced_at_its_models_price(db) -> None:
    """At the model the judge's published spec names."""
    ctx = await _owner(db)
    await _assist(db, ctx, on=True)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=10)
    nano = await _profile(db, ctx, "gpt-4.1-nano")
    judge = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility="org",
        slug=f"strict-{uuid.uuid4().hex[:8]}",
        name="Strict judge",
        status="published",
        kind="judge",
        draft_spec={"name": "Strict judge"},
    )
    db.add(judge)
    await db.flush()
    published = AgentVersion(
        id=uuid.uuid4(),
        agent_id=judge.id,
        organization_id=ctx.organization_id,
        version=1,
        spec={"name": "Strict judge", "model_profile_id": str(nano.id)},
    )
    db.add(published)
    await db.flush()
    judge.current_version_id = published.id
    criteria = [{"name": "Tone", "description": "Polite"}]
    dataset.scoring = {"judge": {"enabled": True, "agent_id": str(judge.id), "criteria": criteria}}
    # What it cost on the model it graded on before: not what it costs now.
    db.add(
        AgentRun(
            organization_id=ctx.organization_id,
            agent_id=judge.id,
            surface=RunSurface.EVAL.value,
            status="completed",
            model_label="gpt-test",
            cost_usd=Decimal("0.02"),
            started_at=datetime.now(UTC),
        )
    )
    await db.flush()
    priced = SimpleNamespace(label="nano", model="gpt-4.1-nano", provider="openai")
    service = EvalRunService(db)

    with patch.object(ModelProfileService, "resolve", new=AsyncMock(return_value=priced)):
        estimate = await service.estimate(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))

    # Ten cases, each 2000 tokens in at $0.10/1M and 400 out at $0.40/1M.
    assert estimate.judge_usd == Decimal("0.0036")
    assert estimate.judge_model_profile_id == nano.id


async def test_a_reused_baseline_is_asked_the_flipped_cases_again_in_this_run(db) -> None:
    """A cached baseline's first answers stand, but a case that flipped is put to
    both sides again the same day, so the confirmation is two-sided."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=3)
    service = EvalRunService(db)
    request = EvalRunRequest(dataset_id=dataset.id, candidate="draft", paired_baseline=True)
    first = await service.start(ctx, agent.id, request)
    await _run_to_end(db, Model(db), first.id, ctx)

    second = await service.start(ctx, agent.id, request)
    draft_fails = Model(
        db,
        answer=lambda prompt, call: (
            _FAIL
            if prompt == "Question 0"
            and isinstance(draft_fails.calls[call]["candidate"], UnpublishedCandidate)
            else _PASS
        ),
    )
    await _run_to_end(db, draft_fails, second.id, ctx)

    # Three first answers from the draft, then the flipped case twice more on
    # each side - the reused baseline answers again here.
    assert len(draft_fails.calls) == 7
    rerun_by_baseline = [
        call for call in draft_fails.calls if isinstance(call["candidate"], PublishedCandidate)
    ]
    assert len(rerun_by_baseline) == 2
    comparison = await service.compare(ctx, second.id)
    assert not comparison.paired
    assert comparison.baseline is not None and comparison.baseline.run_id == first.id
    regression = next(case for case in comparison.cases if case.flip == "regression")
    assert regression.baseline_reruns == [True, True]
    assert regression.confirmed
    read = await service.get(ctx, second.id)
    reused = next(arm for arm in read.arms if arm.role == "baseline")
    # Its first answers are still the earlier run's.
    assert reused.summary.cases == 3


async def test_the_judges_run_names_the_eval_case_it_graded(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    service = EvalRunService(db)
    run = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db), run.id, ctx)
    score = await db.scalar(select(CaseScore).where(CaseScore.eval_run_id == run.id))
    assert score is not None
    judge_run = uuid.uuid4()
    score.results = [*score.results, {"scorer": "judge", "judge_run_id": str(judge_run)}]
    await db.flush()

    link = await service.case_link(ctx, judge_run)

    assert link is not None and link.graded
    assert (link.eval_run_id, link.case_id) == (run.id, score.case_id)
    assert await service.case_links(ctx, [judge_run]) == {judge_run: link}
    # The judge's run is not kept (retention took it), so its price is missing.
    assert (await service.get(ctx, run.id)).cost_is_partial is True
    # A score nobody's eval run produced names no eval run.
    score.eval_run_id = None
    await db.flush()
    assert await service.case_link(ctx, judge_run) is None
    assert await service.case_links(ctx, [judge_run]) == {}


@pytest.mark.security
async def test_run_history_names_each_eval_runs_case_for_who_may_see_it(db) -> None:
    owner = await _owner(db)
    agent, _ = await _agent(db, owner)
    dataset = await _dataset(db, owner, cases=2)
    service = EvalRunService(db)
    run = await service.start(owner, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db), run.id, owner)
    answered = [
        attempt.agent_run_id
        for attempt in (
            await db.scalars(select(EvalRunCase).where(EvalRunCase.eval_run_id == run.id))
        ).all()
    ]

    links = await service.case_links(owner, [*answered, uuid.uuid4()])

    assert {link.case_input for link in links.values()} == {"Question 0", "Question 1"}
    assert set(links) == set(answered)
    assert await service.case_links(owner, []) == {}
    dataset.visibility = "private"
    await db.flush()
    member = await _member(db, owner, OrgRoleName.MEMBER)
    assert await service.case_links(member, answered) == {}


async def _errored(
    db: AsyncSession,
    run_id,
    *,
    answer: str | None = None,
    scorer: str = "check",
    status: str = "error",
    reason_code: str = "judge_run_failed",
) -> CaseScore:
    """One of the run's scores - one that kept `answer`, when given - as a scorer
    that reached no verdict would have left it."""
    query = select(CaseScore).where(CaseScore.eval_run_id == run_id)
    if answer is not None:
        query = query.where(CaseScore.answer == answer)
    score = (await db.execute(query.limit(1))).scalar_one()
    score.results = [
        {**result, "scorer": scorer, "status": status, "reason_code": reason_code}
        for result in score.results
    ]
    score.passed = None
    await db.flush()
    return score


async def test_an_eval_score_is_graded_again_on_the_answer_its_attempt_kept(db) -> None:
    """The run that answered wrote no transcript; the attempt holds what it said."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    started = await EvalRunService(db).start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db), started.id, ctx)
    score = await _errored(db, started.id)
    read = await EvalRunService(db).get(ctx, started.id)
    assert read.ungraded_score_ids == [score.id]
    assert [case.input for case in read.arms[0].ungraded_cases] == ["Question 0"]
    # One that failed on another criterion was decided all the same.
    score.passed = False
    await db.flush()
    read = await EvalRunService(db).get(ctx, started.id)
    assert (read.ungraded_score_ids, read.arms[0].ungraded_cases) == ([], [])
    score.passed = None
    await db.flush()

    rescored = await ScoringService(db).rescore(
        ctx, dataset.id, RescoreRequest(score_ids=[score.id])
    )

    assert [(item.id, item.passed, item.eval_run_id) for item in rescored.rescored] == [
        (score.id, True, started.id)
    ]
    assert (await EvalRunService(db).get(ctx, started.id)).ungraded_score_ids == []


async def test_grading_a_baseline_again_drops_the_verdicts_that_rest_on_it(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    service = EvalRunService(db)
    v6 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    await _run_to_end(db, Model(db), v6.id, ctx)
    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db), v7.id, ctx)
    await service.get(ctx, v6.id)
    await service.get(ctx, v7.id)
    score = await _errored(db, v6.id)
    score.human_passed = True
    await db.flush()
    # A person already decided it, so nothing is left to grade on the run.
    assert (await service.get(ctx, v6.id)).ungraded_score_ids == []

    await ScoringService(db).rescore(ctx, dataset.id, RescoreRequest(score_ids=[score.id]))

    for run_id in (v6.id, v7.id):
        stored = await db.get(EvalRun, run_id)
        assert stored is not None
        await db.refresh(stored)
        assert (stored.outcome, stored.outcome_at) == (None, None)
    outcome = (await service.get(ctx, v7.id)).outcome
    assert outcome is not None and outcome.baseline_pass_rate == 1.0


async def test_an_eval_score_whose_attempt_kept_no_answer_cannot_be_graded_again(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    started = await EvalRunService(db).start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, Model(db), started.id, ctx)
    score = await _errored(db, started.id)
    attempt = (
        await db.execute(select(EvalRunCase).where(EvalRunCase.case_score_id == score.id))
    ).scalar_one()
    attempt.answer = None
    await db.flush()

    with pytest.raises(BadRequestError):
        await ScoringService(db).rescore(ctx, dataset.id, RescoreRequest(score_ids=[score.id]))


async def test_a_run_sends_its_confirmed_regressions_to_review_itself(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=3)
    service = EvalRunService(db)
    v6 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    await _run_to_end(db, Model(db), v6.id, ctx)
    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    model = Model(db, answer=lambda prompt, call: _FAIL if prompt == "Question 0" else _PASS)
    await _run_to_end(db, model, v7.id, ctx)

    read = await service.get(ctx, v7.id)
    assert (read.routed_to_review, (await service.get(ctx, v6.id)).routed_to_review) == (1, 0)
    assert read.routed_replacing == 0
    # The one that failed is waiting, so none is left for a person to send.
    assert read.arms[0].unsent_failed == 0
    waiting = (
        await db.scalars(
            select(CaseScore).where(
                CaseScore.eval_run_id == v7.id, CaseScore.review_state == "pending"
            )
        )
    ).all()
    # The first answer that broke, not its reruns.
    assert [score.answer for score in waiting] == [_FAIL]
    first = await db.scalar(
        select(EvalRunCase).where(
            EvalRunCase.eval_run_id == v7.id,
            EvalRunCase.case_score_id == waiting[0].id,
        )
    )
    assert first is not None and first.attempt == 0

    # The same case broken again by a later run takes the older one's place in review.
    # One transaction gives every score the same clock; only a newer one replaces.
    waiting[0].created_at = datetime.now(UTC) - timedelta(hours=1)
    passed = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    await _run_to_end(db, Model(db), passed.id, ctx)
    again = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await _run_to_end(db, model, again.id, ctx)
    later = await service.get(ctx, again.id)
    assert (later.routed_to_review, later.routed_replacing) == (1, 1)
    await db.refresh(waiting[0])
    assert (waiting[0].review_state, waiting[0].human_passed) == ("none", None)


async def test_what_a_run_sends_to_review_is_what_a_person_should_see(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)
    v6 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    await _run_to_end(db, Model(db), v6.id, ctx)
    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    model = Model(db, answer=lambda prompt, call: _FAIL if prompt == "Question 0" else _PASS)
    await _run_to_end(db, model, v7.id, ctx)
    run = await db.get(EvalRun, v7.id)
    assert run is not None
    broke = await service.review_worthy(ctx, run)
    assert len(broke) == 1

    # A judge that was skipped, or a check that failed to run, is not work for a person.
    for scorer, status, code in (
        ("judge", "skipped", "ai_assistance_off"),
        ("judge", "skipped", "judge_budget"),
        ("check", "error", None),
    ):
        skipped = await _errored(
            db, v7.id, answer=_PASS, scorer=scorer, status=status, reason_code=code
        )
        assert skipped.id not in await service.review_worthy(ctx, run)

    # An answer the judge failed to grade goes too, unless a person decided it.
    errored = await _errored(db, v7.id, answer=_PASS, scorer="judge")
    worthy = await service.review_worthy(ctx, run)
    assert errored.id in worthy and worthy[0] == broke[0]
    errored.human_passed = True
    await db.flush()
    assert errored.id not in await service.review_worthy(ctx, run)

    # A regression under another judge is not one to send.
    await _pin(db, v6.id, {"agent_version_id": None, "rubric_hash": "a"})
    await _pin(db, v7.id, {"agent_version_id": None, "rubric_hash": "b"})
    assert broke[0] not in await service.review_worthy(ctx, run)


async def test_a_run_that_cannot_send_to_review_still_completes_and_says_why(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)
    v6 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    await _run_to_end(db, Model(db), v6.id, ctx)
    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    model = Model(db, answer=lambda prompt, call: _FAIL if prompt == "Question 0" else _PASS)
    refused = BadRequestError(message="The review queue is closed", code="REVIEW_CLOSED")

    with patch.object(ScoringService, "route_to_review", new=AsyncMock(side_effect=refused)):
        await _run_to_end(db, model, v7.id, ctx)

    read = await service.get(ctx, v7.id)
    assert read.status == "completed"
    assert read.routed_to_review == 0
    assert read.arms[0].unsent_failed == 1
    assert read.routing_error is not None
    assert (read.routing_error.code, read.routing_error.message) == (
        "REVIEW_CLOSED",
        "The review queue is closed",
    )
    # The answers and their grades are kept all the same.
    assert read.arms[0].summary.failed == 1


async def test_an_environment_with_an_eval_run_waiting_in_it_is_kept(db) -> None:
    """Removed, the run's environment would read as the default and its cases would
    go on against production's connections."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    environments = AgentEnvironmentService(db)
    staging = await environments.create(ctx, agent.id, EnvironmentCreate(name="staging"))
    started = await EvalRunService(db).start(
        ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, environment_id=staging.id)
    )

    with pytest.raises(ConcurrentChangeError, match="1 eval run"):
        await environments.delete(ctx, agent.id, staging.id)

    await _run_to_end(db, Model(db), started.id, ctx)
    await environments.delete(ctx, agent.id, staging.id)


async def test_a_run_cancelled_before_its_reruns_queues_none(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)
    v6 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=6))
    await _run_to_end(db, Model(db), v6.id, ctx)
    v7 = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    model = Model(db, answer=lambda prompt, call: _FAIL if prompt == "Question 0" else _PASS)
    worker = EvalRunWorker(v7.id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock())

    async def execute(runner, *args, **kwargs):
        return await model.execute(runner, *args, **kwargs)

    with patch.object(AgentRunnerService, "execute", new=execute):
        started = await worker._begin()
        assert started is not None
        await worker._wave(started)
    await service.cancel(ctx, v7.id)

    assert await worker._queue_reruns(started) is False
    reruns = await db.scalars(
        select(EvalRunCase).where(EvalRunCase.eval_run_id == v7.id, EvalRunCase.attempt > 0)
    )
    assert reruns.all() == []


@pytest.mark.security
async def test_who_may_edit_an_agent_is_read_per_agent_not_off_the_role(db) -> None:
    """What the console reads to offer Test draft, Stop and Publish on an eval run."""
    owner = await _owner(db)
    agent, _ = await _agent(db, owner)
    agent.visibility = "private"
    editor = await _member(db, owner, OrgRoleName.VIEWER)
    reader = await _member(db, owner, OrgRoleName.VIEWER)
    for member, level in ((editor, GrantLevel.EDIT), (reader, GrantLevel.READ)):
        db.add(
            ResourceGrant(
                organization_id=owner.organization_id,
                subject_user_id=member.user_id,
                resource_type="agent",
                resource_id=agent.id,
                level=level.value,
            )
        )
    await db.flush()
    registry = AgentRegistryService(db)

    for ctx, editable in ((owner, True), (editor, True), (reader, False)):
        assert await registry.may_edit(ctx, agent) is editable
        rows, _ = await registry.list_agents(ctx)
        assert [(row.id, row.can_edit) for row in rows] == [(agent.id, editable)]


async def test_cases_from_a_proposals_evidence_are_left_out_and_listed(db) -> None:
    """A change is never measured on the conversations it was derived from, and the
    run says which cases it left out so a smaller sample is not a mystery."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=3)
    evidence = uuid.uuid4()
    conversation = Conversation(id=evidence, organization_id=ctx.organization_id)
    db.add(conversation)
    await db.flush()
    first = (
        (
            await db.execute(
                select(DatasetCase)
                .where(DatasetCase.dataset_id == dataset.id)
                .order_by(DatasetCase.input)
            )
        )
        .scalars()
        .first()
    )
    assert first is not None
    first.source_conversation_id = evidence
    await db.flush()
    service = EvalRunService(db)
    projection = AgentSpec(name="Clerk", instructions="Proposed")

    started = await service.start(
        ctx,
        agent.id,
        EvalRunRequest(dataset_id=dataset.id, paired_baseline=True),
        candidate_spec=projection,
        exclude_conversations=[evidence],
    )

    assert started.excluded_case_ids == [first.case_id]
    assert started.cases == 2
    assert started.paired is True
    assert all(arm.reused_from_arm_id is None for arm in started.arms)


async def test_a_dataset_made_wholly_of_the_evidence_is_refused(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    evidence = uuid.uuid4()
    db.add(Conversation(id=evidence, organization_id=ctx.organization_id))
    await db.flush()
    case = (
        await db.execute(select(DatasetCase).where(DatasetCase.dataset_id == dataset.id))
    ).scalar_one()
    case.source_conversation_id = evidence
    await db.flush()

    with pytest.raises(BadRequestError, match="none can measure it"):
        await EvalRunService(db).estimate(
            ctx,
            agent.id,
            EvalRunRequest(dataset_id=dataset.id),
            candidate_spec=AgentSpec(name="Clerk", instructions="Proposed"),
            exclude_conversations=[evidence],
        )


async def test_a_proposed_skill_body_reaches_every_candidate_answer(db) -> None:
    """A skill change is measured with the agent held still: the candidate serves the
    proposed body, the baseline the stored one."""
    from app.agents.capabilities.skills import SkillBody

    ctx = await _owner(db)
    agent, versions = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    skill_id = uuid.uuid4()
    body = SkillBody(description="Refunds", content="Say 30 days.")
    published = AgentSpec.model_validate(versions[7].spec)
    model = Model(db)
    service = EvalRunService(db)

    started = await service.start(
        ctx,
        agent.id,
        EvalRunRequest(dataset_id=dataset.id, paired_baseline=True),
        candidate_spec=published,
        candidate_skills={skill_id: body},
    )
    await _run_to_end(db, model, started.id, ctx)

    candidates = [call["candidate"] for call in model.calls]
    served = [c.skill_bodies for c in candidates if isinstance(c, UnpublishedCandidate)]
    assert served == [{skill_id: body}]
    assert any(isinstance(c, PublishedCandidate) for c in candidates)
    arms = (
        (await db.execute(select(EvalRunArm).where(EvalRunArm.eval_run_id == started.id)))
        .scalars()
        .all()
    )
    candidate = next(arm for arm in arms if arm.role == "candidate")
    baseline = next(arm for arm in arms if arm.role == "baseline")
    assert candidate.skill_bodies == {
        str(skill_id): {"description": "Refunds", "content": "Say 30 days."}
    }
    assert candidate.spec_hash != baseline.spec_hash


async def test_a_published_version_can_carry_a_proposed_skill_body(db) -> None:
    """Checking a skill change runs the published version on both sides - nothing
    unpublished to validate - and serves the proposed body on the candidate only."""
    from app.agents.capabilities.skills import SkillBody

    ctx = await _owner(db)
    agent, versions = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    skill_id = uuid.uuid4()
    body = SkillBody(description="Refunds", content="Say 30 days.")
    model = Model(db)

    started = await EvalRunService(db).start(
        ctx,
        agent.id,
        EvalRunRequest(dataset_id=dataset.id, version=7, baseline_version=7),
        purpose=EvalRunPurpose.GATE,
        candidate_skills={skill_id: body},
    )
    await _run_to_end(db, model, started.id, ctx)

    candidates = [call["candidate"] for call in model.calls]
    assert {type(c) for c in candidates} == {PublishedCandidate}
    assert {c.version_id for c in candidates} == {versions[7].id}
    assert sorted(len(c.skill_bodies) for c in candidates) == [0, 1]
    read = await EvalRunService(db).get(ctx, started.id)
    assert {arm.role: arm.skill_ids for arm in read.arms} == {
        "candidate": [skill_id],
        "baseline": [],
    }


async def test_a_published_version_can_carry_a_proposed_context_body(db) -> None:
    """A context file change is checked like a skill change: the published version on
    both sides, the proposed body on the candidate alone, and no cached baseline."""
    from app.agents.capabilities.context import ContextBody

    ctx = await _owner(db)
    agent, versions = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    context_id = uuid.uuid4()
    body = ContextBody(description="Returns", content="Returns take 30 days.")
    model = Model(db)

    started = await EvalRunService(db).start(
        ctx,
        agent.id,
        EvalRunRequest(dataset_id=dataset.id, version=7, baseline_version=7),
        purpose=EvalRunPurpose.GATE,
        candidate_contexts={context_id: body},
    )
    await _run_to_end(db, model, started.id, ctx)

    candidates = [call["candidate"] for call in model.calls]
    assert {type(c) for c in candidates} == {PublishedCandidate}
    assert sorted(len(c.context_bodies) for c in candidates) == [0, 1]
    read = await EvalRunService(db).get(ctx, started.id)
    assert {arm.role: arm.context_ids for arm in read.arms} == {
        "candidate": [context_id],
        "baseline": [],
    }
    assert all(arm.reused_from_arm_id is None for arm in read.arms)


async def test_a_skill_change_is_never_measured_against_a_cached_baseline(db) -> None:
    """A skill's stored body is not versioned with the agent, so a baseline cached
    before the skill changed would have read a body the change is not replacing."""
    from app.agents.capabilities.skills import SkillBody

    ctx = await _owner(db)
    agent, versions = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    service = EvalRunService(db)
    request = EvalRunRequest(dataset_id=dataset.id, candidate="draft", paired_baseline=True)
    await _run_to_end(db, Model(db), (await service.start(ctx, agent.id, request)).id, ctx)
    assert {arm.role: arm.basis for arm in (await service.estimate(ctx, agent.id, request)).arms}[
        "baseline"
    ] == "cached"

    estimate = await service.estimate(
        ctx,
        agent.id,
        EvalRunRequest(dataset_id=dataset.id, paired_baseline=True),
        candidate_spec=AgentSpec.model_validate(versions[7].spec),
        candidate_skills={uuid.uuid4(): SkillBody(description="Refunds", content="Say 30 days.")},
    )

    baseline = next(arm for arm in estimate.arms if arm.role == "baseline")
    assert baseline.basis != "cached"
    assert baseline.cached_from_run_id is None


async def test_an_earlier_run_named_as_the_baseline_must_match_and_stand_alone(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    other = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)
    earlier = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=7))
    elsewhere = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=other.id, version=7))

    with pytest.raises(BadRequestError, match="a run that completed"):
        await service.estimate(
            ctx,
            agent.id,
            EvalRunRequest(dataset_id=dataset.id, version=7, baseline_run_id=earlier.id),
        )
    await _run_to_end(db, Model(db), elsewhere.id, ctx)
    with pytest.raises(BadRequestError, match="not both"):
        await service.estimate(
            ctx,
            agent.id,
            EvalRunRequest(
                dataset_id=dataset.id,
                version=7,
                paired_baseline=True,
                baseline_run_id=earlier.id,
            ),
        )
    with pytest.raises(BadRequestError, match="same agent on the same dataset"):
        await service.estimate(
            ctx,
            agent.id,
            EvalRunRequest(dataset_id=dataset.id, version=7, baseline_run_id=elsewhere.id),
        )
    with pytest.raises(NotFoundError):
        await service.estimate(
            ctx,
            agent.id,
            EvalRunRequest(dataset_id=dataset.id, version=7, baseline_run_id=uuid.uuid4()),
        )


async def test_a_run_measured_against_an_earlier_one_confirms_its_flips_against_it(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    service = EvalRunService(db)
    earlier = await service.start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, version=7))
    await _run_to_end(db, Model(db), earlier.id, ctx)

    later = await service.start(
        ctx,
        agent.id,
        EvalRunRequest(dataset_id=dataset.id, version=7, baseline_run_id=earlier.id),
    )
    model = Model(db, answer=lambda prompt, call: _FAIL if prompt == "Question 1" else _PASS)
    await _run_to_end(db, model, later.id, ctx)

    comparison = await service.compare(ctx, later.id)
    assert comparison.baseline is not None and comparison.baseline.run_id == earlier.id
    assert (comparison.regressions_confirmed, comparison.paired) == (1, False)


@pytest.mark.security
async def test_who_may_publish_an_agent_is_read_per_agent_not_off_the_role(db) -> None:
    """What the console reads to offer Publish, and not the same answer as editing."""
    owner = await _owner(db)
    shared, _ = await _agent(db, owner)
    shared.visibility = "private"
    publisher = await _member(db, owner, OrgRoleName.VIEWER)
    runner = await _member(db, owner, OrgRoleName.VIEWER)
    for member, level in ((publisher, GrantLevel.EDIT), (runner, GrantLevel.USE)):
        db.add(
            ResourceGrant(
                organization_id=owner.organization_id,
                subject_user_id=member.user_id,
                resource_type="agent",
                resource_id=shared.id,
                level=level.value,
            )
        )
    member = await _member(db, owner, OrgRoleName.MEMBER)
    own, _ = await _agent(db, member)
    own.visibility = "private"
    await db.flush()
    registry = AgentRegistryService(db)

    for ctx, agent, publishable in (
        (owner, shared, True),
        (publisher, shared, True),
        (runner, shared, False),
        (member, own, False),
    ):
        assert await registry.may_publish(ctx, agent) is publishable
        rows, _ = await registry.list_agents(ctx)
        assert {row.id: row.can_publish for row in rows}[agent.id] is publishable
    # A Member edits the agent they own - only publishing it is out of reach.
    assert await registry.may_edit(member, own) is True
