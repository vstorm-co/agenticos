"""Value-free recording at the native action boundary of one opted-in browser task."""

from collections.abc import Awaitable, Callable
from contextlib import suppress
from uuid import UUID, uuid5

import anyio

from app.agents.browser_events import BrowserEvent, BrowserEventSink
from app.agents.capabilities.browser_use._decision import (
    Action,
    Click,
    GoBack,
    Navigate,
    Scroll,
    Select,
    TypeText,
)
from app.agents.capabilities.browser_use._elements import Element
from app.agents.capabilities.browser_use._protected import BrowserOutputGuard
from app.agents.capabilities.browser_use._teaching_hooks import BrowserProcedureTeachingInput
from app.agents.capabilities.browser_use._teaching_page import BrowserProcedureTeachingPage
from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
    BrowserProcedureTeachingState,
)
from app.core.permissions import AuthContext
from app.db.session import get_db_context
from app.schemas.browser_procedure_teaching import BrowserProcedureTeachingRead

from . import _refinement
from ._lease import BrowserProcedureTeachingIdentity

LocateBrowserProcedureTeachingTarget = Callable[[Element], Awaitable[tuple[float, float]]]


class BrowserProcedureTeachingRefinementCapture:
    def __init__(
        self,
        *,
        context: AuthContext,
        identity: BrowserProcedureTeachingIdentity,
        page: BrowserProcedureTeachingPage,
        guard: BrowserOutputGuard,
        step: Callable[[], int],
        locate: LocateBrowserProcedureTeachingTarget | None,
    ) -> None:
        self.context, self.identity, self.page = context, identity, page
        self.guard, self.step, self.locate = guard, step, locate
        self.redacting = False
        self.origin: str | None = None
        self._session_id: UUID | None = None
        self._emit: BrowserEventSink | None = None
        self._sequence = 0

    async def _publish(self, data: BrowserProcedureTeachingRead) -> None:
        if self._emit is not None:
            await self._emit(
                BrowserEvent(
                    kind="browser_procedure_teaching",
                    call_id=self.identity.call_id,
                    tab_id=self.identity.tab_id,
                    run_id=str(self.identity.run_id),
                    step=self.step(),
                    teaching_session_id=data.id,
                    teaching_status=data.status,
                    teaching_revision=data.revision,
                    teaching_reason=data.reason_code,
                )
            )

    async def begin(self, call_id: str, emit: BrowserEventSink | None) -> None:
        await self.finish(completed=False)
        if self.guard.active or self.locate is None or emit is None:
            return
        self.identity = self.identity.model_copy(update={"call_id": call_id})
        try:
            with anyio.fail_after(10):
                origin = (await self.page.observe("origin")).origin
                async with get_db_context() as db:
                    data = await _refinement.start(db, self.context, self.identity, origin)
                if data is None:
                    return
                self._session_id, self._emit, self._sequence = data.id, emit, 0
                self.redacting, self.origin = True, origin
                await self._publish(data)
        except BrowserProcedureTeachingRefused as refused:
            await self.finish(completed=False, reason=refused.reason)
        except Exception:
            await self.finish(
                completed=False, reason=BrowserProcedureTeachingReason.NATIVE_UNAVAILABLE
            )

    async def before(
        self, action: Action, element: Element | None
    ) -> BrowserProcedureTeachingInput | None:
        session_id = self._session_id
        if session_id is None:
            return None
        if self.guard.active:
            await self.finish(completed=False, reason=BrowserProcedureTeachingReason.PROTECTED)
            return None
        if not isinstance(action, (Click, TypeText, Select, Scroll, Navigate, GoBack)):
            return None
        try:
            with anyio.fail_after(10):
                async with get_db_context() as db:
                    await _refinement.authorize_capture(db, self.context, self.identity, session_id)
                self._sequence += 1
                input_id = uuid5(session_id, str(self._sequence))
                if isinstance(action, (Navigate, GoBack)):
                    return BrowserProcedureTeachingInput(input_id, "navigate", None)
                if isinstance(action, Scroll):
                    return BrowserProcedureTeachingInput(
                        input_id,
                        "scroll",
                        await self.page.observe("origin"),
                        action.direction,
                    )
                if element is None or self.locate is None:
                    await self.finish(
                        completed=False, reason=BrowserProcedureTeachingReason.NATIVE_UNAVAILABLE
                    )
                    return None
                x, y = await self.locate(element)
                observed = await self.page.observe("point", x=x, y=y)
                kind = (
                    "click"
                    if isinstance(action, Click)
                    else "select"
                    if isinstance(action, Select)
                    else "input_parameter"
                )
                return BrowserProcedureTeachingInput(input_id, kind, observed)
        except BrowserProcedureTeachingRefused as refused:
            await self.finish(completed=False, reason=refused.reason)
        except Exception:
            await self.finish(
                completed=False, reason=BrowserProcedureTeachingReason.NATIVE_UNAVAILABLE
            )
        return None

    async def after(self, prepared: BrowserProcedureTeachingInput | None) -> None:
        session_id = self._session_id
        if prepared is None or session_id is None:
            return
        if self.guard.active:
            await self.finish(completed=False, reason=BrowserProcedureTeachingReason.PROTECTED)
            return
        try:
            with anyio.fail_after(10):
                current = await self.page.observe("origin")
                if current.origin != self.origin:
                    await self.finish(
                        completed=False, reason=BrowserProcedureTeachingReason.ORIGIN_REFUSED
                    )
                    return
                async with get_db_context() as db:
                    data = await _refinement.append(
                        db,
                        self.context,
                        self.identity,
                        session_id,
                        input_id=prepared.input_id,
                        action=prepared.action,
                        observation=prepared.observation or current,
                        direction=prepared.direction,
                    )
                await self._publish(data)
                if data.status != BrowserProcedureTeachingState.RECORDING:
                    await self.finish(
                        completed=False,
                        reason=data.reason_code
                        or BrowserProcedureTeachingReason.NATIVE_UNAVAILABLE,
                    )
        except BrowserProcedureTeachingRefused as refused:
            await self.finish(completed=False, reason=refused.reason)
        except Exception:
            await self.finish(
                completed=False, reason=BrowserProcedureTeachingReason.NATIVE_UNAVAILABLE
            )

    async def finish(
        self,
        *,
        completed: bool,
        reason: BrowserProcedureTeachingReason = BrowserProcedureTeachingReason.TASK_NOT_COMPLETED,
    ) -> None:
        session_id, self._session_id = self._session_id, None
        if session_id is None:
            return
        # Uncertain cleanup cannot claim success or retry a browser action. The
        # always-on sweep erases abandoned recordings when their run ends.
        with anyio.move_on_after(10, shield=True):
            with suppress(Exception):
                if self.guard.active:
                    completed, reason = False, BrowserProcedureTeachingReason.PROTECTED
                elif completed:
                    try:
                        if (await self.page.observe("origin")).origin != self.origin:
                            completed, reason = False, BrowserProcedureTeachingReason.ORIGIN_REFUSED
                    except BrowserProcedureTeachingRefused:
                        completed, reason = False, BrowserProcedureTeachingReason.NATIVE_UNAVAILABLE
                async with get_db_context() as db:
                    data = await _refinement.finish(
                        db,
                        self.context,
                        self.identity,
                        session_id,
                        completed=completed,
                        reason=reason,
                    )
                if data is not None:
                    await self._publish(data)
        self._emit = None
