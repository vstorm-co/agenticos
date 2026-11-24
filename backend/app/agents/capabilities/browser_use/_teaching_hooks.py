"""Typed hooks at the one accepted browser-input boundary."""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from app.agents.browser_events import BrowserCommand, BrowserEvent, BrowserEventSink
from app.agents.capabilities.browser_use._decision import Action
from app.agents.capabilities.browser_use._elements import Element
from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingAction,
    BrowserProcedureTeachingObservation,
)


@dataclass(frozen=True)
class BrowserProcedureTeachingInput:
    input_id: UUID
    action: BrowserProcedureTeachingAction
    observation: BrowserProcedureTeachingObservation | None
    direction: Literal["up", "down"] | None = None


class BrowserProcedureTeachingCapture(Protocol):
    async def begin_task(self, call_id: str, emit: BrowserEventSink | None) -> None: ...

    async def before_action(
        self, action: Action, element: Element | None
    ) -> BrowserProcedureTeachingInput | None: ...

    async def after_action(self, prepared: BrowserProcedureTeachingInput | None) -> None: ...

    async def finish_task(self, *, completed: bool) -> None: ...

    async def begin(
        self,
        *,
        call_id: str,
        connection_id: UUID | None,
        user_id: str | None,
        emit: BrowserEventSink,
    ) -> UUID | None: ...

    async def before_input(
        self, command: BrowserCommand
    ) -> BrowserProcedureTeachingInput | None: ...

    async def after_input(self, prepared: BrowserProcedureTeachingInput | None) -> None: ...

    async def failed_input(self) -> None: ...

    async def end(self) -> None: ...

    async def protect(self) -> None: ...

    async def close(self) -> None: ...

    def event(self, event: BrowserEvent) -> BrowserEvent: ...
