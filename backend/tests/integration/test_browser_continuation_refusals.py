"""Current human consent, source provenance and stale native claims fail closed in PostgreSQL."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.core.browser_continuation import (
    BrowserContinuationObservation,
    BrowserContinuationReason,
    BrowserContinuationRefused,
    BrowserContinuationState,
)
from app.core.browser_fill import BrowserFillState
from app.core.browser_session import CredentialGeneration
from app.core.exceptions import NotFoundError
from app.db.models.agent_run import ToolApproval
from app.db.models.browser_credential import BrowserCredentialPlan
from app.db.models.browser_sign_in import BrowserSignIn
from app.db.models.organization import OrganizationMember
from app.repositories import browser_credential_continuation as repo
from app.services.browser_credentials._lease import BrowserWriterLease
from tests.integration.test_browser_credential_continuations import (
    add_unknown_contributor,
    submitted,
)
from tests.integration.test_browser_credential_continuations import continuation as continuation
from tests.integration.test_browser_credential_plans import browser as browser
from tests.integration.test_personal_coding_accounts import person
from tests.test_browser_credential_native import ORIGIN

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_diagnostic_representation_excludes_document_and_private_source_metadata(
    continuation,
):
    f, b = continuation, continuation.browser
    operation, seen = await f.prepared()
    row = await repo.get(b.db, b.org.id, operation)
    rendered = repr(row)
    assert str(operation) in rendered and "awaiting_confirmation" in rendered
    assert seen.origin not in rendered and str(seen.document_id) not in rendered
    assert str(f.fill_id) not in rendered and str(b.secret.id) not in rendered


@pytest.mark.parametrize("changed", ["document_id", "authorization_generation"])
async def test_first_consent_refuses_a_replaced_document_or_generation(continuation, changed):
    f, b = continuation, continuation.browser
    operation, seen = await f.prepared()
    decision = f.decision(seen).model_copy(update={changed: uuid4()})
    with pytest.raises(BrowserContinuationRefused) as error:
        await f.service.confirm(b.ctx, b.run.id, f.submission_id, operation, decision)
    assert error.value.reason == BrowserContinuationReason.DOCUMENT_CHANGED
    row = await repo.get(b.db, b.org.id, operation)
    assert row.state == BrowserContinuationState.AWAITING_CONFIRMATION and row.confirmation is None
    assert await b.db.scalar(select(func.count()).select_from(BrowserSignIn)) == 0


@pytest.mark.parametrize("phase", ["requested", "expired"])
async def test_confirmation_cannot_promote_unprepared_or_expired_work(continuation, phase):
    f, b = continuation, continuation.browser
    if phase == "requested":
        operation = (await f.request()).id
        seen = BrowserContinuationObservation(document_id=uuid4(), origin=ORIGIN)
    else:
        operation, seen = await f.prepared()
        row = await repo.get(b.db, b.org.id, operation)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await b.db.flush()
    read = await f.service.confirm(b.ctx, b.run.id, f.submission_id, operation, f.decision(seen))
    assert read.state == (
        BrowserContinuationState.REQUESTED
        if phase == "requested"
        else BrowserContinuationState.EXPIRED
    )
    assert (await repo.get(b.db, b.org.id, operation)).confirmation is None


@pytest.mark.parametrize("phase", ["missing", "not_owned_for_preparation", "expired"])
async def test_native_preparation_requires_its_current_pending_transition(continuation, phase):
    f, b = continuation, continuation.browser
    operation = (await f.request()).id
    if phase == "missing":
        operation = uuid4()
    elif phase == "expired":
        await f.service.pending(b.ctx, b.identity)
        row = await repo.get(b.db, b.org.id, operation)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await b.db.flush()
    with pytest.raises(BrowserContinuationRefused):
        await f.service.prepare(
            b.ctx,
            b.identity,
            operation,
            BrowserContinuationObservation(document_id=uuid4(), origin=ORIGIN),
        )
    assert await b.db.scalar(select(func.count()).select_from(BrowserSignIn)) == 0


async def test_canonical_queue_item_names_exact_source_and_cannot_substitute_for_consent(
    continuation,
):
    f, b = continuation, continuation.browser
    operation, seen = await f.prepared()
    approval = await b.db.get(ToolApproval, operation)
    assert approval.tool_args == {
        "continuation_id": str(operation),
        "source_submission_id": str(f.submission_id),
    }
    with pytest.raises(BrowserContinuationRefused):
        await f.service.claim(b.ctx, b.identity, operation, seen)


@pytest.mark.parametrize(
    "field",
    ["tool_id", "capability_tool_id", "source_submission_id", "always_asks", "decided_by_user_id"],
)
async def test_native_claim_refuses_mismatched_canonical_approval_authority(continuation, field):
    f, b = continuation, continuation.browser
    operation, seen, _ = await f.approved()
    approval = await b.db.get(ToolApproval, operation)
    if field == "source_submission_id":
        approval.tool_args = {
            "continuation_id": str(operation),
            "source_submission_id": str(uuid4()),
        }
    elif field == "always_asks":
        approval.always_asks = False
    elif field == "decided_by_user_id":
        approval.decided_by_user_id = (await person(b.db)).id
    else:
        setattr(approval, field, "unrelated_tool")
    await b.db.flush()
    with pytest.raises(BrowserContinuationRefused) as error:
        await f.service.claim(b.ctx, b.identity, operation, seen)
    assert error.value.reason == BrowserContinuationReason.CONFIRMATION_REQUIRED
    assert (await repo.get(b.db, b.org.id, operation)).attempt_id is None


@pytest.mark.parametrize("phase", ["missing", "different_document"])
async def test_claim_cannot_address_a_missing_or_replaced_observation(continuation, phase):
    f, b = continuation, continuation.browser
    operation, seen, _ = await f.approved()
    if phase == "missing":
        operation = uuid4()
    else:
        seen = seen.model_copy(update={"document_id": uuid4()})
    with pytest.raises(BrowserContinuationRefused):
        await f.service.claim(b.ctx, b.identity, operation, seen)


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "attempt_id",
        "call_id",
        "tab_id",
        "observation",
        "generation",
        "secret",
        "contributors",
        "expired",
        "terminal",
    ],
)
async def test_stale_or_forged_native_effect_identity_never_publishes_or_saves(continuation, field):
    f, b = continuation, continuation.browser
    claim = await f.claimed(keep=True)
    row = await repo.get(b.db, b.org.id, claim.id)
    if field in ("id", "attempt_id"):
        claim = replace(claim, **{field: uuid4()})
    elif field in ("call_id", "tab_id"):
        claim = replace(claim, **{field: str(uuid4())})
    elif field == "observation":
        claim = replace(
            claim, observation=claim.observation.model_copy(update={"document_id": uuid4()})
        )
    elif field in ("generation", "secret"):
        key = "authorization_generation" if field == "generation" else "secret_id"
        claim = replace(claim, provenance=claim.provenance.model_copy(update={key: uuid4()}))
    elif field == "contributors":
        claim = replace(
            claim, provenance=claim.provenance.model_copy(update={"credential_generations": ()})
        )
    elif field == "expired":
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await b.db.flush()
    else:
        await f.service.refuse(b.identity, claim.id, BrowserContinuationReason.PROVIDER_UNAVAILABLE)
    with pytest.raises(BrowserContinuationRefused) as error:
        await f.service.authorize_effect(b.ctx, b.identity, claim)
    assert error.value.reason == BrowserContinuationReason.ALREADY_CONSUMED
    assert await b.db.scalar(select(func.count()).select_from(BrowserSignIn)) == 0


@pytest.mark.parametrize("changed", ["approve", "keep_signed_in"])
async def test_claim_cannot_broaden_the_persisted_decision_after_admission(continuation, changed):
    f, b = continuation, continuation.browser
    claim = await f.claimed(keep=True)
    row = await repo.get(b.db, b.org.id, claim.id)
    row.confirmation = row.confirmation | {changed: False}
    await b.db.flush()
    with pytest.raises(BrowserContinuationRefused) as error:
        await f.service.authorize_effect(b.ctx, b.identity, claim)
    assert error.value.reason == BrowserContinuationReason.CONFIRMATION_REQUIRED


async def test_final_publication_refuses_mismatched_sealed_provenance(continuation):
    f, b = continuation, continuation.browser
    claim = await f.claimed(keep=True)
    state = f.state(claim).model_copy(
        update={"provenance": claim.provenance.model_copy(update={"agent_id": uuid4()})}
    )
    with pytest.raises(BrowserContinuationRefused) as error:
        await f.service.finish(b.ctx, b.identity, claim, state)
    assert error.value.reason == BrowserContinuationReason.STATE_REFUSED
    assert await b.db.scalar(select(func.count()).select_from(BrowserSignIn)) == 0


@pytest.mark.parametrize("phase", ["missing", "wrong_owner", "terminal"])
async def test_refusal_cannot_modify_unrelated_or_completed_receipts(continuation, phase):
    f, b = continuation, continuation.browser
    claim = await f.claimed()
    if phase == "terminal":
        await f.service.finish(b.ctx, b.identity, claim, f.state(claim))
    row = await repo.get(b.db, b.org.id, claim.id)
    before = (row.state, row.reason_code, row.attempt_id)
    identity = (
        b.identity.model_copy(update={"controller_id": uuid4()})
        if phase == "wrong_owner"
        else b.identity
    )
    await f.service.refuse(
        identity,
        uuid4() if phase == "missing" else claim.id,
        BrowserContinuationReason.DOCUMENT_CHANGED,
    )
    row = await repo.get(b.db, b.org.id, claim.id, locked=True)
    assert (row.state, row.reason_code, row.attempt_id) == before


@pytest.mark.parametrize("cause", ["too_old", "missing_completion", "lease_lost"])
async def test_new_preparation_requires_recent_known_submit_and_current_native_owner(
    continuation, cause
):
    f, b = continuation, continuation.browser
    source = await b.db.get(BrowserCredentialPlan, f.submission_id)
    if cause == "lease_lost":
        await b.lease.close()
    else:
        source.finished_at = (
            None if cause == "missing_completion" else datetime.now(UTC) - timedelta(seconds=121)
        )
        await b.db.flush()
    with pytest.raises(BrowserContinuationRefused):
        await f.request()


async def test_membership_revocation_is_checked_before_reading_old_source_receipts(continuation):
    f, b = continuation, continuation.browser
    await f.request()
    await b.db.execute(
        delete(OrganizationMember).where(
            OrganizationMember.organization_id == b.org.id, OrganizationMember.user_id == b.owner.id
        )
    )
    with pytest.raises(BrowserContinuationRefused):
        await f.service.get(b.ctx, b.run.id, f.submission_id)


async def test_source_fill_must_remain_a_known_successful_parent(continuation):
    f, b = continuation, continuation.browser
    parent = await b.db.get(BrowserCredentialPlan, f.fill_id)
    parent.state = BrowserFillState.UNKNOWN
    await b.db.flush()
    with pytest.raises(BrowserContinuationRefused) as error:
        await f.request()
    assert error.value.reason == BrowserContinuationReason.SOURCE_NOT_SUBMITTED


async def test_owner_receipt_lookup_refuses_a_mismatched_source_pin(continuation):
    f, b = continuation, continuation.browser
    requested = await f.request()
    row = await repo.get(b.db, b.org.id, requested.id)
    row.authorization_generation = uuid4()
    await b.db.flush()
    with pytest.raises(NotFoundError):
        await f.service.get(b.ctx, b.run.id, f.submission_id)


async def test_destination_cannot_follow_a_redirect_even_to_a_valid_https_origin(continuation):
    f, b = continuation, continuation.browser
    requested = await f.request()
    await f.service.pending(b.ctx, b.identity)
    with pytest.raises(BrowserContinuationRefused) as error:
        await f.service.prepare(
            b.ctx,
            b.identity,
            requested.id,
            BrowserContinuationObservation(
                document_id=uuid4(), origin="https://another.example.test"
            ),
        )
    assert error.value.reason == BrowserContinuationReason.DESTINATION_REFUSED


async def test_pending_authority_loss_creates_a_fixed_terminal_refusal(continuation):
    f, b = continuation, continuation.browser
    requested = await f.request()
    b.secret.authorization_generation = uuid4()
    await b.db.flush()
    assert await f.service.pending(b.ctx, b.identity) is None
    row = await repo.get(b.db, b.org.id, requested.id)
    assert (
        row.state == BrowserContinuationState.REFUSED
        and row.reason_code == BrowserContinuationReason.AUTHORITY_CHANGED
    )


async def test_a_preparation_id_cannot_be_reused_for_another_completed_submit(continuation):
    f, b = continuation, continuation.browser
    claim = await f.claimed()
    await f.service.finish(b.ctx, b.identity, claim, f.state(claim))
    second = await submitted(b)
    with pytest.raises(BrowserContinuationRefused) as refused:
        await second.request(claim.id)
    assert refused.value.reason == BrowserContinuationReason.ALREADY_CONSUMED
    assert await repo.for_submission(b.db, b.org.id, second.submission_id) is None


async def test_preparation_cannot_race_a_new_pending_fill_in_the_same_view(continuation):
    f, b = continuation, continuation.browser
    await b.service.request(b.ctx, b.run.id, b.request())
    with pytest.raises(BrowserContinuationRefused) as refused:
        await f.request()
    assert refused.value.reason == BrowserContinuationReason.ALREADY_CONSUMED
    assert await repo.for_submission(b.db, b.org.id, f.submission_id) is None


@pytest.mark.parametrize("expired", [False, True])
async def test_distinct_completed_submits_cannot_create_two_live_continuations(
    continuation, expired
):
    first, b = continuation, continuation.browser
    second = await submitted(b)
    first_id = (await first.request()).id
    old = await repo.get(b.db, b.org.id, first_id)
    if expired:
        old.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await b.db.flush()
        new = await second.request()
        assert new.id != first_id and new.state == BrowserContinuationState.REQUESTED
        assert old.state == BrowserContinuationState.EXPIRED
    else:
        with pytest.raises(BrowserContinuationRefused) as refused:
            await second.request()
        assert refused.value.reason == BrowserContinuationReason.ALREADY_CONSUMED
        assert await repo.for_submission(b.db, b.org.id, second.submission_id) is None


async def test_confirmation_of_an_unknown_continuation_is_opaque_even_for_a_valid_source(
    continuation,
):
    f, b = continuation, continuation.browser
    _, seen = await f.prepared()
    with pytest.raises(NotFoundError):
        await f.service.confirm(b.ctx, b.run.id, f.submission_id, uuid4(), f.decision(seen))


async def test_pending_keeps_its_existing_preparation_and_drops_expired_work_without_claim(
    continuation,
):
    f, b = continuation, continuation.browser
    operation = (await f.request()).id
    first = await f.service.pending(b.ctx, b.identity)
    second = await f.service.pending(b.ctx, b.identity)
    assert first.state == BrowserContinuationState.REQUESTED
    assert second.state == BrowserContinuationState.PREPARING
    row = await repo.get(b.db, b.org.id, operation)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await b.db.flush()
    assert await f.service.pending(b.ctx, b.identity) is None
    assert row.state == BrowserContinuationState.EXPIRED and row.attempt_id is None


async def test_a_replaced_source_pin_cannot_prepare_the_current_document(continuation):
    f, b = continuation, continuation.browser
    operation = (await f.request()).id
    await f.service.pending(b.ctx, b.identity)
    row = await repo.get(b.db, b.org.id, operation)
    row.authorization_generation = uuid4()
    await b.db.flush()
    with pytest.raises(BrowserContinuationRefused) as refused:
        await f.service.prepare(
            b.ctx,
            b.identity,
            operation,
            BrowserContinuationObservation(document_id=uuid4(), origin=ORIGIN),
        )
    assert refused.value.reason == BrowserContinuationReason.SOURCE_NOT_SUBMITTED
    assert row.observation is None


@pytest.mark.parametrize("change", ["writer", "contributors"])
async def test_a_stale_writer_or_changed_taint_set_cannot_advance_preparation(continuation, change):
    f, b = continuation, continuation.browser
    operation = (await f.request()).id
    identity = b.identity.model_copy(
        update={"controller_id": uuid4()}
        if change == "writer"
        else {
            "inherited_credentials": (
                CredentialGeneration(secret_id=uuid4(), authorization_generation=uuid4()),
            )
        }
    )
    assert await f.service.pending(b.ctx, identity) is None
    row = await repo.get(b.db, b.org.id, operation)
    assert row.attempt_id is None and row.observation is None
    assert row.state == (
        BrowserContinuationState.REQUESTED
        if change == "writer"
        else BrowserContinuationState.REFUSED
    )


@pytest.mark.parametrize("changed", ["lease_lost", "different_writer"])
async def test_a_claim_cannot_export_after_losing_its_exact_live_identity(continuation, changed):
    f, b = continuation, continuation.browser
    claim = await f.claimed()
    if changed == "lease_lost":
        await b.lease.close()
        identity = b.identity
    else:
        identity = b.identity.model_copy(update={"controller_id": uuid4()})
    with pytest.raises(BrowserContinuationRefused) as refused:
        await f.service.authorize_effect(b.ctx, identity, claim)
    assert refused.value.reason == BrowserContinuationReason.OWNERSHIP_LOST


async def test_removing_a_nonfinal_credential_binding_refuses_all_derived_state(browser):
    b = browser
    await add_unknown_contributor(b)
    try:
        f = await submitted(b)
        spec = json.loads(json.dumps(b.version.spec))
        spec["capabilities"][0]["config"]["browser_credential_ids"] = [str(b.secret.id)]
        b.version.spec, b.agent.draft_spec = spec, spec
        await b.db.flush()
        await b.lease.close()
        b.identity = b.identity.model_copy(update={"credential_ids": (b.secret.id,)})
        b.lease = BrowserWriterLease(b.redis, b.identity)
        await b.lease.acquire()
        await b.lease.observe(ORIGIN)
        with pytest.raises(BrowserContinuationRefused) as refused:
            await f.request()
        assert refused.value.reason == BrowserContinuationReason.AUTHORITY_CHANGED
        assert await repo.for_submission(b.db, b.org.id, f.submission_id) is None
    finally:
        await b.lease.close()
