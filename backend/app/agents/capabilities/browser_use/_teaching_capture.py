"""Compose simple and procedure capture without letting either affect browser actions."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from app.agents.browser_events import BrowserCommand, BrowserEvent, BrowserEventSink
from app.agents.capabilities.browser_use._decision import Action
from app.agents.capabilities.browser_use._elements import Element
from app.agents.capabilities.browser_use._protected import BrowserOutputGuard
from app.agents.capabilities.browser_use._teach import TeachCapture
from app.agents.capabilities.browser_use._teaching_hooks import (
    BrowserProcedureTeachingCapture as BrowserProcedureTeachingCaptureProtocol,
)
from app.agents.capabilities.browser_use._teaching_hooks import (
    BrowserProcedureTeachingInput,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PreparedInput:
    simple: object | None
    procedure: BrowserProcedureTeachingInput | None


class BrowserTeachingCapture:
    """Fan lifecycle calls out to two capture types, with one sticky output gate."""

    def __init__(
        self,
        simple: TeachCapture | None,
        procedure: BrowserProcedureTeachingCaptureProtocol | None,
        guard: BrowserOutputGuard,
    ) -> None:
        self.simple, self.procedure, self.guard = simple, procedure, guard
        self._protected = False
        self._closed = False
        self._simple_disabled = False
        self._procedure_disabled = False

    async def begin_task(self, call_id: str, emit: BrowserEventSink | None) -> None:
        if self._blocked or self.procedure is None or self._procedure_disabled:
            return
        try:
            await self.procedure.begin_task(call_id, emit)
        except Exception as exc:
            await self._disable_procedure(exc)

    async def before_action(
        self, action: Action, element: Element | None
    ) -> BrowserProcedureTeachingInput | None:
        if self._blocked or self.procedure is None or self._procedure_disabled:
            return None
        try:
            return await self.procedure.before_action(action, element)
        except Exception as exc:
            await self._disable_procedure(exc)
            return None

    async def after_action(self, prepared: BrowserProcedureTeachingInput | None) -> None:
        if self._blocked or self.procedure is None or self._procedure_disabled:
            return
        try:
            await self.procedure.after_action(prepared)
        except Exception as exc:
            await self._disable_procedure(exc)

    async def finish_task(self, *, completed: bool) -> None:
        if self._blocked or self.procedure is None or self._procedure_disabled:
            return
        try:
            await self.procedure.finish_task(completed=completed)
        except Exception as exc:
            await self._disable_procedure(exc)

    async def begin(
        self,
        call_id: str,
        by_user_id: str | None = None,
        *,
        connection_id: UUID | None = None,
        user_id: str | None = None,
        emit: BrowserEventSink | None = None,
    ) -> UUID | None:
        """Begin the simple hold and, when given a live socket, the rich takeover."""
        if self._blocked:
            return None
        resolved_user_id = user_id if user_id is not None else by_user_id
        if self.simple is not None and not self._simple_disabled:
            try:
                await self.simple.begin(call_id, resolved_user_id)
            except Exception as exc:
                await self._disable_simple(exc)
        if emit is None or self.procedure is None or self._procedure_disabled:
            return None
        try:
            return await self.procedure.begin(
                call_id=call_id,
                connection_id=connection_id,
                user_id=resolved_user_id,
                emit=emit,
            )
        except Exception as exc:
            await self._disable_procedure(exc)
            return None

    async def before_input(self, command: BrowserCommand) -> object | None:
        if self._blocked:
            return None
        simple: object | None = None
        procedure: BrowserProcedureTeachingInput | None = None
        if self.simple is not None and not self._simple_disabled:
            try:
                simple = await self.simple.before_input(command)
            except Exception as exc:
                await self._disable_simple(exc)
        if self.procedure is not None and not self._procedure_disabled:
            try:
                procedure = await self.procedure.before_input(command)
            except Exception as exc:
                await self._disable_procedure(exc)
        if simple is None and procedure is None:
            return None
        return _PreparedInput(simple=simple, procedure=procedure)

    async def after_input(self, prepared: object | None) -> None:
        if self._blocked or not isinstance(prepared, _PreparedInput):
            return
        if self.simple is not None and not self._simple_disabled:
            try:
                await self.simple.after_input(prepared.simple)
            except Exception as exc:
                await self._disable_simple(exc)
        if self.procedure is not None and not self._procedure_disabled:
            try:
                await self.procedure.after_input(prepared.procedure)
            except Exception as exc:
                await self._disable_procedure(exc)

    async def failed_input(self) -> None:
        if self._blocked:
            return
        if self.simple is not None and not self._simple_disabled:
            try:
                await self.simple.failed_input()
            except Exception as exc:
                await self._disable_simple(exc)
        if self.procedure is not None and not self._procedure_disabled:
            try:
                await self.procedure.failed_input()
            except Exception as exc:
                await self._disable_procedure(exc)

    async def end(self) -> None:
        if self._closed:
            return
        if self.simple is not None:
            await self._quiet(self.simple.end)
        if self.procedure is not None:
            await self._quiet(self.procedure.end)

    async def protect(self) -> None:
        # Close admission synchronously before cleanup awaits; page.protect() is
        # activated by the caller after these capture leases have been stopped.
        self._protected = True
        if self.simple is not None:
            await self._quiet(self.simple.end)
        if self.procedure is not None:
            await self._quiet(self.procedure.protect)

    async def close(self) -> None:
        self._closed = True
        self._protected = True
        if self.simple is not None:
            await self._quiet(self.simple.end)
        if self.procedure is not None:
            await self._quiet(self.procedure.close)

    async def event(self, event: BrowserEvent) -> BrowserEvent:
        if self._blocked:
            return self.guard.event(event)
        if self.procedure is not None and not self._procedure_disabled:
            try:
                return self.procedure.event(event)
            except Exception as exc:
                logger.warning("Browser procedure teaching event failed (%s)", type(exc).__name__)
                self._procedure_disabled = True
                self._simple_disabled = True
                self._protected = True
                if self.simple is not None:
                    await self._quiet(self.simple.end)
                if self.procedure is not None:
                    await self._quiet(self.procedure.end)
                return self.guard.event(event)
        return event

    @property
    def _blocked(self) -> bool:
        return self._protected or self._closed or self.guard.active

    async def _disable_simple(self, exc: Exception) -> None:
        logger.warning("Browser teaching capture failed (%s)", type(exc).__name__)
        self._simple_disabled = True
        if self.simple is not None:
            await self._quiet(self.simple.end)

    async def _disable_procedure(self, exc: Exception) -> None:
        logger.warning("Browser procedure teaching capture failed (%s)", type(exc).__name__)
        self._procedure_disabled = True
        if self.procedure is not None:
            await self._quiet(self.procedure.end)

    @staticmethod
    async def _quiet(operation: Callable[[], Awaitable[None]]) -> None:
        try:
            await operation()
        except Exception as exc:
            logger.warning("Browser teaching cleanup failed (%s)", type(exc).__name__)
