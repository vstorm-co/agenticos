"""The promotion gate end to end against Postgres, with the model replaced by a scripted answer.

What the issue promises:

- promoting a version whose guard failed onto a guarded environment is refused,
  naming the suite;
- an override needs the permission and a reason, and is audited with the
  results it overrode;
- a guarded environment that follows publishes does not follow one whose
  guards fail, and follows one whose guards pass;
- an unguarded environment behaves exactly as before.

And what a pass must be: on that exact version, over the dataset version the
suite reads now and under the threshold it holds now.
"""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    EvalSuiteInUseError,
    NotFoundError,
    PromotionBlockedError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.dataset import Dataset, DatasetVersion
from app.db.models.eval_run import EvalRun
from app.db.models.eval_suite import EvalSuite, EvalSuiteResult
from app.db.models.notification import Notification
from app.db.models.promotion_gate import EnvironmentGuard, PromotionOverride
from app.repositories import eval_suite_repo, promotion_gate_repo
from app.schemas.agent_environment import EnvironmentCreate, EnvironmentUpdate
from app.schemas.dataset import DatasetCaseCreate
from app.schemas.eval_suite import EvalSuiteThreshold, EvalSuiteUpdate
from app.schemas.promotion_gate import PromotionGateRun
from app.schemas.scoring import DatasetScoring, JudgeCreate
from app.services.agent_environment import AgentEnvironmentService
from app.services.agent_registry import AgentRegistryService
from app.services.dataset import DatasetService
from app.services.eval_run import scoring_hash
from app.services.eval_suite import EvalSuiteService
from app.services.promotion_gate import PromotionGateService
from app.services.run_reaper import RunReaperService
from app.services.scoring import ScoringService
from tests.integration.test_eval_suites import (
    _FAIL,
    Model,
    _agent,
    _dataset,
    _environment,
    _finish_runs,
    _member,
    _owner,
    _suite_data,
)

pytestmark = pytest.mark.anyio

__all__ = ["_environment"]

_REASON = "Hotfix for the refund outage, checked by hand."
# Both sides of a paired run answer alike here, so only a pass-rate floor can fail one.
_BAR = EvalSuiteThreshold(min_pass_rate=0.9)


async def _published(db: AsyncSession, ctx: AuthContext, agent: Agent) -> AgentVersion:
    """A second version, published; a pinned environment stays where it was."""
    agent.draft_spec = {**agent.draft_spec, "instructions": f"v-{uuid.uuid4().hex[:4]}"}
    await db.flush()
    return await AgentRegistryService(db).publish(ctx, agent.id)


async def _guarded(
    db: AsyncSession,
    ctx: AuthContext,
    agent: Agent,
    version: AgentVersion,
    dataset: Dataset,
    *,
    tracks_latest: bool = False,
    **suite: object,
) -> tuple[uuid.UUID, EvalSuite]:
    """A `staging` environment on `version`, guarded by one suite on `dataset`."""
    environments = AgentEnvironmentService(db)
    staging = await environments.create(
        ctx,
        agent.id,
        EnvironmentCreate(name="staging", version_id=version.id, tracks_latest=tracks_latest),
    )
    created = await EvalSuiteService(db).create(ctx, agent.id, _suite_data(dataset, **suite))
    await environments.update(
        ctx, agent.id, staging.id, EnvironmentUpdate(guard_suite_ids=[created.id])
    )
    row = await db.get(EvalSuite, created.id)
    assert row is not None
    return staging.id, row


async def _check(db: AsyncSession, ctx: AuthContext, agent: Agent, env_id, version: AgentVersion):
    return await PromotionGateService(db).read(ctx, agent.id, env_id, version.id)


async def _run_guards(
    db: AsyncSession, ctx: AuthContext, agent: Agent, env_id, version: AgentVersion, model: Model
) -> None:
    gate = PromotionGateService(db)
    await gate.run(ctx, agent.id, env_id, PromotionGateRun(version_id=version.id))
    await _finish_runs(db, model)
    await EvalSuiteService(db).settle_finished(now=datetime.now(UTC))


async def _promote(
    db: AsyncSession,
    ctx: AuthContext,
    agent: Agent,
    env_id,
    version: AgentVersion,
    *,
    reason: str | None = None,
):
    return await AgentEnvironmentService(db).update(
        ctx, agent.id, env_id, EnvironmentUpdate(version_id=version.id, override_reason=reason)
    )


async def _audit(db: AsyncSession, ctx: AuthContext, action: str) -> list[AppAdminAuditLog]:
    return list(
        (
            await db.execute(
                select(AppAdminAuditLog).where(
                    AppAdminAuditLog.action == action,
                    AppAdminAuditLog.organization_id == ctx.organization_id,
                )
            )
        ).scalars()
    )


