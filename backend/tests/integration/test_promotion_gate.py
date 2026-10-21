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

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.db.models.dataset import Dataset
from app.db.models.eval_suite import EvalSuite, EvalSuiteResult
from app.db.models.notification import Notification
from app.db.models.promotion_gate import PromotionOverride
from app.schemas.agent_environment import EnvironmentCreate, EnvironmentUpdate
from app.schemas.dataset import DatasetCaseCreate
from app.schemas.eval_suite import EvalSuiteThreshold, EvalSuiteUpdate
from app.schemas.promotion_gate import PromotionGateRun
from app.services.agent_environment import AgentEnvironmentService
from app.services.agent_registry import AgentRegistryService
from app.services.dataset import DatasetService
from app.services.eval_suite import EvalSuiteService
from app.services.promotion_gate import PromotionGateService
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


async def test_a_pass_over_an_older_dataset_version_or_threshold_is_stale(db) -> None:
    """Cases added since the pass, or a bar raised since, are not what passed."""
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    dataset = await _dataset(db, ctx)
    env_id, suite = await _guarded(db, ctx, agent, first, dataset)
    second = await _published(db, ctx, agent)
    await _run_guards(db, ctx, agent, env_id, second, Model(db))
    assert (await _check(db, ctx, agent, env_id, second)).passing

    await DatasetService(db).add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(
            input="A new question", checks=[{"type": "contains", "value": "30 days"}]
        ),
    )
    after_cases = await _check(db, ctx, agent, env_id, second)
    await _run_guards(db, ctx, agent, env_id, second, Model(db))
    await EvalSuiteService(db).update(
        ctx,
        agent.id,
        suite.id,
        EvalSuiteUpdate(threshold=EvalSuiteThreshold(min_pass_rate=0.9)),
    )
    after_threshold = await _check(db, ctx, agent, env_id, second)

    assert [g.state for g in after_cases.guards] == ["stale"]
    assert [g.state for g in after_threshold.guards] == ["stale"]


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
