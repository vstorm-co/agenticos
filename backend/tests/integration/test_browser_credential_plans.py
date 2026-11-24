"""Real durable plans: private ownership, human decisions and exactly one native attempt."""

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.browser_fill import (
    BrowserFillHandle,
    BrowserFillObservation,
    BrowserFillOperation,
    BrowserFillReason,
    BrowserFillRefused,
    BrowserFillState,
)
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, RunSurface, ToolApproval
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.browser_credential import BrowserCredentialPlan
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import browser_credential as repo
from app.schemas.browser_credential import (
    BrowserCredentialConfirmation,
    BrowserCredentialRequest,
    BrowserCredentialSubmission,
)
from app.services.approvals import ApprovalService
from app.services.browser_credentials._lease import BrowserWriterLease, LiveBrowserIdentity
from app.services.browser_credentials._plans import (
    PLAN_SECONDS,
    AuthorizedFill,
    BrowserCredentialPlanService,
    _owned_by,
)
from app.services.organization_secret import OrganizationSecretService
from tests.integration.test_personal_coding_accounts import context, organization, person
from tests.test_browser_credential_lease import MemoryRedis
from tests.test_browser_credential_native import ORIGIN, selection
from tests.test_browser_credentials import PASSWORD, SEED, USERNAME, login

pytestmark = [pytest.mark.anyio, pytest.mark.security]
ENDPOINT = "http://provisioned-browser:9222"


@dataclass
class BrowserFixture:
    db: AsyncSession
    owner: User
    org: Organization
    ctx: AuthContext
    agent: Agent
    version: AgentVersion
    conversation: Conversation
    run: AgentRun
    secret: OrganizationSecret
    identity: LiveBrowserIdentity
    redis: MemoryRedis
    lease: BrowserWriterLease
    service: BrowserCredentialPlanService

    def request(self, *fields: str) -> BrowserCredentialRequest:
        return BrowserCredentialRequest(
            request_id=uuid4(),
            secret_id=self.secret.id,
            authorization_generation=self.secret.authorization_generation,
            call_id=self.identity.call_id,
            tab_id=self.identity.tab_id,
            fields=selection(*(fields or ("username", "password"))).fields,
        )

    async def prepared(self, *fields: str) -> tuple[UUID, BrowserFillObservation]:
        request = self.request(*fields)
        await self.service.request(self.ctx, self.run.id, request)
        pending = await self.service.pending(self.ctx, self.identity)
        assert pending is not None and pending.state == BrowserFillState.REQUESTED
        observed = BrowserFillObservation(
            document_id=uuid4(),
            origin=ORIGIN,
            fields=tuple(
                BrowserFillHandle(
                    field=item.field,
                    handle=uuid4(),
                    role="password" if item.field == "password" else "text",
                    form_origin=ORIGIN,
                )
                for item in request.fields
            ),
        )
        plan = await self.service.prepare(self.ctx, self.identity, request.request_id, observed)
        assert plan.state == BrowserFillState.AWAITING_CONFIRMATION
        return plan.id, observed

    def confirmation(self, observed: BrowserFillObservation, approve: bool = True):
        return BrowserCredentialConfirmation(
            document_id=observed.document_id,
            authorization_generation=self.secret.authorization_generation,
            approve=approve,
        )

    async def approved(self) -> tuple[UUID, BrowserFillObservation]:
        plan_id, observed = await self.prepared()
        plan = await self.service.confirm(
            self.ctx,
            self.run.id,
            plan_id,
            self.confirmation(observed),
        )
        assert plan.state == BrowserFillState.APPROVED
        return plan_id, observed

    async def claimed(self) -> AuthorizedFill:
        plan_id, observed = await self.approved()
        return await self.service.claim(
            self.ctx,
            self.identity,
            plan_id,
            observed,
            output_protected=True,
        )


