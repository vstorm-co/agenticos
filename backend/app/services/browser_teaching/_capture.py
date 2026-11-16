"""Capture belongs to the live page, and only accepted inputs from its exact socket."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

import anyio

from app.agents.browser_events import BrowserCommand, BrowserEvent, BrowserEventSink
from app.agents.capabilities.browser_use._decision import Action
from app.agents.capabilities.browser_use._elements import Element
from app.agents.capabilities.browser_use._protected import BrowserOutputGuard
from app.agents.capabilities.browser_use._teaching_hooks import TeachingInput
from app.agents.capabilities.browser_use._teaching_page import TeachingPage
from app.agents.deps import AgentDeps
from app.clients.redis import RedisClient
from app.core.browser_teaching import (
    CaptureObservation,
    TeachingReason,
    TeachingRefused,
    TeachingState,
)
from app.core.permissions import AuthContext
from app.db.session import get_db_context
from app.repositories import browser_teaching as repo
from app.schemas.browser_teaching import TeachingRead

from . import _access
from ._lease import RENEW_SECONDS, TeachingIdentity, TeachingLease, TeachingTakeover
from ._refinement_capture import BrowserRefinementCapture, LocateTeachingTarget
from ._service import BrowserTeachingService, matches, require_capture_time


class BrowserTeachingCapture:
    def __init__(
        self,
        *,
        context: AuthContext,
        identity: TeachingIdentity,
        redis: RedisClient,
        page: TeachingPage,
        guard: BrowserOutputGuard,
        step: Callable[[], int],
        locate: LocateTeachingTarget | None = None,
    ) -> None:
        self.context, self.identity, self.redis = context, identity, redis
        self.page, self.guard, self.step = page, guard, step
        self._lease: TeachingLease | None = None
        self._heartbeat: asyncio.Task[None] | None = None
        self._emit: BrowserEventSink | None = None
        self._blocked = False
        self._redacting = False
        self._origin: str | None = None
        self._session_id: UUID | None = None
        self._refinement = BrowserRefinementCapture(
            context=context,
            identity=identity,
            page=page,
            guard=guard,
            step=step,
            locate=locate,
        )

    @classmethod
    async def create(
        cls,
        *,
        deps: AgentDeps,
        tab_id: str,
        redis: RedisClient,
        page: TeachingPage,
        guard: BrowserOutputGuard,
        step: Callable[[], int],
        locate: LocateTeachingTarget | None = None,
    ) -> BrowserTeachingCapture | None:
        audience = deps.audience
        if (
            deps.organization_id is None
            or deps.run_id is None
            or deps.agent_id is None
            or deps.impersonated
            or deps.delegated
            or audience is None
            or not audience.browses_signed_in
            or not audience.private
            or audience.user_id is None
            or audience.shared_transcript
            or deps.run_person != audience.user_id
            or deps.user_id != str(audience.user_id)
            or not _access.deployment_enabled(deps.organization_id)
            or guard.active
        ):
            return None
        identity = TeachingIdentity(
            organization_id=deps.organization_id,
            run_id=deps.run_id,
            agent_id=deps.agent_id,
            user_id=audience.user_id,
            controller_id=uuid4(),
            tab_id=tab_id,
            call_id="unheld",
        )
        context = AuthContext(
            user_id=identity.user_id, organization_id=identity.organization_id, role="member"
        )
        try:
            async with get_db_context() as db:
                admission = await _access.admit(db, context, identity, live=True)
        except TeachingRefused:
            return None
        return cls(
            context=admission.context,
            identity=identity,
            redis=redis,
            page=page,
            guard=guard,
            step=step,
            locate=locate,
        )

    async def begin_task(self, call_id: str, emit: BrowserEventSink | None) -> None:
        if not self._blocked and self._lease is None:
            await self._refinement.begin(call_id, emit)
            if self._refinement.redacting:
                self._redacting, self._origin = True, self._refinement.origin

    async def before_action(self, action: Action, element: Element | None) -> TeachingInput | None:
        return await self._refinement.before(action, element)

    async def after_action(self, prepared: TeachingInput | None) -> None:
        await self._refinement.after(prepared)

    async def finish_task(self, *, completed: bool) -> None:
        await self._refinement.finish(completed=completed)

    async def begin(
        self,
        *,
        call_id: str,
        connection_id: UUID | None,
        user_id: str | None,
        emit: BrowserEventSink,
    ) -> UUID | None:
        await self.end()
        if (
            self._blocked
            or self.guard.active
            or connection_id is None
            or user_id != str(self.identity.user_id)
        ):
            return None
        held = TeachingTakeover(
            **self.identity.model_copy(update={"call_id": call_id}).model_dump(),
            connection_id=connection_id,
            takeover_id=uuid4(),
        )
        lease = TeachingLease(self.redis, held)
        try:
            async with get_db_context() as db:
                await _access.admit(db, self.context, held, live=True)
            origin = await self.page.observe("origin")
            await lease.acquire()
        except TeachingRefused:
            await lease.close()
            return None
        except BaseException:
            await lease.close()
            raise
        self._lease, self._emit = lease, emit
        self._session_id = None
        self._redacting, self._origin = True, origin.origin
        self._heartbeat = asyncio.create_task(self._maintain())
        return held.takeover_id

    async def _publish(
        self, data: TeachingRead | None, reason: TeachingReason | None = None
    ) -> None:
        if self._emit is None or self._lease is None:
            return
        if data is not None:
            self._session_id = data.id
        selected_reason = (
            reason if reason is not None else None if data is None else data.reason_code
        )
        await self._emit(
            BrowserEvent(
                kind="browser_teaching",
                call_id=self._lease.identity.call_id,
                tab_id=self.identity.tab_id,
                run_id=str(self.identity.run_id),
                step=self.step(),
                teaching_session_id=self._session_id,
                teaching_status=TeachingState.PAUSED if data is None else data.status,
                teaching_revision=None if data is None else data.revision,
                teaching_reason=selected_reason,
            )
        )

    async def _pause(self, reason: TeachingReason) -> None:
        lease = self._lease
        if lease is None:
            return
        data = None
        with anyio.move_on_after(3, shield=True):
            with suppress(Exception):
                async with get_db_context() as db:
                    data = await BrowserTeachingService(db, self.redis).pause_live(
                        lease.identity, reason
                    )
        with anyio.move_on_after(3, shield=True):
            with suppress(Exception):
                await self._publish(data, reason)

    async def _maintain(self) -> None:
        try:
            while self._lease is not None:
                await asyncio.sleep(RENEW_SECONDS)
                lease = self._lease
                if lease is None:
                    return
                await lease.check()
                async with get_db_context() as db:
                    await _access.admit(db, self.context, lease.identity, live=True)
                    row = await repo.active(
                        db, lease.identity.organization_id, lease.identity.controller_id
                    )
                    if row is not None and matches(row, lease.identity):
                        await _access.authorize(db, self.context, row, live=True)
                        require_capture_time(row, datetime.now(UTC))
        except TeachingRefused as refused:
            await self._end(refused.reason)
        except Exception:
            await self._end(TeachingReason.NATIVE_UNAVAILABLE)

    async def before_input(self, command: BrowserCommand) -> TeachingInput | None:
        lease = self._lease
        if lease is None or self._blocked or self.guard.active:
            return None
        if (
            command.control_connection_id != lease.identity.connection_id
            or command.by_user_id != str(lease.identity.user_id)
            or command.control_sequence is None
        ):
            return None
        if command.type in {"take_over", "give_back", "control_lost", "resize"}:
            return None
        try:
            await lease.check()
            async with get_db_context() as db:
                row = await repo.active(
                    db, lease.identity.organization_id, lease.identity.controller_id
                )
                if (
                    row is None
                    or row.status != TeachingState.RECORDING
                    or not matches(row, lease.identity)
                ):
                    return None
                self._session_id = row.id
                await _access.authorize(db, self.context, row, live=True)
            input_id = uuid5(lease.identity.connection_id, str(command.control_sequence))
            if command.type in {"navigate", "back", "forward", "reload"}:
                if command.type == "navigate" and command.url is None:
                    return None
                return TeachingInput(input_id, "navigate", None)
            if command.type == "scroll":
                if command.dy is None or command.dy == 0:
                    return None
                return TeachingInput(
                    input_id,
                    "scroll",
                    await self.page.observe("origin"),
                    "up" if command.dy < 0 else "down",
                )
            if command.type == "click":
                if command.x is None or command.y is None:
                    return None
                observed = await self.page.observe("point", x=command.x, y=command.y)
                return TeachingInput(input_id, "click", observed)
            if command.type == "type":
                if command.text is None:
                    return None
                observed = await self.page.observe("focus")
                return TeachingInput(
                    input_id,
                    "select"
                    if observed.target is not None and observed.target.role == "combobox"
                    else "input_parameter",
                    observed,
                )
            # No keystrokes are recorded. Enter/other keyboard actions that cannot
            # be proven as a structural click become an explicit human checkpoint.
            if command.key in {"Tab", "Shift+Tab", "Escape"} or command.key is None:
                return None
            observed = await self.page.observe("focus")
            if (
                observed.target is not None
                and observed.target.role == "combobox"
                and command.key in {"ArrowDown", "ArrowUp", "Home", "End", "Enter"}
            ):
                # The choice becomes a reviewed parameter. Neither the key nor
                # the page's option value is retained in the demonstration.
                return TeachingInput(input_id, "select", observed)
            if (
                command.key == "Enter"
                and observed.target is not None
                and observed.target.role in {"button", "link"}
            ):
                return TeachingInput(input_id, "click", observed)
            return TeachingInput(
                input_id,
                "checkpoint",
                CaptureObservation(origin=observed.origin, human_required=True),
            )
        except TeachingRefused as refused:
            await self._pause(refused.reason)
            return None
        except Exception:
            await self._end(TeachingReason.NATIVE_UNAVAILABLE)
            return None

    async def after_input(self, prepared: TeachingInput | None) -> None:
        lease = self._lease
        if prepared is None or lease is None or self._blocked or self.guard.active:
            return
        try:
            await lease.check()
            observed = prepared.observation or await self.page.observe("origin")
            self._origin = observed.origin
            async with get_db_context() as db:
                data = await BrowserTeachingService(db, self.redis).append(
                    self.context,
                    lease.identity,
                    input_id=prepared.input_id,
                    action=prepared.action,
                    observation=observed,
                    direction=prepared.direction,
                )
            await self._publish(data)
        except TeachingRefused as refused:
            await self._pause(refused.reason)
        except Exception:
            await self._end(TeachingReason.NATIVE_UNAVAILABLE)

    async def failed_input(self) -> None:
        await self._pause(TeachingReason.NATIVE_UNAVAILABLE)

    async def end(self) -> None:
        await self._refinement.finish(completed=False, reason=TeachingReason.OWNERSHIP_LOST)
        await self._end(TeachingReason.OWNERSHIP_LOST)

    async def _end(self, reason: TeachingReason) -> None:
        task, self._heartbeat = self._heartbeat, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self._pause(reason)
        lease, self._lease = self._lease, None
        if lease is not None:
            await lease.close()
        self._emit = None

    async def protect(self) -> None:
        self._blocked = True
        await self._refinement.finish(completed=False, reason=TeachingReason.PROTECTED)
        await self._end(TeachingReason.PROTECTED)

    async def close(self) -> None:
        self._blocked = True
        await self.end()

    def event(self, event: BrowserEvent) -> BrowserEvent:
        if not self._redacting and not self._refinement.redacting:
            return event
        # Preview images remain ephemeral live-view data, never teaching payloads.
        # The credential guard runs after this and removes images permanently.
        return BrowserEvent(
            kind=event.kind,
            call_id=event.call_id,
            step=event.step,
            tab_id=event.tab_id,
            run_id=event.run_id,
            outcome=event.outcome,
            image=event.image,
            by_user_id=event.by_user_id,
            takeover_id=event.takeover_id,
            teaching_session_id=event.teaching_session_id,
            teaching_status=event.teaching_status,
            teaching_revision=event.teaching_revision,
            teaching_reason=event.teaching_reason,
            credential_plan_id=event.credential_plan_id,
            credential_operation=event.credential_operation,
            url=self._origin if self._redacting else self._refinement.origin,
            title="Browser teaching",
            navigable=event.navigable,
            detail="Browser input unavailable"
            if event.kind == "browser_control_error" and event.detail
            else None,
        )
