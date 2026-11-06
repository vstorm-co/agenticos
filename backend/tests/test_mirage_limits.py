"""Output and retained RAM are bounded before the console or a paused run stores them."""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from mirage import Workspace
from mirage.vfs.ram import RAMVFS
from pydantic import ValidationError
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart
from pydantic_ai.workspaces import WorkspaceTimeoutError

from app.agents.capabilities.mirage import _backend, _scratch
from app.agents.capabilities.mirage._scratch import ScratchFolder, ScratchState
from app.services.mirage_mounts import hosts_of

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_streaming_output_stops_pulling_and_closes_at_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_backend, "OUTPUT_BYTES", 4)
    pulled: list[int] = []
    closed = asyncio.Event()

    async def chunks() -> AsyncIterator[bytes]:
        try:
            for index in range(100):
                pulled.append(index)
                yield b"abc"
        finally:
            closed.set()

    assert await _backend._collect(chunks()) == ("abca", True)
    assert pulled == [0, 1] and closed.is_set()


async def test_streaming_output_preserves_small_results(monkeypatch: pytest.MonkeyPatch) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"ok"

    assert await _backend._collect(chunks()) == ("ok", False)
    assert await _backend._collect(None) == ("", False)
    monkeypatch.setattr(_backend, "OUTPUT_BYTES", 2)
    assert await _backend._collect(b"123") == ("12", True)
    assert await _backend._collect(b"ok") == ("ok", False)


async def test_command_deadline_includes_reading_output(monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = Workspace({"/scratch": RAMVFS()})
    waiting = asyncio.Event()

    async def hangs(*args: object, **kwargs: object) -> None:
        await waiting.wait()

    monkeypatch.setattr(workspace, "shell", AsyncMock(side_effect=hangs))
    try:
        with pytest.raises(WorkspaceTimeoutError):
            await _backend.BoundedBackend(workspace).run(["ls"], timeout=0.001)
        with pytest.raises(TypeError):
            await _backend.BoundedBackend(workspace).run("ls")
    finally:
        await workspace.close()


def test_a_paused_run_cannot_retain_unbounded_scratch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_scratch, "MAX_BYTES", 4)
    with pytest.raises(ValidationError, match="memory limit"):
        ScratchFolder(files={"/x": b"12345"})
    with pytest.raises(ValidationError, match="memory limit"):
        ScratchState(
            folders={
                "/a": ScratchFolder(files={"/x": b"123"}),
                "/b": ScratchFolder(files={"/y": b"456"}),
            }
        )
    assert _scratch.restore([ModelRequest(parts=[])]).folders == {}
    _scratch.keep([], ScratchState())
    message = ModelResponse(parts=[TextPart("kept")], metadata={"existing": True})
    _scratch.keep([message], ScratchState())
    assert _scratch.restore([message]).folders == {} and message.metadata == {"existing": True}


@pytest.mark.parametrize(
    "parameter",
    ["host=attacker.example", "%68ost=attacker.example", "hostaddr=127.0.0.1", "service=local"],
)
def test_a_postgres_query_cannot_override_the_allowlisted_host(parameter: str) -> None:
    assert hosts_of(f"postgresql://user:password@allowed.example/db?{parameter}") == ()
    assert hosts_of("postgresql://u:p@[invalid/db") == ()


@pytest.mark.parametrize("command", ["curl", "wget"])
@pytest.mark.parametrize("explicit_allow", [False, True])
async def test_shell_http_cannot_reach_even_an_allowlisted_server(
    command: str, explicit_allow: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.capabilities.mirage import ResolvedMount
    from app.agents.capabilities.mirage._capability import Mirage
    from app.core.config import settings

    monkeypatch.setattr(settings, "MIRAGE_ALLOWED_HOSTS", ["127.0.0.1"])
    connected = asyncio.Event()

    async def answer(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connected.set()
        try:
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(answer, "127.0.0.1", 0)
    terminal = Mirage(
        mounts=(ResolvedMount("/scratch/", "ram", "write", False, {}, "Scratch"),),
        allowed_commands=(command,) if explicit_allow else (),
    )
    try:
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        workspace = await terminal.workspace()
        result = await _backend.BoundedBackend(workspace).run(
            [command, f"http://127.0.0.1:{port}/"], timeout=2
        )
        assert result.exit_code != 0
        assert not connected.is_set()
    finally:
        if terminal._workspace is not None:
            await terminal._workspace.close()
        server.close()
        await server.wait_closed()
