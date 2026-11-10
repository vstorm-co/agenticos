"""A review decision changes every stored verdict without moving follower environments."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.models.agent_environment import AgentEnvironment
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.case_score import CaseScore
from app.db.models.eval_run import EvalRun, EvalRunArm, EvalRunCase
from app.db.models.notification import Notification
from app.schemas.scoring import CaseVerdict
from app.services.eval_run import EvalRunService
from app.services.eval_suite import EvalSuiteService
from app.services.scoring import ScoringService
from tests.integration.test_eval_suites import (
    _FAIL,
    _PASS,
    Model,
    _agent,
    _dataset,
    _finish_runs,
    _owner,
    _suite_data,
)
from tests.integration.test_eval_suites import _environment as _environment
from tests.integration.test_promotion_gate import _BAR, _check, _guarded, _published

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


class CandidateFailure(Model):
    def __init__(self, db, bad_version):
        super().__init__(db)
        self.bad_version = bad_version

    async def execute(self, runner, ctx, agent_id, prompt, **kw):
        _, run = await super().execute(runner, ctx, agent_id, prompt, **kw)
        return (_FAIL if kw["candidate"].version_id == self.bad_version else _PASS), run


async def test_review_and_undo_recompute_suite_gate_run_notification_and_audit_without_follow(db):
    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    environment_id, suite = await _guarded(
        db, ctx, agent, first, dataset, tracks_latest=True, threshold=_BAR
    )
    second = await _published(db, ctx, agent)
    service = EvalSuiteService(db)
    await service.start_due(now=datetime.now(UTC))
    await _finish_runs(db, CandidateFailure(db, second.id))
    await service.settle_finished(now=datetime.now(UTC))
    failed = await service.get(ctx, agent.id, suite.id)
    assert failed.last_result is not None and failed.last_result.status == "failed"
    run_id = failed.last_result.eval_run_id
    assert run_id is not None
    assert not (await _check(db, ctx, agent, environment_id, second)).passing
    score = await db.scalar(
        select(CaseScore)
        .join(EvalRunCase, EvalRunCase.case_score_id == CaseScore.id)
        .join(EvalRunArm, EvalRunArm.id == EvalRunCase.arm_id)
        .where(
            CaseScore.eval_run_id == run_id,
            EvalRunArm.role == "candidate",
            EvalRunCase.attempt == 0,
        )
    )
    assert score is not None
    await ScoringService(db).set_verdict(
        ctx, dataset.id, score.id, CaseVerdict(passed=True, note="The answer is correct")
    )
    passed = await service.get(ctx, agent.id, suite.id)
    assert passed.last_result is not None and passed.last_result.status == "passed"
    summary = passed.last_result.summary
    assert summary is not None and summary.pass_rate == 1
    assert summary.review is not None and summary.review.by_user_id == ctx.user_id
    assert summary.review.by_name is not None
    gate = await _check(db, ctx, agent, environment_id, second)
    assert gate.passing and gate.guards[0].result is not None
    assert gate.guards[0].result.summary == summary
    run = await EvalRunService(db).get(ctx, run_id)
    assert run.review is not None and run.review.by_user_id == ctx.user_id
    assert next(arm for arm in run.arms if arm.role == "candidate").summary.pass_rate == 1
    assert await service.reconcile_followers() == 0
    environment = await db.get(AgentEnvironment, environment_id)
    assert environment is not None and environment.version_id == first.id
    await ScoringService(db).set_verdict(ctx, dataset.id, score.id, CaseVerdict(passed=None))
    undone = await service.get(ctx, agent.id, suite.id)
    assert undone.last_result is not None and undone.last_result.status == "failed"
    assert undone.last_result.summary is not None and undone.last_result.summary.review is not None
    assert undone.last_result.summary.review.undo
    assert not (await _check(db, ctx, agent, environment_id, second)).passing
    run = await EvalRunService(db).get(ctx, run_id)
    assert next(arm for arm in run.arms if arm.role == "candidate").summary.pass_rate == 0
    audits = list(
        await db.scalars(
            select(AppAdminAuditLog)
            .where(
                AppAdminAuditLog.organization_id == ctx.organization_id,
                AppAdminAuditLog.action == "eval_suite.result_reevaluated",
            )
            .order_by(AppAdminAuditLog.seq)
        )
    )
    assert [(row.details["previous_status"], row.details["status"]) for row in audits] == [
        ("failed", "passed"),
        ("passed", "failed"),
    ]
    assert all("The answer is correct" not in str(row.details) for row in audits)
    notices = list(
        await db.scalars(
            select(Notification).where(
                Notification.organization_id == ctx.organization_id,
                Notification.event_type == "eval_suite_reevaluated",
            )
        )
    )
    assert len(notices) == 2


async def test_gate_retains_a_failed_run_on_a_different_serving_baseline_as_stale(db):
    from tests.integration.test_promotion_gate import _REASON, _promote, _run_guards

    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    environment_id, suite = await _guarded(db, ctx, agent, first, dataset, threshold=_BAR)
    second = await _published(db, ctx, agent)
    await _run_guards(db, ctx, agent, environment_id, second, Model(db, answer=lambda _: _FAIL))
    before = await _check(db, ctx, agent, environment_id, second)
    assert before.guards[0].state == "failed"
    old_result = before.guards[0].result
    assert old_result is not None and old_result.eval_run_id is not None
    third = await _published(db, ctx, agent)
    await _promote(db, ctx, agent, environment_id, third, reason=_REASON)
    after = await _check(db, ctx, agent, environment_id, second)
    assert after.guards[0].state == "stale"
    result = after.guards[0].result
    assert result is not None and result.eval_run_id == old_result.eval_run_id
    assert result.summary is not None and result.summary.pass_rate == 0


async def test_reviewing_an_older_run_does_not_displace_a_newer_completed_check(db):
    from tests.integration.test_promotion_gate import _run_guards

    ctx = await _owner(db)
    agent, first = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    environment_id, suite = await _guarded(db, ctx, agent, first, dataset, threshold=_BAR)
    second = await _published(db, ctx, agent)
    await _run_guards(db, ctx, agent, environment_id, second, CandidateFailure(db, second.id))
    original = (await _check(db, ctx, agent, environment_id, second)).guards[0].result
    assert original is not None and original.eval_run_id is not None
    settled_at = original.settled_at
    score = await db.scalar(
        select(CaseScore)
        .join(EvalRunCase, EvalRunCase.case_score_id == CaseScore.id)
        .join(EvalRunArm, EvalRunArm.id == EvalRunCase.arm_id)
        .where(
            CaseScore.eval_run_id == original.eval_run_id,
            EvalRunArm.role == "candidate",
            EvalRunCase.attempt == 0,
        )
    )
    assert score is not None
    await _run_guards(db, ctx, agent, environment_id, second, Model(db))
    newest = (await _check(db, ctx, agent, environment_id, second)).guards[0].result
    assert newest is not None and newest.id != original.id
    await ScoringService(db).set_verdict(ctx, dataset.id, score.id, CaseVerdict(passed=True))
    gate = await _check(db, ctx, agent, environment_id, second)
    assert gate.guards[0].result is not None and gate.guards[0].result.id == newest.id
    from app.db.models.eval_suite import EvalSuiteResult

    stored = await db.get(EvalSuiteResult, original.id)
    assert stored is not None and stored.settled_at == settled_at
    assert stored.summary is not None and "by_name" not in stored.summary["review"]


@pytest.mark.security
async def test_a_recompute_reaches_no_run_of_another_organization(db):
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    service = EvalSuiteService(db)
    suite = await service.create(ctx, agent.id, _suite_data(dataset))
    await service.run_now(ctx, agent.id, suite.id)
    await _finish_runs(db, Model(db))
    await service.settle_finished(now=datetime.now(UTC))
    before = (await service.get(ctx, agent.id, suite.id)).last_result
    assert before is not None and before.eval_run_id is not None
    stranger = await _owner(db)

    await service.recompute_after_review(stranger, [before.eval_run_id], undo=False)

    run = await db.get(EvalRun, before.eval_run_id)
    assert run is not None and run.review_metadata is None
    after = (await service.get(ctx, agent.id, suite.id)).last_result
    assert after == before
    assert after is not None and after.summary is not None and after.summary.review is None
    assert not list(
        await db.scalars(
            select(AppAdminAuditLog).where(
                AppAdminAuditLog.action == "eval_suite.result_reevaluated"
            )
        )
    )
