"""Which calls this process holds, so a shutdown hangs them up first (#54).

The per-call `finally` is the guarantee; this is what makes a SIGTERM run those
`finally` blocks before the process stops, instead of after the event loop is
gone. The reaper is the net under both.
"""

import os
import socket
from typing import Protocol
from uuid import UUID

import anyio

from app.db.models.voice_call import VoiceEndReason

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


class EndableCall(Protocol):
    """A call this process holds, as the shutdown hook and a reconnect see it."""

    def request_end(self, reason: VoiceEndReason) -> None:
        """Ask the call to end; its own `finally` hangs it up."""
        ...

    async def closed(self) -> None:
        """Return once the call has finished ending."""
        ...


class LiveCalls:
    """The calls this process holds, by object and by call row."""

    def __init__(self) -> None:
        self._calls: set[EndableCall] = set()
        self._by_id: dict[UUID, EndableCall] = {}

    def add(self, call: EndableCall) -> None:
        """Hold a call from the moment its socket is accepted."""
        self._calls.add(call)

    def bind(self, call_id: UUID, call: EndableCall) -> None:
        """Name a live call by its row, so a reconnect on this worker can end it."""
        self._by_id[call_id] = call

    def request_end_for(self, call_id: UUID, reason: VoiceEndReason) -> bool:
        """End the call this worker holds under `call_id`. `False` when it holds none."""
        call = self._by_id.get(call_id)
        if call is None:
            return False
        call.request_end(reason)
        return True

    def discard(self, call: EndableCall) -> None:
        """Forget a call that has ended."""
        self._calls.discard(call)
        self._by_id = {key: held for key, held in self._by_id.items() if held is not call}

    async def end_all(self, *, timeout: float = 10.0) -> int:
        """End every call this process holds and wait for each to close, up to `timeout`."""
        calls = list(self._calls)
        for call in calls:
            call.request_end(VoiceEndReason.SHUTDOWN)
        with anyio.move_on_after(timeout):
            for call in calls:
                await call.closed()
        return len(calls)


LIVE_CALLS = LiveCalls()
