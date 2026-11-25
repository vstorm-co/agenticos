"""Real SDK sessions retain HTTP JSON, event-stream and legacy SSE contracts."""

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx2
import pytest
import uvicorn
from fastmcp import FastMCP
from httpcore2._backends.auto import AutoBackend
from httpcore2._backends.base import AsyncNetworkStream
from mcp import ClientSession
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from starlette.types import Receive, Scope, Send

from app.agents import mcp, mcp_http
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import PrivateAllowlist

pytestmark = [pytest.mark.anyio, pytest.mark.security]

PUBLIC = "93.184.216.34"


@dataclass
class _Server:
    url: str
    calls: list[int] = field(default_factory=list)
    requests: list[tuple[str, str, dict[bytes, bytes]]] = field(default_factory=list)
    clients: list[PinnedAsyncClient] = field(default_factory=list)
    dials: list[str] = field(default_factory=list)


@pytest.fixture(params=["json", "event-stream", "legacy-sse"])
async def remote(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[_Server]:
    endpoint = "/sse" if request.param == "legacy-sse" else "/mcp"
    state = _Server(url="")
    service = FastMCP("local protocol fixture")

    @service.tool
    def increment(value: int) -> str:
        state.calls.append(value)
        return f"fixture-answer-{value + 1}"

    app = service.http_app(
        path=endpoint,
        transport="sse" if request.param == "legacy-sse" else "streamable-http",
        json_response=request.param == "json",
        stateless_http=False,
        allowed_hosts=["mcp.example.test", "mcp.example.test:*"],
    )

    async def traced(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            state.requests.append((scope["method"], scope["path"], dict(scope["headers"])))
        await app(scope, receive, send)

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    state.url = f"http://mcp.example.test:{port}{endpoint}"
    server = uvicorn.Server(uvicorn.Config(traced, log_level="error", timeout_graceful_shutdown=1))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    real_resolve = socket.getaddrinfo
    real_connect = AutoBackend.connect_tcp

    def resolve(host: str, port: int, *args: object, **kwargs: object) -> list[tuple[object, ...]]:
        if host == "mcp.example.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (PUBLIC, port))]
        assert host == "127.0.0.1"
        return real_resolve(host, port, *args, **kwargs)

    async def connect(
        self: AutoBackend, host: str, port: int, **kwargs: object
    ) -> AsyncNetworkStream:
        state.dials.append(host)
        assert host == PUBLIC
        return await real_connect(self, "127.0.0.1", port, **kwargs)

    def client(
        *,
        timeout: httpx2.Timeout,
        private_allowlist: PrivateAllowlist,
        allowlist_origin: str | None = None,
    ) -> PinnedAsyncClient:
        made = PinnedAsyncClient(
            timeout=timeout, private_allowlist=private_allowlist, allowlist_origin=allowlist_origin
        )
        state.clients.append(made)
        return made

    monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", resolve)
    monkeypatch.setattr(AutoBackend, "connect_tcp", connect)
    monkeypatch.setattr(mcp_http, "PinnedAsyncClient", client)
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if serving.done():
                    await serving
                await asyncio.sleep(0.01)
        yield state
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 5)
        listener.close()


async def test_probe_sessions_preserve_authentication_and_execute_each_message_once(
    remote: _Server,
) -> None:
    async with (
        mcp._mcp_transport(
            remote.url, {"Authorization": "Bearer synthetic-fixture"}, timeout=3
        ) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        assert [tool.name for tool in tools.tools] == ["increment"]
        result = await session.call_tool("increment", {"value": 7})
        assert result.content[0].text == "fixture-answer-8"

    assert remote.calls == [7]
    assert remote.clients and all(client.is_closed for client in remote.clients)
    assert set(remote.dials) == {PUBLIC}
    assert all(
        headers[b"authorization"] == b"Bearer synthetic-fixture"
        for _, _, headers in remote.requests
    )
    if remote.url.endswith("/mcp"):
        assert any(b"mcp-session-id" in headers for _, _, headers in remote.requests)


async def test_runtime_toolsets_own_fresh_clients_on_each_reconnection(remote: _Server) -> None:
    toolset = mcp._make_toolset(
        mcp.McpServerSpec(name="fixture", url=remote.url, headers={"X-Test": "runtime"})
    )
    context = RunContext(deps=None, model=TestModel(), usage=RunUsage())
    for _ in range(2):
        async with toolset:
            tools = await toolset.get_tools(context)
            assert set(tools) == {"fixture_increment"}
            result = await toolset.call_tool(
                "fixture_increment", {"value": 7}, context, tools["fixture_increment"]
            )
            assert "fixture-answer-8" in str(result)
        assert all(client.is_closed for client in remote.clients)

    assert remote.calls == [7, 7]
    assert len(remote.clients) == 2
    assert all(headers[b"x-test"] == b"runtime" for _, _, headers in remote.requests)


async def test_cancelling_a_live_session_closes_its_owned_http_client(remote: _Server) -> None:
    initialized = asyncio.Event()

    async def use() -> None:
        async with (
            mcp._mcp_transport(remote.url, None, timeout=3) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            initialized.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(use())
    try:
        await asyncio.wait_for(initialized.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert remote.clients and all(client.is_closed for client in remote.clients)
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
