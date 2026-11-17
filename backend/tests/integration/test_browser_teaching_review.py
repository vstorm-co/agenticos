"""Browser teaching review and proposal (#113 slice 2) against a real database.

Checked here: review edits are idempotent and conflict when stale, labels and
parameter names are the only reviewed content, a proposal request checks
authority and budget before anything is queued, the queued build checks them
again before it writes, and one session yields at most one proposal whose body
names only the reviewed steps, parameter names and allowed origins.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update

from app.agents.capabilities.budget import BudgetExceeded, BudgetScope
from app.core.browser_teaching import Observation, ReviewedStep, TeachingConflict, TeachingReason, TeachingRefused
from app.core.config import settings
from app.db.models.background_job import BackgroundJob
from app.db.models.browser_teaching import BrowserTeachingSession
from app.db.models.organization import OrganizationMember
from app.db.models.skill_proposal import SkillProposal
from app.schemas.browser_teaching import TeachingPropose, TeachingReview
from app.services.browser_teaching import _service
from tests.integration.test_browser_teaching_capture import (
    ORIGIN,
    SECRETS,
    _ctx,
    _recording,
    _seen,
    enabled,  # noqa: F401 - fixture
    redis,  # noqa: F401 - fixture
)

pytestmark = pytest.mark.anyio

FINGERPRINT_PREFIX = "sha256:"


async def _in_review(db, redis, enabled):
    """A stopped demonstration: open a page, type an invoice number, click Download."""
    organization, owner, agent, run, hold, service, started = await _recording(db, redis, enabled)
    await service.record(hold, input_id=uuid.uuid4(), action="navigate", observation=Observation(origin=ORIGIN))
    await service.record(hold, input_id=uuid.uuid4(), action="input_parameter", observation=_seen("textbox", 2))
    await service.record(hold, input_id=uuid.uuid4(), action="click", observation=_seen("button", 3))
    stopped = await service.stop(_ctx(owner, organization), started.id)
    return organization, owner, service, stopped


def _review(**overrides: ReviewedStep) -> TeachingReview:
    steps = {
        1: ReviewedStep(sequence=1, label="Invoices page"),
        2: ReviewedStep(sequence=2, label="Invoice number", parameter="invoice_number"),
        3: ReviewedStep(sequence=3, label="Download"),
    }
    steps.update({int(key.removeprefix("s")): value for key, value in overrides.items()})
    return TeachingReview(action="review", steps=tuple(steps.values()))


async def _reviewed(db, redis, enabled):
    organization, owner, service, stopped = await _in_review(db, redis, enabled)
    reviewed = await service.review(_ctx(owner, organization), stopped.id, _review(), stopped.revision)
    return organization, owner, service, reviewed


async def _jobs(db) -> int:
    return await db.scalar(select(func.count()).select_from(BackgroundJob).where(BackgroundJob.kind == "build-teaching-proposal"))


async def _proposals(db, session_id: uuid.UUID) -> list[SkillProposal]:
    return list(await db.scalars(select(SkillProposal).where(SkillProposal.browser_teaching_id == session_id)))


async def test_review_stores_labels_and_parameters_and_a_retry_changes_nothing(db, redis, enabled) -> None:
    organization, owner, service, stopped = await _in_review(db, redis, enabled)
    reviewed = await service.review(_ctx(owner, organization), stopped.id, _review(), stopped.revision)
    assert reviewed.revision == stopped.revision + 1
    assert reviewed.parameters == ("invoice_number",)
    assert [step.sequence for step in reviewed.review] == [1, 2, 3]
    again = await service.review(_ctx(owner, organization), stopped.id, _review(), stopped.revision)
    assert again == reviewed


async def test_a_stale_review_edit_conflicts(db, redis, enabled) -> None:
    organization, owner, service, stopped = await _in_review(db, redis, enabled)
    await service.review(_ctx(owner, organization), stopped.id, _review(), stopped.revision)
    changed = _review(s3=ReviewedStep(sequence=3, label="Save as PDF"))
    with pytest.raises(TeachingConflict) as conflict:
        await service.review(_ctx(owner, organization), stopped.id, changed, stopped.revision)
    assert conflict.value.reason == TeachingReason.STALE_REVISION


async def test_review_refuses_an_unknown_step_and_a_parameter_on_a_click(db, redis, enabled) -> None:
    organization, owner, service, stopped = await _in_review(db, redis, enabled)
    unknown = _review(s9=ReviewedStep(sequence=9, label="Ghost"))
    with pytest.raises(TeachingRefused) as refused:
        await service.review(_ctx(owner, organization), stopped.id, unknown, stopped.revision)
    assert refused.value.reason == TeachingReason.REVIEW_UNKNOWN_STEP
    clicked = _review(s3=ReviewedStep(sequence=3, label="Download", parameter="file"))
    with pytest.raises(TeachingRefused):
        await service.review(_ctx(owner, organization), stopped.id, clicked, stopped.revision)


@pytest.mark.security
async def test_another_member_cannot_review_or_propose(db, redis, enabled) -> None:
    from app.core.exceptions import NotFoundError
    from tests.integration.test_browser_teaching_capture import _person

    organization, _, service, stopped = await _in_review(db, redis, enabled)
    intruder = await _person(db, organization)
    with pytest.raises(NotFoundError):
        await service.review(_ctx(intruder, organization), stopped.id, _review(), stopped.revision)
    with pytest.raises(NotFoundError):
        await service.propose(_ctx(intruder, organization), stopped.id, TeachingPropose(name="x"), stopped.revision)


async def test_an_unfinished_review_cannot_be_proposed(db, redis, enabled) -> None:
    organization, owner, service, stopped = await _in_review(db, redis, enabled)
    with pytest.raises(TeachingRefused) as refused:
        await service.propose(_ctx(owner, organization), stopped.id, TeachingPropose(name="download-invoice"), stopped.revision)
    assert refused.value.reason == TeachingReason.REVIEW_INCOMPLETE
    assert await _jobs(db) == 0


async def test_budget_refusal_queues_nothing(db, redis, enabled, monkeypatch) -> None:
    organization, owner, service, reviewed = await _reviewed(db, redis, enabled)

    async def over_budget(_db, _organization_id) -> None:
        raise BudgetExceeded(limit_usd=Decimal("1"), spent_usd=Decimal("1"), scope=BudgetScope.ORGANIZATION)

    monkeypatch.setattr(_service, "assert_organization_within_budget", over_budget)
    with pytest.raises(TeachingRefused) as refused:
        await service.propose(_ctx(owner, organization), reviewed.id, TeachingPropose(name="download-invoice"), reviewed.revision)
    assert refused.value.reason == TeachingReason.BUDGET
    assert await _jobs(db) == 0
    assert (await db.get(BrowserTeachingSession, reviewed.id)).status == "review"


async def test_a_repeated_proposal_request_queues_one_build_and_yields_one_proposal(db, redis, enabled) -> None:
    organization, owner, service, reviewed = await _reviewed(db, redis, enabled)
    ctx, body = _ctx(owner, organization), TeachingPropose(name="download-invoice")
    asked = await service.propose(ctx, reviewed.id, body, reviewed.revision)
    assert asked.status == "proposing"
    assert await service.propose(ctx, reviewed.id, body, reviewed.revision) == asked
    assert await _jobs(db) == 1
    with pytest.raises(TeachingConflict):
        await service.propose(ctx, reviewed.id, TeachingPropose(name="other-name"), asked.revision)
    row = await db.get(BrowserTeachingSession, reviewed.id)
    await service.build_proposal(organization.id, reviewed.id, row.source_hash)
    await service.build_proposal(organization.id, reviewed.id, row.source_hash)
    proposals = await _proposals(db, reviewed.id)
    assert len(proposals) == 1
    done = await service.get(ctx, reviewed.id)
    assert (done.status, done.proposal_id, done.events, done.review) == ("proposed", proposals[0].id, (), ())
    assert await service.propose(ctx, reviewed.id, body, None) == done


async def test_the_proposal_holds_only_reviewed_steps_parameter_names_and_allowed_origins(db, redis, enabled) -> None:
    organization, owner, service, reviewed = await _reviewed(db, redis, enabled)
    await service.propose(_ctx(owner, organization), reviewed.id, TeachingPropose(name="download-invoice"), reviewed.revision)
    row = await db.get(BrowserTeachingSession, reviewed.id)
    await service.build_proposal(organization.id, reviewed.id, row.source_hash)
    (proposal,) = await _proposals(db, reviewed.id)
    assert (proposal.skill_id, proposal.status, proposal.name) == (None, "pending", "download-invoice")
    body = proposal.description + proposal.content
    assert ORIGIN in body and "`{invoice_number}`" in body and '"Download"' in body
    assert FINGERPRINT_PREFIX not in body and "Download invoice" not in body
    assert not any(secret in body for secret in SECRETS)
    assert {line.removeprefix("- ") for line in body.splitlines() if line.startswith("- https://")} == {ORIGIN}


async def test_permission_loss_before_the_build_writes_no_proposal(db, redis, enabled) -> None:
    organization, owner, service, reviewed = await _reviewed(db, redis, enabled)
    await service.propose(_ctx(owner, organization), reviewed.id, TeachingPropose(name="download-invoice"), reviewed.revision)
    row = await db.get(BrowserTeachingSession, reviewed.id)
    digest = row.source_hash
    await db.execute(update(OrganizationMember).where(OrganizationMember.user_id == owner.id).values(role="viewer"))
    await service.build_proposal(organization.id, reviewed.id, digest)
    assert await _proposals(db, reviewed.id) == []
    row = await db.get(BrowserTeachingSession, reviewed.id)
    assert (row.status, row.reason_code, row.source_hash) == ("review", "authority_changed", None)


async def test_budget_refusal_at_build_time_writes_no_proposal(db, redis, enabled, monkeypatch) -> None:
    organization, owner, service, reviewed = await _reviewed(db, redis, enabled)
    await service.propose(_ctx(owner, organization), reviewed.id, TeachingPropose(name="download-invoice"), reviewed.revision)
    row = await db.get(BrowserTeachingSession, reviewed.id)

    async def over_budget(_db, _organization_id) -> None:
        raise BudgetExceeded(limit_usd=Decimal("1"), spent_usd=Decimal("1"), scope=BudgetScope.ORGANIZATION)

    monkeypatch.setattr(_service, "assert_organization_within_budget", over_budget)
    await service.build_proposal(organization.id, reviewed.id, row.source_hash)
    assert await _proposals(db, reviewed.id) == []
    assert (await db.get(BrowserTeachingSession, reviewed.id)).reason_code == "budget_exceeded"


async def test_a_disabled_flag_or_a_discarded_session_stops_the_build(db, redis, enabled, monkeypatch) -> None:
    organization, owner, service, reviewed = await _reviewed(db, redis, enabled)
    await service.propose(_ctx(owner, organization), reviewed.id, TeachingPropose(name="download-invoice"), reviewed.revision)
    digest = (await db.get(BrowserTeachingSession, reviewed.id)).source_hash
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", False)
    await service.build_proposal(organization.id, reviewed.id, digest)
    assert (await db.get(BrowserTeachingSession, reviewed.id)).reason_code == "teaching_disabled"
    await service.discard(_ctx(owner, organization), reviewed.id)
    await service.build_proposal(organization.id, reviewed.id, digest)
    assert await _proposals(db, reviewed.id) == []


async def test_an_applied_teaching_proposal_creates_the_skill_through_the_existing_flow(db, redis, enabled) -> None:
    from app.schemas.resource_usage import ProposalDecision
    from app.services.skill_proposal import SkillProposalService

    organization, owner, service, reviewed = await _reviewed(db, redis, enabled)
    await service.propose(_ctx(owner, organization), reviewed.id, TeachingPropose(name="download-invoice"), reviewed.revision)
    await service.build_proposal(organization.id, reviewed.id, (await db.get(BrowserTeachingSession, reviewed.id)).source_hash)
    (proposal,) = await _proposals(db, reviewed.id)
    applied = await SkillProposalService(db).apply(_ctx(owner, organization), proposal.id, ProposalDecision(revision=1))
    assert applied.status == "applied"
