"""Always-on cleanup, durable generation refusal, and consent changes during work."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.browser_procedure_teaching import BrowserProcedureTeachingReason
from app.core.config import settings
from app.db.models.agent_run import RunStatus
from app.repositories import browser_procedure_teaching as repo
from app.repositories import skill_proposal as proposal_repo
from app.schemas.browser_procedure_teaching import BrowserProcedureTeachingPropose
from app.services.browser_procedure_teaching import _generation, _maintenance, _refinement
from tests.integration.test_browser_procedure_teaching import draft_runtime as draft_runtime
from tests.integration.test_browser_procedure_teaching import generated
from tests.integration.test_browser_procedure_teaching import teaching as teaching
from tests.integration.test_browser_procedure_teaching_refinement import identity, start
from tests.test_browser_procedure_teaching_contracts import ORIGIN

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def queued(t, runtime):
    reviewed = await t.reviewed()
    await _generation.BrowserProcedureTeachingDraftService(t.db, t.redis).propose(
        t.ctx,
        reviewed.id,
        reviewed.revision,
        BrowserProcedureTeachingPropose(),
    )
    return await repo.session(t.db, t.org.id, reviewed.id), runtime[0][-1][1]


async def test_disabled_feature_still_erases_expired_capture_and_cancels_its_job(
    teaching, draft_runtime, monkeypatch
):
    t = teaching
    row, job = await queued(t, draft_runtime)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await t.db.flush()
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", False)
    assert await _maintenance.sweep_browser_procedure_teachings() == 1
    assert row.status == "expired" and row.generation_state == "cancelled"
    assert row.sanitized_events == [] and row.review is None and row.procedure is None
    await _generation.draft_browser_procedure_teaching(job)
    assert row.proposal_id is None


async def test_manual_capture_loses_ownership_when_its_live_connection_is_gone(
    teaching, draft_runtime, monkeypatch
):
    t = teaching
    data = await t.start()
    monkeypatch.setattr(_maintenance.live_browse, "credential_redis", lambda: t.redis)
    assert await _maintenance.sweep_browser_procedure_teachings() == 1
    row = await repo.session(t.db, t.org.id, data.id)
    assert row.status == "recording"
    await t.lease.close()
    assert await _maintenance.sweep_browser_procedure_teachings() == 1
    assert (
        row.status == "paused" and row.reason_code == BrowserProcedureTeachingReason.OWNERSHIP_LOST
    )


async def test_missing_redis_cannot_keep_a_manual_capture_alive(
    teaching, draft_runtime, monkeypatch
):
    t = teaching
    data = await t.start()
    monkeypatch.setattr(_maintenance.live_browse, "credential_redis", lambda: None)
    await _maintenance.sweep_browser_procedure_teachings()
    assert (
        await repo.session(t.db, t.org.id, data.id)
    ).reason_code == BrowserProcedureTeachingReason.OWNERSHIP_LOST


async def test_revoked_policy_cancels_a_queued_draft_before_generation(teaching, draft_runtime):
    t = teaching
    row, job = await queued(t, draft_runtime)
    policy = await repo.policy(t.db, t.org.id)
    policy.generation = uuid4()
    await t.db.flush()
    await _maintenance.sweep_browser_procedure_teachings()
    assert (
        row.generation_state == "cancelled"
        and row.reason_code == BrowserProcedureTeachingReason.AUTHORITY_CHANGED
    )
    await _generation.draft_browser_procedure_teaching(job)
    assert row.proposal_id is None


async def test_worker_loss_after_generation_claim_is_unknown_and_never_retried(
    teaching, draft_runtime
):
    t = teaching
    row, job = await queued(t, draft_runtime)
    assert await _generation._claim(job) is not None
    row.generation_started_at = datetime.now(UTC) - timedelta(minutes=10)
    await t.db.flush()
    await _maintenance.sweep_browser_procedure_teachings()
    assert (
        row.generation_state == "unknown"
        and row.reason_code == BrowserProcedureTeachingReason.GENERATION_UNKNOWN
    )
    assert await _generation._claim(job) is None


async def test_a_worker_claim_between_candidate_read_and_lock_is_not_declared_abandoned(
    teaching, draft_runtime, monkeypatch
):
    t = teaching
    row, job = await queued(t, draft_runtime)
    original = repo.sweep_candidates

    async def candidates(db, now, before):
        result = await original(db, now, before)
        assert await _generation._claim(job) is not None
        return result

    monkeypatch.setattr(repo, "sweep_candidates", candidates)
    assert await _maintenance.sweep_browser_procedure_teachings() == 1
    assert row.generation_state == "generating" and row.reason_code is None


@pytest.mark.parametrize("state", ["pending", "applied", "wrong_source", "expired"])
async def test_proposal_retention_keeps_only_pending_unexpired_review_material(
    teaching, draft_runtime, state
):
    t = teaching
    data, proposal = await generated(t, draft_runtime)
    row = await repo.session(t.db, t.org.id, data.id)
    if state == "applied":
        proposal.status = "applied"
    elif state == "wrong_source":
        proposal.source = "workspace"
    elif state == "expired":
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await t.db.flush()
    await _maintenance.sweep_browser_procedure_teachings()
    assert bool(row.sanitized_events) == (state == "pending")
    assert bool(row.review) == (state == "pending")
    assert (await proposal_repo.get(t.db, proposal.id, organization_id=t.org.id)) is not None


async def test_automatic_capture_is_discarded_when_run_fails_before_browser_completion(
    teaching, draft_runtime
):
    t = teaching
    data = await start(t)
    assert await _maintenance.sweep_browser_procedure_teachings() == 1
    row = await repo.session(t.db, t.org.id, data.id)
    assert row.status == "recording"
    t.run.status = RunStatus.FAILED.value
    await t.db.flush()
    await _maintenance.sweep_browser_procedure_teachings()
    assert row.status == "discarded" and row.sanitized_events == []


async def test_sweep_confirms_only_actual_completed_run_evidence(teaching, draft_runtime):
    t = teaching
    data = await start(t)
    await _refinement.finish(t.db, t.ctx, identity(t), data.id, completed=True)
    row = await repo.session(t.db, t.org.id, data.id)
    assert await _maintenance.sweep_browser_procedure_teachings() == 1
    assert not row.verified_success
    t.run.status = RunStatus.COMPLETED.value
    await t.db.flush()
    assert await _maintenance.sweep_browser_procedure_teachings() == 1
    assert row.verified_success
    assert await _maintenance.sweep_browser_procedure_teachings() == 0


async def test_missing_candidate_after_cascade_is_skipped_without_recreation(
    teaching, draft_runtime, monkeypatch
):
    t = teaching
    monkeypatch.setattr(repo, "sweep_candidates", AsyncMock(return_value=[(t.org.id, uuid4())]))
    assert await _maintenance.sweep_browser_procedure_teachings() == 0


async def test_completed_browser_suggestion_is_erased_when_consent_changes_before_reconciliation(
    teaching, draft_runtime
):
    t = teaching
    data = await start(t)
    await _refinement.finish(t.db, t.ctx, identity(t), data.id, completed=True)
    preference = await repo.preference(t.db, t.org.id, t.owner.id, t.agent.id)
    preference.enabled = False
    await t.db.flush()
    await _maintenance.sweep_browser_procedure_teachings()
    row = await repo.session(t.db, t.org.id, data.id)
    assert row.status == "discarded" and row.reason_code == BrowserProcedureTeachingReason.OPTED_OUT
    assert row.allowed_origins == [] and ORIGIN not in str(row.sanitized_events)


async def test_model_representations_never_include_captured_or_reviewed_material(teaching):
    t = teaching
    data = await start(t)
    row = await repo.session(t.db, t.org.id, data.id)
    preference = await repo.preference(t.db, t.org.id, t.owner.id, t.agent.id)
    policy = await repo.policy(t.db, t.org.id)
    assert str(row.id) in repr(row) and ORIGIN not in repr(row)
    assert str(t.agent.id) in repr(preference)
    assert str(t.org.id) in repr(policy)


async def test_a_current_queued_review_is_retained_without_requiring_a_live_capture(
    teaching, draft_runtime
):
    t = teaching
    row, _ = await queued(t, draft_runtime)
    revision = row.revision
    assert await _maintenance.sweep_browser_procedure_teachings() == 1
    assert row.status == "review" and row.generation_state == "queued"
    assert row.revision == revision and row.sanitized_events and row.reason_code is None


@pytest.mark.parametrize("claimed", [False, True])
async def test_org_opt_out_cancels_queued_and_claimed_manual_drafts(
    teaching, draft_runtime, claimed
):
    from app.schemas.browser_procedure_teaching import BrowserProcedureTeachingPolicyWrite
    from app.services.browser_procedure_teaching._policy import (
        BrowserProcedureTeachingPolicyService,
    )

    t = teaching
    row, job = await queued(t, draft_runtime)
    if claimed:
        assert await _generation._claim(job) is not None
    revision = row.revision
    policy = await repo.policy(t.db, t.org.id)
    await BrowserProcedureTeachingPolicyService(t.db).update(
        t.ctx,
        BrowserProcedureTeachingPolicyWrite(generation=policy.generation, enabled=False),
    )
    assert (
        row.generation_state == "cancelled"
        and row.reason_code == BrowserProcedureTeachingReason.DISABLED
    )
    assert row.revision == revision + 1
    await _generation.draft_browser_procedure_teaching(job)
    assert row.proposal_id is None


async def test_current_opt_in_authorizes_only_its_active_owning_recording(teaching):
    t = teaching
    data = await start(t)
    row = await _refinement.authorize_capture(t.db, t.ctx, identity(t), data.id)
    assert row.id == data.id and row.status == "recording" and row.source == "refinement"
