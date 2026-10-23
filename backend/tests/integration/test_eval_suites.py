"""Eval suites end to end against Postgres, with the model replaced by a scripted answer.

What the issue promises, checked where only a database shows it:

- a suite on a daily schedule runs once a day and records its result; a paused
  suite does not run;
- publishing a version starts the suites set to run on publish, and only those;
- a result below the threshold tells the owner once, naming the failing cases;
- a change to a bound skill fires the suites watching it, and an unrelated one
  does not;

and the refusals: another organization, the grants, a script or an
administrator acting as somebody, the budget, the cost ceiling, AI assistance
off, and an owner who has left.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConfigurationError,
    EvalSuiteNotRunnableError,
    NotFoundError,
    SystemAgentRestrictedError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.dataset import Dataset
from app.db.models.eval_run import EvalRun
from app.db.models.eval_suite import EvalSuite, EvalSuiteResult
from app.db.models.notification import Notification
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, ResourceGrant
from app.db.models.user import User
from app.repositories import agent_environment_repo
from app.schemas.agent_environment import EnvironmentCreate, EnvironmentUpdate
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.schemas.eval_run import ArmSummaryRead, EvalUngradedCaseRead
from app.schemas.eval_suite import (
    EvalSuiteCreate,
    EvalSuiteEstimateRequest,
    EvalSuiteSchedule,
    EvalSuiteThreshold,
    EvalSuiteUpdate,
)
from app.schemas.skill import SkillUpdate
from app.services.access import resolve_access
from app.services.agent_environment import AgentEnvironmentService
from app.services.agent_registry import AgentRegistryService, PublishedCandidate
from app.services.agent_runner import AgentRunnerService
from app.services.dataset import DatasetService
from app.services.eval_run import EvalRunService
from app.services.eval_run_worker import EvalRunWorker
from app.services.eval_suite import EvalSuiteService
from app.services.model_profile import ModelProfileService
from app.services.run_reaper import RunReaperService
from app.services.skills import SkillService

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


async def _agent(
    db: AsyncSession, ctx: AuthContext, *, spec: dict[str, Any] | None = None
) -> tuple[Agent, AgentVersion]:
    """An agent with one published version, served by its default environment."""
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility="org",
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        status="published",
        draft_spec={"name": "Clerk", "instructions": "v2", **(spec or {})},
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        organization_id=ctx.organization_id,
        version=1,
        spec={"name": "Clerk", "instructions": "v1", **(spec or {})},
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    await db.flush()
    await agent_environment_repo.create(
        db,
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        name="production",
        version_id=version.id,
        is_default=True,
        created_by_user_id=ctx.user_id,
    )
    return agent, version


async def _dataset(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    cases: int = 4,
    checks: list[dict[str, Any]] | None = None,
) -> Dataset:
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name=f"refunds-{uuid.uuid4().hex[:6]}"))
    for index in range(cases):
        await service.add_case(
            ctx,
            dataset.id,
            DatasetCaseCreate(
                input=f"Question {index}",
                checks=checks if checks is not None else [{"type": "contains", "value": "30 days"}],
            ),
        )
    stored = await db.get(Dataset, dataset.id)
    assert stored is not None
    return stored


def _suite_data(dataset: Dataset, **values: Any) -> EvalSuiteCreate:
    return EvalSuiteCreate(name=f"nightly-{uuid.uuid4().hex[:6]}", dataset_id=dataset.id, **values)


class Model:
    """Stands in for the runner: answers from a script and writes the run row a real run would."""

    def __init__(self, db: AsyncSession, *, answer: Any = lambda prompt: _PASS) -> None:
        self.db = db
        self.answer = answer
        self.calls = 0

    async def execute(self, runner: AgentRunnerService, ctx: AuthContext, agent_id, prompt, **kw):
        self.calls += 1
        candidate = kw["candidate"]
        started = datetime.now(UTC)
        run = AgentRun(
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            agent_version_id=candidate.version_id
            if isinstance(candidate, PublishedCandidate)
            else None,
            user_id=ctx.user_id,
            surface=kw["surface"].value,
            status="completed",
            model_label="gpt-test",
            cost_usd=Decimal("0.01"),
            input_tokens=100,
            output_tokens=20,
            started_at=started,
            ended_at=started + timedelta(milliseconds=500),
        )
        self.db.add(run)
        await self.db.flush()
        return self.answer(prompt), run


def _sessions(db: AsyncSession):
    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    return session


@pytest.fixture(autouse=True)
def _environment():
    """No real model, no dispatch and no Redis - the session is shared, so serial."""

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
        patch("app.services.eval_suite.spawn_after_commit", side_effect=dropped),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
        patch("app.services.eval_run.settings.EVAL_FALLBACK_CASE_COST_USD", Decimal("0.05")),
    ):
        yield


async def _finish_runs(db: AsyncSession, model: Model) -> None:
    """Run every eval run a suite started to its end, as the worker would."""

    async def execute(runner, *args, **kwargs):
        return await model.execute(runner, *args, **kwargs)

    for result in (
        await db.execute(select(EvalSuiteResult).where(EvalSuiteResult.status == "running"))
    ).scalars():
        assert result.eval_run_id is not None
        with patch.object(AgentRunnerService, "execute", new=execute):
            await EvalRunWorker(
                result.eval_run_id,
                result.organization_id,
                sessions=_sessions(db),
                sleep=AsyncMock(),
            ).run()


async def _sweep(db: AsyncSession, model: Model, *, now: datetime) -> None:
    """One tick of the sweep with the eval runs it started carried to their end."""
    service = EvalSuiteService(db)
    await service.fire_schedules(now=now)
    await service.start_due(now=now)
    await _finish_runs(db, model)
    await service.settle_finished(now=now + timedelta(seconds=1))


async def _results(db: AsyncSession, suite_id) -> list[EvalSuiteResult]:
    return list(
        (
            await db.execute(
                select(EvalSuiteResult)
                .where(EvalSuiteResult.suite_id == suite_id)
                .order_by(EvalSuiteResult.created_at, EvalSuiteResult.due_at)
            )
        ).scalars()
    )


async def _notifications(db: AsyncSession, user_id) -> list[Notification]:
    return list(
        (
            await db.execute(
                select(Notification).where(
                    Notification.recipient_user_id == user_id,
                    Notification.event_type == "eval_suite_failed",
                )
            )
        ).scalars()
    )


async def test_a_daily_suite_runs_once_a_day_and_records_its_result(db) -> None:
    ctx = await _owner(db)
    agent, version = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    created = await service.create(
        ctx,
        agent.id,
        _suite_data(
            dataset, schedule=EvalSuiteSchedule(cron="0 6 * * *", timezone="Europe/Warsaw")
        ),
    )
    suite = await db.get(EvalSuite, created.id)
    assert suite is not None and suite.next_fire_at is not None
    due = suite.next_fire_at
    # 06:00 in Warsaw the next day, which is 23 or 25 hours on across a change of clocks.
    tomorrow = (due.astimezone(ZoneInfo("Europe/Warsaw")) + timedelta(days=1)).astimezone(UTC)
    model = Model(db)

    await _sweep(db, model, now=due)
    await _sweep(db, model, now=due + timedelta(minutes=1))
    await _sweep(db, model, now=tomorrow - timedelta(hours=1))

    [result] = await _results(db, suite.id)
    assert (result.trigger, result.status, result.version_number) == ("schedule", "passed", 1)
    assert result.summary is not None and result.summary["pass_rate"] == 1.0
    assert model.calls == 4
    await db.refresh(suite)
    assert suite.next_fire_at == tomorrow

    await _sweep(db, model, now=tomorrow)
    results = await _results(db, suite.id)
    assert [r.status for r in results] == ["passed", "passed"]
    # The second day measures the same version against the first day's run.
    assert results[1].baseline_eval_run_id == results[0].eval_run_id

    read = await service.get(ctx, agent.id, suite.id)
    assert read.last_result is not None and read.last_result.id == results[1].id
    assert read.schedule is not None and read.schedule.timezone == "Europe/Warsaw"
    assert results[0].eval_run_id is not None
    run = await service.evals.get(ctx, results[0].eval_run_id)
    assert run.suite is not None
    assert (run.suite.id, run.suite.trigger) == (suite.id, "schedule")


async def test_a_paused_suite_does_not_run(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    created = await service.create(
        ctx,
        agent.id,
        _suite_data(dataset, on_publish=True, schedule=EvalSuiteSchedule(cron="0 6 * * *")),
    )
    suite = await db.get(EvalSuite, created.id)
    assert suite is not None and suite.next_fire_at is not None
    due = suite.next_fire_at

    paused = await service.update(ctx, agent.id, suite.id, EvalSuiteUpdate(is_active=False))
    await _sweep(db, Model(db), now=due + timedelta(days=3))
    await AgentRegistryService(db).publish(ctx, agent.id)

    assert paused.is_active is False
    assert await _results(db, suite.id) == []
    with pytest.raises(EvalSuiteNotRunnableError) as refused:
        await service.run_now(ctx, agent.id, suite.id)
    assert refused.value.details == {"suite_id": suite.id, "reason": "paused"}

    resumed = await service.update(ctx, agent.id, suite.id, EvalSuiteUpdate(is_active=True))
    assert resumed.is_active and resumed.next_fire_at is not None
    assert resumed.next_fire_at > datetime.now(UTC)


async def test_pausing_forgets_a_run_that_was_waiting(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(dataset, on_publish=True))
    await AgentRegistryService(db).publish(ctx, agent.id)
    assert [r.status for r in await _results(db, suite.id)] == ["pending"]

    await service.update(ctx, agent.id, suite.id, EvalSuiteUpdate(is_active=False))

    assert await _results(db, suite.id) == []


async def test_publishing_starts_the_on_publish_suites_of_that_agent_and_only_those(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    other, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    watching = await service.create(ctx, agent.id, _suite_data(dataset, on_publish=True))
    scheduled = await service.create(
        ctx, agent.id, _suite_data(dataset, schedule=EvalSuiteSchedule(cron="0 6 * * *"))
    )
    elsewhere = await service.create(ctx, other.id, _suite_data(dataset, on_publish=True))

    published = await AgentRegistryService(db).publish(ctx, agent.id)

    [result] = await _results(db, watching.id)
    assert (result.trigger, result.version_number, result.baseline_version_number) == (
        "publish",
        published.version,
        1,
    )
    assert await _results(db, scheduled.id) == []
    assert await _results(db, elsewhere.id) == []

    model = Model(db)
    await _sweep(db, model, now=datetime.now(UTC))
    [settled] = await _results(db, watching.id)
    assert settled.status == "passed"
    assert settled.summary is not None and settled.summary["paired"] is True
    # Four cases on the new version and four on the one before it, side by side.
    assert model.calls == 8


async def test_an_environment_following_a_publish_is_a_promotion_onto_it(db) -> None:
    ctx = await _owner(db)
    agent, version = await _agent(db, ctx)
    dev = await AgentEnvironmentService(db).create(
        ctx, agent.id, EnvironmentCreate(name="dev", version_id=version.id, tracks_latest=True)
    )
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    promoted = await service.create(
        ctx, agent.id, _suite_data(dataset, environment_id=dev.id, on_promotion=True)
    )
    both = await service.create(
        ctx,
        agent.id,
        _suite_data(dataset, environment_id=dev.id, on_publish=True, on_promotion=True),
    )
    pinned = await service.create(ctx, agent.id, _suite_data(dataset, on_promotion=True))

    await AgentRegistryService(db).publish(ctx, agent.id)

    [result] = await _results(db, promoted.id)
    assert (result.trigger, result.version_number, result.baseline_version_number) == (
        "promotion",
        2,
        1,
    )
    # One run for a suite watching both: the publish and the promotion are one version.
    assert [r.trigger for r in await _results(db, both.id)] == ["publish"]
    # Production is pinned, so the publish did not reach it.
    assert await _results(db, pinned.id) == []


async def test_promoting_a_version_onto_the_suites_environment_runs_it_against_the_one_replaced(
    db,
) -> None:
    ctx = await _owner(db)
    agent, version = await _agent(db, ctx)
    newer = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        organization_id=ctx.organization_id,
        version=2,
        spec={"name": "Clerk"},
    )
    db.add(newer)
    await db.flush()
    environments = AgentEnvironmentService(db)
    staging = await environments.create(
        ctx, agent.id, EnvironmentCreate(name="staging", version_id=version.id)
    )
    qa = await environments.create(
        ctx, agent.id, EnvironmentCreate(name="qa", version_id=version.id)
    )
    dataset = await _dataset(db, ctx)
    suite = await EvalSuiteService(db).create(
        ctx, agent.id, _suite_data(dataset, environment_id=staging.id, on_promotion=True)
    )

    await environments.update(ctx, agent.id, qa.id, EnvironmentUpdate(version_id=newer.id))
    assert await _results(db, suite.id) == []

    await environments.update(ctx, agent.id, staging.id, EnvironmentUpdate(version_id=newer.id))
    [result] = await _results(db, suite.id)
    assert (result.trigger, result.version_number, result.baseline_version_number) == (
        "promotion",
        2,
        1,
    )


async def test_a_suite_naming_no_environment_watches_promotions_onto_the_default(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    newer = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        organization_id=ctx.organization_id,
        version=2,
        spec={"name": "Clerk"},
    )
    db.add(newer)
    await db.flush()
    dataset = await _dataset(db, ctx)
    suite = await EvalSuiteService(db).create(
        ctx, agent.id, _suite_data(dataset, on_promotion=True)
    )
    environments = AgentEnvironmentService(db)
    production = next(
        env for env in await environments.list_for_agent(ctx, agent.id) if env.is_default
    )

    await environments.update(ctx, agent.id, production.id, EnvironmentUpdate(version_id=newer.id))

    [result] = await _results(db, suite.id)
    assert (result.trigger, result.version_number, result.baseline_version_number) == (
        "promotion",
        2,
        1,
    )


async def test_a_result_below_the_threshold_tells_the_owner_once_naming_the_failing_cases(
    db,
) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(
        ctx, agent.id, _suite_data(dataset, threshold=EvalSuiteThreshold(min_pass_rate=0.9))
    )
    half = Model(
        db, answer=lambda prompt: _FAIL if prompt in {"Question 1", "Question 3"} else _PASS
    )

    await service.run_now(ctx, agent.id, suite.id)
    await _finish_runs(db, half)
    await service.settle_finished(now=datetime.now(UTC))

    [result] = await _results(db, suite.id)
    assert result.status == "failed"
    assert result.summary is not None
    assert [r["code"] for r in result.summary["reasons"]] == ["pass_rate_below"]
    assert {case["input"] for case in result.summary["failing_cases"]} == {
        "Question 1",
        "Question 3",
    }
    [notice] = await _notifications(db, ctx.user_id)
    assert "Question 1" in notice.summary and "Question 3" in notice.summary
    assert "pass rate 50% is below 90%" in notice.summary
    assert notice.context_url is not None and str(result.eval_run_id) in notice.context_url

    await service.run_now(ctx, agent.id, suite.id)
    await _finish_runs(db, half)
    await service.settle_finished(now=datetime.now(UTC))
    assert len(await _notifications(db, ctx.user_id)) == 1

    await service.run_now(ctx, agent.id, suite.id)
    await _finish_runs(db, Model(db))
    await service.settle_finished(now=datetime.now(UTC))
    await service.run_now(ctx, agent.id, suite.id)
    await _finish_runs(db, half)
    await service.settle_finished(now=datetime.now(UTC))

    assert [r.status for r in await _results(db, suite.id)] == [
        "failed",
        "failed",
        "passed",
        "failed",
    ]
    assert len(await _notifications(db, ctx.user_id)) == 2


async def test_a_confirmed_regression_fails_the_suite_by_default(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    suite = await EvalSuiteService(db).create(ctx, agent.id, _suite_data(dataset, on_publish=True))
    published = await AgentRegistryService(db).publish(ctx, agent.id)

    def answer(prompt: str) -> str:
        return _PASS

    model = Model(db, answer=answer)
    service = EvalSuiteService(db)
    await service.start_due(now=datetime.now(UTC))
    [running] = await _results(db, suite.id)
    # The new version breaks "Question 2" every time it is asked; the old one never does.
    model.answer = lambda prompt: _PASS
    calls: list[tuple[str, Any]] = []

    async def execute(runner, ctx_, agent_id, prompt, **kw):
        calls.append((prompt, kw["candidate"]))
        broken = (
            isinstance(kw["candidate"], PublishedCandidate)
            and kw["candidate"].version_id == published.id
        )
        model.answer = lambda _p: _FAIL if broken and prompt == "Question 2" else _PASS
        return await model.execute(runner, ctx_, agent_id, prompt, **kw)

    assert running.eval_run_id is not None
    with patch.object(AgentRunnerService, "execute", new=execute):
        await EvalRunWorker(
            running.eval_run_id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
        ).run()
    await service.settle_finished(now=datetime.now(UTC))

    [result] = await _results(db, suite.id)
    assert result.status == "failed"
    assert result.summary is not None
    assert result.summary["regressions_confirmed"] == 1
    assert [r["code"] for r in result.summary["reasons"]] == ["regressions"]
    assert result.summary["failing_cases"][0] == {
        "case_id": result.summary["failing_cases"][0]["case_id"],
        "input": "Question 2",
        "kind": "regression",
    }


async def test_a_bound_skill_changing_fires_the_suite_and_an_unrelated_one_does_not(db) -> None:
    ctx = await _owner(db)
    skills = SkillService(db)
    bound = await skills.create(ctx, name="refunds", description="Refund policy", content="30 days")
    unrelated = await skills.create(ctx, name="shipping", description="Shipping", content="2 days")
    agent, _ = await _agent(db, ctx, spec={"skill_ids": [str(bound.id)]})
    dataset = await _dataset(db, ctx)
    suite = await EvalSuiteService(db).create(
        ctx, agent.id, _suite_data(dataset, on_dependency_change=True)
    )

    await skills.update(ctx, unrelated.id, SkillUpdate(content="3 days"))
    assert await _results(db, suite.id) == []

    before = datetime.now(UTC)
    await skills.update(ctx, bound.id, SkillUpdate(content="45 days"))
    await skills.update(ctx, bound.id, SkillUpdate(content="30 days"))

    [result] = await _results(db, suite.id)
    assert result.trigger == "dependency"
    assert result.trigger_detail == {"kind": "skill", "id": str(bound.id)}
    # Due once the burst is over, so the second edit joined the first.
    assert result.due_at >= before + timedelta(minutes=9)
    assert await EvalSuiteService(db).start_due(now=before) == 0


async def test_a_specialists_skill_is_the_versions_too(db) -> None:
    ctx = await _owner(db)
    skill = await SkillService(db).create(
        ctx, name="refunds", description="Refunds", content="30 days"
    )
    delegation = {
        "id": "subagents",
        "enabled": True,
        "config": {
            "inline": [
                {
                    "name": "Refunds",
                    "description": "Refunds",
                    "instructions": "Answer refund questions.",
                    "skill_ids": [str(skill.id)],
                }
            ]
        },
    }
    agent, _ = await _agent(db, ctx, spec={"capabilities": [delegation]})
    dataset = await _dataset(db, ctx)
    suite = await EvalSuiteService(db).create(
        ctx, agent.id, _suite_data(dataset, on_dependency_change=True)
    )

    await SkillService(db).update(ctx, skill.id, SkillUpdate(content="45 days"))

    assert [r.trigger for r in await _results(db, suite.id)] == ["dependency"]


@pytest.mark.security
async def test_nothing_crosses_organizations(db) -> None:
    ctx = await _owner(db)
    stranger = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(dataset))

    with pytest.raises(NotFoundError):
        await service.get(stranger, agent.id, suite.id)
    with pytest.raises(NotFoundError):
        await service.run_now(stranger, agent.id, suite.id)
    assert (await service.list_visible(stranger)).items == []
    own, _ = await _agent(db, stranger)
    # A suite id is not reachable through an agent of the other organization either.
    with pytest.raises(NotFoundError):
        await service.get(stranger, own.id, suite.id)


@pytest.mark.security
async def test_an_edit_grant_lets_an_operator_set_one_up_and_nothing_else_does(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    other, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    operator = await _member(db, ctx, OrgRoleName.OPERATOR)
    service = EvalSuiteService(db)

    with pytest.raises(AuthorizationError):
        await service.create(operator, agent.id, _suite_data(dataset))
    db.add(
        ResourceGrant(
            organization_id=ctx.organization_id,
            subject_user_id=operator.user_id,
            resource_type="agent",
            resource_id=agent.id,
            level=GrantLevel.EDIT.value,
        )
    )
    await db.flush()

    created = await service.create(operator, agent.id, _suite_data(dataset))
    assert created.owner_user_id == operator.user_id
    with pytest.raises(AuthorizationError):
        await service.create(operator, other.id, _suite_data(dataset))


@pytest.mark.security
async def test_reading_suites_needs_permission_to_view_runs(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    viewer = await _member(db, ctx, OrgRoleName.VIEWER)

    with pytest.raises(AuthorizationError):
        await EvalSuiteService(db).list_for_agent(viewer, agent.id)


@pytest.mark.security
async def test_only_a_person_signed_in_as_themselves_saves_a_suite(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    scripted = replace(ctx, api_key_id=uuid.uuid4())

    with pytest.raises(AuthorizationError):
        await EvalSuiteService(db).create(scripted, agent.id, _suite_data(dataset))
    with (
        patch("app.services.eval_suite.current_impersonator", return_value=uuid.uuid4()),
        pytest.raises(AuthorizationError),
    ):
        await EvalSuiteService(db).create(ctx, agent.id, _suite_data(dataset))


@pytest.mark.security
async def test_a_dataset_the_saver_cannot_run_is_refused(db) -> None:
    ctx = await _owner(db)
    stranger = await _owner(db)
    agent, _ = await _agent(db, ctx)
    theirs = await _dataset(db, stranger)
    suite = await EvalSuiteService(db).create(ctx, agent.id, _suite_data(await _dataset(db, ctx)))

    with pytest.raises(NotFoundError):
        await EvalSuiteService(db).create(ctx, agent.id, _suite_data(theirs))
    with pytest.raises(NotFoundError):
        await EvalSuiteService(db).update(
            ctx, agent.id, suite.id, EvalSuiteUpdate(dataset_id=theirs.id)
        )


async def test_a_system_agent_has_no_suites(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    agent.kind = "judge"
    await db.flush()
    dataset = await _dataset(db, ctx)

    with pytest.raises(SystemAgentRestrictedError):
        await EvalSuiteService(db).create(ctx, agent.id, _suite_data(dataset))


async def test_a_suite_name_is_one_per_agent_and_an_environment_must_be_the_agents(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    other, other_version = await _agent(db, ctx)
    foreign = await AgentEnvironmentService(db).create(
        ctx, other.id, EnvironmentCreate(name="staging", version_id=other_version.id)
    )
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    await service.create(ctx, agent.id, EvalSuiteCreate(name="nightly", dataset_id=dataset.id))

    with pytest.raises(AlreadyExistsError):
        await service.create(ctx, agent.id, EvalSuiteCreate(name="nightly", dataset_id=dataset.id))
    with pytest.raises(NotFoundError):
        await service.create(ctx, agent.id, _suite_data(dataset, environment_id=foreign.id))


@pytest.mark.security
async def test_a_run_past_the_budget_is_skipped_and_said(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=20)
    org = await db.get(Organization, ctx.organization_id)
    assert org is not None
    org.monthly_budget_usd = Decimal("0.10")
    await db.flush()
    suite = await EvalSuiteService(db).create(
        ctx, agent.id, _suite_data(dataset, schedule=EvalSuiteSchedule(cron="0 6 * * *"))
    )
    row = await db.get(EvalSuite, suite.id)
    assert row is not None and row.next_fire_at is not None

    await _sweep(db, Model(db), now=row.next_fire_at)

    [result] = await _results(db, suite.id)
    assert (result.status, result.reason) == ("skipped", "budget")
    assert result.eval_run_id is None
    [notice] = await _notifications(db, ctx.user_id)
    assert "did not run" in notice.summary


async def test_a_run_over_the_suites_ceiling_is_skipped_and_refused_by_hand(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=20)
    service = EvalSuiteService(db)
    suite = await service.create(
        ctx, agent.id, _suite_data(dataset, on_publish=True, max_run_usd=Decimal("0.10"))
    )

    with pytest.raises(BadRequestError) as refused:
        await service.run_now(ctx, agent.id, suite.id)
    assert refused.value.details is not None and refused.value.details["reason"] == "over_cost_cap"

    await AgentRegistryService(db).publish(ctx, agent.id)
    await service.start_due(now=datetime.now(UTC))
    [result] = await _results(db, suite.id)
    assert (result.status, result.reason) == ("skipped", "over_cost_cap")


async def test_with_ai_assistance_off_a_judged_suite_is_skipped_and_a_checked_one_runs(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    judged = await _dataset(db, ctx, checks=[{"type": "judge", "criterion": "Cites the policy"}])
    checked = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    one = await service.create(ctx, agent.id, _suite_data(judged, on_publish=True))
    two = await service.create(ctx, agent.id, _suite_data(checked, on_publish=True))

    await AgentRegistryService(db).publish(ctx, agent.id)
    await _sweep(db, Model(db), now=datetime.now(UTC))

    [skipped] = await _results(db, one.id)
    [ran] = await _results(db, two.id)
    assert (skipped.status, skipped.reason) == ("skipped", "ai_assistance_off")
    assert ran.status == "passed"


async def test_a_suite_whose_owner_left_pauses_and_says_why(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    builder = await _member(db, ctx, OrgRoleName.BUILDER)
    suite = await EvalSuiteService(db).create(
        builder, agent.id, _suite_data(dataset, on_publish=True)
    )

    await db.execute(
        delete(OrganizationMember).where(
            OrganizationMember.organization_id == ctx.organization_id,
            OrganizationMember.user_id == builder.user_id,
        )
    )
    await AgentRegistryService(db).publish(ctx, agent.id)
    await EvalSuiteService(db).start_due(now=datetime.now(UTC))

    row = await db.get(EvalSuite, suite.id)
    assert row is not None
    assert (row.is_active, row.paused_reason) == (False, "owner_inactive")
    [result] = await _results(db, suite.id)
    assert (result.status, result.reason) == ("skipped", "owner_inactive")
    audits = (
        await db.execute(
            select(func.count()).where(
                AppAdminAuditLog.action == "eval_suite.disabled",
                AppAdminAuditLog.organization_id == ctx.organization_id,
            )
        )
    ).scalar_one()
    assert audits == 1


async def test_a_suite_on_an_unpublished_agent_says_there_is_nothing_to_check(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(
        ctx, agent.id, _suite_data(dataset, schedule=EvalSuiteSchedule(cron="0 6 * * *"))
    )
    agent.current_version_id = None
    await db.flush()
    row = await db.get(EvalSuite, suite.id)
    assert row is not None and row.next_fire_at is not None

    await service.fire_schedules(now=row.next_fire_at)

    [result] = await _results(db, suite.id)
    assert (result.status, result.reason) == ("skipped", "not_published")
    with pytest.raises(BadRequestError):
        await service.run_now(ctx, agent.id, suite.id)
    with pytest.raises(BadRequestError):
        await service.estimate(ctx, agent.id, EvalSuiteEstimateRequest(dataset_id=dataset.id))


async def test_a_suite_already_running_is_not_run_again_by_hand(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(dataset))
    await service.run_now(ctx, agent.id, suite.id)

    with pytest.raises(EvalSuiteNotRunnableError) as refused:
        await service.run_now(ctx, agent.id, suite.id)
    assert refused.value.details == {"suite_id": suite.id, "reason": "running"}


async def test_a_cancelled_eval_run_leaves_the_result_inconclusive_and_the_suite_free(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(dataset))
    started = await service.run_now(ctx, agent.id, suite.id)
    assert started.eval_run_id is not None
    # Its job withdrawn from the queue before a worker took it.
    await RunReaperService(db).settle_lost_eval(
        started.eval_run_id, organization_id=ctx.organization_id, why="cancelled"
    )

    await service.settle_finished(now=datetime.now(UTC))

    [result] = await _results(db, suite.id)
    assert (result.status, result.reason) == ("inconclusive", "cancelled")
    assert result.summary is not None
    assert result.summary["message"] == "Its eval run was cancelled."
    again = await service.run_now(ctx, agent.id, suite.id)
    assert again.eval_run_id not in (None, started.eval_run_id)


async def test_an_eval_run_that_failed_ends_the_result_in_error(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(dataset))
    started = await service.run_now(ctx, agent.id, suite.id)
    assert started.eval_run_id is not None
    await RunReaperService(db).settle_lost_eval(
        started.eval_run_id, organization_id=ctx.organization_id, why="worker killed"
    )

    await service.settle_finished(now=datetime.now(UTC))

    [result] = await _results(db, suite.id)
    assert (result.status, result.reason) == ("error", "failed")
    assert result.summary is not None
    assert result.summary["message"] == "This eval's job ended before the run did. Run it again."


async def test_the_estimate_prices_a_run_a_paired_run_and_a_month(db) -> None:
    ctx = await _owner(db)
    agent, version = await _agent(db, ctx)
    newer = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        organization_id=ctx.organization_id,
        version=2,
        spec={"name": "Clerk"},
    )
    db.add(newer)
    await db.flush()
    agent.current_version_id = newer.id
    await db.flush()
    dataset = await _dataset(db, ctx)

    estimate = await EvalSuiteService(db).estimate(
        ctx,
        agent.id,
        EvalSuiteEstimateRequest(
            dataset_id=dataset.id, schedule=EvalSuiteSchedule(cron="0 6 * * *")
        ),
    )

    assert estimate.run.cases == 4
    assert estimate.paired_run is not None and len(estimate.paired_run.arms) == 2
    assert estimate.fires_per_month == 30
    assert estimate.monthly_usd == estimate.run.total_usd * 30
    assert version.version == 1


async def test_an_edit_takes_the_suite_over_and_is_audited(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    other = await _dataset(db, ctx)
    builder = await _member(db, ctx, OrgRoleName.BUILDER)
    service = EvalSuiteService(db)
    suite = await service.create(
        ctx, agent.id, _suite_data(dataset, schedule=EvalSuiteSchedule(cron="0 6 * * *"))
    )

    updated = await service.update(
        builder,
        agent.id,
        suite.id,
        EvalSuiteUpdate(
            name="renamed",
            description="Checked nightly",
            dataset_id=other.id,
            threshold=EvalSuiteThreshold(min_pass_rate=0.8, max_p95_rise=0.5),
            on_publish=True,
            schedule=None,
            max_run_usd=Decimal("2"),
        ),
    )

    assert updated.owner_user_id == builder.user_id
    assert (updated.name, updated.dataset_id, updated.on_publish) == ("renamed", other.id, True)
    assert updated.schedule is None and updated.next_fire_at is None
    assert updated.threshold.min_pass_rate == 0.8 and updated.threshold.max_p95_rise == 0.5
    assert updated.max_run_usd == Decimal("2")
    listed = await service.list_for_agent(ctx, agent.id)
    assert [item.name for item in listed.items] == ["renamed"]
    assert listed.items[0].owner_email is not None

    await service.delete(ctx, agent.id, suite.id)
    assert (await service.list_for_agent(ctx, agent.id)).items == []
    actions = (
        (
            await db.execute(
                select(AppAdminAuditLog.action).where(
                    AppAdminAuditLog.organization_id == ctx.organization_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert {"eval_suite.created", "eval_suite.updated", "eval_suite.deleted"} <= set(actions)


async def test_the_results_list_is_newest_first(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(dataset))
    await service.run_now(ctx, agent.id, suite.id)
    await _finish_runs(db, Model(db))
    await service.settle_finished(now=datetime.now(UTC))
    second = await service.run_now(ctx, agent.id, suite.id)

    page = await service.results(ctx, agent.id, suite.id)

    assert page.total == 2
    assert page.items[0].id == second.id
    read = await service.get(ctx, agent.id, suite.id)
    assert read.open_result is not None and read.open_result.id == second.id


async def _role(db: AsyncSession, ctx: AuthContext, user_id: uuid.UUID, role: OrgRoleName) -> None:
    member = (
        await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == ctx.organization_id,
                OrganizationMember.user_id == user_id,
            )
        )
    ).scalar_one()
    member.role = role.value
    await db.flush()


@pytest.mark.security
async def test_an_owner_who_can_no_longer_read_runs_starts_no_run(db) -> None:
    """A Member still runs the agent and the dataset, but starting an eval needs
    runs:view - so the scheduled run is refused before anything is spent."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    builder = await _member(db, ctx, OrgRoleName.BUILDER)
    suite = await EvalSuiteService(db).create(
        builder, agent.id, _suite_data(dataset, on_publish=True)
    )
    await _role(db, ctx, builder.user_id, OrgRoleName.MEMBER)

    await AgentRegistryService(db).publish(ctx, agent.id)
    await EvalSuiteService(db).start_due(now=datetime.now(UTC))

    row = await db.get(EvalSuite, suite.id)
    assert row is not None and (row.is_active, row.paused_reason) == (False, "owner_lacks_access")
    [result] = await _results(db, suite.id)
    assert (result.status, result.reason) == ("error", "owner_lacks_access")
    assert (await db.scalar(select(func.count()).select_from(EvalRun))) == 0