async def test_an_unguarded_environment_takes_any_version_as_before(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    staging = await AgentEnvironmentService(db).create(
        ctx, agent.id, EnvironmentCreate(name="staging", version_id=first.id)
    )
    second = await _published(db, ctx, agent)

    promoted = await _promote(db, ctx, agent, staging.id, second)

    assert promoted.version_id == second.id
    gate = await _check(db, ctx, agent, staging.id, second)
    assert (gate.guarded, gate.passing, gate.guards) == (False, True, [])


async def test_a_version_nobody_checked_is_refused_naming_the_guard(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    second = await _published(db, ctx, agent)

    with pytest.raises(PromotionBlockedError) as refused:
        await _promote(db, ctx, agent, env_id, second)

    assert suite.name in refused.value.message and "staging" in refused.value.message
    gate = refused.value.details["gate"]
    assert (gate["version"], gate["passing"], gate["can_override"]) == (2, False, True)
    assert [(g["suite_id"], g["state"]) for g in gate["guards"]] == [(str(suite.id), "unchecked")]


async def test_a_failing_guard_holds_the_version_back_until_it_passes(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx), threshold=_BAR)
    second = await _published(db, ctx, agent)

    await _run_guards(db, ctx, agent, env_id, second, Model(db, answer=lambda prompt: _FAIL))
    failed = await _check(db, ctx, agent, env_id, second)
    with pytest.raises(PromotionBlockedError):
        await _promote(db, ctx, agent, env_id, second)

    await _run_guards(db, ctx, agent, env_id, second, Model(db))
    passed = await _check(db, ctx, agent, env_id, second)
    promoted = await _promote(db, ctx, agent, env_id, second)

    assert [g.state for g in failed.guards] == ["failed"]
    [guard] = failed.guards
    assert guard.result is not None and guard.result.trigger == "gate"
    assert guard.result.baseline_version_number == 1
    assert (passed.passing, promoted.version_id) == (True, second.id)


async def test_a_run_in_progress_holds_the_version_back(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, _ = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    second = await _published(db, ctx, agent)

    started = await PromotionGateService(db).run(
        ctx, agent.id, env_id, PromotionGateRun(version_id=second.id)
    )
    again = await PromotionGateService(db).run(
        ctx, agent.id, env_id, PromotionGateRun(version_id=second.id)
    )

    assert [g.state for g in started.gate.guards] == ["checking"]
    assert (len(started.started), again.started) == (1, [])


async def test_a_run_whose_job_was_withdrawn_leaves_checking_for_inconclusive(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    second = await _published(db, ctx, agent)
    await PromotionGateService(db).run(
        ctx, agent.id, env_id, PromotionGateRun(version_id=second.id)
    )
    [result] = [row for row in await _results(db, suite.id) if row.status == "running"]
    assert result.eval_run_id is not None

    await RunReaperService(db).settle_lost_eval(
        result.eval_run_id, organization_id=ctx.organization_id, why="cancelled"
    )
    await EvalSuiteService(db).settle_finished(now=datetime.now(UTC))

    gate = await _check(db, ctx, agent, env_id, second)
    assert [g.state for g in gate.guards] == ["inconclusive"]
    assert gate.passing is False


async def test_editing_a_guards_dataset_leaves_what_it_checks_until_the_pin_moves(db) -> None:
    """Cases, grading and the judge are a builder's to edit; what a guard reads is not."""
    ctx = await _owner(db)
    builder = await _member(db, ctx, OrgRoleName.BUILDER)
    agent, first = await _agent(db, ctx)
    dataset = await _dataset(db, builder)
    env_id, suite = await _guarded(db, ctx, agent, first, dataset)
    pinned = (suite.pinned_dataset_version, suite.pinned_scoring)
    assert pinned == (dataset.latest_version, dataset.scoring)
    second = await _published(db, ctx, agent)
    await _run_guards(db, ctx, agent, env_id, second, Model(db))
    assert (await _check(db, ctx, agent, env_id, second)).passing

    await DatasetService(db).add_case(
        builder,
        dataset.id,
        DatasetCaseCreate(
            input="A new question", checks=[{"type": "contains", "value": "30 days"}]
        ),
    )
    scoring = ScoringService(db)
    await scoring.set_scoring(
        builder,
        dataset.id,
        DatasetScoring.model_validate(
            {**dataset.scoring, "trajectory": {"enabled": False, "required": False}}
        ),
    )
    await scoring.create_judge(builder, dataset.id, JudgeCreate(name="Lenient judge"))
    edited = await _check(db, ctx, agent, env_id, second)
    third = await _published(db, ctx, agent)
    await _run_guards(db, ctx, agent, env_id, third, Model(db))
    [result] = [row for row in await _results(db, suite.id) if row.version_number == third.version]
    run = await db.get(EvalRun, result.eval_run_id)
    read = await db.get(DatasetVersion, run.dataset_version_id) if run else None

    assert edited.passing
    assert read is not None and read.number == pinned[0]
    assert run is not None and run.scoring_hash == scoring_hash(
        DatasetScoring.model_validate(pinned[1])
    )

    moved = await EvalSuiteService(db).move_pin(ctx, agent.id, suite.id)
    assert moved.pin is not None
    assert (moved.pin.dataset_version, moved.pin.scoring_current) == (dataset.latest_version, True)
    assert [g.state for g in (await _check(db, ctx, agent, env_id, second)).guards] == ["stale"]


async def test_a_suite_whose_dataset_has_no_cases_cannot_become_a_guard(db) -> None:
    """It could not pass, and pinned to nothing it would read whatever came first."""
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    empty = await _dataset(db, ctx, cases=0)
    loose = await EvalSuiteService(db).create(ctx, agent.id, _suite_data(empty))
    environments = AgentEnvironmentService(db)

    with pytest.raises(BadRequestError, match="no cases yet") as refused:
        await environments.update(
            ctx, agent.id, env_id, EnvironmentUpdate(guard_suite_ids=[suite.id, loose.id])
        )
    with pytest.raises(BadRequestError, match="no cases yet") as moved:
        await EvalSuiteService(db).update(
            ctx, agent.id, suite.id, EvalSuiteUpdate(dataset_id=empty.id)
        )
    assert refused.value.details is not None and moved.value.details is not None
    assert [f["field"] for f in refused.value.details["fields"]] == ["guard_suite_ids"]
    assert [f["field"] for f in moved.value.details["fields"]] == ["dataset_id"]

    # No guard is ever left unpinned: every suite guarding anything holds a pin.
    unpinned = (
        await db.execute(
            select(EvalSuite.id)
            .join(EnvironmentGuard, EnvironmentGuard.suite_id == EvalSuite.id)
            .where(EvalSuite.pinned_dataset_version.is_(None))
        )
    ).all()
    assert unpinned == []


async def test_a_suite_guarding_two_environments_stays_pinned_until_both_are_gone(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    staging, suite = await _guarded(db, ctx, agent, first, dataset)
    environments = AgentEnvironmentService(db)
    canary = await environments.create(
        ctx, agent.id, EnvironmentCreate(name="canary", version_id=first.id)
    )
    await environments.update(
        ctx, agent.id, canary.id, EnvironmentUpdate(guard_suite_ids=[suite.id])
    )

    await environments.delete(ctx, agent.id, staging)
    await db.refresh(suite)
    assert suite.pinned_dataset_version == dataset.latest_version

    await environments.delete(ctx, agent.id, canary.id)
    await db.refresh(suite)
    assert (suite.pinned_dataset_version, suite.pinned_scoring) == (None, None)
    assert (await EvalSuiteService(db).get(ctx, agent.id, suite.id)).pin is None


async def test_two_changes_to_one_suites_guards_wait_on_each_other_rather_than_deadlock(
    db, engine
) -> None:
    """Each writes a guard row - a key share on the suite for its foreign key - and then
    locks the suite to pin it; a lock that took the key share's place would deadlock."""
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    suite = await EvalSuiteService(db).create(ctx, agent.id, _suite_data(await _dataset(db, ctx)))
    environments = AgentEnvironmentService(db)
    left, right = [
        await environments.create(ctx, agent.id, EnvironmentCreate(name=name, version_id=first.id))
        for name in ("left", "right")
    ]
    await db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as one, sessions() as two:
        for session, environment in ((one, left), (two, right)):
            await promotion_gate_repo.replace_guards(
                session, environment.id, [suite.id], organization_id=ctx.organization_id
            )
        with anyio.fail_after(5):
            held = await eval_suite_repo.lock(one, suite.id, organization_id=ctx.organization_id)
        assert held is not None
        await one.commit()
        with anyio.fail_after(5):
            assert await eval_suite_repo.lock(two, suite.id, organization_id=ctx.organization_id)
        await two.commit()


async def test_a_raised_bar_makes_an_earlier_pass_stale(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    second = await _published(db, ctx, agent)
    await _run_guards(db, ctx, agent, env_id, second, Model(db))
    assert (await _check(db, ctx, agent, env_id, second)).passing

    await EvalSuiteService(db).update(
        ctx,
        agent.id,
        suite.id,
        EvalSuiteUpdate(threshold=EvalSuiteThreshold(min_pass_rate=0.9)),
    )

    assert [g.state for g in (await _check(db, ctx, agent, env_id, second)).guards] == ["stale"]


async def test_a_pass_graded_under_other_scoring_than_the_pin_is_stale(db) -> None:
    """Scoring changes without a dataset version, so the run's own fingerprint decides."""
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    second = await _published(db, ctx, agent)
    await _run_guards(db, ctx, agent, env_id, second, Model(db))
    assert (await _check(db, ctx, agent, env_id, second)).passing

    suite.pinned_scoring = DatasetScoring.model_validate(
        {**(suite.pinned_scoring or {}), "trajectory": {"enabled": False, "required": False}}
    ).model_dump(mode="json")
    await db.flush()

    assert [g.state for g in (await _check(db, ctx, agent, env_id, second)).guards] == ["stale"]


async def test_moving_a_pin_needs_the_permission_and_is_recorded(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    env_id, suite = await _guarded(db, ctx, agent, first, dataset)
    loose = await EvalSuiteService(db).create(ctx, agent.id, _suite_data(dataset))
    builder = await _member(db, ctx, OrgRoleName.BUILDER)
    agent.owner_user_id = builder.user_id
    await db.flush()
    suites = EvalSuiteService(db)

    # Current already: nothing moves, nothing is recorded.
    await suites.move_pin(ctx, agent.id, suite.id)
    before = len(await _audit(db, ctx, "agent.environment_guards_changed"))

    await DatasetService(db).add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(input="Another", checks=[{"type": "contains", "value": "x"}]),
    )
    with pytest.raises(AuthorizationError, match="override promotions"):
        await suites.move_pin(builder, agent.id, suite.id)
    with pytest.raises(BadRequestError, match="guards no environment"):
        await suites.move_pin(ctx, agent.id, loose.id)
    with pytest.raises(NotFoundError):
        await suites.move_pin(await _owner(db), agent.id, suite.id)
    assert len(await _audit(db, ctx, "agent.environment_guards_changed")) == before

    await suites.move_pin(ctx, agent.id, suite.id)

    [entry] = [
        change
        for change in await _audit(db, ctx, "agent.environment_guards_changed")
        if change.details and change.details.get("fields") == ["pin"]
    ]
    assert entry.details is not None
    assert entry.details["environment_id"] == str(env_id)
    assert entry.details["from"]["dataset_version"] == dataset.latest_version - 1
    assert entry.details["to"]["dataset_version"] == dataset.latest_version
    assert entry.details["from"]["scoring_hash"] == entry.details["to"]["scoring_hash"]


async def test_a_suite_is_pinned_while_it_guards_and_follows_the_latest_after(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    env_id, suite = await _guarded(db, ctx, agent, first, dataset)
    assert suite.pinned_dataset_version == dataset.latest_version
    read = await EvalSuiteService(db).get(ctx, agent.id, suite.id)
    assert read.pin is not None and read.pin.latest_dataset_version == dataset.latest_version

    await AgentEnvironmentService(db).update(
        ctx, agent.id, env_id, EnvironmentUpdate(guard_suite_ids=[])
    )
    await db.refresh(suite)

    assert (suite.pinned_dataset_version, suite.pinned_scoring) == (None, None)
    assert (await EvalSuiteService(db).get(ctx, agent.id, suite.id)).pin is None


async def test_a_stricter_bar_needs_no_override_and_a_looser_one_does(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(
        db,
        ctx,
        agent,
        first,
        await _dataset(db, ctx),
        threshold=EvalSuiteThreshold(
            min_pass_rate=0.8, max_confirmed_regressions=2, max_cost_per_pass_rise=0.5
        ),
    )
    builder = await _member(db, ctx, OrgRoleName.BUILDER)
    agent.owner_user_id = builder.user_id
    await db.flush()
    suites = EvalSuiteService(db)

    def bar(**values: object) -> EvalSuiteUpdate:
        return EvalSuiteUpdate(
            threshold=EvalSuiteThreshold.model_validate(
                {
                    "min_pass_rate": 0.8,
                    "max_confirmed_regressions": 2,
                    "max_cost_per_pass_rise": 0.5,
                    **values,
                }
            )
        )

    stricter = bar(min_pass_rate=0.9, max_confirmed_regressions=1, max_cost_per_pass_rise=0.2)
    await suites.update(builder, agent.id, suite.id, stricter)
    for looser in (
        {"min_pass_rate": 0.5},
        {"min_pass_rate": None},
        {"max_confirmed_regressions": 5},
        {"max_cost_per_pass_rise": None},
        # One bar raised does not buy another lowered.
        {"min_pass_rate": 0.95, "max_confirmed_regressions": 3},
    ):
        with pytest.raises(AuthorizationError, match="override promotions"):
            await suites.update(
                builder,
                agent.id,
                suite.id,
                bar(
                    **{
                        "min_pass_rate": 0.9,
                        "max_confirmed_regressions": 1,
                        "max_cost_per_pass_rise": 0.2,
                        **looser,
                    }
                ),
            )

    changes = await _audit(db, ctx, "agent.environment_guards_changed")
    assert [
        c.details["fields"]
        for c in changes
        if c.details and c.details.get("suite_id") == str(suite.id) and "fields" in c.details
    ] == [["threshold"]]
    assert str(env_id) in {c.details["environment_id"] for c in changes if c.details}


async def test_a_paused_guard_with_nothing_to_show_holds_the_version_back(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    await EvalSuiteService(db).update(ctx, agent.id, suite.id, EvalSuiteUpdate(is_active=False))
    second = await _published(db, ctx, agent)

    gate = await _check(db, ctx, agent, env_id, second)
    run = await PromotionGateService(db).run(
        ctx, agent.id, env_id, PromotionGateRun(version_id=second.id)
    )

    assert [g.state for g in gate.guards] == ["paused"]
    assert run.started == []


@pytest.mark.security
async def test_an_override_needs_the_permission_and_a_reason_and_is_kept(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    builder = await _member(db, ctx, OrgRoleName.BUILDER)
    env_id, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    second = await _published(db, ctx, agent)
    owner_of_suite = suite.owner_user_id
    admin = await _member(db, ctx, OrgRoleName.ADMIN)
    script = replace(admin, api_key_id=uuid.uuid4())

    # A builder may promote this agent but not wave its evals aside.
    agent.owner_user_id = builder.user_id
    await db.flush()
    with pytest.raises(PromotionBlockedError) as refused:
        await _promote(db, builder, agent, env_id, second, reason=_REASON)
    assert "permission to override" in refused.value.message
    assert refused.value.details["gate"]["can_override"] is False
    with pytest.raises(PromotionBlockedError):
        await _promote(db, script, agent, env_id, second, reason=_REASON)

    promoted = await _promote(db, admin, agent, env_id, second, reason=_REASON)

    assert promoted.version_id == second.id
    [override] = (await db.execute(select(PromotionOverride))).scalars().all()
    assert (override.user_id, override.reason, override.environment_name) == (
        admin.user_id,
        _REASON,
        "staging",
    )
    assert [(g["suite_id"], g["state"]) for g in override.gate] == [(str(suite.id), "unchecked")]
    [entry] = await _audit(db, ctx, "agent.environment_promotion_overridden")
    assert entry.details is not None and entry.details["reason"] == _REASON
    versions, _ = await AgentRegistryService(db).list_versions(ctx, agent.id)
    shown = {v.version: v.overrides for v in versions}
    assert [(o.environment_name, o.reason) for o in shown[2]] == [("staging", _REASON)]
    assert shown[1] == []
    notices = (
        await db.execute(
            select(Notification).where(Notification.event_type == "promotion_overridden")
        )
    ).scalars()
    assert [n.recipient_user_id for n in notices] == [owner_of_suite]


async def test_an_owner_overriding_their_own_failing_guard_is_not_told_of_it(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, _ = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    passing = await EvalSuiteService(db).create(ctx, agent.id, _suite_data(await _dataset(db, ctx)))
    second = await _published(db, ctx, agent)
    environments = AgentEnvironmentService(db)
    await _run_guards(db, ctx, agent, env_id, second, Model(db))
    await environments.update(
        ctx,
        agent.id,
        env_id,
        EnvironmentUpdate(
            guard_suite_ids=[*(await _guard_ids(db, ctx, agent, env_id)), passing.id]
        ),
    )

    await _promote(db, ctx, agent, env_id, second, reason=_REASON)

    [override] = (await db.execute(select(PromotionOverride))).scalars().all()
    assert sorted(g["state"] for g in override.gate) == ["passed", "unchecked"]
    notices = await db.execute(
        select(Notification).where(Notification.event_type == "promotion_overridden")
    )
    assert notices.scalars().all() == []


async def _guard_ids(db: AsyncSession, ctx: AuthContext, agent: Agent, env_id) -> list[uuid.UUID]:
    listed = await AgentEnvironmentService(db).list_for_agent(ctx, agent.id)
    return next(e.guard_suite_ids for e in listed if e.id == env_id)


async def test_a_reason_under_ten_characters_is_refused_on_the_field() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        EnvironmentUpdate(override_reason="because")


async def test_a_reason_is_not_recorded_when_the_guards_pass(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, _ = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    second = await _published(db, ctx, agent)
    await _run_guards(db, ctx, agent, env_id, second, Model(db))

    await _promote(db, ctx, agent, env_id, second, reason=_REASON)

    assert (await db.execute(select(PromotionOverride))).scalars().all() == []


@pytest.mark.security
async def test_changing_the_guards_needs_the_permission_and_is_audited(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    builder = await _member(db, ctx, OrgRoleName.BUILDER)
    agent.owner_user_id = builder.user_id
    await db.flush()
    environments = AgentEnvironmentService(db)

    with pytest.raises(AuthorizationError, match="override promotions"):
        await environments.update(builder, agent.id, env_id, EnvironmentUpdate(guard_suite_ids=[]))
    # Naming the same set again changes nothing, so it needs nothing.
    await environments.update(
        builder, agent.id, env_id, EnvironmentUpdate(guard_suite_ids=[suite.id])
    )
    other, _ = await _agent(db, ctx)
    foreign = await EvalSuiteService(db).create(ctx, other.id, _suite_data(await _dataset(db, ctx)))
    with pytest.raises(BadRequestError, match="this agent's eval suites"):
        await environments.update(
            ctx, agent.id, env_id, EnvironmentUpdate(guard_suite_ids=[foreign.id])
        )
    await environments.update(ctx, agent.id, env_id, EnvironmentUpdate(guard_suite_ids=[]))

    [listed] = [e for e in await environments.list_for_agent(ctx, agent.id) if e.id == env_id]
    assert listed.guard_suite_ids == []
    changes = await _audit(db, ctx, "agent.environment_guards_changed")
    assert [c.details["removed"] for c in changes if c.details] == [[], [str(suite.id)]]


@pytest.mark.security
async def test_what_a_guard_checks_changes_only_with_the_permission(db) -> None:
    """A lower bar or an easier dataset is a guard taken off by another road."""
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    easier = await _dataset(db, ctx)
    builder = await _member(db, ctx, OrgRoleName.BUILDER)
    agent.owner_user_id = builder.user_id
    await db.flush()
    suites = EvalSuiteService(db)
    lower = EvalSuiteUpdate(threshold=EvalSuiteThreshold(max_confirmed_regressions=10_000))

    with pytest.raises(AuthorizationError, match="override promotions"):
        await suites.update(builder, agent.id, suite.id, lower)
    with pytest.raises(AuthorizationError, match="staging"):
        await suites.update(builder, agent.id, suite.id, EvalSuiteUpdate(dataset_id=easier.id))
    # What it checks stays; when it runs, or whether it is paused, is not a weakening.
    await suites.update(builder, agent.id, suite.id, EvalSuiteUpdate(on_publish=False))
    await suites.update(ctx, agent.id, suite.id, lower)

    changes = await _audit(db, ctx, "agent.environment_guards_changed")
    assert [c.details["fields"] for c in changes if c.details and "fields" in c.details] == [
        ["threshold"]
    ]
    assert str(env_id) in {c.details["environment_id"] for c in changes if c.details}


async def test_a_dataset_a_guard_checks_cannot_be_deleted(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    env_id, _ = await _guarded(db, ctx, agent, first, dataset)
    datasets = DatasetService(db)

    with pytest.raises(EvalSuiteInUseError, match="staging"):
        await datasets.delete(ctx, dataset.id)
    assert await db.get(Dataset, dataset.id) is not None

    await AgentEnvironmentService(db).update(
        ctx, agent.id, env_id, EnvironmentUpdate(guard_suite_ids=[])
    )
    await datasets.delete(ctx, dataset.id)
    assert await db.get(Dataset, dataset.id) is None


async def test_removing_an_agent_takes_its_guards_with_it(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    await _guarded(db, ctx, agent, first, await _dataset(db, ctx))

    await AgentRegistryService(db).delete(ctx, agent.id)
    await db.flush()

    assert (await db.execute(select(EnvironmentGuard))).scalars().all() == []
    assert await db.get(Agent, agent.id) is None


async def test_a_suite_that_guards_an_environment_cannot_be_deleted(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))

    with pytest.raises(EvalSuiteInUseError, match="staging"):
        await EvalSuiteService(db).delete(ctx, agent.id, suite.id)
    await AgentEnvironmentService(db).update(
        ctx, agent.id, env_id, EnvironmentUpdate(guard_suite_ids=[])
    )
    await EvalSuiteService(db).delete(ctx, agent.id, suite.id)

    assert await db.get(EvalSuite, suite.id) is None


async def test_a_guarded_environment_that_follows_publishes_waits_for_its_guards(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(
        db, ctx, agent, first, await _dataset(db, ctx), tracks_latest=True, threshold=_BAR
    )
    environments = AgentEnvironmentService(db)

    def serving() -> int:
        return next(e.version for e in listed if e.id == env_id)

    second = await _published(db, ctx, agent)
    listed = await environments.list_for_agent(ctx, agent.id)
    held = serving()
    [queued] = [r for r in await _results(db, suite.id) if r.agent_version_id == second.id]
    sweep = EvalSuiteService(db)
    await sweep.start_due(now=datetime.now(UTC) + timedelta(seconds=1))
    await _finish_runs(db, Model(db, answer=lambda prompt: _FAIL))
    await sweep.settle_finished(now=datetime.now(UTC) + timedelta(seconds=2))
    listed = await environments.list_for_agent(ctx, agent.id)
    after_failing = serving()

    third = await _published(db, ctx, agent)
    await sweep.start_due(now=datetime.now(UTC) + timedelta(seconds=3))
    await _finish_runs(db, Model(db))
    await sweep.settle_finished(now=datetime.now(UTC) + timedelta(seconds=4))
    listed = await environments.list_for_agent(ctx, agent.id)

    assert (queued.trigger, queued.baseline_version_number) == ("gate", 1)
    assert (held, after_failing, serving()) == (1, 1, third.version)
    [moved] = [
        e for e in await _audit(db, ctx, "agent.environment_promoted") if e.actor_user_id is None
    ]
    assert moved.details is not None
    assert (moved.details["by"], moved.details["passed"]) == ("gate", [suite.name])


async def test_a_guarded_default_follows_once_every_guard_passed_and_never_backwards(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    suites = EvalSuiteService(db)
    lenient = await suites.create(ctx, agent.id, _suite_data(await _dataset(db, ctx)))
    strict = await suites.create(
        ctx, agent.id, _suite_data(await _dataset(db, ctx), threshold=_BAR)
    )
    environments = AgentEnvironmentService(db)
    [production] = await environments.list_for_agent(ctx, agent.id)
    await environments.update(
        ctx,
        agent.id,
        production.id,
        EnvironmentUpdate(tracks_latest=True, guard_suite_ids=[lenient.id, strict.id]),
    )

    second = await _published(db, ctx, agent)
    await suites.start_due(now=datetime.now(UTC))
    await _finish_runs(db, Model(db, answer=lambda prompt: _FAIL))
    await suites.settle_finished(now=datetime.now(UTC))
    await db.refresh(agent)
    held = agent.current_version_id

    await _run_guards(db, ctx, agent, production.id, second, Model(db))
    await db.refresh(agent)
    moved = agent.current_version_id
    # A pass on the version it left does not take it back.
    await _run_guards(db, ctx, agent, production.id, first, Model(db))
    await db.refresh(agent)

    assert (held, moved, agent.current_version_id) == (first.id, second.id, second.id)


async def test_a_paused_guard_is_not_queued_by_a_publish(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    _, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx), tracks_latest=True)
    await EvalSuiteService(db).update(ctx, agent.id, suite.id, EvalSuiteUpdate(is_active=False))

    await _published(db, ctx, agent)

    assert await _results(db, suite.id) == []


async def test_following_latest_switched_on_goes_through_the_gate(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, _ = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    await _published(db, ctx, agent)

    with pytest.raises(PromotionBlockedError):
        await AgentEnvironmentService(db).update(
            ctx, agent.id, env_id, EnvironmentUpdate(tracks_latest=True)
        )


@pytest.mark.security
async def test_nothing_of_the_gate_crosses_organizations(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, _ = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    stranger = await _owner(db)

    with pytest.raises(NotFoundError):
        await _check(db, stranger, agent, env_id, first)
    with pytest.raises(NotFoundError):
        await PromotionGateService(db).run(
            stranger, agent.id, env_id, PromotionGateRun(version_id=first.id)
        )


async def _serving(db: AsyncSession, ctx: AuthContext, agent: Agent, env_id) -> int:
    listed = await AgentEnvironmentService(db).list_for_agent(ctx, agent.id)
    return next(e.version for e in listed if e.id == env_id)


async def _settle(db: AsyncSession, model: Model) -> None:
    sweep = EvalSuiteService(db)
    await sweep.start_due(now=datetime.now(UTC))
    await _finish_runs(db, model)
    await sweep.settle_finished(now=datetime.now(UTC))


async def test_a_pass_beside_one_environments_version_does_not_open_another(db) -> None:
    """Measured against staging's v2, a version says nothing about replacing production's v1."""
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    staging_id, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx))
    second = await _published(db, ctx, agent)
    environments = AgentEnvironmentService(db)
    await _run_guards(db, ctx, agent, staging_id, second, Model(db))
    await _promote(db, ctx, agent, staging_id, second)
    [production] = [e for e in await environments.list_for_agent(ctx, agent.id) if e.is_default]
    await environments.update(
        ctx, agent.id, production.id, EnvironmentUpdate(guard_suite_ids=[suite.id])
    )
    third = await _published(db, ctx, agent)

    await _run_guards(db, ctx, agent, staging_id, third, Model(db))

    assert (await _check(db, ctx, agent, staging_id, third)).passing
    production_gate = await _check(db, ctx, agent, production.id, third)
    assert [g.state for g in production_gate.guards] == ["unchecked"]
    # Production's own run is a check of its own, not absorbed into staging's.
    await PromotionGateService(db).run(
        ctx, agent.id, production.id, PromotionGateRun(version_id=third.id)
    )
    own = [
        r
        for r in await _results(db, suite.id)
        if r.agent_version_id == third.id and r.baseline_version_number == 1
    ]
    assert len(own) == 1


async def test_a_guard_paused_while_its_run_goes_on_holds_the_follower_back(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(
        db, ctx, agent, first, await _dataset(db, ctx), tracks_latest=True
    )
    await _published(db, ctx, agent)
    sweep = EvalSuiteService(db)
    await sweep.start_due(now=datetime.now(UTC))
    await sweep.update(ctx, agent.id, suite.id, EvalSuiteUpdate(is_active=False))
    await _finish_runs(db, Model(db))
    await sweep.settle_finished(now=datetime.now(UTC))

    assert await _serving(db, ctx, agent, env_id) == 1


@pytest.mark.security
async def test_a_guards_test_connections_change_only_with_the_permission(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    environments = AgentEnvironmentService(db)
    staging = await environments.create(
        ctx, agent.id, EnvironmentCreate(name="staging", version_id=first.id)
    )
    through = await EvalSuiteService(db).create(
        ctx, agent.id, _suite_data(await _dataset(db, ctx), environment_id=staging.id)
    )
    [production] = [e for e in await environments.list_for_agent(ctx, agent.id) if e.is_default]
    await environments.update(
        ctx, agent.id, production.id, EnvironmentUpdate(guard_suite_ids=[through.id])
    )
    builder = await _member(db, ctx, OrgRoleName.BUILDER)
    agent.owner_user_id = builder.user_id
    await db.flush()

    with pytest.raises(AuthorizationError, match="test connections"):
        await environments.update(builder, agent.id, staging.id, EnvironmentUpdate(connections=[]))
    await environments.update(ctx, agent.id, staging.id, EnvironmentUpdate(connections=[]))

    changes = await _audit(db, ctx, "agent.environment_guards_changed")
    assert [c.details["fields"] for c in changes if c.details and "fields" in c.details] == [
        ["connections"]
    ]


async def test_a_rollback_queues_the_guards_of_a_follower(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    _, suite = await _guarded(db, ctx, agent, first, await _dataset(db, ctx), tracks_latest=True)
    await _published(db, ctx, agent)

    rolled = await AgentRegistryService(db).rollback(ctx, agent.id, to_version_id=first.id)

    assert [r.trigger for r in await _results(db, suite.id) if r.agent_version_id == rolled.id] == [
        "gate"
    ]


async def test_a_promotion_that_fails_after_a_pass_leaves_the_pass_and_tries_again(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, suite = await _guarded(
        db, ctx, agent, first, await _dataset(db, ctx), tracks_latest=True
    )
    second = await _published(db, ctx, agent)

    with patch.object(PromotionGateService, "follow", side_effect=RuntimeError("busy")):
        await _settle(db, Model(db))
    [result] = [r for r in await _results(db, suite.id) if r.agent_version_id == second.id]
    held = await _serving(db, ctx, agent, env_id)
    moved = await EvalSuiteService(db).reconcile_followers()

    assert (result.status, held) == ("passed", 1)
    assert (moved, await _serving(db, ctx, agent, env_id)) == (1, 2)
    # Caught up, it is no longer among the followers the sweep reads.
    assert await promotion_gate_repo.guarded_followers(db, limit=10) == []
    assert await EvalSuiteService(db).reconcile_followers() == 0


async def test_taking_off_the_guard_holding_a_follower_back_moves_it(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    env_id, _ = await _guarded(
        db, ctx, agent, first, await _dataset(db, ctx), tracks_latest=True, threshold=_BAR
    )
    await _published(db, ctx, agent)
    await _settle(db, Model(db, answer=lambda prompt: _FAIL))
    held = await _serving(db, ctx, agent, env_id)
    # Behind, but its guard failed: the sweep's look leaves it where it is.
    assert await EvalSuiteService(db).reconcile_followers() == 0

    await AgentEnvironmentService(db).update(
        ctx, agent.id, env_id, EnvironmentUpdate(guard_suite_ids=[])
    )

    assert (held, await _serving(db, ctx, agent, env_id)) == (1, 2)


async def test_an_unguarded_default_that_follows_catches_up_with_the_agent(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    suite = await EvalSuiteService(db).create(
        ctx, agent.id, _suite_data(await _dataset(db, ctx), threshold=_BAR)
    )
    environments = AgentEnvironmentService(db)
    [production] = await environments.list_for_agent(ctx, agent.id)
    await environments.update(
        ctx, agent.id, production.id, EnvironmentUpdate(guard_suite_ids=[suite.id])
    )
    await environments.update(ctx, agent.id, production.id, EnvironmentUpdate(tracks_latest=True))
    second = await _published(db, ctx, agent)

    await environments.update(ctx, agent.id, production.id, EnvironmentUpdate(guard_suite_ids=[]))
    await db.refresh(agent)

    assert agent.current_version_id == second.id


async def test_an_automatic_promotion_is_announced_as_a_change_to_the_agent(db) -> None:
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    await _guarded(db, ctx, agent, first, await _dataset(db, ctx), tracks_latest=True)
    await _published(db, ctx, agent)
    announced = []

    def spawn(_db, coro, *, name):
        announced.append(name)
        coro.close()

    with patch("app.services.promotion_gate.spawn_after_commit", side_effect=spawn):
        await _settle(db, Model(db))

    assert [name for name in announced if name.startswith("promotion-gate-advance:")]


async def _results(db: AsyncSession, suite_id) -> list[EvalSuiteResult]:
    return list(
        (
            await db.execute(
                select(EvalSuiteResult)
                .where(EvalSuiteResult.suite_id == suite_id)
                .order_by(EvalSuiteResult.created_at)
            )
        ).scalars()
    )
