"""Capture attached to one managed tab, active only while the run's own person holds it.

Created per browse session when the deployment flag admits the organization
and the run is the person at the keyboard, privately, in a T3OS-provisioned
browser. It never records an agent's own actions, another viewer's input, a
native desktop tab or a hosted endpoint. Typed text, keys and URLs are read only
to decide the action kind and are never passed on.

Failures are logged by exception type only and pause the session; they never
reach the browse loop.
"""

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4, uuid5

from app.agents.browser_events import BrowserCommand
from app.agents.deps import AgentDeps
from app.clients.redis import RedisClient
from app.core.browser_teaching import Action, Observation, TeachingReason
from app.db.session import get_db_context
from app.services import live_browse

from . import _access, _hold
from ._hold import RENEW_SECONDS, Hold
from ._observe import ObserveFailed, ObserveFn, observe
from ._service import BrowserTeachingService

logger = logging.getLogger(__name__)

_NAVIGATION = frozenset({"navigate", "back", "forward", "reload"})


@dataclass(frozen=True)
class _Prepared:
    input_id: UUID
    action: Action
    observation: Observation | None
    direction: Literal["up", "down"] | None = None
    failed: bool = False


class HoldCapture:
    def __init__(
        self,
        *,
        organization_id: UUID,
        run_id: UUID,
        agent_id: UUID,
        user_id: UUID,
        tab_id: str,
        redis: RedisClient,
        run_observer: ObserveFn,
    ) -> None:
        self.organization_id, self.run_id, self.agent_id = organization_id, run_id, agent_id
        self.user_id, self.tab_id = user_id, tab_id
        self.redis, self.run_observer = redis, run_observer
        self.hold: Hold | None = None
        self._inputs = 0
        self._renewer: asyncio.Task[None] | None = None

    async def begin(self, call_id: str, by_user_id: str | None) -> None:
        await self.end()
        if by_user_id != str(self.user_id) or not _access.deployment_enabled(self.organization_id):
            return
        hold = Hold(
            organization_id=self.organization_id,
            run_id=self.run_id,
            agent_id=self.agent_id,
            user_id=self.user_id,
            call_id=call_id,
            tab_id=self.tab_id,
            hold_id=uuid4(),
        )
        if await _hold.claim(self.redis, hold):
            self.hold, self._inputs = hold, 0
            self._renewer = asyncio.create_task(self._renew(hold))

    async def _renew(self, hold: Hold) -> None:
        while self.hold == hold:
            await asyncio.sleep(RENEW_SECONDS)
            if self.hold == hold and not await _hold.renew(self.redis, hold):
                self.hold = None
                await self._release(hold, TeachingReason.OWNERSHIP_LOST)
                return

    async def before_input(self, command: BrowserCommand) -> _Prepared | None:
        hold = self.hold
        if hold is None or command.by_user_id != str(hold.user_id):
            return None
        self._inputs += 1
        input_id = uuid5(hold.hold_id, str(self._inputs))
        try:
            return await self._prepare(input_id, command)
        except ObserveFailed:
            return _Prepared(input_id, "checkpoint", None, failed=True)

    async def _prepare(self, input_id: UUID, command: BrowserCommand) -> _Prepared | None:
        if command.type in _NAVIGATION:
            return _Prepared(input_id, "navigate", None)
        if command.type == "scroll" and command.dy:
            seen = await observe(self.run_observer, "origin")
            return _Prepared(input_id, "scroll", seen, "down" if command.dy > 0 else "up")
        if command.type == "click" and command.x is not None and command.y is not None:
            seen = await observe(self.run_observer, "point", command.x, command.y)
            if seen.target is None and not seen.authentication:
                return None
            role = None if seen.target is None else seen.target.role
            return _Prepared(input_id, "select" if role == "combobox" else "click", seen)
        if command.type == "type" and command.text:
            seen = await observe(self.run_observer, "focus")
            if seen.target is None and not seen.authentication:
                return None
            role = None if seen.target is None else seen.target.role
            return _Prepared(input_id, "select" if role == "combobox" else "input_parameter", seen)
        if command.type == "key" and command.key == "Enter":
            seen = await observe(self.run_observer, "focus")
            if seen.target is not None and seen.target.role in ("button", "link"):
                return _Prepared(input_id, "click", seen)
            bare = Observation(origin=seen.origin, authentication=seen.authentication)
            return _Prepared(input_id, "checkpoint", bare)
        return None

    async def after_input(self, prepared: object | None) -> None:
        hold = self.hold
        if hold is None or not isinstance(prepared, _Prepared):
            return
        if prepared.failed:
            await self._release(hold, TeachingReason.CAPTURE_FAILED)
            return
        try:
            seen = prepared.observation or await observe(self.run_observer, "origin")
            async with get_db_context() as db:
                await BrowserTeachingService(db, self.redis).record(
                    hold,
                    input_id=prepared.input_id,
                    action=prepared.action,
                    observation=seen,
                    direction=prepared.direction,
                )
        except Exception as exc:
            logger.warning("Browser teaching step not recorded (%s)", type(exc).__name__)
            await self._release(hold, TeachingReason.CAPTURE_FAILED)

    async def end(self) -> None:
        hold, self.hold = self.hold, None
        task, self._renewer = self._renewer, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if hold is not None:
            await self._release(hold, TeachingReason.OWNERSHIP_LOST)
            await _hold.release(self.redis, hold)

    async def _release(self, hold: Hold, reason: TeachingReason) -> None:
        try:
            async with get_db_context() as db:
                await BrowserTeachingService(db, self.redis).release(hold, reason)
        except Exception as exc:
            # The sweep pauses a recording whose hold is gone; nothing is lost here.
            logger.warning("Browser teaching pause deferred (%s)", type(exc).__name__)


def attach(
    deps: AgentDeps, page: object, *, provisioned: bool, tab_id: str | None
) -> HoldCapture | None:
    """A capture for this tab, or `None` when this run may not be taught from.

    `provisioned` is true only for the deployment's own server browser. The page
    must be a CDP page with an isolated-world observer; a native desktop tab has
    none and is refused here rather than given a fallback.
    """
    audience = deps.audience
    run_observer = getattr(page, "observe_structure", None)
    redis = live_browse.client()
    if (
        not provisioned
        or redis is None
        or run_observer is None
        or getattr(page, "native_id", None) is not None
        or deps.organization_id is None
        or deps.run_id is None
        or deps.agent_id is None
        or deps.impersonated
        or deps.delegated
        or audience is None
        or audience.user_id is None
        or not audience.browses_signed_in
        or audience.shared_transcript
        or deps.run_person != audience.user_id
        or deps.user_id != str(audience.user_id)
        or not _access.deployment_enabled(deps.organization_id)
    ):
        return None
    return HoldCapture(
        organization_id=deps.organization_id,
        run_id=deps.run_id,
        agent_id=deps.agent_id,
        user_id=audience.user_id,
        tab_id=tab_id or "main",
        redis=redis,
        run_observer=run_observer,
    )
