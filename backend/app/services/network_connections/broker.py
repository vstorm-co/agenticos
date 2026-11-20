"""A private pipe to a dedicated userspace Tailscale node, never a shared proxy."""

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from contextlib import suppress
from functools import partial
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import ValidationError

from app.schemas.network_connection import NetworkErrorCode
from app.services.network_connections.protocol import (
    FRAME_ADAPTER,
    HEARTBEAT_SECONDS,
    MAX_FRAME_BYTES,
    CompleteFrame,
    ErrorFrame,
    NodeState,
    StateFrame,
    StatusFrame,
)


class BrokerFailure(RuntimeError):
    """A controlled failure code; provider output and state are never exceptions."""

    def __init__(self, code: NetworkErrorCode) -> None:
        self.code = code
        super().__init__(code)


class NodeCallbacks(Protocol):
    async def heartbeat(self) -> None: ...

    async def persist(self, frame: StateFrame) -> None: ...

    async def observe(self, frame: StatusFrame) -> None: ...


class TailscaleBroker:
    """Own exactly one child and terminate it when its committed lease is lost."""

    def __init__(self, executable: str) -> None:
        self.executable = executable

    def available(self) -> bool:
        return (
            bool(self.executable)
            and Path(self.executable).is_file()
            and os.access(self.executable, os.X_OK)
        )

    async def run(
        self,
        *,
        connection_id: UUID,
        mode: Literal["enroll", "status", "logout"],
        state: NodeState,
        callbacks: NodeCallbacks,
    ) -> Literal["ready", "timeout", "logged_out", "stopped"]:
        """Persist each state event before ACK and renew authority before heartbeat.

        The environment is allowlisted rather than deleting known auth variables:
        future Tailscale auth knobs cannot silently enroll another person's node.
        The process never receives the platform's configuration, vault key or DB URL.
        """
        if not self.available():
            raise BrokerFailure("runtime_unavailable")
        child_env = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR")
            if key in os.environ
        }
        child_env["TS_NO_LOGS_NO_SUPPORT"] = "true"
        try:
            process = await asyncio.create_subprocess_exec(
                self.executable,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=child_env,
                limit=MAX_FRAME_BYTES,
            )
        except OSError:
            raise BrokerFailure("runtime_unavailable") from None
        try:
            if process.stdin is None or process.stdout is None:
                raise BrokerFailure("runtime_unavailable")
            # Spawning can be slow. Recheck the lease before handing identity to
            # the child, so an expired lease cannot start a second copy of a node.
            await self._bounded(callbacks.heartbeat)
            await self._write(
                process.stdin,
                json.dumps(
                    {
                        "version": 1,
                        "type": "start",
                        "connection_id": str(connection_id),
                        "hostname": f"t3os-{connection_id.hex[:20]}",
                        "mode": mode,
                        "state": state.wire_state(),
                    },
                    separators=(",", ":"),
                ),
            )
            return await self._receive(
                process, callbacks=callbacks, timeout=610 if mode == "enroll" else 30
            )
        finally:
            await self._stop(process)

    async def _receive(
        self,
        process: asyncio.subprocess.Process,
        *,
        callbacks: NodeCallbacks,
        timeout: int,
    ) -> Literal["ready", "timeout", "logged_out", "stopped"]:
        reader, writer = process.stdout, process.stdin
        if reader is None or writer is None:
            raise BrokerFailure("runtime_unavailable")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        next_heartbeat = 0.0
        sequence = 0
        while loop.time() < deadline:
            if loop.time() >= next_heartbeat:
                await self._bounded(callbacks.heartbeat)
                await self._write(writer, '{"type":"heartbeat"}')
                next_heartbeat = loop.time() + HEARTBEAT_SECONDS
            try:
                raw = await asyncio.wait_for(reader.readline(), timeout=1)
            except TimeoutError:
                continue
            except ValueError, asyncio.LimitOverrunError:
                raise BrokerFailure("invalid_runtime_response") from None
            if not raw:
                raise BrokerFailure("runtime_disconnected")
            if len(raw) > MAX_FRAME_BYTES:
                raise BrokerFailure("runtime_frame_too_large")
            try:
                frame = FRAME_ADAPTER.validate_json(raw)
            except ValidationError:
                # ValidationError's input can contain node keys or the login URL.
                raise BrokerFailure("invalid_runtime_response") from None
            if isinstance(frame, StateFrame):
                if frame.sequence != sequence + 1:
                    raise BrokerFailure("invalid_runtime_sequence")
                await self._bounded(partial(callbacks.persist, frame))
                sequence = frame.sequence
                await self._write(writer, json.dumps({"type": "ack", "sequence": sequence}))
            elif isinstance(frame, StatusFrame):
                await self._bounded(partial(callbacks.observe, frame))
            elif isinstance(frame, CompleteFrame):
                return frame.reason
            elif isinstance(frame, ErrorFrame):
                # Only our fixed code crosses the boundary, never a child-supplied message.
                raise BrokerFailure("runtime_failed")
        raise BrokerFailure("runtime_timeout")

    @staticmethod
    async def _bounded(callback: Callable[[], Awaitable[None]]) -> None:
        try:
            async with asyncio.timeout(3):
                await callback()
        except TimeoutError:
            raise BrokerFailure("control_plane_unavailable") from None

    @staticmethod
    async def _write(writer: asyncio.StreamWriter, value: str) -> None:
        payload = value.encode() + b"\n"
        if len(payload) > MAX_FRAME_BYTES:
            raise BrokerFailure("runtime_frame_too_large")
        try:
            async with asyncio.timeout(2):
                writer.write(payload)
                await writer.drain()
        except TimeoutError, BrokenPipeError, ConnectionResetError:
            raise BrokerFailure("runtime_disconnected") from None

    @staticmethod
    async def _stop(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if process.stdin is not None:
            with suppress(BrokerFailure):
                await TailscaleBroker._write(process.stdin, '{"type":"stop"}')
            process.stdin.close()
        try:
            async with asyncio.timeout(3):
                await process.wait()
        except TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
