"""One run at a time may observe or drive a shared sandbox desktop.

The workspace can outlive a conversation, and toolset sequencing is local to
one run. Redis owns this lease so separate workers agree on who has the screen.
Human takeover uses the same computer and keeps the run's lease. A lost lease
never reacquires itself: the model's old coordinates no longer describe a
desktop it owns.

This fences calls through computer use, not shell commands in the workspace.
A command already dispatched cannot be recalled if a worker stalls past the
lease's TTL; the next operation is refused. The TTL exceeds the sandbox's
60-second command timeout and is renewed while the model or viewer is idle.
"""

import asyncio
import hashlib
import json
import logging
from contextlib import suppress
from uuid import uuid4

import anyio
from pydantic_ai.workspaces import WorkspaceRef
from redis.exceptions import RedisError

from app.agents.capabilities.computer_use._backends import (
    DISPLAY,
    Capture,
    Computer,
    ComputerError,
    NativeAction,
)
from app.agents.capabilities.computer_use._desktop_apps import App
from app.clients.redis import RedisClient

logger = logging.getLogger(__name__)

LEASE_SECONDS = 120
RENEW_EVERY = 30.0
REDIS_TIMEOUT = 5.0

_RENEW = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_UNAVAILABLE = (RedisError, OSError, TimeoutError)


class DesktopLeaseLost(ComputerError):
    """The run must stop using this desktop, including any human takeover."""


def _key(ref: WorkspaceRef) -> str:
    # Include the connection/provider as well as the session. Neither a model
    # argument nor a conversation id decides which actual desktop is shared.
    identity = json.dumps([ref.provider, ref.id, DISPLAY], separators=(",", ":"))
    return f"computer-use:desktop:{hashlib.sha256(identity.encode()).hexdigest()}"


class LeasedComputer:
    """A sandbox computer whose every operation must still hold its run's lease."""

    def __init__(self, computer: Computer, redis: RedisClient, key: str, holder: str) -> None:
        self.label = computer.label
        self._computer = computer
        self._redis = redis
        self._key = key
        self._holder = holder
        self._heartbeat: asyncio.Task[None] | None = None
        self._checking = asyncio.Lock()
        self._closed = False
        self._lost = False

    @classmethod
    async def acquire(
        cls, computer: Computer, ref: WorkspaceRef | None, run_id: str | None
    ) -> LeasedComputer:
        """Claim the actual workspace, refusing before any screen or input is sent."""
        if ref is None or not run_id:
            await computer.close()
            raise ComputerError("The sandbox desktop has no workspace or run identity to lock.")
        lease = cls(computer, RedisClient(), _key(ref), f"{run_id}:{uuid4().hex}")
        try:
            with anyio.fail_after(REDIS_TIMEOUT):
                await lease._redis.connect()
                claimed = await lease._redis.set(
                    lease._key, lease._holder, ttl=LEASE_SECONDS, nx=True
                )
        except _UNAVAILABLE as exc:
            await lease.close()
            logger.warning("desktop lease could not be claimed: %s", type(exc).__name__)
            raise ComputerError(
                "The desktop's exclusive access could not be verified. Try again later."
            ) from exc
        except BaseException:
            # A timeout/cancellation can arrive after Redis accepted the claim.
            # Compare-delete our token even if no successful reply reached us.
            await lease.close()
            raise
        if not claimed:
            await lease.close()
            raise ComputerError(
                "This desktop is being used by another run. Wait for it to finish, then try again."
            )
        lease._heartbeat = asyncio.create_task(lease._maintain())
        return lease

    async def _check(self) -> None:
        # A failed heartbeat must stay terminal even if an overlapping tool's
        # earlier renewal reply arrives after it.
        async with self._checking:
            await self._renew()

    async def _renew(self) -> None:
        if self._closed or self._lost:
            raise DesktopLeaseLost(
                "This run no longer has exclusive access to the desktop. Stop here and start a new run."
            )
        try:
            with anyio.fail_after(REDIS_TIMEOUT):
                renewed = await self._redis.raw.eval(
                    _RENEW, 1, self._key, self._holder, LEASE_SECONDS
                )
        except _UNAVAILABLE as exc:
            self._lost = True
            logger.warning("desktop lease could not be verified: %s", type(exc).__name__)
            raise DesktopLeaseLost(
                "The desktop's exclusive access could not be verified. Stop here and start a new run."
            ) from exc
        if not renewed:
            self._lost = True
            raise DesktopLeaseLost(
                "Another run may now use this desktop. Stop here and start a new run."
            )

    async def _maintain(self) -> None:
        try:
            while True:
                await asyncio.sleep(RENEW_EVERY)
                await self._check()
        except DesktopLeaseLost:
            # The next call reports the refusal; this background task must not
            # become an unobserved exception while the model thinks.
            return

    async def capture(self) -> Capture:
        await self._check()
        capture = await self._computer.capture()
        # Do not return a screen captured after ownership was lost mid-request.
        await self._check()
        return capture

    async def perform(self, action: NativeAction) -> None:
        await self._check()
        await self._computer.perform(action)
        await self._check()

    async def apps(self) -> list[App]:
        await self._check()
        apps = await self._computer.apps()
        await self._check()
        return apps

    async def close(self) -> None:
        """Release only our claim, including on cancellation or a broken live view."""
        if self._closed:
            return
        self._closed = True
        with anyio.CancelScope(shield=True):
            if self._heartbeat is not None:
                self._heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await self._heartbeat
            try:
                await self._computer.close()
            finally:
                try:
                    with anyio.fail_after(REDIS_TIMEOUT):
                        await self._redis.delete_if_equal(self._key, self._holder)
                except (*_UNAVAILABLE, RuntimeError) as exc:
                    # The TTL releases an unreachable claim; never delete a new
                    # holder's lease after ours expired or was taken away.
                    logger.warning("desktop lease could not be released: %s", type(exc).__name__)
                finally:
                    try:
                        with anyio.move_on_after(REDIS_TIMEOUT):
                            await self._redis.close()
                    except _UNAVAILABLE as exc:
                        logger.warning(
                            "desktop lease client could not close: %s", type(exc).__name__
                        )
