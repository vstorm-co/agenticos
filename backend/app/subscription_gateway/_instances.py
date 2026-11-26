"""One CLIProxyAPI process per person, started on demand and stopped when idle.

CLIProxyAPI routes a request by model to any account it holds, and has no way
to bind an account to a client key. A process shared by several people would
let each spend the others' subscriptions, so every scope gets its own process,
its own sign-in directory and its own random keys. The scope is an opaque digest
the AgenticOS backend derives from an organization and a person; this module
never learns who it belongs to.

Processes listen on loopback only. The supervisor is the only way in, so an
account's client and management keys never leave this container.
"""

import asyncio
import contextlib
import json
import logging
import re
import secrets
import shutil
import socket
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import anyio
import httpx
import yaml

logger = logging.getLogger(__name__)

SCOPE = re.compile(r"^[a-f0-9]{64}$")
STOP_GRACE_SECONDS = 5.0

type Spawn = Callable[[str, Path], Awaitable[asyncio.subprocess.Process]]
type Probe = Callable[[int, str], Awaitable[bool]]


class GatewayError(Exception):
    """A request the gateway refuses or cannot serve; the message is safe to show."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class Instance:
    scope: str
    port: int
    client_key: str
    management_key: str
    process: asyncio.subprocess.Process
    last_used: float
    active: int = 0

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


async def spawn_cliproxyapi(binary: str, config: Path) -> asyncio.subprocess.Process:
    """Start one CLIProxyAPI with its own configuration, output discarded."""
    return await asyncio.create_subprocess_exec(
        binary,
        "--config",
        str(config),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=str(config.parent),
    )


async def answers(port: int, client_key: str) -> bool:
    """Whether a started process serves its model list to its own key yet."""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(
                f"http://127.0.0.1:{port}/v1/models",
                headers={"Authorization": f"Bearer {client_key}"},
            )
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@dataclass
class Supervisor:
    """Owns every scope's process; all access goes through :meth:`use`."""

    root: Path
    binary: str
    idle_seconds: float = 600
    max_instances: int = 64
    start_timeout: float = 20
    spawn: Spawn = spawn_cliproxyapi
    probe: Probe = answers
    clock: Callable[[], float] = time.monotonic
    _running: dict[str, Instance] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    _room: asyncio.Lock = field(default_factory=asyncio.Lock)

    def directory(self, scope: str) -> Path:
        if not SCOPE.fullmatch(scope):
            raise GatewayError("Unknown account scope", status=404)
        return self.root / scope

    def _keys(self, folder: Path) -> tuple[str, str]:
        """The scope's own keys, created once and readable only by this process."""
        stored = folder / "keys.json"
        if stored.exists():
            keys = json.loads(stored.read_text())
            return str(keys["client"]), str(keys["management"])
        client, management = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        stored.write_text(json.dumps({"client": client, "management": management}))
        stored.chmod(0o600)
        return client, management

    def _configure(self, folder: Path, port: int, client: str, management: str) -> Path:
        auths = folder / "auths"
        auths.mkdir(mode=0o700, exist_ok=True)
        config = folder / "config.yaml"
        config.write_text(
            yaml.safe_dump(
                {
                    "config-version": 8,
                    "server": {"host": "127.0.0.1", "port": port},
                    "management": {
                        "allow-remote": False,
                        "secret-key": management,
                        "disable-control-panel": True,
                    },
                    "access": {"api-keys": [client]},
                    "oauth": {"auth-dir": str(auths)},
                    "observability": {
                        "logs": {"request-log": False},
                        "usage": {"usage-statistics-enabled": False},
                    },
                }
            )
        )
        config.chmod(0o600)
        return config

    async def _start(self, scope: str) -> Instance:
        folder = self.directory(scope)
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        client, management = self._keys(folder)
        port = _free_port()
        process = await self.spawn(self.binary, self._configure(folder, port, client, management))
        admitted = False
        try:
            deadline = self.clock() + self.start_timeout
            while process.returncode is None and self.clock() < deadline:
                if await self.probe(port, client):
                    admitted = True
                    return Instance(scope, port, client, management, process, self.clock())
                await asyncio.sleep(0.2)
            raise GatewayError("The account gateway did not start. Try again shortly.", status=503)
        finally:
            if not admitted:
                with anyio.CancelScope(shield=True):
                    await _terminate(process)

    async def _make_room(self) -> None:
        """Stop the least recently used idle process when the ceiling is reached."""
        if len(self._running) < self.max_instances:
            return
        idle = [instance for instance in self._running.values() if instance.active == 0]
        if not idle:
            raise GatewayError("Every account gateway slot is busy. Try again shortly.", status=503)
        oldest = min(idle, key=lambda instance: instance.last_used)
        await self.stop(oldest.scope)

    async def _ensure(self, scope: str) -> Instance:
        self.directory(scope)
        lock = self._locks.setdefault(scope, asyncio.Lock())
        async with lock:
            current = self._running.get(scope)
            if current is not None and current.process.returncode is None:
                return current
            self._running.pop(scope, None)
            async with self._room:
                await self._make_room()
                instance = await self._start(scope)
                self._running[scope] = instance
            return instance

    @contextlib.asynccontextmanager
    async def use(self, scope: str) -> AsyncGenerator[Instance]:
        """A running process for this scope, kept alive while the caller holds it."""
        instance = await self._ensure(scope)
        instance.active += 1
        try:
            yield instance
        finally:
            instance.active -= 1
            instance.last_used = self.clock()

    async def stop(self, scope: str) -> None:
        instance = self._running.pop(scope, None)
        if instance is not None:
            await _terminate(instance.process)

    async def wipe(self, scope: str) -> None:
        """Stop the scope's process and delete its sign-ins and keys for good."""
        folder = self.directory(scope)
        async with self._locks.setdefault(scope, asyncio.Lock()):
            await self.stop(scope)
            try:
                shutil.rmtree(folder)
            except FileNotFoundError:
                if folder.exists():
                    raise GatewayError(
                        "Account credential deletion is incomplete; retry shortly", status=503
                    ) from None
            except OSError:
                logger.exception("Account credential deletion failed")
                raise GatewayError(
                    "Account credential deletion failed; retry shortly", status=503
                ) from None

    async def reap(self) -> None:
        """Stop processes nobody has used for `idle_seconds`; their sign-ins stay on disk."""
        now = self.clock()
        for instance in list(self._running.values()):
            dead = instance.process.returncode is not None
            if dead or (instance.active == 0 and now - instance.last_used > self.idle_seconds):
                await self.stop(instance.scope)

    async def close(self) -> None:
        for scope in list(self._running):
            await self.stop(scope)


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=STOP_GRACE_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
    logger.info("Stopped an account gateway process")
