"""The live browser owner's bounded plan loop. API workers never import or hold page handles."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, suppress
from uuid import UUID, uuid4

import anyio
from pydantic import SecretStr

from app.agents.browser_events import BrowserEvent, BrowserEventSink
from app.agents.capabilities.browser_use._credential_page import FILL_SECONDS, NativeFillValues
from app.agents.capabilities.browser_use._elements import Snapshot
from app.agents.capabilities.browser_use._page import CdpPage
from app.agents.capabilities.browser_use._transport_privacy import require_private_transport
from app.agents.deps import AgentDeps
from app.clients.redis import RedisClient
from app.core.browser_continuation import (
    ACTIVE_CONTINUATION_STATES,
    BrowserContinuationReason,
    BrowserContinuationRefused,
    BrowserContinuationState,
)
from app.core.browser_fill import (
    ACTIVE_FILL_STATES,
    BrowserFillOperation,
    BrowserFillReason,
    BrowserFillRefused,
    BrowserFillSelection,
    BrowserFillState,
)
from app.core.browser_session import ProtectedSignIn
from app.core.browser_totp import browser_code
from app.core.permissions import AuthContext
from app.core.secret_kinds import BrowserLoginSecret, BrowserProfileSecret
from app.db.session import get_db_context
from app.schemas.browser_credential import BrowserCredentialPlanRead, BrowserCredentialRequest
from app.services.access import member_context

from . import _access
from ._continuation import (
    BrowserCredentialContinuationService,
    ContinuationClaim,
    NativeContinuation,
)
from ._lease import BrowserWriterLease, LiveBrowserIdentity
from ._plans import PLAN_SECONDS, AuthorizedFill, BrowserCredentialPlanService, NativePlan

IDLE_SECONDS = 150
POLL_SECONDS = 0.5

ContinuationOpener = Callable[
    [ContinuationClaim, ProtectedSignIn], AbstractAsyncContextManager[None]
]


def fill_values(claim: AuthorizedFill, now: float) -> NativeFillValues:
    """Open only selected values, generating a code immediately before its one write."""
    value = claim.value
    values: list[SecretStr] = []
    for item in claim.observation.fields:
        if isinstance(value, BrowserLoginSecret):
            if item.field == "username":
                values.append(SecretStr(value.username.get_secret_value()))
            elif item.field == "password":
                values.append(SecretStr(value.password.get_secret_value()))
            elif item.field == "totp" and value.totp is not None:
                code = browser_code(value.totp, at=now)
                if code.valid_until - now < FILL_SECONDS + 1:
                    raise BrowserFillRefused(BrowserFillReason.TOTP_WINDOW)
                values.append(code.value)
            else:
                raise BrowserFillRefused(BrowserFillReason.FIELD_REFUSED)
        elif isinstance(value, BrowserProfileSecret) and item.field in value.fields:
            values.append(SecretStr(value.fields[item.field].get_secret_value()))
        else:
            raise BrowserFillRefused(BrowserFillReason.FIELD_REFUSED)
    return NativeFillValues(tuple(values))


class BrowserCredentialController:
    """One lifetime, one private CDP page and one Redis ownership lease."""

    def __init__(
        self,
        identity: LiveBrowserIdentity,
        ctx: AuthContext,
        redis: RedisClient,
        page: CdpPage,
        tab_lock: asyncio.Lock,
        snapshot: Callable[[], Snapshot | None],
        protect: Callable[[str], Awaitable[None]],
        sink: BrowserEventSink,
        continue_session: ContinuationOpener | None = None,
    ) -> None:
        self.identity, self.ctx, self.redis = identity, ctx, redis
        self.page, self.tab_lock, self.snapshot, self.protect, self.sink = (
            page,
            tab_lock,
            snapshot,
            protect,
            sink,
        )
        self.lease = BrowserWriterLease(redis, identity)
        self._task: asyncio.Task[None] | None = None
        self._prepared: UUID | None = None
        self._active: UUID | None = None
        self._closed = False
        self._used_at = time.monotonic()
        self.continue_session = continue_session
        self._continuation_prepared: UUID | None = None
        self._continuation_active: UUID | None = None

    @classmethod
    async def create(
        cls,
        *,
        deps: AgentDeps,
        credential_ids: tuple[UUID, ...],
        tab_id: str,
        call_id: str,
        redis: RedisClient,
        page: CdpPage,
        tab_lock: asyncio.Lock,
        snapshot: Callable[[], Snapshot | None],
        protect: Callable[[str], Awaitable[None]],
        sink: BrowserEventSink,
        continue_session: ContinuationOpener | None = None,
    ) -> BrowserCredentialController | None:
        audience = deps.audience
        if (
            not credential_ids
            or deps.organization_id is None
            or deps.run_id is None
            or deps.agent_id is None
            or deps.impersonated
            or deps.delegated
            or audience is None
            or not audience.browses_signed_in
            or audience.shared_transcript
            or audience.user_id is None
            or deps.run_person != audience.user_id
            or deps.user_id != str(audience.user_id)
        ):
            return None
        try:
            _access.enabled(deps.organization_id, audience.user_id)
            require_private_transport()
            identity = LiveBrowserIdentity(
                organization_id=deps.organization_id,
                run_id=deps.run_id,
                agent_id=deps.agent_id,
                user_id=audience.user_id,
                call_id=call_id,
                tab_id=tab_id,
                controller_id=uuid4(),
                credential_ids=credential_ids,
                inherited_credentials=page.inherited_credentials,
            )
            async with get_db_context() as db:
                ctx = await member_context(
                    db, organization_id=identity.organization_id, user_id=identity.user_id
                )
                if ctx is None:
                    return None
                await _access.private_run(db, ctx, identity)
        except BrowserFillRefused:
            return None
        controller = cls(
            identity, ctx, redis, page, tab_lock, snapshot, protect, sink, continue_session
        )
        try:
            await controller.lease.acquire()
            origin = await page.credentials.origin()
            if origin:
                await controller.lease.observe(origin)
        except BrowserFillRefused:
            await controller.lease.close()
            return None
        except asyncio.CancelledError:
            await controller.lease.close()
            raise
        controller._task = asyncio.create_task(controller._run())
        return controller

    @property
    def alive(self) -> bool:
        return not self._closed and self._task is not None and not self._task.done()

    async def _receipt(self, reason: BrowserFillReason) -> None:
        await self._continuation_receipt(BrowserContinuationReason.OWNERSHIP_LOST)
        plan_id = self._active or self._prepared
        if plan_id is None:
            return
        with anyio.move_on_after(10, shield=True):
            async with get_db_context() as db:
                await BrowserCredentialPlanService(db, self.redis).refuse(
                    self.identity,
                    plan_id,
                    reason,
                    output_protected=self.page.output_guard.active,
                )

    async def _run(self) -> None:
        try:
            while time.monotonic() - self._used_at < IDLE_SECONDS:
                async with self.tab_lock:
                    await self.lease.check()
                    origin = await self.page.credentials.origin()
                    if origin:
                        await self.lease.observe(origin)
                    async with get_db_context() as db:
                        plan = await BrowserCredentialPlanService(db, self.redis).pending(
                            self.ctx, self.identity
                        )
                    if plan is not None:
                        self._used_at = time.monotonic()
                        self._active = plan.plan_id
                        try:
                            await self._step(plan)
                        except BrowserFillRefused as refused:
                            await self._receipt(refused.reason)
                            await self.page.credentials.close()
                            self._prepared = None
                        finally:
                            self._active = None
                    elif self.continue_session is not None:
                        await self._poll_continuation()
                await asyncio.sleep(POLL_SECONDS)
        except BrowserFillRefused as refused:
            await self._receipt(refused.reason)
        except asyncio.CancelledError:
            await self._receipt(BrowserFillReason.OWNERSHIP_LOST)
            raise
        except Exception:
            # A failed native command or persistence call can contain private transport
            # details. Only the durable fixed receipt leaves this boundary.
            await self._receipt(BrowserFillReason.PROVIDER_UNAVAILABLE)
        finally:
            self._closed = True
            try:
                await self.page.credentials.close()
            finally:
                try:
                    if self.continue_session is not None:
                        await self.page.continuation.close()
                finally:
                    await self.lease.close()

    async def _continuation_receipt(self, reason: BrowserContinuationReason) -> None:
        continuation_id = self._continuation_active or self._continuation_prepared
        if continuation_id is None:
            return
        with anyio.move_on_after(10, shield=True):
            async with get_db_context() as db:
                await BrowserCredentialContinuationService(db, self.redis).refuse(
                    self.identity, continuation_id, reason
                )

    async def _poll_continuation(self) -> None:
        async with get_db_context() as db:
            pending = await BrowserCredentialContinuationService(db, self.redis).pending(
                self.ctx, self.identity
            )
        if pending is None:
            return
        self._used_at = time.monotonic()
        self._continuation_active = pending.id
        try:
            await self._step_continuation(pending)
        except BrowserContinuationRefused as refused:
            await self._continuation_receipt(refused.reason)
            await self.page.continuation.close()
            self._continuation_prepared = None
        finally:
            self._continuation_active = None

    async def _step_continuation(self, plan: NativeContinuation) -> None:
        native = self.page.continuation
        if plan.state == BrowserContinuationState.REQUESTED:
            seen = await native.prepare()
            async with get_db_context() as db:
                await BrowserCredentialContinuationService(db, self.redis).prepare(
                    self.ctx, self.identity, plan.id, seen
                )
            self._continuation_prepared = plan.id
            return
        if self._continuation_prepared != plan.id:
            raise BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED)
        seen = await native.verify()
        if plan.observation != seen:
            raise BrowserContinuationRefused(BrowserContinuationReason.DOCUMENT_CHANGED)
        if plan.state != BrowserContinuationState.APPROVED:
            return
        if self.continue_session is None:
            raise BrowserContinuationRefused(BrowserContinuationReason.NOT_AVAILABLE)
        require_private_transport()
        await self.lease.check()
        async with get_db_context() as db:
            claim = await BrowserCredentialContinuationService(db, self.redis).claim(
                self.ctx, self.identity, plan.id, seen
            )
        # Keep cleanup outside the DB context: a failed commit must close the new
        # owned page too, while the already committed claim remains non-retryable.
        with anyio.fail_after(40):
            async with AsyncExitStack() as opened, get_db_context() as db:
                service = BrowserCredentialContinuationService(db, self.redis)
                await service.authorize_effect(self.ctx, self.identity, claim)
                await self.lease.check()
                require_private_transport()
                cookies = await native.export(now=time.time())
                state = ProtectedSignIn(provenance=claim.provenance, cookies=cookies)
                await opened.enter_async_context(self.continue_session(claim, state))
                await self.lease.check()
                await service.finish(self.ctx, self.identity, claim, state)
        await native.close()
        self._continuation_prepared = None

    async def _step(self, plan: NativePlan) -> None:
        native = self.page.credentials
        if plan.state == BrowserFillState.REQUESTED:
            seen = self.snapshot()
            if seen is None:
                raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED)
            observation = await native.prepare(plan.selection, seen)
            async with get_db_context() as db:
                await BrowserCredentialPlanService(db, self.redis).prepare(
                    self.ctx, self.identity, plan.plan_id, observation
                )
            self._prepared = plan.plan_id
            return
        expected = (
            plan.parent_plan_id if plan.operation == BrowserFillOperation.SUBMIT else plan.plan_id
        )
        if self._prepared != expected:
            raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED)
        observation = (
            await native.verify_submission()
            if plan.operation == BrowserFillOperation.SUBMIT
            else await native.verify()
        )
        if plan.observation != observation:
            raise BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED)
        if plan.state != BrowserFillState.APPROVED:
            return
        await self.protect(observation.origin)
        require_private_transport()
        await self.lease.check()
        async with get_db_context() as db:
            claim = await BrowserCredentialPlanService(db, self.redis).claim(
                self.ctx,
                self.identity,
                plan.plan_id,
                observation,
                output_protected=self.page.output_guard.active,
            )
        # The claim is committed before the external effect. Recheck and hold the
        # credential lock across this bounded effect, so rotation/policy revocation
        # cannot overtake a write already admitted at this final boundary.
        async with get_db_context() as db:
            service = BrowserCredentialPlanService(db, self.redis)
            await service.authorize_effect(self.ctx, self.identity, claim)
            await self.lease.check()
            require_private_transport()
            with anyio.fail_after(20):
                if claim.operation == BrowserFillOperation.FILL:
                    filled = await native.fill(lambda: fill_values(claim, time.time()))
                else:
                    filled = await native.submit()
            await service.finish(self.identity, claim, filled=filled)
        if not filled or claim.operation == BrowserFillOperation.SUBMIT:
            await native.close()
            self._prepared = None

    async def request(
        self,
        secret_id: UUID,
        generation: UUID,
        selection: BrowserFillSelection,
    ) -> BrowserCredentialPlanRead:
        if not self.alive:
            raise BrowserFillRefused(BrowserFillReason.LIVE_BROWSER_REQUIRED)
        self._used_at = time.monotonic()
        async with get_db_context() as db:
            return await BrowserCredentialPlanService(db, self.redis).request(
                self.ctx,
                self.identity.run_id,
                BrowserCredentialRequest(
                    request_id=uuid4(),
                    secret_id=secret_id,
                    authorization_generation=generation,
                    call_id=self.identity.call_id,
                    tab_id=self.identity.tab_id,
                    fields=selection.fields,
                ),
            )

    async def wait(self, plan_id: UUID) -> str:
        """Keep native handles alive for human confirmation, then a separate optional submit."""
        notified: set[str] = set()
        with anyio.move_on_after(
            (4 if self.continue_session is not None else 2) * PLAN_SECONDS + 10
        ):
            while self.alive:
                async with get_db_context() as db:
                    service = BrowserCredentialPlanService(db, self.redis)
                    row = await service.get(self.ctx, self.identity.run_id, plan_id)
                    submission = (
                        await service.submitted(self.ctx, self.identity.run_id, plan_id)
                        if row.state == BrowserFillState.FILLED
                        else None
                    )
                if row.state == BrowserFillState.AWAITING_CONFIRMATION and "fill" not in notified:
                    await self.sink(
                        BrowserEvent(
                            kind="browser_needs_person",
                            call_id=self.identity.call_id,
                            step=0,
                            run_id=str(self.identity.run_id),
                            tab_id=self.identity.tab_id,
                            credential_plan_id=str(row.id),
                            credential_operation="fill",
                            url=row.origin,
                            reason="Review the destination and selected credential fields.",
                        )
                    )
                    notified.add("fill")
                if row.state == BrowserFillState.FILLED:
                    if "submit" not in notified:
                        await self.sink(
                            BrowserEvent(
                                kind="browser_needs_person",
                                call_id=self.identity.call_id,
                                step=0,
                                run_id=str(self.identity.run_id),
                                tab_id=self.identity.tab_id,
                                credential_plan_id=str(row.id),
                                credential_operation="submit",
                                url=row.origin,
                                reason="Fields were filled. Submitting the protected form requires a separate action.",
                            )
                        )
                        notified.add("submit")
                    if submission is not None and submission.state not in ACTIVE_FILL_STATES:
                        if (
                            submission.state == BrowserFillState.SUBMITTED
                            and self.continue_session is not None
                        ):
                            async with get_db_context() as db:
                                continuation = await BrowserCredentialContinuationService(
                                    db, self.redis
                                ).get(self.ctx, self.identity.run_id, submission.id)
                            if (
                                continuation is None
                                or continuation.state in ACTIVE_CONTINUATION_STATES
                            ):
                                await asyncio.sleep(POLL_SECONDS)
                                continue
                            return (
                                f"Protected session continuation: {continuation.state.value}. "
                                f"Protected tab: {continuation.continuation_tab_id or 'unavailable'}. "
                                "Page output remains hidden; authentication was not inferred."
                            )
                        return f"Protected browser submission: {submission.state.value}. Page output remains hidden."
                elif row.state not in ACTIVE_FILL_STATES:
                    return f"Browser credential operation: {row.state.value}. No automatic retry was made."
                await asyncio.sleep(POLL_SECONDS)
        return "The protected credential session ended. Page output remains hidden; no form was submitted automatically."

    async def close(self) -> None:
        self._closed = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with anyio.move_on_after(15, shield=True):
                with suppress(asyncio.CancelledError):
                    await self._task
        # A task cancelled before its first scheduling turn never enters _run's
        # finally block. Cleanup is idempotent and must also cover that interval.
        with anyio.move_on_after(12, shield=True):
            try:
                await self.page.credentials.close()
            finally:
                try:
                    if self.continue_session is not None:
                        await self.page.continuation.close()
                finally:
                    await self.lease.close()