@pytest.fixture
async def browser(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[BrowserFixture]:
    owner = await person(db)
    org = await organization(db, owner)
    ctx = context(owner, org)
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", ENDPOINT)
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_FILL_ENABLED", True)
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_ORGANIZATION_IDS", [org.id])
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_USER_IDS", [])
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_TOTP_ENABLED", True)
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_PROFILE_ENABLED", True)
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_SHARED_ENABLED", True)
    secret = await OrganizationSecretService(db).create(
        ctx,
        name="Synthetic portal credential",
        value=login(),
        usage_scope="personal",
        visibility=Visibility.PRIVATE,
    )
    spec = AgentSpec.model_validate(
        {
            "name": "Synthetic browser agent",
            "capabilities": [
                {
                    "id": "browser_use",
                    "config": {
                        "connection": "built_in",
                        "cdp_url": ENDPOINT,
                        "browser_credential_ids": [str(secret.id)],
                    },
                }
            ],
        }
    ).model_dump(mode="json")
    agent = Agent(
        organization_id=org.id,
        owner_user_id=owner.id,
        name="Synthetic browser agent",
        slug=uuid4().hex,
        draft_spec=spec,
    )
    chat = Conversation(organization_id=org.id, user_id=owner.id, title="Private browser task")
    db.add_all([agent, chat])
    await db.flush()
    version = AgentVersion(organization_id=org.id, agent_id=agent.id, version=1, spec=spec)
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    run = AgentRun(
        organization_id=org.id,
        user_id=owner.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        conversation_id=chat.id,
        status=RunStatus.RUNNING.value,
        surface=RunSurface.WEB.value,
    )
    db.add(run)
    await db.flush()
    identity = LiveBrowserIdentity(
        organization_id=org.id,
        run_id=run.id,
        agent_id=agent.id,
        user_id=owner.id,
        controller_id=uuid4(),
        call_id="browser-call",
        tab_id="main",
        credential_ids=(secret.id,),
    )
    redis = MemoryRedis()
    lease = BrowserWriterLease(redis, identity)
    await lease.acquire()
    await lease.observe(ORIGIN)
    try:
        yield BrowserFixture(
            db,
            owner,
            org,
            ctx,
            agent,
            version,
            chat,
            run,
            secret,
            identity,
            redis,
            lease,
            BrowserCredentialPlanService(db, redis),
        )
    finally:
        await lease.close()


async def test_owner_confirmation_claim_and_separate_submit_are_durable_single_attempts(
    browser: BrowserFixture,
) -> None:
    b = browser
    assert [
        item.id for item in await b.service.eligible(b.ctx, b.run.id, "browser-call", "main")
    ] == [b.secret.id]
    request = b.request()
    first = await b.service.request(b.ctx, b.run.id, request)
    assert await b.service.request(b.ctx, b.run.id, request) == first
    assert await b.service.submitted(b.ctx, b.run.id, first.id) is None
    with pytest.raises(ConflictError):
        await b.service.request(b.ctx, b.run.id, b.request())
    pending = await b.service.pending(b.ctx, b.identity)
    assert pending.state == BrowserFillState.REQUESTED
    assert (await b.service.pending(b.ctx, b.identity)).state == BrowserFillState.PREPARING
    observed = BrowserFillObservation(
        document_id=uuid4(),
        origin=ORIGIN,
        fields=tuple(
            BrowserFillHandle(field=item.field, handle=uuid4(), role="text", form_origin=ORIGIN)
            for item in request.fields
        ),
    )
    prepared = await b.service.prepare(b.ctx, b.identity, first.id, observed)
    assert prepared.origin == ORIGIN and prepared.fields == ["username", "password"]
    approval = await b.db.get(ToolApproval, first.id)
    assert approval.always_asks and approval.status == ApprovalStatus.PENDING
    assert approval.tool_args == {"plan_id": str(first.id)}
    assert ORIGIN not in json.dumps(approval.context)
    assert (
        await b.service.pending(b.ctx, b.identity)
    ).state == BrowserFillState.AWAITING_CONFIRMATION
    confirmed = await b.service.confirm(b.ctx, b.run.id, first.id, b.confirmation(observed))
    assert confirmed.state == BrowserFillState.APPROVED and not confirmed.output_protected
    assert await b.service.confirm(b.ctx, b.run.id, first.id, b.confirmation(observed)) == confirmed
    with pytest.raises(BrowserFillRefused):
        await b.service.claim(b.ctx, b.identity, first.id, observed, output_protected=False)
    claim = await b.service.claim(b.ctx, b.identity, first.id, observed, output_protected=True)
    assert claim.value == login()
    await b.service.authorize_effect(b.ctx, b.identity, claim)
    with pytest.raises(BrowserFillRefused):
        await b.service.claim(b.ctx, b.identity, first.id, observed, output_protected=True)
    await b.service.finish(b.identity, claim, filled=True)
    finished = await b.service.get(b.ctx, b.run.id, first.id)
    assert finished.state == BrowserFillState.FILLED and finished.output_protected
    persisted = await repo.plan(b.db, b.org.id, first.id)
    assert finished.submission_expires_at == persisted.finished_at + timedelta(seconds=PLAN_SECONDS)
    assert confirmed.submission_expires_at is None
    assert await b.service.submitted(b.ctx, b.run.id, first.id) is None
    count = await b.db.scalar(select(func.count()).select_from(AppAdminAuditLog))
    await b.service.finish(b.identity, claim, filled=False)
    assert await b.db.scalar(select(func.count()).select_from(AppAdminAuditLog)) == count
    assert await b.service.get(b.ctx, b.run.id, first.id) == finished
    assert await b.service.pending(b.ctx, b.identity) is None

    submission = BrowserCredentialSubmission(
        request_id=uuid4(),
        document_id=observed.document_id,
        authorization_generation=b.secret.authorization_generation,
    )
    submit = await b.service.submit(b.ctx, b.run.id, first.id, submission)
    assert submit.operation == BrowserFillOperation.SUBMIT and submit.parent_plan_id == first.id
    assert await b.service.submit(b.ctx, b.run.id, first.id, submission) == submit
    with pytest.raises(BrowserFillRefused):
        await b.service.submit(
            b.ctx, b.run.id, first.id, submission.model_copy(update={"request_id": uuid4()})
        )
    assert (await b.service.submitted(b.ctx, b.run.id, first.id)).id == submit.id
    submit_claim = await b.service.claim(
        b.ctx, b.identity, submit.id, observed, output_protected=True
    )
    assert submit_claim.value is None
    await b.service.authorize_effect(b.ctx, b.identity, submit_claim)
    await b.service.finish(b.identity, submit_claim, filled=True)
    assert (await b.service.get(b.ctx, b.run.id, submit.id)).state == BrowserFillState.SUBMITTED
    recovered = await b.service.submitted(b.ctx, b.run.id, first.id)
    assert recovered.id == submit.id and recovered.state == BrowserFillState.SUBMITTED
    assert recovered.submission_expires_at is None
    assert await b.service.submit(b.ctx, b.run.id, first.id, submission) == recovered
    with pytest.raises(BrowserFillRefused):
        await b.service.submit(
            b.ctx, b.run.id, first.id, submission.model_copy(update={"request_id": uuid4()})
        )
    with pytest.raises((NotFoundError, BrowserFillRefused)):
        await b.service.submitted(
            AuthContext(user_id=uuid4(), organization_id=b.org.id, role="member"),
            b.run.id,
            first.id,
        )
    assert len(await repo.list_for_run(b.db, b.org.id, b.run.id, b.owner.id)) == 2
    audit = list(await b.db.scalars(select(AppAdminAuditLog.details)))
    plans = list(await b.db.scalars(select(BrowserCredentialPlan)))
    outward = (
        json.dumps(audit, default=str)
        + repr(claim)
        + json.dumps(
            [{"selection": row.selection, "observation": row.observation} for row in plans]
        )
        + finished.model_dump_json()
    )
    assert not any(value in outward for value in (PASSWORD, USERNAME, SEED))


@pytest.mark.parametrize("stage", ["requested", "awaiting", "claimed"])
async def test_expiry_and_lost_lease_are_terminal_and_never_revive_a_claim(
    browser: BrowserFixture,
    stage: str,
) -> None:
    b = browser
    claim = None
    if stage == "claimed":
        claim = await b.claimed()
        plan_id = claim.plan_id
    elif stage == "awaiting":
        plan_id, _ = await b.prepared()
    else:
        plan_id = (await b.service.request(b.ctx, b.run.id, b.request())).id
    row = await repo.plan(b.db, b.org.id, plan_id)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await b.db.flush()
    result = await b.service.get(b.ctx, b.run.id, plan_id)
    assert result.state == (BrowserFillState.UNKNOWN if claim else BrowserFillState.EXPIRED)
    if claim:
        await b.service.finish(b.identity, claim, filled=True)
        assert (await b.service.get(b.ctx, b.run.id, plan_id)).state == BrowserFillState.UNKNOWN
    else:
        assert await b.service.pending(b.ctx, b.identity) is None
    approval = await b.db.get(ToolApproval, plan_id)
    if approval is not None and not claim:
        assert approval.status == ApprovalStatus.EXPIRED


@pytest.mark.parametrize("change", ["controller_id", "tab_id", "agent_id", "credential_ids"])
async def test_discovered_replacement_controller_expires_old_plan(
    browser: BrowserFixture,
    change: str,
) -> None:
    b = browser
    plan_id, _ = await b.prepared()
    value = (
        (uuid4(),)
        if change == "credential_ids"
        else ("other-tab" if change == "tab_id" else uuid4())
    )
    replacement = b.identity.model_copy(update={change: value})
    b.redis.values[b.lease._key] = replacement.model_dump_json()
    assert (await b.service.get(b.ctx, b.run.id, plan_id)).state == BrowserFillState.EXPIRED


@pytest.mark.parametrize("change", ["document_id", "authorization_generation"])
async def test_stale_confirmation_is_refused_and_expires_the_pending_approval(
    browser: BrowserFixture,
    change: str,
) -> None:
    b = browser
    plan_id, observed = await b.prepared()
    result = await b.service.confirm(
        b.ctx, b.run.id, plan_id, b.confirmation(observed).model_copy(update={change: uuid4()})
    )
    assert result.state == BrowserFillState.REFUSED
    assert result.reason_code == BrowserFillReason.AUTHORITY_CHANGED
    assert (await b.db.get(ToolApproval, plan_id)).status == ApprovalStatus.EXPIRED


async def test_decline_is_a_real_human_decision_and_generic_approval_cannot_fill(
    browser: BrowserFixture,
) -> None:
    b = browser
    plan_id, observed = await b.prepared()
    declined = await b.service.confirm(b.ctx, b.run.id, plan_id, b.confirmation(observed, False))
    assert declined.state == BrowserFillState.DECLINED
    assert (await b.db.get(ToolApproval, plan_id)).status == ApprovalStatus.REJECTED
    next_id, next_observed = await b.prepared()
    await ApprovalService(b.db).decide(b.ctx, next_id, approved=True)
    assert await b.service.pending(b.ctx, b.identity) is None
    assert (await b.service.get(b.ctx, b.run.id, next_id)).state == BrowserFillState.REFUSED
    with pytest.raises(BrowserFillRefused):
        await b.service.claim(b.ctx, b.identity, next_id, next_observed, output_protected=True)


async def test_other_owner_or_organization_cannot_read_confirm_or_select(
    browser: BrowserFixture,
) -> None:
    b = browser
    plan_id, observed = await b.prepared()
    other = await person(b.db)
    b.db.add(OrganizationMember(organization_id=b.org.id, user_id=other.id, role="owner"))
    elsewhere = await organization(b.db, b.owner)
    await b.db.flush()
    for ctx in (context(other, b.org), context(b.owner, elsewhere)):
        with pytest.raises(NotFoundError):
            await b.service.get(ctx, b.run.id, plan_id)
        with pytest.raises(NotFoundError):
            await b.service.confirm(ctx, b.run.id, plan_id, b.confirmation(observed))
        with pytest.raises(BrowserFillRefused):
            await b.service.eligible(ctx, b.run.id, "browser-call", "main")
        with pytest.raises(BrowserFillRefused):
            await b.service.request(ctx, b.run.id, b.request())


async def test_rotation_revokes_approved_authority_and_does_not_make_a_new_attempt(
    browser: BrowserFixture,
) -> None:
    b = browser
    claim = await b.claimed()
    previous = b.secret.authorization_generation
    await OrganizationSecretService(b.db).update(b.ctx, b.secret.id, value=login(totp=False))
    assert b.secret.authorization_generation != previous
    with pytest.raises(BrowserFillRefused):
        await b.service.authorize_effect(b.ctx, b.identity, claim)
    await b.service.refuse(
        b.identity, claim.plan_id, BrowserFillReason.AUTHORITY_CHANGED, output_protected=True
    )
    result = await b.service.get(b.ctx, b.run.id, claim.plan_id)
    assert result.state == BrowserFillState.UNKNOWN and result.output_protected


@pytest.mark.parametrize(
    "field",
    [
        "organization_id",
        "run_id",
        "agent_id",
        "user_id",
        "controller_id",
        "call_id",
        "tab_id",
        "credential_ids",
    ],
)
async def test_full_native_identity_is_required_even_if_the_controller_nonce_matches(
    browser: BrowserFixture,
    field: str,
) -> None:
    b = browser
    plan_id, observed = await b.approved()
    row = await repo.plan(b.db, b.org.id, plan_id)
    changed = (
        (uuid4(),)
        if field == "credential_ids"
        else ("different" if field in {"call_id", "tab_id"} else uuid4())
    )
    identity = b.identity.model_copy(update={field: changed})
    assert _owned_by(row, b.identity) and not _owned_by(row, identity)
    # Fixed receipts cannot let a stale controller alter this owner's plan.
    await b.service.refuse(identity, plan_id, BrowserFillReason.OWNERSHIP_LOST)
    assert (await b.service.get(b.ctx, b.run.id, plan_id)).state == BrowserFillState.APPROVED


async def test_eligible_metadata_requires_current_live_origin_and_readable_bound_credential(
    browser,
):
    b = browser
    with pytest.raises(BrowserFillRefused):
        await b.service.live(b.ctx, b.run.id, "missing-call", "main")
    with pytest.raises(BrowserFillRefused):
        await b.service.live(b.ctx, b.run.id, "browser-call", "another-tab")
    b.redis.values.pop(b.lease._key + ":origin")
    assert await b.service.eligible(b.ctx, b.run.id, "browser-call", "main") == []
    await b.lease.observe("https://different.example.test")
    assert await b.service.eligible(b.ctx, b.run.id, "browser-call", "main") == []
    await b.lease.observe(ORIGIN)
    b.secret.sealed_secret = "not-an-envelope"
    await b.db.flush()
    assert await b.service.eligible(b.ctx, b.run.id, "browser-call", "main") == []
    b.secret.kind = "api_key"
    await b.db.flush()
    assert await b.service.eligible(b.ctx, b.run.id, "browser-call", "main") == []


async def test_request_rejects_unbound_fields_disabled_totp_and_id_reuse_but_replaces_expired_plan(
    browser, monkeypatch
):
    b = browser
    with pytest.raises(BrowserFillRefused):
        await b.service.request(
            b.ctx, b.run.id, b.request().model_copy(update={"secret_id": uuid4()})
        )
    with pytest.raises(BrowserFillRefused):
        await b.service.request(b.ctx, b.run.id, b.request("country"))
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_TOTP_ENABLED", False)
    with pytest.raises(BrowserFillRefused):
        await b.service.request(b.ctx, b.run.id, b.request("totp"))
    request = b.request("password")
    first = await b.service.request(b.ctx, b.run.id, request)
    with pytest.raises(NotFoundError):
        await b.service.request(
            b.ctx, b.run.id, request.model_copy(update={"fields": selection("username").fields})
        )
    row = await repo.plan(b.db, b.org.id, first.id)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await b.db.flush()
    second = await b.service.request(b.ctx, b.run.id, b.request("password"))
    assert second.id != first.id and row.state == BrowserFillState.EXPIRED
    row2 = await repo.plan(b.db, b.org.id, second.id)
    row2.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await b.db.flush()
    assert await b.service.pending(b.ctx, b.identity) is None


@pytest.mark.parametrize("fault", ["missing", "wrong_state", "wrong_origin", "wrong_fields"])
async def test_native_preparation_cannot_replace_stale_or_unbound_observations(browser, fault):
    b = browser
    request = b.request("password")
    await b.service.request(b.ctx, b.run.id, request)
    if fault != "wrong_state":
        await b.service.pending(b.ctx, b.identity)
    origin = "https://different.example.test" if fault == "wrong_origin" else ORIGIN
    observed = BrowserFillObservation(
        document_id=uuid4(),
        origin=origin,
        fields=(
            BrowserFillHandle(
                field="username" if fault == "wrong_fields" else "password",
                handle=uuid4(),
                role="text",
                form_origin=origin,
            ),
        ),
    )
    with pytest.raises(BrowserFillRefused):
        await b.service.prepare(
            b.ctx, b.identity, uuid4() if fault == "missing" else request.request_id, observed
        )
    assert await b.db.get(ToolApproval, request.request_id) is None


@pytest.mark.parametrize(
    "fault", ["missing_approval", "generic_approval", "corrupt_observation", "wrong_destination"]
)
async def test_confirmation_refuses_without_a_pending_exact_safe_plan(browser, fault):
    b = browser
    plan_id, observed = await b.prepared()
    if fault == "missing_approval":
        await b.db.delete(await b.db.get(ToolApproval, plan_id))
    elif fault == "generic_approval":
        await ApprovalService(b.db).decide(b.ctx, plan_id, approved=True)
    else:
        row = await repo.plan(b.db, b.org.id, plan_id)
        if fault == "corrupt_observation":
            row.observation = {"document_id": "invalid"}
        else:
            bad = "https://different.example.test"
            row.observation = observed.model_copy(
                update={
                    "origin": bad,
                    "fields": tuple(
                        item.model_copy(update={"form_origin": bad}) for item in observed.fields
                    ),
                }
            ).model_dump(mode="json")
    await b.db.flush()
    result = await b.service.confirm(b.ctx, b.run.id, plan_id, b.confirmation(observed))
    assert result.state == BrowserFillState.REFUSED
    if fault == "corrupt_observation":
        assert result.origin is None and result.document_id is None
        assert result.reason_code == BrowserFillReason.DOCUMENT_CHANGED


@pytest.mark.parametrize(
    "fault",
    [
        "approval_missing",
        "approval_wrong_person",
        "approval_wrong_tool",
        "approval_wrong_args",
        "disabled_totp",
    ],
)
async def test_claim_requires_the_exact_human_decision_and_current_field_policy(
    browser, monkeypatch, fault
):
    b = browser
    plan_id, observed = await b.prepared("totp" if fault == "disabled_totp" else "password")
    await b.service.confirm(b.ctx, b.run.id, plan_id, b.confirmation(observed))
    approval = await b.db.get(ToolApproval, plan_id)
    if fault == "approval_missing":
        await b.db.delete(approval)
    elif fault == "approval_wrong_person":
        other = await person(b.db)
        approval.decided_by_user_id = other.id
    elif fault == "approval_wrong_tool":
        approval.tool_id = "unrelated_tool"
    elif fault == "approval_wrong_args":
        approval.tool_args = {"plan_id": str(uuid4())}
    else:
        monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_TOTP_ENABLED", False)
    await b.db.flush()
    with pytest.raises(BrowserFillRefused):
        await b.service.claim(b.ctx, b.identity, plan_id, observed, output_protected=True)
    assert (await repo.plan(b.db, b.org.id, plan_id)).attempt_id is None


@pytest.mark.parametrize(
    "fault", ["not_filled", "document", "generation", "id_collision", "expired", "another_active"]
)
async def test_submission_refuses_stale_or_ambiguous_parent_and_never_creates_second_attempt(
    browser, fault
):
    b = browser
    claim = await b.claimed()
    if fault != "not_filled":
        await b.service.finish(b.identity, claim, filled=True)
    request = BrowserCredentialSubmission(
        request_id=uuid4(),
        document_id=claim.observation.document_id,
        authorization_generation=claim.generation,
    )
    if fault == "document":
        request = request.model_copy(update={"document_id": uuid4()})
    elif fault == "generation":
        request = request.model_copy(update={"authorization_generation": uuid4()})
    elif fault == "id_collision":
        request = request.model_copy(update={"request_id": claim.plan_id})
    elif fault == "expired":
        row = await repo.plan(b.db, b.org.id, claim.plan_id)
        row.finished_at = datetime.now(UTC) - timedelta(seconds=61)
        await b.db.flush()
    elif fault == "another_active":
        await b.service.request(b.ctx, b.run.id, b.request())
    with pytest.raises((BrowserFillRefused, NotFoundError)):
        await b.service.submit(b.ctx, b.run.id, claim.plan_id, request)
    assert await repo.submission(b.db, b.org.id, claim.plan_id) is None


async def test_submission_can_follow_an_expired_unexecuted_request_and_unknown_effect_is_terminal(
    browser,
):
    b = browser
    claim = await b.claimed()
    await b.service.finish(b.identity, claim, filled=True)
    pending = await b.service.request(b.ctx, b.run.id, b.request())
    row = await repo.plan(b.db, b.org.id, pending.id)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await b.db.flush()
    submit = await b.service.submit(
        b.ctx,
        b.run.id,
        claim.plan_id,
        BrowserCredentialSubmission(
            request_id=uuid4(),
            document_id=claim.observation.document_id,
            authorization_generation=claim.generation,
        ),
    )
    submitted = await b.service.claim(
        b.ctx, b.identity, submit.id, claim.observation, output_protected=True
    )
    await b.service.finish(b.identity, submitted, filled=False)
    assert (await b.service.get(b.ctx, b.run.id, submit.id)).state == BrowserFillState.UNKNOWN
    last = (
        await b.db.scalars(
            select(AppAdminAuditLog).where(
                AppAdminAuditLog.action == "browser_credential.finished",
                AppAdminAuditLog.target_id == str(submit.id),
            )
        )
    ).first()
    assert last.details["state"] == "unknown"


async def test_disabled_admission_expires_pending_plan_and_late_or_foreign_claim_cannot_finish(
    browser, monkeypatch
):
    b = browser
    plan_id, _ = await b.prepared()
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_FILL_ENABLED", False)
    result = await b.service.get(b.ctx, b.run.id, plan_id)
    assert (
        result.state == BrowserFillState.EXPIRED
        and result.reason_code == BrowserFillReason.DISABLED
    )
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_FILL_ENABLED", True)
    claim = await b.claimed()
    foreign = b.identity.model_copy(update={"controller_id": uuid4()})
    await b.service.finish(foreign, claim, filled=True)
    assert (await b.service.get(b.ctx, b.run.id, claim.plan_id)).state == BrowserFillState.CLAIMED
    from dataclasses import replace

    with pytest.raises(BrowserFillRefused):
        await b.service.authorize_effect(b.ctx, b.identity, replace(claim, attempt_id=uuid4()))
    await b.service.refuse(b.identity, claim.plan_id, BrowserFillReason.OWNERSHIP_LOST)
    with pytest.raises(BrowserFillRefused):
        await b.service.authorize_effect(b.ctx, b.identity, claim)


@pytest.mark.parametrize("stage", ["approved", "claimed"])
@pytest.mark.parametrize("revoke", ["policy", "member", "binding", "deployment"])
async def test_shared_delegation_revocation_is_rechecked_at_claim_and_final_native_effect(
    browser, monkeypatch, stage, revoke
):
    from app.schemas.browser_credential import BrowserCredentialPolicyWrite
    from app.services.browser_credentials import BrowserCredentialPolicyService

    b = browser
    await BrowserCredentialPolicyService(b.db).update(
        b.ctx,
        b.secret.id,
        BrowserCredentialPolicyWrite(
            generation=b.secret.authorization_generation,
            mode="shared",
            agent_ids=(b.agent.id,),
            member_ids=(b.owner.id,),
        ),
    )
    plan_id, observed = await b.approved()
    claim = (
        await b.service.claim(b.ctx, b.identity, plan_id, observed, output_protected=True)
        if stage == "claimed"
        else None
    )
    if revoke == "policy":
        await BrowserCredentialPolicyService(b.db).update(
            b.ctx,
            b.secret.id,
            BrowserCredentialPolicyWrite(
                generation=b.secret.authorization_generation,
                mode="personal",
            ),
        )
    elif revoke == "member":
        member = await b.db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == b.org.id,
                OrganizationMember.user_id == b.owner.id,
            )
        )
        await b.db.delete(member)
        await b.db.flush()
    elif revoke == "binding":
        spec = AgentSpec.model_validate(
            {
                "name": "Binding withdrawn",
                "capabilities": [
                    {
                        "id": "browser_use",
                        "config": {"connection": "built_in", "cdp_url": ENDPOINT},
                    }
                ],
            }
        ).model_dump(mode="json")
        version = AgentVersion(organization_id=b.org.id, agent_id=b.agent.id, version=2, spec=spec)
        b.db.add(version)
        await b.db.flush()
        b.agent.current_version_id = version.id
        await b.db.flush()
    else:
        monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_FILL_ENABLED", False)
    with pytest.raises(BrowserFillRefused):
        if claim is not None:
            await b.service.authorize_effect(b.ctx, b.identity, claim)
        else:
            await b.service.claim(b.ctx, b.identity, plan_id, observed, output_protected=True)
