"""One durable human decision before exporting or continuing a protected session."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.audit import record_audit
from app.core.browser_continuation import (
    ACTIVE_CONTINUATION_STATES,
    BrowserContinuationObservation,
    BrowserContinuationReason,
    BrowserContinuationRefused,
    BrowserContinuationState,
)
from app.core.browser_fill import (
    BrowserFillObservation,
    BrowserFillOperation,
    BrowserFillRefused,
    BrowserFillState,
)
from app.core.browser_session import (
    MAX_SESSION_AGE_SECONDS,
    CredentialGeneration,
    CredentialSessionProvenance,
    ProtectedSignIn,
    credential_generations,
)
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent_run import ApprovalStatus
from app.db.models.browser_credential import BrowserCredentialPlan
from app.db.models.browser_credential_continuation import BrowserCredentialContinuation
from app.repositories import agent_run as run_repo
from app.repositories import browser_credential as plans
from app.repositories import browser_credential_continuation as repo
from app.schemas.browser_credential_continuation import (
    BrowserCredentialContinuationConfirmation,
    BrowserCredentialContinuationRead,
    BrowserCredentialContinuationRequest,
)
from app.services.approvals import ApprovalService

from . import _access
from ._lease import LiveBrowserIdentity, discover
from ._plans import PLAN_SECONDS
from ._saved_sessions import remember_protected

CONTINUATION_TOOL_ID = "browser_continue_credential_session"
_GENERATIONS = TypeAdapter(tuple[CredentialGeneration, ...])


@dataclass(frozen=True)
class NativeContinuation:
    id: UUID
    state: BrowserContinuationState
    observation: BrowserContinuationObservation | None


@dataclass(frozen=True)
class ContinuationClaim:
    id: UUID
    attempt_id: UUID
    observation: BrowserContinuationObservation
    provenance: CredentialSessionProvenance
    keep_signed_in: bool
    call_id: str
    tab_id: str


def read_continuation(row: BrowserCredentialContinuation) -> BrowserCredentialContinuationRead:
    seen = (
        None
        if row.observation is None
        else BrowserContinuationObservation.model_validate(row.observation)
    )
    decision = (
        None
        if row.confirmation is None
        else BrowserCredentialContinuationConfirmation.model_validate(row.confirmation)
    )
    return BrowserCredentialContinuationRead(
        id=row.id,
        organization_id=row.organization_id,
        user_id=row.user_id,
        run_id=row.run_id,
        source_submission_id=row.source_submission_id,
        source_fill_id=row.source_fill_id,
        source_call_id=row.source_call_id,
        source_tab_id=row.source_tab_id,
        secret_id=row.secret_id,
        authorization_generation=row.authorization_generation,
        state=BrowserContinuationState(row.state),
        origin=None if seen is None else seen.origin,
        document_id=None if seen is None else seen.document_id,
        expires_at=row.expires_at,
        keep_signed_in=None if decision is None else decision.keep_signed_in,
        saved_sign_in_id=row.saved_sign_in_id,
        continuation_call_id=row.continuation_call_id,
        continuation_tab_id=row.continuation_tab_id,
        reason_code=None if row.reason_code is None else BrowserContinuationReason(row.reason_code),
        output_protected=True,
    )


def _owned_by(row: BrowserCredentialContinuation, identity: LiveBrowserIdentity) -> bool:
    return (
        row.organization_id == identity.organization_id
        and row.user_id == identity.user_id
        and row.run_id == identity.run_id
        and row.agent_id == identity.agent_id
        and row.controller_id == identity.controller_id
        and row.source_call_id == identity.call_id
        and row.source_tab_id == identity.tab_id
        and row.secret_id in identity.credential_ids
    )


def _matches_source(row: BrowserCredentialContinuation, source: BrowserCredentialPlan) -> bool:
    return (
        row.user_id,
        row.run_id,
        row.agent_id,
        row.secret_id,
        row.authorization_generation,
        row.source_submission_id,
        row.source_fill_id,
        row.controller_id,
        row.source_call_id,
        row.source_tab_id,
    ) == (
        source.user_id,
        source.run_id,
        source.agent_id,
        source.secret_id,
        source.authorization_generation,
        source.id,
        source.parent_plan_id,
        source.controller_id,
        source.call_id,
        source.tab_id,
    )


async def _person(db: AsyncSession, ctx: AuthContext) -> AuthContext:
    try:
        return await _access.person(db, ctx)
    except BrowserFillRefused:
        raise BrowserContinuationRefused(BrowserContinuationReason.NOT_AVAILABLE) from None


async def _audit(db: AsyncSession, row: BrowserCredentialContinuation) -> None:
    await record_audit(
        db,
        actor_user_id=row.user_id,
        organization_id=row.organization_id,
        action="browser_credential.continuation",
        target_type="browser_credential_continuation",
        target_id=str(row.id),
        details={
            "source_submission_id": str(row.source_submission_id),
            "state": row.state,
            "reason_code": row.reason_code,
            "output_protected": True,
        },
    )


class BrowserCredentialContinuationService:
    def __init__(self, db: AsyncSession, redis: RedisClient) -> None:
        self.db, self.redis = db, redis

    async def _source(
        self, current: AuthContext, run_id: UUID, submission_id: UUID
    ) -> BrowserCredentialPlan:
        source = await plans.plan(self.db, current.organization_id, submission_id, locked=True)
        if source is None or source.user_id != current.user_id or source.run_id != run_id:
            raise NotFoundError(message="Browser submission not found")
        if (
            source.operation != BrowserFillOperation.SUBMIT
            or source.state != BrowserFillState.SUBMITTED
            or source.parent_plan_id is None
            or source.observation is None
            or not source.output_protected
        ):
            raise BrowserContinuationRefused(BrowserContinuationReason.SOURCE_NOT_SUBMITTED)
        parent = await plans.plan(
            self.db, current.organization_id, source.parent_plan_id, locked=True
        )
        if parent is None or (
            parent.user_id,
            parent.run_id,
            parent.agent_id,
            parent.secret_id,
            parent.authorization_generation,
            parent.controller_id,
            parent.call_id,
            parent.tab_id,
            parent.observation,
            parent.state,
            parent.operation,
            parent.output_protected,
        ) != (
            source.user_id,
            source.run_id,
            source.agent_id,
            source.secret_id,
            source.authorization_generation,
            source.controller_id,
            source.call_id,
            source.tab_id,
            source.observation,
            BrowserFillState.FILLED,
            BrowserFillOperation.FILL,
            True,
        ):
            raise BrowserContinuationRefused(BrowserContinuationReason.SOURCE_NOT_SUBMITTED)
        return source

    async def _authority(
        self,
        ctx: AuthContext,
        identity: LiveBrowserIdentity,
        row: BrowserCredentialContinuation,
        observation: BrowserContinuationObservation | None = None,
    ) -> None:
        if not _owned_by(row, identity):
            raise BrowserContinuationRefused(BrowserContinuationReason.OWNERSHIP_LOST)
        contributors = credential_generations(
            [
                *identity.inherited_credentials,
                *await repo.contributors(
                    self.db, identity.organization_id, identity.run_id, identity.tab_id
                ),
            ]
        )
        if contributors != _GENERATIONS.validate_python(row.credential_generations):
            raise BrowserContinuationRefused(BrowserContinuationReason.AUTHORITY_CHANGED)
        try:
            current, _ = await _access.private_run(self.db, ctx, identity)
            allowed: set[str] | None = None
            for contributor in contributors:
                if contributor.secret_id not in identity.credential_ids:
                    raise BrowserContinuationRefused(BrowserContinuationReason.AUTHORITY_CHANGED)
                secret = await _access.credential(
                    self.db,
                    current,
                    secret_id=contributor.secret_id,
                    agent_id=row.agent_id,
                    generation=contributor.authorization_generation,
                    locked=True,
                )
                origins = set(_access.open_value(secret).allowed_origins)
                allowed = origins if allowed is None else allowed & origins
            # Membership/binding can change while the credential row lock is acquired.
            await _access.private_run(self.db, current, identity)
        except BadRequestError:
            raise BrowserContinuationRefused(BrowserContinuationReason.AUTHORITY_CHANGED) from None
        source = await self._source(current, row.run_id, row.source_submission_id)
        if not _matches_source(row, source):
            raise BrowserContinuationRefused(BrowserContinuationReason.SOURCE_NOT_SUBMITTED)
        if observation is not None:
            original = BrowserFillObservation.model_validate(source.observation)
            if (
                observation.origin != original.origin
                or allowed is None
                or observation.origin not in allowed
            ):
                raise BrowserContinuationRefused(BrowserContinuationReason.DESTINATION_REFUSED)

    async def _live(self, row: BrowserCredentialContinuation) -> LiveBrowserIdentity:
        identity = await discover(self.redis, row.run_id, row.source_call_id)
        if identity is None or not _owned_by(row, identity):
            raise BrowserContinuationRefused(BrowserContinuationReason.OWNERSHIP_LOST)
        return identity

    async def _expire(self, row: BrowserCredentialContinuation) -> None:
        if row.state not in ACTIVE_CONTINUATION_STATES:
            return
        live = await discover(self.redis, row.run_id, row.source_call_id)
        enabled = True
        try:
            _access.enabled(row.organization_id, row.user_id)
        except BrowserFillRefused:
            enabled = False
        if (
            row.expires_at > datetime.now(UTC)
            and live is not None
            and _owned_by(row, live)
            and enabled
        ):
            return
        claimed = row.state == BrowserContinuationState.CLAIMED
        row.state = (
            BrowserContinuationState.UNKNOWN if claimed else BrowserContinuationState.EXPIRED
        )
        row.reason_code = (
            BrowserContinuationReason.UNCERTAIN_EFFECT
            if claimed
            else BrowserContinuationReason.CONFIRMATION_EXPIRED
            if enabled
            else BrowserContinuationReason.DISABLED
        )
        row.finished_at = datetime.now(UTC)
        await ApprovalService(self.db).expire_now(row.id, organization_id=row.organization_id)
        await self.db.flush()
        await _audit(self.db, row)

    async def get(
        self, ctx: AuthContext, run_id: UUID, submission_id: UUID
    ) -> BrowserCredentialContinuationRead | None:
        """Reconcile metadata only. GET never prepares, exports, saves or opens a browser."""
        current = await _person(self.db, ctx)
        await plans.lock_run(self.db, current.organization_id, run_id)
        source = await self._source(current, run_id, submission_id)
        row = await repo.for_submission(self.db, current.organization_id, submission_id)
        if row is None:
            return None
        if not _matches_source(row, source):
            raise NotFoundError(message="Browser continuation not found")
        await self._expire(row)
        return read_continuation(row)

    async def request(
        self,
        ctx: AuthContext,
        run_id: UUID,
        submission_id: UUID,
        data: BrowserCredentialContinuationRequest,
    ) -> BrowserCredentialContinuationRead:
        current = await _person(self.db, ctx)
        await plans.lock_run(self.db, current.organization_id, run_id)
        source = await self._source(current, run_id, submission_id)
        existing = await repo.for_submission(self.db, current.organization_id, submission_id)
        if existing is not None:
            if existing.id != data.request_id or not _matches_source(existing, source):
                raise BrowserContinuationRefused(BrowserContinuationReason.ALREADY_CONSUMED)
            await self._expire(existing)
            return read_continuation(existing)
        if await repo.get(self.db, current.organization_id, data.request_id) is not None:
            raise BrowserContinuationRefused(BrowserContinuationReason.ALREADY_CONSUMED)
        now = datetime.now(UTC)
        if (
            source.finished_at is None
            or source.finished_at + timedelta(seconds=2 * PLAN_SECONDS) <= now
        ):
            raise BrowserContinuationRefused(BrowserContinuationReason.CONFIRMATION_EXPIRED)
        assert source.parent_plan_id is not None
        identity = await discover(self.redis, source.run_id, source.call_id)
        if identity is None:
            raise BrowserContinuationRefused(BrowserContinuationReason.OWNERSHIP_LOST)
        contributors = credential_generations(
            [
                *identity.inherited_credentials,
                *await repo.contributors(self.db, source.organization_id, run_id, source.tab_id),
            ]
        )
        active_fill = await plans.active_for_view(
            self.db, source.organization_id, run_id, source.call_id
        )
        if active_fill is not None:
            raise BrowserContinuationRefused(BrowserContinuationReason.ALREADY_CONSUMED)
        row = BrowserCredentialContinuation(
            id=data.request_id,
            organization_id=source.organization_id,
            user_id=source.user_id,
            run_id=source.run_id,
            agent_id=source.agent_id,
            secret_id=source.secret_id,
            authorization_generation=source.authorization_generation,
            source_submission_id=source.id,
            source_fill_id=source.parent_plan_id,
            controller_id=source.controller_id,
            source_call_id=source.call_id,
            source_tab_id=source.tab_id,
            state=BrowserContinuationState.REQUESTED.value,
            expires_at=now + timedelta(seconds=PLAN_SECONDS),
            output_protected=True,
            credential_generations=[item.model_dump(mode="json") for item in contributors],
        )
        identity = await self._live(row)
        await self._authority(current, identity, row)
        active = await repo.active_for_view(
            self.db, row.organization_id, run_id, row.source_call_id
        )
        if active is not None:
            await self._expire(active)
            if active.state in ACTIVE_CONTINUATION_STATES:
                raise BrowserContinuationRefused(BrowserContinuationReason.ALREADY_CONSUMED)
        try:
            async with self.db.begin_nested():
                await repo.create(self.db, row)
        except IntegrityError as error:
            # Request IDs are global, while every preceding lookup is tenant scoped.
            # Keep the outer transaction usable and never return a foreign receipt.
            constraints = {
                getattr(error.orig, "constraint_name", None),
                getattr(getattr(error.orig, "__cause__", None), "constraint_name", None),
            }
            if getattr(error.orig, "sqlstate", None) != "23505" or constraints.isdisjoint(
                {
                    "browser_credential_continuations_pkey",
                    "uq_browser_continuations_org_id",
                    "uq_browser_continuation_submission",
                }
            ):
                raise
            raise BrowserContinuationRefused(BrowserContinuationReason.ALREADY_CONSUMED) from None
        await _audit(self.db, row)
        return read_continuation(row)

    async def confirm(
        self,
        ctx: AuthContext,
        run_id: UUID,
        submission_id: UUID,
        continuation_id: UUID,
        data: BrowserCredentialContinuationConfirmation,
    ) -> BrowserCredentialContinuationRead:
        current = await _person(self.db, ctx)
        await plans.lock_run(self.db, current.organization_id, run_id)
        await self._source(current, run_id, submission_id)
        row = await repo.get(self.db, current.organization_id, continuation_id, locked=True)
        if (
            row is None
            or row.user_id != current.user_id
            or row.run_id != run_id
            or row.source_submission_id != submission_id
        ):
            raise NotFoundError(message="Browser continuation not found")
        decision = data.model_dump(mode="json")
        if row.confirmation is not None:
            if row.confirmation != decision:
                raise BrowserContinuationRefused(BrowserContinuationReason.ALREADY_CONSUMED)
            await self._expire(row)
            return read_continuation(row)
        await self._expire(row)
        if row.state != BrowserContinuationState.AWAITING_CONFIRMATION:
            return read_continuation(row)
        seen = BrowserContinuationObservation.model_validate(row.observation)
        if (
            data.document_id != seen.document_id
            or data.authorization_generation != row.authorization_generation
        ):
            raise BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED)
        identity = await self._live(row)
        await self._authority(current, identity, row, seen)
        await ApprovalService(self.db).decide(current, row.id, approved=data.approve)
        row.confirmation = decision
        row.state = (
            BrowserContinuationState.APPROVED if data.approve else BrowserContinuationState.DECLINED
        )
        if not data.approve:
            row.finished_at = datetime.now(UTC)
        await self.db.flush()
        await _audit(self.db, row)
        return read_continuation(row)

    async def pending(
        self, ctx: AuthContext, identity: LiveBrowserIdentity
    ) -> NativeContinuation | None:
        await plans.lock_run(self.db, identity.organization_id, identity.run_id)
        row = await repo.active_for_view(
            self.db, identity.organization_id, identity.run_id, identity.call_id
        )
        if row is None:
            return None
        await self._expire(row)
        if row.state not in ACTIVE_CONTINUATION_STATES:
            return None
        try:
            await self._authority(ctx, identity, row)
        except BrowserContinuationRefused as refused:
            await self.refuse(identity, row.id, refused.reason)
            return None
        state = BrowserContinuationState(row.state)
        if state == BrowserContinuationState.REQUESTED:
            row.state = BrowserContinuationState.PREPARING
            await self.db.flush()
        return NativeContinuation(
            row.id,
            state,
            None
            if row.observation is None
            else BrowserContinuationObservation.model_validate(row.observation),
        )

    async def prepare(
        self,
        ctx: AuthContext,
        identity: LiveBrowserIdentity,
        continuation_id: UUID,
        observed: BrowserContinuationObservation,
    ) -> None:
        await plans.lock_run(self.db, identity.organization_id, identity.run_id)
        row = await repo.get(self.db, identity.organization_id, continuation_id, locked=True)
        if row is None or row.state != BrowserContinuationState.PREPARING:
            raise BrowserContinuationRefused(BrowserContinuationReason.ALREADY_CONSUMED)
        await self._expire(row)
        if row.state != BrowserContinuationState.PREPARING:
            raise BrowserContinuationRefused(BrowserContinuationReason.CONFIRMATION_EXPIRED)
        await self._authority(ctx, identity, row, observed)
        row.observation = observed.model_dump(mode="json")
        row.state = BrowserContinuationState.AWAITING_CONFIRMATION
        row.expires_at = datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)
        await ApprovalService(self.db).request(
            approval_id=row.id,
            organization_id=row.organization_id,
            run_id=row.run_id,
            agent_id=row.agent_id,
            tool_id=CONTINUATION_TOOL_ID,
            capability_tool_id=CONTINUATION_TOOL_ID,
            tool_args={
                "continuation_id": str(row.id),
                "source_submission_id": str(row.source_submission_id),
            },
            context={
                "action": "Continue with a protected site session; saving requires separate consent"
            },
            always_asks=True,
        )
        await self.db.flush()
        await _audit(self.db, row)

    async def claim(
        self,
        ctx: AuthContext,
        identity: LiveBrowserIdentity,
        continuation_id: UUID,
        observed: BrowserContinuationObservation,
    ) -> ContinuationClaim:
        await plans.lock_run(self.db, identity.organization_id, identity.run_id)
        row = await repo.get(self.db, identity.organization_id, continuation_id, locked=True)
        if row is None:
            raise BrowserContinuationRefused(BrowserContinuationReason.NOT_AVAILABLE)
        await self._expire(row)
        if row.state != BrowserContinuationState.APPROVED:
            raise BrowserContinuationRefused(BrowserContinuationReason.ALREADY_CONSUMED)
        if row.observation != observed.model_dump(mode="json"):
            raise BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED)
        decision = BrowserCredentialContinuationConfirmation.model_validate(row.confirmation)
        approval = await run_repo.get_approval(self.db, row.id, organization_id=row.organization_id)
        if (
            not decision.approve
            or approval is None
            or approval.status != ApprovalStatus.APPROVED.value
            or approval.decided_by_user_id != row.user_id
            or approval.run_id != row.run_id
            or approval.agent_id != row.agent_id
            or approval.tool_id != CONTINUATION_TOOL_ID
            or approval.capability_tool_id != CONTINUATION_TOOL_ID
            or approval.tool_args
            != {
                "continuation_id": str(row.id),
                "source_submission_id": str(row.source_submission_id),
            }
            or not approval.always_asks
        ):
            raise BrowserContinuationRefused(BrowserContinuationReason.CONFIRMATION_REQUIRED)
        await self._authority(ctx, identity, row, observed)
        now = datetime.now(UTC)
        attempt_id, call_id, tab_id = uuid4(), str(uuid4()), str(uuid4())
        row.state, row.attempt_id, row.claimed_at = (
            BrowserContinuationState.CLAIMED,
            attempt_id,
            now,
        )
        row.continuation_call_id, row.continuation_tab_id = call_id, tab_id
        await self.db.flush()
        await _audit(self.db, row)
        return ContinuationClaim(
            row.id,
            attempt_id,
            observed,
            CredentialSessionProvenance(
                organization_id=row.organization_id,
                user_id=row.user_id,
                agent_id=row.agent_id,
                continuation_id=row.id,
                source_submission_id=row.source_submission_id,
                source_fill_id=row.source_fill_id,
                secret_id=row.secret_id,
                authorization_generation=row.authorization_generation,
                origin=observed.origin,
                credential_generations=_GENERATIONS.validate_python(row.credential_generations),
                created_at=now,
                expires_at=now + timedelta(seconds=MAX_SESSION_AGE_SECONDS),
            ),
            decision.keep_signed_in,
            call_id,
            tab_id,
        )

    async def authorize_effect(
        self, ctx: AuthContext, identity: LiveBrowserIdentity, claim: ContinuationClaim
    ) -> BrowserCredentialContinuation:
        await plans.lock_run(self.db, identity.organization_id, identity.run_id)
        row = await repo.get(self.db, identity.organization_id, claim.id, locked=True)
        if (
            row is None
            or row.state != BrowserContinuationState.CLAIMED
            or row.attempt_id != claim.attempt_id
            or row.expires_at <= datetime.now(UTC)
            or row.continuation_call_id != claim.call_id
            or row.continuation_tab_id != claim.tab_id
            or row.observation != claim.observation.model_dump(mode="json")
            or row.authorization_generation != claim.provenance.authorization_generation
            or row.secret_id != claim.provenance.secret_id
            or _GENERATIONS.validate_python(row.credential_generations)
            != claim.provenance.credential_generations
        ):
            raise BrowserContinuationRefused(BrowserContinuationReason.ALREADY_CONSUMED)
        decision = BrowserCredentialContinuationConfirmation.model_validate(row.confirmation)
        if not decision.approve or decision.keep_signed_in != claim.keep_signed_in:
            raise BrowserContinuationRefused(BrowserContinuationReason.CONFIRMATION_REQUIRED)
        if await self._live(row) != identity:
            raise BrowserContinuationRefused(BrowserContinuationReason.OWNERSHIP_LOST)
        await self._authority(ctx, identity, row, claim.observation)
        return row

    async def finish(
        self,
        ctx: AuthContext,
        identity: LiveBrowserIdentity,
        claim: ContinuationClaim,
        state: ProtectedSignIn,
    ) -> None:
        """Save and settle together, after I/O and a fresh final authority check."""
        row = await self.authorize_effect(ctx, identity, claim)
        if state.provenance != claim.provenance:
            raise BrowserContinuationRefused(BrowserContinuationReason.STATE_REFUSED)
        if claim.keep_signed_in:
            saved = await remember_protected(self.db, state)
            row.saved_sign_in_id = saved.id
        row.state, row.finished_at = BrowserContinuationState.CONTINUED, datetime.now(UTC)
        await self.db.flush()
        await _audit(self.db, row)

    async def refuse(
        self,
        identity: LiveBrowserIdentity,
        continuation_id: UUID,
        reason: BrowserContinuationReason,
    ) -> None:
        await plans.lock_run(self.db, identity.organization_id, identity.run_id)
        row = await repo.get(self.db, identity.organization_id, continuation_id, locked=True)
        if (
            row is None
            or not _owned_by(row, identity)
            or row.state not in ACTIVE_CONTINUATION_STATES
        ):
            return
        claimed = row.state == BrowserContinuationState.CLAIMED
        row.state = (
            BrowserContinuationState.UNKNOWN if claimed else BrowserContinuationState.REFUSED
        )
        row.reason_code = BrowserContinuationReason.UNCERTAIN_EFFECT if claimed else reason
        row.finished_at = datetime.now(UTC)
        await ApprovalService(self.db).expire_now(row.id, organization_id=row.organization_id)
        await self.db.flush()
        await _audit(self.db, row)
