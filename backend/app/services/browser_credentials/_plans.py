"""A live fill has two decisions: the human confirms, then its native owner claims once."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.audit import record_audit
from app.core.browser_fill import (
    ACTIVE_FILL_STATES,
    BrowserFillObservation,
    BrowserFillOperation,
    BrowserFillReason,
    BrowserFillRefused,
    BrowserFillSelection,
    BrowserFillState,
)
from app.core.browser_session import CredentialGeneration, credential_generations
from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import BrowserSecret
from app.db.models.agent_run import ApprovalStatus
from app.db.models.browser_credential import BrowserCredentialPlan
from app.repositories import agent_run as run_repo
from app.repositories import browser_credential as repo
from app.repositories import browser_credential_continuation as continuation_repo
from app.schemas.browser_credential import (
    BrowserCredentialConfirmation,
    BrowserCredentialEligible,
    BrowserCredentialPlanRead,
    BrowserCredentialRequest,
    BrowserCredentialSubmission,
)
from app.schemas.secret import BrowserSecretMetadata
from app.services.approvals import ApprovalService

from . import _access
from ._lease import LiveBrowserIdentity, discover, observed_origin

PLAN_SECONDS = 60
TOOL_ID = "browser_fill_credential"
SUBMIT_TOOL_ID = "browser_submit_credential_form"


def read_plan(row: BrowserCredentialPlan) -> BrowserCredentialPlanRead:
    selection = BrowserFillSelection.model_validate(row.selection)
    observed = (
        None if row.observation is None else BrowserFillObservation.model_validate(row.observation)
    )
    return BrowserCredentialPlanRead(
        id=row.id,
        operation=BrowserFillOperation(row.operation),
        parent_plan_id=row.parent_plan_id,
        run_id=row.run_id,
        call_id=row.call_id,
        tab_id=row.tab_id,
        secret_id=row.secret_id,
        authorization_generation=row.authorization_generation,
        state=BrowserFillState(row.state),
        fields=[item.field for item in selection.fields],
        origin=None if observed is None else observed.origin,
        document_id=None if observed is None else observed.document_id,
        expires_at=row.expires_at,
        submission_expires_at=(
            row.finished_at + timedelta(seconds=PLAN_SECONDS)
            if row.operation == BrowserFillOperation.FILL
            and row.state == BrowserFillState.FILLED
            and row.finished_at is not None
            else None
        ),
        reason_code=None if row.reason_code is None else BrowserFillReason(row.reason_code),
        output_protected=row.output_protected,
    )


@dataclass(frozen=True)
class AuthorizedFill:
    """Internal only. The caller must finish its transaction before sending these values."""

    plan_id: UUID
    attempt_id: UUID
    secret_id: UUID
    generation: UUID
    operation: BrowserFillOperation
    observation: BrowserFillObservation
    value: BrowserSecret | None


@dataclass(frozen=True)
class NativePlan:
    """Internal selection and state for the controller that owns these handles."""

    plan_id: UUID
    state: BrowserFillState
    operation: BrowserFillOperation
    parent_plan_id: UUID | None
    selection: BrowserFillSelection
    observation: BrowserFillObservation | None


def _owned_by(row: BrowserCredentialPlan, identity: LiveBrowserIdentity) -> bool:
    """A controller nonce never substitutes for the complete persisted authority."""
    return (
        row.organization_id == identity.organization_id
        and row.run_id == identity.run_id
        and row.agent_id == identity.agent_id
        and row.user_id == identity.user_id
        and row.controller_id == identity.controller_id
        and row.call_id == identity.call_id
        and row.tab_id == identity.tab_id
        and row.secret_id in identity.credential_ids
    )


def _confirmation_matches(
    row: BrowserCredentialPlan,
    identity: LiveBrowserIdentity,
    observed: BrowserFillObservation,
    confirmation: BrowserCredentialConfirmation,
) -> None:
    if (
        not _owned_by(row, identity)
        or confirmation.document_id != observed.document_id
        or confirmation.authorization_generation != row.authorization_generation
    ):
        raise BrowserFillRefused(BrowserFillReason.AUTHORITY_CHANGED)


def _destination_allowed(origin: str, value: BrowserSecret) -> None:
    if origin not in value.allowed_origins:
        raise BrowserFillRefused(BrowserFillReason.DESTINATION_REFUSED)


async def audit(db: AsyncSession, row: BrowserCredentialPlan, action: str) -> None:
    observed = (
        None if row.observation is None else BrowserFillObservation.model_validate(row.observation)
    )
    await record_audit(
        db,
        actor_user_id=row.user_id,
        organization_id=row.organization_id,
        action=action,
        target_type="browser_credential_plan",
        target_id=str(row.id),
        details={
            "operation": row.operation,
            "parent_plan_id": None if row.parent_plan_id is None else str(row.parent_plan_id),
            "run_id": str(row.run_id),
            "agent_id": str(row.agent_id),
            "secret_id": str(row.secret_id),
            "generation": str(row.authorization_generation),
            "origin": None if observed is None else observed.origin,
            "fields": [
                item.field for item in BrowserFillSelection.model_validate(row.selection).fields
            ],
            "state": row.state,
            "reason_code": row.reason_code,
        },
    )


class BrowserCredentialPlanService:
    def __init__(self, db: AsyncSession, redis: RedisClient) -> None:
        self.db, self.redis = db, redis

    async def live(
        self, ctx: AuthContext, run_id: UUID, call_id: str, tab_id: str
    ) -> tuple[AuthContext, LiveBrowserIdentity]:
        identity = await discover(self.redis, run_id, call_id)
        if identity is None or identity.tab_id != tab_id:
            raise BrowserFillRefused(BrowserFillReason.LIVE_BROWSER_REQUIRED)
        current, _ = await _access.private_run(self.db, ctx, identity)
        return current, identity

    async def eligible(
        self, ctx: AuthContext, run_id: UUID, call_id: str, tab_id: str
    ) -> list[BrowserCredentialEligible]:
        current, identity = await self.live(ctx, run_id, call_id, tab_id)
        origin = await observed_origin(self.redis, identity)
        if origin is None:
            return []
        result: list[BrowserCredentialEligible] = []
        for secret_id in identity.credential_ids:
            try:
                row = await _access.credential(
                    self.db, current, secret_id=secret_id, agent_id=identity.agent_id
                )
                metadata = BrowserSecretMetadata.from_secret(_access.open_value(row))
            except BrowserFillRefused, BadRequestError:
                continue
            if origin in metadata.allowed_origins:
                result.append(
                    BrowserCredentialEligible(
                        id=row.id,
                        name=row.name,
                        kind="browser_login" if row.kind == "browser_login" else "browser_profile",
                        authorization_generation=row.authorization_generation,
                        usage_scope="personal" if row.usage_scope == "personal" else "organization",
                        browser=metadata,
                    )
                )
        return result

    async def request(
        self, ctx: AuthContext, run_id: UUID, request: BrowserCredentialRequest
    ) -> BrowserCredentialPlanRead:
        current, identity = await self.live(ctx, run_id, request.call_id, request.tab_id)
        if request.secret_id not in identity.credential_ids:
            raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
        await repo.lock_run(self.db, identity.organization_id, run_id)
        secret = await _access.credential(
            self.db,
            current,
            secret_id=request.secret_id,
            agent_id=identity.agent_id,
            generation=request.authorization_generation,
            locked=True,
        )
        metadata = BrowserSecretMetadata.from_secret(_access.open_value(secret))
        selected = {item.field for item in request.fields}
        if not selected <= set(metadata.available_fields) or (
            "totp" in selected and not settings.BROWSER_CREDENTIAL_TOTP_ENABLED
        ):
            raise BrowserFillRefused(BrowserFillReason.FIELD_REFUSED)
        selection = BrowserFillSelection(fields=request.fields).model_dump(mode="json")
        existing = await repo.plan(
            self.db, identity.organization_id, request.request_id, locked=True
        )
        if existing is not None:
            if (
                existing.user_id != identity.user_id
                or existing.operation != BrowserFillOperation.FILL
                or existing.run_id != run_id
                or existing.call_id != request.call_id
                or existing.tab_id != request.tab_id
                or existing.secret_id != request.secret_id
                or existing.authorization_generation != request.authorization_generation
                or existing.selection != selection
            ):
                raise NotFoundError(message="Browser credential plan not found")
            await self.expire(current, existing)
            return read_plan(existing)
        if (
            await continuation_repo.active_for_view(
                self.db, identity.organization_id, run_id, identity.call_id
            )
            is not None
        ):
            raise BrowserFillRefused(BrowserFillReason.ALREADY_CONSUMED)
        active = await repo.active_for_view(
            self.db, identity.organization_id, run_id, request.call_id
        )
        if active is not None:
            await self.expire(current, active)
            if active.state in ACTIVE_FILL_STATES:
                raise ConflictError(message="This browser already has a credential plan to finish")
        row = await repo.create(
            self.db,
            BrowserCredentialPlan(
                id=request.request_id,
                organization_id=identity.organization_id,
                run_id=run_id,
                agent_id=identity.agent_id,
                user_id=identity.user_id,
                secret_id=secret.id,
                authorization_generation=secret.authorization_generation,
                controller_id=identity.controller_id,
                tab_id=identity.tab_id,
                call_id=identity.call_id,
                operation=BrowserFillOperation.FILL.value,
                selection=selection,
                state=BrowserFillState.REQUESTED.value,
                output_protected=False,
                expires_at=datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS),
            ),
        )
        await audit(self.db, row, "browser_credential.requested")
        return read_plan(row)

    async def get(self, ctx: AuthContext, run_id: UUID, plan_id: UUID) -> BrowserCredentialPlanRead:
        current = await _access.person(self.db, ctx)
        row = await repo.plan(self.db, current.organization_id, plan_id, locked=True)
        if row is None or row.user_id != current.user_id or row.run_id != run_id:
            raise NotFoundError(message="Browser credential plan not found")
        await self.expire(current, row)
        return read_plan(row)

    async def submit(
        self,
        ctx: AuthContext,
        run_id: UUID,
        parent_id: UUID,
        request: BrowserCredentialSubmission,
    ) -> BrowserCredentialPlanRead:
        """A separate owner action. Repeating its ID reads the same durable attempt."""
        current = await _access.person(self.db, ctx)
        await repo.lock_run(self.db, current.organization_id, run_id)
        parent = await repo.plan(self.db, current.organization_id, parent_id, locked=True)
        if (
            parent is None
            or parent.user_id != current.user_id
            or parent.run_id != run_id
            or parent.operation != BrowserFillOperation.FILL
            or parent.state != BrowserFillState.FILLED
            or parent.observation is None
        ):
            raise NotFoundError(message="Filled browser credential plan not found")
        observed = BrowserFillObservation.model_validate(parent.observation)
        if (
            observed.document_id != request.document_id
            or parent.authorization_generation != request.authorization_generation
        ):
            raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED)
        existing = await repo.submission(self.db, current.organization_id, parent.id)
        if existing is not None:
            if existing.id != request.request_id:
                raise BrowserFillRefused(BrowserFillReason.ALREADY_CONSUMED)
            await self.expire(current, existing)
            return read_plan(existing)
        if await repo.plan(self.db, current.organization_id, request.request_id) is not None:
            raise BrowserFillRefused(BrowserFillReason.ALREADY_CONSUMED)
        current, identity = await self.live(current, run_id, parent.call_id, parent.tab_id)
        now = datetime.now(UTC)
        if (
            not _owned_by(parent, identity)
            or not parent.output_protected
            or parent.finished_at is None
            or parent.finished_at + timedelta(seconds=PLAN_SECONDS) <= now
        ):
            raise BrowserFillRefused(BrowserFillReason.CONFIRMATION_EXPIRED)
        active = await repo.active_for_view(
            self.db, current.organization_id, run_id, parent.call_id
        )
        if active is not None:
            await self.expire(current, active)
            if active.state in ACTIVE_FILL_STATES:
                raise BrowserFillRefused(BrowserFillReason.ALREADY_CONSUMED)
        secret = await _access.credential(
            self.db,
            current,
            secret_id=parent.secret_id,
            agent_id=parent.agent_id,
            generation=parent.authorization_generation,
            locked=True,
        )
        _destination_allowed(observed.origin, _access.open_value(secret))
        row = await repo.create(
            self.db,
            BrowserCredentialPlan(
                id=request.request_id,
                organization_id=parent.organization_id,
                run_id=run_id,
                agent_id=parent.agent_id,
                user_id=parent.user_id,
                secret_id=parent.secret_id,
                authorization_generation=parent.authorization_generation,
                controller_id=parent.controller_id,
                tab_id=parent.tab_id,
                call_id=parent.call_id,
                operation=BrowserFillOperation.SUBMIT.value,
                parent_plan_id=parent.id,
                selection=parent.selection,
                observation=parent.observation,
                state=BrowserFillState.APPROVED.value,
                output_protected=True,
                expires_at=parent.finished_at + timedelta(seconds=PLAN_SECONDS),
            ),
        )
        authority = ApprovalService(self.db)
        await authority.request(
            approval_id=row.id,
            organization_id=row.organization_id,
            run_id=row.run_id,
            agent_id=row.agent_id,
            tool_id=SUBMIT_TOOL_ID,
            capability_tool_id=SUBMIT_TOOL_ID,
            tool_args={"plan_id": str(row.id)},
            context={"action": "Confirm submission of a private browser credential plan"},
            always_asks=True,
        )
        await authority.decide(current, row.id, approved=True)
        await audit(self.db, row, "browser_credential.submission_confirmed")
        return read_plan(row)

    async def submitted(
        self, ctx: AuthContext, run_id: UUID, parent_id: UUID
    ) -> BrowserCredentialPlanRead | None:
        await self.get(ctx, run_id, parent_id)
        row = await repo.submission(self.db, ctx.organization_id, parent_id)
        if row is None:
            return None
        await self.expire(ctx, row)
        return read_plan(row)

    async def expire(self, ctx: AuthContext, row: BrowserCredentialPlan) -> None:
        if row.state not in ACTIVE_FILL_STATES:
            return
        now = datetime.now(UTC)
        identity = await discover(self.redis, row.run_id, row.call_id)
        live = identity is not None and _owned_by(row, identity)
        disabled = False
        try:
            _access.enabled(row.organization_id, row.user_id)
        except BrowserFillRefused:
            disabled = True
        if row.expires_at > now and live and not disabled:
            return
        if row.state == BrowserFillState.CLAIMED:
            row.state = BrowserFillState.UNKNOWN.value
            row.reason_code = BrowserFillReason.UNCERTAIN_EFFECT.value
        else:
            row.state = BrowserFillState.EXPIRED.value
            row.reason_code = (
                BrowserFillReason.DISABLED.value
                if disabled
                else BrowserFillReason.CONFIRMATION_EXPIRED.value
            )
        row.finished_at = now
        await ApprovalService(self.db).expire_now(row.id, organization_id=row.organization_id)
        await self.db.flush()
        await audit(self.db, row, "browser_credential.expired")

    async def confirm(
        self,
        ctx: AuthContext,
        run_id: UUID,
        plan_id: UUID,
        confirmation: BrowserCredentialConfirmation,
    ) -> BrowserCredentialPlanRead:
        current = await _access.person(self.db, ctx)
        await repo.lock_run(self.db, current.organization_id, run_id)
        row = await repo.plan(self.db, current.organization_id, plan_id, locked=True)
        if row is None or row.user_id != current.user_id or row.run_id != run_id:
            raise NotFoundError(message="Browser credential plan not found")
        await self.expire(current, row)
        if row.state != BrowserFillState.AWAITING_CONFIRMATION:
            return read_plan(row)
        try:
            current, identity = await self.live(current, run_id, row.call_id, row.tab_id)
            observed = BrowserFillObservation.model_validate(row.observation)
            _confirmation_matches(row, identity, observed, confirmation)
            secret = await _access.credential(
                self.db,
                current,
                secret_id=row.secret_id,
                agent_id=row.agent_id,
                generation=row.authorization_generation,
                locked=True,
            )
            _destination_allowed(observed.origin, _access.open_value(secret))
        except (BrowserFillRefused, ValidationError) as refused:
            row.state = BrowserFillState.REFUSED.value
            if isinstance(refused, ValidationError):
                # Imported/corrupt observations have no safe destination metadata
                # to display or audit. They cannot remain a pending confirmation.
                row.observation = None
            row.reason_code = (
                refused.reason.value
                if isinstance(refused, BrowserFillRefused)
                else BrowserFillReason.DOCUMENT_CHANGED.value
            )
            row.finished_at = datetime.now(UTC)
            await ApprovalService(self.db).expire_now(row.id, organization_id=row.organization_id)
            await self.db.flush()
            await audit(self.db, row, "browser_credential.refused")
            return read_plan(row)
        approval = await run_repo.get_approval(
            self.db, row.id, organization_id=row.organization_id, for_update=True
        )
        if approval is None or approval.status != ApprovalStatus.PENDING.value:
            row.state = BrowserFillState.REFUSED.value
            row.reason_code = BrowserFillReason.CONFIRMATION_REQUIRED.value
            row.finished_at = datetime.now(UTC)
        else:
            await ApprovalService(self.db).decide(current, row.id, approved=confirmation.approve)
            row.state = (
                BrowserFillState.APPROVED.value
                if confirmation.approve
                else BrowserFillState.DECLINED.value
            )
            row.reason_code = (
                None if confirmation.approve else BrowserFillReason.CONFIRMATION_DECLINED.value
            )
            if not confirmation.approve:
                row.finished_at = datetime.now(UTC)
        await self.db.flush()
        await audit(self.db, row, "browser_credential.confirmed")
        return read_plan(row)

    async def pending(self, ctx: AuthContext, identity: LiveBrowserIdentity) -> NativePlan | None:
        """Claim preparation under the run lock; only this live controller observes the page."""
        current, _ = await _access.private_run(self.db, ctx, identity)
        await repo.lock_run(self.db, identity.organization_id, identity.run_id)
        row = await repo.active_for_view(
            self.db, identity.organization_id, identity.run_id, identity.call_id
        )
        if row is None:
            return None
        await self.expire(current, row)
        if row.state not in ACTIVE_FILL_STATES or not _owned_by(row, identity):
            return None
        if row.state == BrowserFillState.AWAITING_CONFIRMATION:
            approval = await run_repo.get_approval(
                self.db, row.id, organization_id=row.organization_id
            )
            if approval is None or approval.status != ApprovalStatus.PENDING:
                # Only the dedicated confirmation transaction may move both rows.
                # A generic approval decision cannot authorize credential use.
                await self.refuse(identity, row.id, BrowserFillReason.CONFIRMATION_REQUIRED)
                return None
        state = BrowserFillState(row.state)
        if state == BrowserFillState.REQUESTED:
            row.state = BrowserFillState.PREPARING.value
            await self.db.flush()
        return NativePlan(
            row.id,
            state,
            BrowserFillOperation(row.operation),
            row.parent_plan_id,
            BrowserFillSelection.model_validate(row.selection),
            None
            if row.observation is None
            else BrowserFillObservation.model_validate(row.observation),
        )

    async def refuse(
        self,
        identity: LiveBrowserIdentity,
        plan_id: UUID,
        reason: BrowserFillReason,
        *,
        output_protected: bool = False,
    ) -> None:
        """A terminal controller receipt; cancellation after claim is always uncertain."""
        await repo.lock_run(self.db, identity.organization_id, identity.run_id)
        row = await repo.plan(self.db, identity.organization_id, plan_id, locked=True)
        if row is None or not _owned_by(row, identity) or row.state not in ACTIVE_FILL_STATES:
            return
        claimed = row.state == BrowserFillState.CLAIMED
        row.state = BrowserFillState.UNKNOWN.value if claimed else BrowserFillState.REFUSED.value
        row.reason_code = BrowserFillReason.UNCERTAIN_EFFECT.value if claimed else reason.value
        row.output_protected = row.output_protected or output_protected
        row.finished_at = datetime.now(UTC)
        await ApprovalService(self.db).expire_now(row.id, organization_id=row.organization_id)
        await self.db.flush()
        await audit(self.db, row, "browser_credential.refused")

    async def finish(
        self, identity: LiveBrowserIdentity, claim: AuthorizedFill, *, filled: bool
    ) -> None:
        """CAS the one durable attempt. An expired/unknown claim cannot be revived."""
        row = await repo.plan(self.db, identity.organization_id, claim.plan_id, locked=True)
        if row is None or not _owned_by(row, identity):
            return
        completed = (
            BrowserFillState.FILLED
            if claim.operation == BrowserFillOperation.FILL
            else BrowserFillState.SUBMITTED
        )
        state = completed if filled else BrowserFillState.UNKNOWN
        reason = None if filled else BrowserFillReason.UNCERTAIN_EFFECT
        changed = await repo.finish(
            self.db,
            organization_id=identity.organization_id,
            plan_id=claim.plan_id,
            controller_id=identity.controller_id,
            attempt_id=claim.attempt_id,
            state=state,
            reason=reason,
            now=datetime.now(UTC),
        )
        if changed:
            # The UPDATE synchronizes this identity-map row under its existing
            # lock. It cannot disappear between the successful CAS and its audit.
            await audit(self.db, row, "browser_credential.finished")

    async def prepare(
        self,
        ctx: AuthContext,
        identity: LiveBrowserIdentity,
        plan_id: UUID,
        observation: BrowserFillObservation,
    ) -> BrowserCredentialPlanRead:
        current, _ = await _access.private_run(self.db, ctx, identity)
        await repo.lock_run(self.db, identity.organization_id, identity.run_id)
        row = await repo.plan(self.db, identity.organization_id, plan_id, locked=True)
        if (
            row is None
            or not _owned_by(row, identity)
            or row.state != BrowserFillState.PREPARING
            or row.expires_at <= datetime.now(UTC)
        ):
            raise BrowserFillRefused(BrowserFillReason.CONFIRMATION_EXPIRED)
        secret = await _access.credential(
            self.db,
            current,
            secret_id=row.secret_id,
            agent_id=row.agent_id,
            generation=row.authorization_generation,
            locked=True,
        )
        value = _access.open_value(secret)
        selection = BrowserFillSelection.model_validate(row.selection)
        if observation.origin not in value.allowed_origins or [
            item.field for item in selection.fields
        ] != [item.field for item in observation.fields]:
            raise BrowserFillRefused(BrowserFillReason.DESTINATION_REFUSED)
        row.observation = observation.model_dump(mode="json")
        row.state = BrowserFillState.AWAITING_CONFIRMATION.value
        await ApprovalService(self.db).request(
            approval_id=row.id,
            organization_id=row.organization_id,
            run_id=row.run_id,
            agent_id=row.agent_id,
            tool_id=TOOL_ID,
            capability_tool_id=TOOL_ID,
            tool_args={"plan_id": str(row.id)},
            # The general approval queue may be visible to organization admins.
            # Only the owner-scoped plan API exposes its origin and field choices.
            context={"action": "Confirm a private browser credential plan"},
            always_asks=True,
        )
        await self.db.flush()
        await audit(self.db, row, "browser_credential.prepared")
        return read_plan(row)

    async def claim(
        self,
        ctx: AuthContext,
        identity: LiveBrowserIdentity,
        plan_id: UUID,
        observation: BrowserFillObservation,
        *,
        output_protected: bool,
    ) -> AuthorizedFill:
        if not output_protected:
            raise BrowserFillRefused(BrowserFillReason.PROTECTION_UNAVAILABLE)
        current, _ = await _access.private_run(self.db, ctx, identity)
        await repo.lock_run(self.db, identity.organization_id, identity.run_id)
        row = await repo.plan(self.db, identity.organization_id, plan_id, locked=True)
        if (
            row is None
            or not _owned_by(row, identity)
            or row.state != BrowserFillState.APPROVED
            or row.expires_at <= datetime.now(UTC)
            or row.observation != observation.model_dump(mode="json")
        ):
            raise BrowserFillRefused(BrowserFillReason.ALREADY_CONSUMED)
        approval = await run_repo.get_approval(self.db, row.id, organization_id=row.organization_id)
        if (
            approval is None
            or approval.status != ApprovalStatus.APPROVED.value
            or approval.decided_by_user_id != row.user_id
            or approval.run_id != row.run_id
            or approval.agent_id != row.agent_id
            or approval.tool_id
            != (TOOL_ID if row.operation == BrowserFillOperation.FILL else SUBMIT_TOOL_ID)
            or approval.capability_tool_id
            != (TOOL_ID if row.operation == BrowserFillOperation.FILL else SUBMIT_TOOL_ID)
            or not approval.always_asks
            or approval.tool_args != {"plan_id": str(row.id)}
        ):
            raise BrowserFillRefused(BrowserFillReason.CONFIRMATION_REQUIRED)
        secret = await _access.credential(
            self.db,
            current,
            secret_id=row.secret_id,
            agent_id=row.agent_id,
            generation=row.authorization_generation,
            locked=True,
        )
        value = _access.open_value(secret)
        selected = {item.field for item in observation.fields}
        if (
            observation.origin not in value.allowed_origins
            or not selected <= set(BrowserSecretMetadata.from_secret(value).available_fields)
            or ("totp" in selected and not settings.BROWSER_CREDENTIAL_TOTP_ENABLED)
        ):
            raise BrowserFillRefused(BrowserFillReason.DESTINATION_REFUSED)
        attempt_id = uuid4()
        row.state = BrowserFillState.CLAIMED.value
        row.output_protected = True
        row.attempt_id = attempt_id
        row.claimed_at = datetime.now(UTC)
        await self.db.flush()
        await audit(self.db, row, "browser_credential.claimed")
        operation = BrowserFillOperation(row.operation)
        return AuthorizedFill(
            row.id,
            attempt_id,
            row.secret_id,
            row.authorization_generation,
            operation,
            observation,
            value if operation == BrowserFillOperation.FILL else None,
        )

    async def authorize_effect(
        self, ctx: AuthContext, identity: LiveBrowserIdentity, claim: AuthorizedFill
    ) -> None:
        """Hold the exact claim and credential through the bounded native effect."""
        await repo.lock_run(self.db, identity.organization_id, identity.run_id)
        row = await repo.plan(self.db, identity.organization_id, claim.plan_id, locked=True)
        if (
            row is None
            or row.state != BrowserFillState.CLAIMED
            or row.attempt_id != claim.attempt_id
            or not _owned_by(row, identity)
            or row.expires_at <= datetime.now(UTC)
            or not row.output_protected
            or row.authorization_generation != claim.generation
            or row.secret_id != claim.secret_id
            or row.operation != claim.operation
            or row.observation != claim.observation.model_dump(mode="json")
        ):
            raise BrowserFillRefused(BrowserFillReason.ALREADY_CONSUMED)
        current, _ = await _access.private_run(self.db, ctx, identity)
        contributors = credential_generations(
            [
                *identity.inherited_credentials,
                CredentialGeneration(
                    secret_id=claim.secret_id, authorization_generation=claim.generation
                ),
            ]
        )
        for contributor in contributors:
            await _access.credential(
                self.db,
                current,
                secret_id=contributor.secret_id,
                agent_id=identity.agent_id,
                generation=contributor.authorization_generation,
                locked=True,
            )
        await _access.private_run(self.db, current, identity)