async def test_an_owner_who_lost_access_pauses_the_suite_and_hears_why(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    builder = await _member(db, ctx, OrgRoleName.BUILDER)
    suite = await EvalSuiteService(db).create(
        builder, agent.id, _suite_data(dataset, on_publish=True)
    )
    await _role(db, ctx, builder.user_id, OrgRoleName.VIEWER)

    await AgentRegistryService(db).publish(ctx, agent.id)
    await EvalSuiteService(db).start_due(now=datetime.now(UTC))

    row = await db.get(EvalSuite, suite.id)
    assert row is not None and (row.is_active, row.paused_reason) == (False, "owner_lacks_access")
    [result] = await _results(db, suite.id)
    assert (result.status, result.reason) == ("error", "owner_lacks_access")
    [notice] = await _notifications(db, builder.user_id)
    assert "did not run" in notice.summary


async def test_a_result_whose_version_is_gone_is_skipped(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    suite = await EvalSuiteService(db).create(ctx, agent.id, _suite_data(dataset, on_publish=True))
    await AgentRegistryService(db).publish(ctx, agent.id)
    [waiting] = await _results(db, suite.id)
    waiting.agent_version_id = None
    await db.flush()

    await EvalSuiteService(db).start_due(now=datetime.now(UTC))

    [result] = await _results(db, suite.id)
    assert (result.status, result.reason) == ("skipped", "version_gone")


async def test_a_run_whose_eval_run_is_gone_ends_in_error(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(dataset))
    started = await service.run_now(ctx, agent.id, suite.id)
    [running] = await _results(db, suite.id)
    running.eval_run_id = None
    await db.flush()

    await service.settle_finished(now=datetime.now(UTC))

    [result] = await _results(db, suite.id)
    assert result.id == started.id
    assert (result.status, result.reason) == ("error", "run_gone")


async def test_a_run_whose_runner_left_or_lost_access_ends_in_error(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    gone = await _member(db, ctx, OrgRoleName.BUILDER)
    demoted = await _member(db, ctx, OrgRoleName.BUILDER)
    service = EvalSuiteService(db)
    first = await service.create(gone, agent.id, _suite_data(dataset))
    second = await service.create(demoted, agent.id, _suite_data(dataset))
    await service.run_now(gone, agent.id, first.id)
    await service.run_now(demoted, agent.id, second.id)
    await _finish_runs(db, Model(db))
    await db.execute(delete(OrganizationMember).where(OrganizationMember.user_id == gone.user_id))
    await _role(db, ctx, demoted.user_id, OrgRoleName.MEMBER)

    await service.settle_finished(now=datetime.now(UTC))

    [left] = await _results(db, first.id)
    [refused] = await _results(db, second.id)
    assert (left.status, left.reason) == ("error", "owner_inactive")
    assert (refused.status, refused.reason) == ("error", "owner_lacks_access")
    for suite_id, reason in ((first.id, "owner_inactive"), (second.id, "owner_lacks_access")):
        row = await db.get(EvalSuite, suite_id)
        assert row is not None
        await db.refresh(row)
        assert (row.is_active, row.paused_reason) == (False, reason)


async def test_a_hand_run_by_someone_who_left_does_not_pause_the_owners_suite(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    gone = await _member(db, ctx, OrgRoleName.BUILDER)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(dataset))
    await service.run_now(gone, agent.id, suite.id)
    await _finish_runs(db, Model(db))
    await db.execute(delete(OrganizationMember).where(OrganizationMember.user_id == gone.user_id))

    await service.settle_finished(now=datetime.now(UTC))

    [result] = await _results(db, suite.id)
    assert (result.status, result.reason) == ("error", "owner_inactive")
    assert (await service.get(ctx, agent.id, suite.id)).is_active


async def test_at_most_twenty_failing_cases_are_named(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=22)
    service = EvalSuiteService(db)
    suite = await service.create(
        ctx, agent.id, _suite_data(dataset, threshold=EvalSuiteThreshold(min_pass_rate=0.5))
    )
    await service.run_now(ctx, agent.id, suite.id)
    await _finish_runs(db, Model(db, answer=lambda prompt: _FAIL))
    await service.settle_finished(now=datetime.now(UTC))

    [result] = await _results(db, suite.id)
    assert result.summary is not None and len(result.summary["failing_cases"]) == 20


async def test_a_run_within_the_ceiling_starts(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    staging = await AgentEnvironmentService(db).create(
        ctx, agent.id, EnvironmentCreate(name="staging", version_id=agent.current_version_id)
    )
    service = EvalSuiteService(db)
    suite = await service.create(
        ctx,
        agent.id,
        _suite_data(dataset, environment_id=staging.id, max_run_usd=Decimal("5")),
    )

    started = await service.run_now(ctx, agent.id, suite.id)

    assert (started.status, started.version_number, started.environment_id) == (
        "running",
        1,
        staging.id,
    )
    moved = await service.update(ctx, agent.id, suite.id, EvalSuiteUpdate(environment_id=None))
    assert moved.environment_id is None
    back = await service.update(ctx, agent.id, suite.id, EvalSuiteUpdate(environment_id=staging.id))
    assert back.environment_name == "staging"


async def _settle_failed_cases(db: AsyncSession, ctx: AuthContext, agent: Agent, dataset: Dataset):
    """A suite whose last result named failing cases, read back by the caller."""
    service = EvalSuiteService(db)
    suite = await service.create(
        ctx, agent.id, _suite_data(dataset, threshold=EvalSuiteThreshold(min_pass_rate=0.9))
    )
    await service.run_now(ctx, agent.id, suite.id)
    await _finish_runs(db, Model(db, answer=lambda prompt: _FAIL))
    await service.settle_finished(now=datetime.now(UTC))
    return suite


@pytest.mark.security
async def test_a_reader_who_cannot_open_the_dataset_reads_no_case_of_it(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    suite = await _settle_failed_cases(db, ctx, agent, dataset)
    # A key issued to read runs and agents, and nothing of datasets.
    narrow = replace(
        ctx,
        api_key_id=uuid.uuid4(),
        key_scopes=frozenset({Perm.RUNS_VIEW, Perm.AGENTS_VIEW}),
    )
    service = EvalSuiteService(db)

    own = await service.get(ctx, agent.id, suite.id)
    assert own.last_result is not None and own.last_result.summary is not None
    assert own.last_result.summary.failing_cases

    reads = [
        (await service.get(narrow, agent.id, suite.id)).last_result,
        (await service.list_for_agent(narrow, agent.id)).items[0].last_result,
        (await service.list_visible(narrow)).items[0].last_result,
        (await service.results(narrow, agent.id, suite.id)).items[0],
    ]
    for result in reads:
        assert result is not None and result.summary is not None
        assert result.summary.failing_cases == []
    assert (await service.get(narrow, agent.id, suite.id)).dataset_name is None


async def test_a_run_in_which_nothing_could_be_graded_is_inconclusive(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(dataset))
    await service.run_now(ctx, agent.id, suite.id)
    await _finish_runs(db, Model(db))

    ungraded = ArmSummaryRead(
        cases=4,
        passed=0,
        failed=0,
        incomplete=4,
        pass_rate=None,
        first_pass_rate=None,
        cost_usd=Decimal("0.04"),
        cost_per_pass_usd=None,
        avg_tokens=None,
        p50_ms=None,
        p95_ms=None,
    )
    real = EvalRunService.get

    async def nothing_graded(self, reader, run_id):
        read = await real(self, reader, run_id)
        arms = [arm.model_copy(update={"summary": ungraded}) for arm in read.arms]
        return read.model_copy(update={"arms": arms})

    with patch.object(EvalRunService, "get", new=nothing_graded):
        await service.settle_finished(now=datetime.now(UTC))

    [result] = await _results(db, suite.id)
    assert (result.status, result.reason) == ("inconclusive", None)
    assert result.summary is not None
    assert [r["code"] for r in result.summary["reasons"]] == ["nothing_graded"]


async def test_a_result_queued_as_its_suite_was_paused_never_starts(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    suite = await EvalSuiteService(db).create(ctx, agent.id, _suite_data(dataset, on_publish=True))
    await AgentRegistryService(db).publish(ctx, agent.id)
    # The pause committed after the publish read the suite as running.
    row = await db.get(EvalSuite, suite.id)
    assert row is not None
    row.is_active = False
    await db.flush()

    started = await EvalSuiteService(db).start_due(now=datetime.now(UTC))

    assert started == 0
    assert await _results(db, suite.id) == []


async def test_a_start_that_fails_unexpectedly_ends_that_result_and_spares_the_rest(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    other, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    broken = await service.create(ctx, agent.id, _suite_data(dataset, on_publish=True))
    fine = await service.create(ctx, other.id, _suite_data(dataset, on_publish=True))
    await AgentRegistryService(db).publish(ctx, agent.id)
    await AgentRegistryService(db).publish(ctx, other.id)
    real = EvalRunService.start

    async def start(self, owner, agent_id, request, **kwargs):
        if agent_id == agent.id:
            raise ConfigurationError(message="The provider is not configured")
        return await real(self, owner, agent_id, request, **kwargs)

    with patch.object(EvalRunService, "start", new=start):
        assert await service.start_due(now=datetime.now(UTC)) == 1

    [failed] = await _results(db, broken.id)
    [running] = await _results(db, fine.id)
    assert (failed.status, failed.reason) == ("error", "start_failed")
    assert failed.summary is not None
    assert failed.summary["message"] == "The provider is not configured"
    assert running.status == "running"


async def test_a_settlement_that_fails_unexpectedly_ends_that_result_in_error(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(dataset))
    await service.run_now(ctx, agent.id, suite.id)
    await _finish_runs(db, Model(db))

    with patch.object(EvalRunService, "compare", new=AsyncMock(side_effect=RuntimeError("bug"))):
        await service.settle_finished(now=datetime.now(UTC))

    [result] = await _results(db, suite.id)
    # An unplanned failure's own text is the server's, so the result keeps none.
    assert (result.status, result.reason, result.summary) == ("error", "settle_failed", None)


async def test_a_case_that_breaks_overnight_on_the_same_version_fails_the_daily_suite(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    created = await service.create(
        ctx, agent.id, _suite_data(dataset, schedule=EvalSuiteSchedule(cron="0 6 * * *"))
    )
    suite = await db.get(EvalSuite, created.id)
    assert suite is not None and suite.next_fire_at is not None
    day = suite.next_fire_at

    await _sweep(db, Model(db), now=day)
    # The provider changed the model overnight: one case now fails every time.
    drifted = Model(db, answer=lambda prompt: _FAIL if prompt == "Question 2" else _PASS)
    await _sweep(db, drifted, now=day + timedelta(days=1))

    # Nothing changes on the third day: the case is still broken.
    await _sweep(db, drifted, now=day + timedelta(days=2))

    first, second, third = await _results(db, suite.id)
    assert (first.status, second.status, third.status) == ("passed", "failed", "failed")
    assert second.summary is not None
    assert second.summary["regressions_confirmed"] == 1
    assert second.summary["baseline_run_id"] == str(first.eval_run_id)
    assert second.summary["failing_cases"][0]["kind"] == "regression"
    # Measured against the last good day, not against yesterday's failure.
    assert third.summary is not None
    assert third.summary["baseline_run_id"] == str(first.eval_run_id)
    assert third.summary["regressions_confirmed"] == 1
    # One notice for the run of failures, on the day it began.
    assert (second.notified_at is not None, third.notified_at) == (True, None)
    assert len(await _notifications(db, ctx.user_id)) == 1


async def test_a_suite_moved_to_another_dataset_is_not_measured_against_the_old_one(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    first = await _dataset(db, ctx)
    second = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(first))
    await service.run_now(ctx, agent.id, suite.id)
    await _finish_runs(db, Model(db))
    await service.settle_finished(now=datetime.now(UTC))
    await service.update(ctx, agent.id, suite.id, EvalSuiteUpdate(dataset_id=second.id))

    rerun = await service.run_now(ctx, agent.id, suite.id)

    assert rerun.baseline_eval_run_id is None


@pytest.mark.security
async def test_saving_a_suite_needs_permission_to_run_the_agent(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    real = resolve_access

    async def no_run(db_, ctx_, resource, perm, **kwargs):
        return False if perm is Perm.AGENTS_RUN else await real(db_, ctx_, resource, perm, **kwargs)

    with (
        patch("app.services.eval_suite.resolve_access", new=no_run),
        pytest.raises(AuthorizationError, match="permission to run it"),
    ):
        await EvalSuiteService(db).create(ctx, agent.id, _suite_data(dataset))


async def test_a_suite_on_an_environment_being_removed_pauses_and_says_why(db) -> None:
    ctx = await _owner(db)
    agent, version = await _agent(db, ctx)
    environments = AgentEnvironmentService(db)
    staging = await environments.create(
        ctx, agent.id, EnvironmentCreate(name="staging", version_id=version.id)
    )
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(dataset, environment_id=staging.id))
    paused_already = await service.create(
        ctx, agent.id, _suite_data(dataset, environment_id=staging.id)
    )
    await service.update(ctx, agent.id, paused_already.id, EvalSuiteUpdate(is_active=False))

    await environments.delete(ctx, agent.id, staging.id)

    row = await db.get(EvalSuite, suite.id)
    assert row is not None
    await db.refresh(row)
    assert (row.is_active, row.paused_reason, row.environment_id) == (
        False,
        "environment_gone",
        None,
    )
    # One paused by hand is marked too: resumed as it is, it would quietly move
    # onto the agent's current version.
    kept = await db.get(EvalSuite, paused_already.id)
    assert kept is not None
    await db.refresh(kept)
    assert kept.paused_reason == "environment_gone"
    with pytest.raises(BadRequestError, match="Choose the one this suite checks"):
        await service.update(ctx, agent.id, kept.id, EvalSuiteUpdate(is_active=True))
    resumed = await service.update(
        ctx, agent.id, kept.id, EvalSuiteUpdate(is_active=True, environment_id=None)
    )
    assert (resumed.is_active, resumed.paused_reason, resumed.environment_id) == (True, None, None)


async def test_a_case_no_scorer_decided_keeps_the_suite_from_passing_and_says_which(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(dataset))
    await service.run_now(ctx, agent.id, suite.id)
    await _finish_runs(db, Model(db))
    real = EvalRunService.get

    async def one_ungraded(self, reader, run_id):
        read = await real(self, reader, run_id)
        candidate = read.arms[0]
        undecided = EvalUngradedCaseRead(case_id=uuid.uuid4(), input="Where is my parcel?")
        arms = [candidate.model_copy(update={"ungraded_cases": [undecided]}), *read.arms[1:]]
        return read.model_copy(update={"arms": arms})

    with patch.object(EvalRunService, "get", new=one_ungraded):
        await service.settle_finished(now=datetime.now(UTC))

    [result] = await _results(db, suite.id)
    assert result.status == "inconclusive"
    assert result.summary is not None
    assert [(r["code"], r["value"]) for r in result.summary["reasons"]] == [("ungraded", 1.0)]
    assert [(c["input"], c["kind"]) for c in result.summary["failing_cases"]] == [
        ("Where is my parcel?", "ungraded")
    ]
    [notice] = await _notifications(db, ctx.user_id)
    assert "could not decide" in notice.summary and "Where is my parcel?" in notice.summary


@pytest.mark.security
async def test_a_result_shows_its_cases_by_the_dataset_it_checked_not_the_suites_current_one(
    db,
) -> None:
    """Moved onto a dataset its reader may open, a suite does not open the old one's cases."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    old = await _dataset(db, ctx)
    new = await _dataset(db, ctx)
    suite = await _settle_failed_cases(db, ctx, agent, old)
    service = EvalSuiteService(db)
    await service.update(ctx, agent.id, suite.id, EvalSuiteUpdate(dataset_id=new.id))
    [before] = (await service.results(ctx, agent.id, suite.id)).items
    assert before.summary is not None and before.summary.failing_cases

    # Nobody may open a dataset that is gone; the suite's current one is still there.
    await db.delete(old)
    await db.flush()

    [after] = (await service.results(ctx, agent.id, suite.id)).items
    last = (await service.get(ctx, agent.id, suite.id)).last_result
    assert after.summary is not None and after.summary.failing_cases == []
    assert last is not None and last.summary is not None and last.summary.failing_cases == []


async def test_moving_a_suite_to_another_dataset_drops_the_run_waiting_on_the_old_one(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    first = await _dataset(db, ctx)
    second = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    created = await service.create(
        ctx, agent.id, _suite_data(first, schedule=EvalSuiteSchedule(cron="0 6 * * *"))
    )
    suite = await db.get(EvalSuite, created.id)
    assert suite is not None and suite.next_fire_at is not None
    await service.fire_schedules(now=suite.next_fire_at)
    assert [r.status for r in await _results(db, suite.id)] == ["pending"]

    await service.update(ctx, agent.id, suite.id, EvalSuiteUpdate(dataset_id=first.id))
    assert [r.status for r in await _results(db, suite.id)] == ["pending"]
    await service.update(ctx, agent.id, suite.id, EvalSuiteUpdate(dataset_id=second.id))

    assert await _results(db, suite.id) == []


async def test_a_run_due_while_the_suite_is_running_waits_for_it_to_settle(db) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    created = await service.create(
        ctx, agent.id, _suite_data(dataset, schedule=EvalSuiteSchedule(cron="0 6 * * *"))
    )
    suite = await db.get(EvalSuite, created.id)
    assert suite is not None and suite.next_fire_at is not None
    due = suite.next_fire_at
    await service.run_now(ctx, agent.id, suite.id)
    await service.fire_schedules(now=due)

    assert await service.start_due(now=due) == 0
    assert sorted(r.status for r in await _results(db, suite.id)) == ["pending", "running"]
    # A sweep that claimed the result before the press committed, then waited on the
    # suite's lock, finds the run started meanwhile and leaves its result waiting.
    [pending] = [r for r in await _results(db, suite.id) if r.status == "pending"]
    assert await service._start(pending, now=due) is False
    assert pending.status == "pending"

    await _finish_runs(db, Model(db))
    await service.settle_finished(now=due)
    assert await service.start_due(now=due + timedelta(seconds=1)) == 1


async def test_after_a_result_that_could_not_be_compared_the_next_run_sets_a_new_reference(
    db,
) -> None:
    """A judge republished since the last good run makes the next result inconclusive,
    once: the run after it is held to its own numbers and becomes the reference."""
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    service = EvalSuiteService(db)
    created = await service.create(
        ctx, agent.id, _suite_data(dataset, schedule=EvalSuiteSchedule(cron="0 6 * * *"))
    )
    suite = await db.get(EvalSuite, created.id)
    assert suite is not None and suite.next_fire_at is not None
    day = suite.next_fire_at
    real = EvalRunService.compare

    async def judged_anew(self, reader, run_id):
        read = await real(self, reader, run_id)
        return read.model_copy(
            update={"verdict": "invalid", "invalid_reason": "A different judge graded it."}
        )

    await _sweep(db, Model(db), now=day)
    with patch.object(EvalRunService, "compare", new=judged_anew):
        await _sweep(db, Model(db), now=day + timedelta(days=1))
    await _sweep(db, Model(db), now=day + timedelta(days=2))
    await _sweep(db, Model(db), now=day + timedelta(days=3))

    first, second, third, fourth = await _results(db, suite.id)
    assert [r.status for r in (first, second, third, fourth)] == [
        "passed",
        "inconclusive",
        "passed",
        "passed",
    ]
    assert second.baseline_eval_run_id == first.eval_run_id
    assert third.baseline_eval_run_id is None
    assert fourth.baseline_eval_run_id == third.eval_run_id
