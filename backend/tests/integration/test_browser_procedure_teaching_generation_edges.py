"""A reviewed draft is attempted once and every uncertain or revoked boundary refuses."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingGeneration,
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
)
from app.core.exceptions import (
    ConflictError,
    SystemAgentOutputError,
    SystemAgentRunError,
    SystemAgentUnavailableError,
)
from app.db.models.skill_proposal import SkillProposal
from app.repositories import browser_procedure_teaching as repo
from app.schemas.browser_procedure_teaching import BrowserProcedureTeachingPropose
from app.services.browser_procedure_teaching import _generation
from app.services.browser_procedure_teaching._draft import render, reviewed_draft
from tests.integration.test_browser_procedure_teaching import draft_runtime as draft_runtime
from tests.integration.test_browser_procedure_teaching import teaching as teaching
from tests.test_browser_procedure_teaching_contracts import SECRET

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def queued(t, runtime, *, assistant=False):
    data = await t.reviewed()
    request = (
        BrowserProcedureTeachingPropose(mode="assistant", max_cost_usd=Decimal("0.05"))
        if assistant
        else BrowserProcedureTeachingPropose()
    )
    await _generation.BrowserProcedureTeachingDraftService(t.db, t.redis).propose(
        t.ctx, data.id, data.revision, request
    )
    return data, await repo.session(t.db, t.org.id, data.id), runtime[0][-1][1]


@pytest.mark.parametrize("case", ["unreviewed", "stale", "other_attempt"])
async def test_generation_requires_the_exact_review_and_does_not_duplicate_a_changed_request(
    teaching, draft_runtime, case
):
    t = teaching
    service = _generation.BrowserProcedureTeachingDraftService(t.db, t.redis)
    if case == "unreviewed":
        data = await t.start()
        with pytest.raises(BrowserProcedureTeachingRefused):
            await service.propose(t.ctx, data.id, data.revision, BrowserProcedureTeachingPropose())
        return
    data, _, _ = await queued(t, draft_runtime)
    revision = data.revision + 1 if case == "stale" else data.revision
    request = (
        BrowserProcedureTeachingPropose()
        if case == "stale"
        else BrowserProcedureTeachingPropose(mode="assistant", max_cost_usd=Decimal("0.05"))
    )
    with pytest.raises(ConflictError):
        await service.propose(t.ctx, data.id, revision, request)
    assert len(draft_runtime[0]) == 1


async def test_stale_review_before_first_enqueue_is_refused(teaching, draft_runtime):
    t = teaching
    data = await t.reviewed()
    with pytest.raises(ConflictError):
        await _generation.BrowserProcedureTeachingDraftService(t.db, t.redis).propose(
            t.ctx, data.id, data.revision + 1, BrowserProcedureTeachingPropose()
        )
    assert draft_runtime[0] == []


async def test_assistant_unavailability_refuses_before_any_job_is_queued(
    teaching, draft_runtime, monkeypatch
):
    t = teaching
    data = await t.reviewed()
    monkeypatch.setattr(
        _generation.SystemAgentRunner,
        "require_runnable",
        AsyncMock(
            side_effect=SystemAgentUnavailableError(
                SECRET, key="authoring_improver", reason="no_access"
            )
        ),
    )
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await _generation.BrowserProcedureTeachingDraftService(t.db, t.redis).propose(
            t.ctx,
            data.id,
            data.revision,
            BrowserProcedureTeachingPropose(mode="assistant", max_cost_usd=Decimal("0.05")),
        )
    assert (
        caught.value.reason == BrowserProcedureTeachingReason.BUDGET_REFUSED
        and draft_runtime[0] == []
    )


@pytest.mark.parametrize("change", ["none", "mismatched", "invalid", "authority"])
async def test_corrupted_or_revoked_review_is_refused_at_claim_without_a_model(
    teaching, draft_runtime, change
):
    t = teaching
    _, row, job = await queued(t, draft_runtime)
    if change == "none":
        row.review = None
    elif change == "invalid":
        row.review = {"invalid": "review"}
    elif change == "mismatched":
        row.review = {**row.review, "description": "A different reviewed description"}
    else:
        (await repo.policy(t.db, t.org.id)).generation = uuid4()
    await t.db.flush()
    assert await _generation._claim(job) is None
    assert row.generation_state == "refused"
    assert row.reason_code == (
        BrowserProcedureTeachingReason.INVALID_DRAFT
        if change == "invalid"
        else BrowserProcedureTeachingReason.AUTHORITY_CHANGED
        if change == "authority"
        else BrowserProcedureTeachingReason.REVIEW_REQUIRED
    )


async def test_expired_queued_review_never_becomes_a_generation_claim(teaching, draft_runtime):
    t = teaching
    _, row, job = await queued(t, draft_runtime)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await t.db.flush()
    assert await _generation._claim(job) is None
    assert row.status == "expired" and row.generation_state == "cancelled"


@pytest.mark.parametrize("change", ["missing", "expired", "changed_claim_review", "cancelled"])
async def test_fresh_authority_check_rejects_a_changed_generation_boundary(
    teaching, draft_runtime, change
):
    t = teaching
    _, row, job = await queued(t, draft_runtime)
    claim = await _generation._claim(job)
    if change == "missing":
        claim = replace(claim, job=job.model_copy(update={"session_id": uuid4()}))
    elif change == "expired":
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await t.db.flush()
    elif change == "changed_claim_review":
        claim = replace(
            claim, review=claim.review.model_copy(update={"description": "Changed claim"})
        )
    else:
        await t.service.discard(t.ctx, row.id)
    with pytest.raises(BrowserProcedureTeachingRefused):
        await _generation._current(t.db, claim)
    await _generation._settle(
        replace(claim, job=job.model_copy(update={"token": uuid4()})),
        BrowserProcedureTeachingGeneration.UNKNOWN,
        BrowserProcedureTeachingReason.GENERATION_UNKNOWN,
    )


@pytest.mark.parametrize("budget", [None, Decimal("0")])
async def test_no_assistant_request_exists_without_a_positive_attempt_budget(
    teaching, draft_runtime, budget
):
    t = teaching
    _, _, job = await queued(t, draft_runtime)
    claim = await _generation._claim(job)
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await _generation._assistant(replace(claim, mode="assistant", max_cost_usd=budget))
    assert caught.value.reason == BrowserProcedureTeachingReason.BUDGET_REFUSED


@pytest.mark.parametrize(
    "kind", ["invalid", "unavailable", "failed", "cancelled", "revoked", "success"]
)
async def test_model_boundary_uses_fixed_receipts_and_never_retries(
    teaching, draft_runtime, monkeypatch, kind, caplog
):
    t = teaching
    monkeypatch.setattr(_generation.SystemAgentRunner, "require_runnable", AsyncMock())
    _, row, job = await queued(t, draft_runtime, assistant=True)
    attempts = []

    async def model(self, context, **kwargs):
        attempts.append("model")
        await kwargs["check_model_request"](t.db)
        assert kwargs["run_limit_usd"] == Decimal("0.05")
        assert SECRET not in kwargs["prompt"]
        if kind == "invalid":
            raise SystemAgentOutputError(SECRET, run_id=uuid4(), answer=SECRET)
        if kind == "unavailable":
            raise SystemAgentUnavailableError(SECRET, key="authoring_improver", reason="no_access")
        if kind == "failed":
            raise SystemAgentRunError(SECRET, run_id=uuid4(), status="failed")
        if kind == "cancelled":
            raise asyncio.CancelledError()
        chosen, procedure = _generation._reviewed(row)
        if kind == "revoked":
            (await repo.policy(t.db, t.org.id)).generation = uuid4()
            await t.db.flush()
        return SimpleNamespace(output=reviewed_draft(chosen, procedure))

    monkeypatch.setattr(_generation.SystemAgentRunner, "run", model)
    if kind == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await _generation.draft_browser_procedure_teaching(job)
    else:
        await _generation.draft_browser_procedure_teaching(job)
    await _generation.draft_browser_procedure_teaching(job)
    assert attempts == ["model"] and SECRET not in caplog.text
    assert row.generation_state == (
        "unknown" if kind == "cancelled" else "succeeded" if kind == "success" else "refused"
    )
    assert (row.proposal_id is not None) == (kind == "success")


@pytest.mark.parametrize("matching", [False, True])
async def test_existing_proposal_is_reused_only_with_the_same_reviewed_provenance(
    teaching, draft_runtime, matching
):
    t = teaching
    _, row, job = await queued(t, draft_runtime)
    claim = await _generation._claim(job)
    draft = reviewed_draft(claim.review, claim.procedure)
    metadata = claim.procedure.model_dump(mode="json")
    if not matching:
        metadata = {**metadata, "verified_success": True}
    proposal = SkillProposal(
        organization_id=t.org.id,
        name=claim.review.name,
        source="browser_teaching",
        content=render(claim.review, claim.procedure, draft),
        description=draft.description,
        browser_procedure=metadata,
        resources={},
    )
    await repo.create_proposal(t.db, proposal)
    if matching:
        await _generation._finish(claim, draft)
        assert row.proposal_id == proposal.id
    else:
        with pytest.raises(BrowserProcedureTeachingRefused):
            await _generation._finish(claim, draft)
        assert row.proposal_id is None


async def test_unknown_stored_mode_is_refused_without_guessing():
    with pytest.raises(BrowserProcedureTeachingRefused):
        _generation._mode(SimpleNamespace(generation_mode="future_mode"))
