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
    NotFoundError,
    NothingToScoreError,
    PaymentRequiredError,
)
from app.core.permissions import ROLE_PERMS, AuthContext, OrgRoleName, Perm, Scope
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.case_score import CaseScore
from app.db.models.credential import ModelProfile
from app.db.models.dataset import Dataset, DatasetCase
from app.db.models.eval_run import EvalRun, EvalRunCase, EvalRunStatus
from app.db.models.intercepted_tool_call import InterceptedToolCall
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, ResourceGrant
from app.db.models.user import User
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.schemas.eval_run import EvalRunRequest
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
    # One confirmed flip cannot tell two versions apart.
    assert comparison.verdict == "inconclusive"
    assert comparison.compared == 4
    assert comparison.flips_by_tag["refunds"]["regression"] == 1

    failed = await service.cases(ctx, v7.id, outcome="failed")
    assert [case.input for case in failed.items] == ["Question 0"]
    assert [attempt.attempt for attempt in failed.items[0].attempts] == [0, 1, 2]


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
    dataset = await _dataset(db, ctx, cases=1)
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

    # No judge is published in this organization, so that is the judge now.
    await _pin(db, first.id, {"agent_version_id": None, "rubric_hash": "a"})
    assert await baseline_basis() == "cached"
    await _pin(db, first.id, {"agent_version_id": str(uuid.uuid4()), "rubric_hash": "a"})
    assert await baseline_basis() == "history"
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
    assert outcome.verdict == "inconclusive"
    assert outcome.baseline is not None and outcome.baseline.run_id == v6.id
    assert outcome.regressions_confirmed == 1
    assert (outcome.candidate_pass_rate, outcome.baseline_pass_rate) == (0.75, 1.0)
    read = await service.get(ctx, v7.id)
    assert (read.cases, read.first_done, read.first_total, read.attempts_total) == (4, 4, 4, 6)
    assert read.rerun_ceiling_usd == Decimal("0.08")

    # Read again, the verdict is the one kept rather than compared anew.
    stored = await db.get(EvalRun, v7.id)
    assert stored is not None and stored.outcome_at is not None
    kept_at = stored.outcome_at
    await service.get(ctx, v7.id)
    assert stored.outcome_at == kept_at

    # A person passes the case that broke: the regression is gone from the listing.
    await _decide(db, v7.id, "Question 0", passed=True)
    decided = await service.get(ctx, v7.id)
    assert decided.outcome is not None
    assert decided.outcome.regressions_confirmed == 0
    assert decided.outcome.candidate_pass_rate == 1.0
    assert stored.outcome_at > kept_at


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
