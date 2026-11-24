"""Native PostgreSQL consent, privacy, tenant and one-winner continuation boundaries."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.browser_continuation import (
    BrowserContinuationObservation,
    BrowserContinuationReason,
    BrowserContinuationRefused,
    BrowserContinuationState,
)
from app.core.browser_fill import BrowserFillOperation
from app.core.browser_session import ProtectedSignIn, bounded_cookies
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.db.models.browser_credential_continuation import BrowserCredentialContinuation
from app.db.models.browser_sign_in import BrowserSignIn
from app.db.models.resource_grant import Visibility
from app.repositories import browser_credential_continuation as repo
from app.schemas.browser_credential import BrowserCredentialSubmission
from app.schemas.browser_credential_continuation import (
    BrowserCredentialContinuationConfirmation,
    BrowserCredentialContinuationRequest,
)
from app.services import browser_sign_in
from app.services.browser_credentials import BrowserCredentialContinuationService, _access
from app.services.browser_credentials._lease import BrowserWriterLease
from app.services.browser_credentials._saved_sessions import load_protected
from app.services.organization_secret import OrganizationSecretService
from tests.integration.test_browser_credential_plans import BrowserFixture
from tests.integration.test_browser_credential_plans import browser as browser
from tests.integration.test_personal_coding_accounts import context, organization, person
from tests.test_browser_credential_native import ORIGIN
from tests.test_browser_credentials import login
from tests.test_browser_session import PRIVATE, raw_cookie

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@dataclass
class ContinuationFixture:
    browser: BrowserFixture
    service: BrowserCredentialContinuationService
    submission_id: UUID
    fill_id: UUID

    async def request(self, request_id=None):
        b = self.browser
        return await self.service.request(
            b.ctx,
            b.run.id,
            self.submission_id,
            BrowserCredentialContinuationRequest(request_id=request_id or uuid4()),
        )

    async def prepared(self):
        b = self.browser
        requested = await self.request()
        pending = await self.service.pending(b.ctx, b.identity)
        assert pending is not None and pending.state == BrowserContinuationState.REQUESTED
        seen = BrowserContinuationObservation(document_id=uuid4(), origin=ORIGIN)
        await self.service.prepare(b.ctx, b.identity, requested.id, seen)
        return requested.id, seen

    def decision(self, seen, keep=False, approve=True):
        return BrowserCredentialContinuationConfirmation(
            document_id=seen.document_id,
            authorization_generation=self.browser.secret.authorization_generation,
            approve=approve,
            keep_signed_in=keep,
        )

    async def approved(self, keep=False):
        continuation_id, seen = await self.prepared()
        b = self.browser
        decision = self.decision(seen, keep)
        row = await self.service.confirm(
            b.ctx, b.run.id, self.submission_id, continuation_id, decision
        )
        assert row.state == BrowserContinuationState.APPROVED
        return continuation_id, seen, decision

    async def claimed(self, keep=False):
        continuation_id, seen, _ = await self.approved(keep)
        return await self.service.claim(
            self.browser.ctx, self.browser.identity, continuation_id, seen
        )

    def state(self, claim):
        cookie = raw_cookie(
            domain="portal.example.com", expires=claim.provenance.expires_at.timestamp()
        )
        # The fixture's actual canonical credential origin supplies cookie host identity.
        from urllib.parse import urlsplit

        cookie["domain"] = urlsplit(ORIGIN).hostname
        return ProtectedSignIn(
            provenance=claim.provenance, cookies=bounded_cookies(ORIGIN, [cookie], now=20)
        )


async def submitted(b: BrowserFixture, *, known=True) -> ContinuationFixture:
    fill = await b.claimed()
    await b.service.finish(b.identity, fill, filled=True)
    submission = await b.service.submit(
        b.ctx,
        b.run.id,
        fill.plan_id,
        BrowserCredentialSubmission(
            request_id=uuid4(),
            document_id=fill.observation.document_id,
            authorization_generation=fill.generation,
        ),
    )
    claim = await b.service.claim(
        b.ctx, b.identity, submission.id, fill.observation, output_protected=True
    )
    assert claim.operation == BrowserFillOperation.SUBMIT
    await b.service.finish(b.identity, claim, filled=known)
    return ContinuationFixture(
        b, BrowserCredentialContinuationService(b.db, b.redis), submission.id, fill.plan_id
    )


@pytest.fixture
async def continuation(browser):
    return await submitted(browser)


async def test_preparation_never_saves_and_confirmation_cannot_add_persistence_after_replay(
    continuation,
):
    f, b = continuation, continuation.browser
    assert await f.service.get(b.ctx, b.run.id, f.submission_id) is None
    continuation_id, seen, decision = await f.approved(keep=False)
    assert await b.db.scalar(select(func.count()).select_from(BrowserSignIn)) == 0
    repeated = await f.service.confirm(b.ctx, b.run.id, f.submission_id, continuation_id, decision)
    assert repeated.keep_signed_in is False
    for changed in (
        decision.model_copy(update={"keep_signed_in": True}),
        decision.model_copy(update={"approve": False}),
        decision.model_copy(update={"document_id": uuid4()}),
        decision.model_copy(update={"authorization_generation": uuid4()}),
    ):
        with pytest.raises(BrowserContinuationRefused) as caught:
            await f.service.confirm(b.ctx, b.run.id, f.submission_id, continuation_id, changed)
        assert caught.value.reason == BrowserContinuationReason.ALREADY_CONSUMED
    claim = await f.service.claim(b.ctx, b.identity, continuation_id, seen)
    await f.service.finish(b.ctx, b.identity, claim, f.state(claim))
    read = await f.service.get(b.ctx, b.run.id, f.submission_id)
    assert read.state == BrowserContinuationState.CONTINUED and read.saved_sign_in_id is None
    assert (
        read.continuation_call_id != read.source_call_id
        and read.continuation_tab_id != read.source_tab_id
    )
    assert read.output_protected is True and PRIVATE not in read.model_dump_json()
    assert await b.db.scalar(select(func.count()).select_from(BrowserSignIn)) == 0
    assert (await f.request(continuation_id)).state == BrowserContinuationState.CONTINUED
    with pytest.raises(BrowserContinuationRefused):
        await f.request()


async def test_explicit_saved_state_is_sealed_and_cannot_enter_legacy_loader(
    continuation, monkeypatch
):
    f, b = continuation, continuation.browser
    claim = await f.claimed(keep=True)
    state = f.state(claim)
    await f.service.finish(b.ctx, b.identity, claim, state)
    read = await f.service.get(b.ctx, b.run.id, f.submission_id)
    row = await b.db.get(BrowserSignIn, read.saved_sign_in_id)
    assert row.protection_kind == "credential" and PRIVATE not in row.sealed_state
    assert await load_protected(b.db, b.ctx, b.identity, ORIGIN) == state

    @asynccontextmanager
    async def session():
        yield b.db

    monkeypatch.setattr(browser_sign_in, "get_db_context", session)
    assert await browser_sign_in.load_for(b.org.id, b.owner.id) == []
    await browser_sign_in.BrowserSignInService(b.db).forget(b.ctx, row.id)
    assert await load_protected(b.db, b.ctx, b.identity, ORIGIN) is None
    assert (
        await f.service.get(b.ctx, b.run.id, f.submission_id)
    ).state == BrowserContinuationState.CONTINUED


@pytest.mark.parametrize("stage", ["prepare", "confirm", "claim", "effect", "finish", "restore"])
async def test_generation_revocation_is_rechecked_at_every_boundary(continuation, stage):
    f, b = continuation, continuation.browser
    if stage == "prepare":
        requested = await f.request()
        pending = await f.service.pending(b.ctx, b.identity)
        assert pending is not None
        seen = BrowserContinuationObservation(document_id=uuid4(), origin=ORIGIN)
        action = f.service.prepare(b.ctx, b.identity, requested.id, seen)
    elif stage == "confirm":
        continuation_id, seen = await f.prepared()
        decision = f.decision(seen)
        action = f.service.confirm(b.ctx, b.run.id, f.submission_id, continuation_id, decision)
    elif stage == "claim":
        continuation_id, seen, _ = await f.approved()
        action = f.service.claim(b.ctx, b.identity, continuation_id, seen)
    else:
        claim = await f.claimed(keep=True)
        state = f.state(claim)
        if stage == "restore":
            await f.service.finish(b.ctx, b.identity, claim, state)
            action = load_protected(b.db, b.ctx, b.identity, ORIGIN)
        elif stage == "effect":
            action = f.service.authorize_effect(b.ctx, b.identity, claim)
        else:
            action = f.service.finish(b.ctx, b.identity, claim, state)
    b.secret.authorization_generation = uuid4()
    await b.db.flush()
    with pytest.raises(BrowserContinuationRefused):
        await action
    if stage != "restore":
        assert await b.db.scalar(select(func.count()).select_from(BrowserSignIn)) == 0


async def test_unknown_submission_is_not_a_successful_source_and_cannot_authorize_export(browser):
    f = await submitted(browser, known=False)
    with pytest.raises(BrowserContinuationRefused) as caught:
        await f.request()
    assert caught.value.reason == BrowserContinuationReason.SOURCE_NOT_SUBMITTED
    assert (
        await browser.db.scalar(select(func.count()).select_from(BrowserCredentialContinuation))
        == 0
    )


async def test_lost_effect_acknowledgement_is_terminal_and_get_never_repeats_it(
    continuation, monkeypatch
):
    f, b = continuation, continuation.browser
    claim = await f.claimed(keep=True)
    await f.service.refuse(b.identity, claim.id, BrowserContinuationReason.PROVIDER_UNAVAILABLE)

    async def forbidden(*args, **kwargs):
        raise AssertionError("GET must not unwrap, export, save or reauthorize a native effect")

    monkeypatch.setattr(_access, "credential", forbidden)
    read = await f.service.get(b.ctx, b.run.id, f.submission_id)
    assert (
        read.state == BrowserContinuationState.UNKNOWN
        and read.reason_code == BrowserContinuationReason.UNCERTAIN_EFFECT
    )
    assert (await f.request(claim.id)).state == BrowserContinuationState.UNKNOWN
    with pytest.raises(BrowserContinuationRefused):
        await f.service.claim(b.ctx, b.identity, claim.id, claim.observation)
    assert await b.db.scalar(select(func.count()).select_from(BrowserSignIn)) == 0


@pytest.mark.parametrize("state", ["requested", "awaiting_confirmation", "claimed"])
@pytest.mark.parametrize("loss", ["deadline", "lease", "disabled"])
async def test_abandoned_work_expires_without_reviving_a_claimed_effect(
    continuation, monkeypatch, state, loss
):
    f, b = continuation, continuation.browser
    if state == "requested":
        continuation_id = (await f.request()).id
    elif state == "awaiting_confirmation":
        continuation_id, _ = await f.prepared()
    else:
        continuation_id = (await f.claimed()).id
    row = await repo.get(b.db, b.org.id, continuation_id)
    if loss == "deadline":
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await b.db.flush()
    elif loss == "lease":
        await b.lease.close()
    else:
        monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_FILL_ENABLED", False)
    read = await f.service.get(b.ctx, b.run.id, f.submission_id)
    assert read.state == (
        BrowserContinuationState.UNKNOWN if state == "claimed" else BrowserContinuationState.EXPIRED
    )
    assert (await f.request(continuation_id)).state == read.state


async def test_declining_is_an_exact_terminal_decision_and_does_not_keep_cookies(continuation):
    f, b = continuation, continuation.browser
    continuation_id, seen = await f.prepared()
    decision = f.decision(seen, keep=False, approve=False)
    read = await f.service.confirm(b.ctx, b.run.id, f.submission_id, continuation_id, decision)
    assert read.state == BrowserContinuationState.DECLINED
    assert (
        await f.service.confirm(b.ctx, b.run.id, f.submission_id, continuation_id, decision)
    ).state == read.state
    assert await f.service.pending(b.ctx, b.identity) is None
    assert await b.db.scalar(select(func.count()).select_from(BrowserSignIn)) == 0


async def test_owner_and_tenant_refusals_are_opaque(continuation):
    f, b = continuation, continuation.browser
    await f.request()
    other = await person(b.db)
    other_org = await organization(b.db, other)
    for wrong_ctx, wrong_run, wrong_source in (
        (context(other, other_org), b.run.id, f.submission_id),
        (b.ctx, uuid4(), f.submission_id),
        (b.ctx, b.run.id, uuid4()),
    ):
        with pytest.raises(NotFoundError):
            await f.service.get(wrong_ctx, wrong_run, wrong_source)


async def test_simultaneous_collectors_cannot_claim_or_open_two_contexts(continuation, engine):
    f, b = continuation, continuation.browser
    continuation_id, seen, _ = await f.approved()
    await b.db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def claim_once():
        async with sessions() as db:
            try:
                result = await BrowserCredentialContinuationService(db, b.redis).claim(
                    b.ctx, b.identity, continuation_id, seen
                )
                await db.commit()
                return result
            except BrowserContinuationRefused:
                await db.rollback()
                return None

    outcomes = await asyncio.gather(claim_once(), claim_once())
    assert sum(outcome is not None for outcome in outcomes) == 1
    stored = await repo.get(b.db, b.org.id, continuation_id, locked=True)
    assert stored.state == BrowserContinuationState.CLAIMED and stored.attempt_id is not None


async def add_unknown_contributor(b):
    earlier = await OrganizationSecretService(b.db).create(
        b.ctx,
        name="Earlier synthetic input",
        value=login(),
        usage_scope="personal",
        visibility=Visibility.PRIVATE,
    )
    spec = json.loads(json.dumps(b.version.spec))
    spec["capabilities"][0]["config"]["browser_credential_ids"].append(str(earlier.id))
    b.version.spec, b.agent.draft_spec = spec, spec
    await b.db.flush()
    await b.lease.close()
    b.identity = b.identity.model_copy(update={"credential_ids": (b.secret.id, earlier.id)})
    b.lease = BrowserWriterLease(b.redis, b.identity)
    await b.lease.acquire()
    await b.lease.observe(ORIGIN)
    final = b.secret
    b.secret = earlier
    claim = await b.claimed()
    await b.service.finish(b.identity, claim, filled=False)
    b.secret = final
    return earlier


@pytest.mark.parametrize("at", ["export", "restore"])
async def test_revoking_a_nonfinal_uncertain_contributor_blocks_the_derived_session(browser, at):
    earlier = await add_unknown_contributor(browser)
    try:
        f, b = await submitted(browser), browser
        claim = await f.claimed(keep=True)
        assert len(claim.provenance.credential_generations) == 2
        assert any(
            value.secret_id == earlier.id for value in claim.provenance.credential_generations
        )
        if at == "restore":
            await f.service.finish(b.ctx, b.identity, claim, f.state(claim))
        earlier.authorization_generation = uuid4()
        await b.db.flush()
        with pytest.raises(BrowserContinuationRefused):
            if at == "export":
                await f.service.authorize_effect(b.ctx, b.identity, claim)
            else:
                await load_protected(b.db, b.ctx, b.identity, ORIGIN)
    finally:
        await browser.lease.close()


async def test_native_tenant_keys_and_per_source_uniqueness_refuse_cross_scope_rows(continuation):
    f, b = continuation, continuation.browser
    requested = await f.request()
    row = await repo.get(b.db, b.org.id, requested.id)
    values = {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in ("created_at", "updated_at")
    }
    other_org = await organization(b.db, b.owner)
    for overrides in (
        {"id": uuid4(), "organization_id": other_org.id},
        {"id": uuid4(), "source_call_id": "another-view"},
        {
            "id": uuid4(),
            "source_submission_id": f.fill_id,
            "source_call_id": "other",
            "output_protected": False,
        },
    ):
        with pytest.raises(IntegrityError):
            async with b.db.begin_nested():
                b.db.add(BrowserCredentialContinuation(**(values | overrides)))
                await b.db.flush()
    assert await b.db.scalar(select(func.count()).select_from(BrowserCredentialContinuation)) == 1
