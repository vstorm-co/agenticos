"""Workflow deadlines over real Streamable HTTP, with silent JSON tool responses."""

import asyncio
import ipaddress
import socket
import struct
from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

import httpx2
import pytest
import uvicorn
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from app.agents import mcp_http
from app.agents.mcp import CONNECT_TIMEOUT_SECS
from app.core.config import settings
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import PrivateAllowlist
from app.workflows.contracts.results import Failed, Uncertain
from app.workflows.nodes.mcp_call import _handler as node

pytestmark = pytest.mark.anyio


class _Server(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Generator[None]:
        # A fixture must not replace the pytest process's signal handlers.
        yield


@dataclass
class _Endpoint:
    url: str
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    attempts: int = 0


def _private_interface() -> str:
    import fcntl

    networks = tuple(
        ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    )
    # SIOCGIFADDR reads this namespace's interface configuration; it sends no packets.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        for _index, name in socket.if_nameindex():
            try:
                configured = fcntl.ioctl(probe.fileno(), 0x8915, struct.pack("256s", name.encode()))
            except OSError:
                continue
            address = ipaddress.IPv4Address(configured[20:24])
            if any(address in network for network in networks):
                return str(address)
    raise RuntimeError("The real MCP HTTP fixture requires a local RFC1918 IPv4 interface.")


@pytest.fixture
async def endpoint(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[_Endpoint]:
    address = _private_interface()
    # Exercise the deployment's exact-host exception, keeping loopback forbidden.
    monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", [address])
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((address, 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert isinstance(port, int)
        state = _Endpoint(f"http://{address}:{port}/mcp")
        mcp = FastMCP("Silent slow tools")

        async def answer(delay_seconds: float) -> dict[str, bool]:
            state.attempts += 1
            state.entered.set()
            await asyncio.sleep(delay_seconds)
            return {"ok": True}

        mcp.tool(answer, name="slow_read", annotations=ToolAnnotations(read_only_hint=True))
        mcp.tool(answer, name="slow_write", annotations=ToolAnnotations(read_only_hint=False))
        server = _Server(
            uvicorn.Config(
                mcp.http_app(
                    path="/mcp",
                    json_response=True,
                    stateless_http=True,
                    allowed_hosts=[address, f"{address}:*"],
                ),
                log_level="critical",
                access_log=False,
                lifespan="on",
                timeout_graceful_shutdown=0,
            )
        )
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    if serving.done():
                        await serving
                        raise RuntimeError("The fixture server exited before starting")
                    await asyncio.sleep(0.01)
            yield state
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(serving, timeout=5)
            finally:
                if not serving.done():
                    serving.cancel()
                    with suppress(asyncio.CancelledError):
                        await serving


async def _call(
    endpoint: _Endpoint, *, timeout: int, write: bool = False
) -> node.McpCallOutput | Literal["ask"] | Failed | Uncertain:
    return await node._call(
        node.McpCallConfig(
            connection_id=uuid4(),
            tool="slow_write" if write else "slow_read",
            timeout_seconds=timeout,
            approval="none" if write else "writes",
        ),
        endpoint.url,
        {},
        {"delay_seconds": 6},
        ask_first=not write,
        recorded_read_only=not write,
    )


async def test_a_silent_six_second_tool_finishes_with_a_ninety_second_deadline(
    endpoint: _Endpoint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_client = mcp_http.PinnedAsyncClient
    clients: list[httpx2.AsyncClient] = []

    def checked_client(
        *,
        timeout: httpx2.Timeout,
        private_allowlist: PrivateAllowlist,
        allowlist_origin: str | None = None,
    ) -> PinnedAsyncClient:
        client = create_client(
            timeout=timeout,
            private_allowlist=private_allowlist,
            allowlist_origin=allowlist_origin,
        )
        clients.append(client)
        return client

    monkeypatch.setattr(mcp_http, "PinnedAsyncClient", checked_client)
    result = await _call(endpoint, timeout=90)
    assert isinstance(result, node.McpCallOutput)
    assert result.structured == {"ok": True}
    assert endpoint.attempts == 1
    [client] = clients
    assert client.timeout.read == 90
    assert client.timeout.connect == CONNECT_TIMEOUT_SECS
    assert client.is_closed


async def test_a_shorter_deadline_still_stops_the_real_http_read(endpoint: _Endpoint) -> None:
    result = await _call(endpoint, timeout=1)
    assert isinstance(result, Failed)
    assert result.error.code == "MCP_CALL_FAILED"
    assert result.error.retryable is True
    assert endpoint.attempts <= 1
    # Initialization shares the outer deadline and may time out before dispatch.
    assert "timeout" in result.error.message.lower() or "timed out" in result.error.message.lower()


async def test_a_timed_out_unkeyed_write_is_uncertain_without_replay(endpoint: _Endpoint) -> None:
    result = await _call(endpoint, timeout=1, write=True)
    assert isinstance(result, Uncertain)
    assert endpoint.attempts == 1


async def test_cancelling_a_real_http_call_propagates_instead_of_becoming_a_tool_failure(
    endpoint: _Endpoint,
) -> None:
    call = asyncio.create_task(_call(endpoint, timeout=90))
    try:
        await asyncio.wait_for(endpoint.entered.wait(), timeout=3)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
    finally:
        if not call.done():
            call.cancel()
            with suppress(asyncio.CancelledError):
                await call
