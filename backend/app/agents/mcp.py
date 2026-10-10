"""MCP server toolsets for published agents.

Servers arrive here as uniform :class:`McpServerSpec` entries, resolved from
the connections an agent's spec names (see
:func:`app.services.mcp_connection.build_toolsets_for_agent`).

Each spec is probed with a short `tools/list` round-trip before the turn;
unreachable servers are skipped (with a warning) instead of failing the chat,
because pydantic-ai enters every toolset when the run starts and a dead
server would otherwise abort the whole turn.

The transport (streamable HTTP or SSE) is inferred from each server's URL, so
SSE-only servers such as Atlassian/Jira work alongside streamable-HTTP ones.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import re
from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.toolsets import WrapperToolset
from pydantic_ai.toolsets.abstract import ToolsetTool

from app.agents.spec import McpApproval
from app.core.sanitize import validate_webhook_url

logger = logging.getLogger(__name__)

# How long a server gets to answer a connect or a probe. A constant rather than
# a setting: the right value is a property of the protocol round-trip, not of a
# deployment, and no installation ever tuned it.
CONNECT_TIMEOUT_SECS = 3.0


class McpProbeError(Exception):
    """A failed liveness probe, with its root cause already unwrapped.

    The MCP client runs on anyio task groups, so a failure surfaces as a
    (possibly `BaseException`-carrying) group that `except Exception`
    would miss. :func:`probe_mcp_server` collapses those into this type so
    every caller can handle a dead server with a plain `except Exception`.
    """


async def validate_mcp_url(url: str) -> str:
    """SSRF-check a URL before we talk to it (same policy as webhooks).

    For a URL an operator typed: the connection's own address, and the consent
    URL the OAuth flow hands to somebody's browser rather than fetching. Runs
    in a thread because validation resolves DNS.

    Everything the OAuth flow *fetches* is chosen by the remote server, so it
    goes through :class:`app.core.pinned_http.PinnedAsyncClient` instead, which
    connects to the address it checked rather than handing the name back to be
    resolved again (#860).
    """
    return await asyncio.to_thread(validate_webhook_url, url)


@dataclass(frozen=True)
class McpToolInfo:
    """One tool advertised by an MCP server (for the /test endpoint and UI)."""

    name: str
    description: str


@dataclass(frozen=True)
class McpServerSpec:
    """Transport-level description of one MCP server to attach to a run."""

    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    # None = expose every tool the server offers.
    allowed_tools: list[str] | None = None
    approval: McpApproval = "writes"
    # This deployment's own server (`/mcp`), reached through the application in
    # this process rather than over the network - never probed, never dialled out.
    in_process: bool = False


@asynccontextmanager
async def _mcp_transport(
    url: str, headers: dict[str, str] | None
) -> AsyncGenerator[tuple[Any, Any], None]:
    """Open the right client transport for *url*, yielding `(read, write)`.

    The transport is inferred from the URL exactly as the toolset layer does it
    (FastMCP): a path segment `/sse` selects the SSE client (used by servers
    like Atlassian/Jira), everything else uses streamable HTTP.

    The streamable client takes a **client**, not headers, since MCP 2.0: it was
    `streamablehttp_client(url, headers=...)` yielding three values, and is
    `streamable_http_client(url, http_client=...)` yielding two. A rename alone
    compiles and silently drops every `Authorization` a connection carries -
    which is the whole of what reaches a private MCP server - so the headers go
    into the client `create_mcp_http_client` builds, and the client is owned
    here so it closes with the transport (#1820).
    """
    from pydantic_ai.mcp import infer_transport_type_from_url

    if infer_transport_type_from_url(url) == "sse":
        from mcp.client.sse import sse_client

        async with sse_client(url, headers=headers or None) as (read, write):
            yield read, write
    else:
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        async with (
            create_mcp_http_client(headers=headers or None) as http_client,
            streamable_http_client(url, http_client=http_client) as (read, write),
        ):
            yield read, write


async def probe_mcp_server(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> list[McpToolInfo]:
    """Connect to an MCP server and list its tools.

    Any failure is raised as :class:`McpProbeError` with the root cause already
    unwrapped, so callers can skip a dead server with `except Exception`.
    Cancellation always propagates.

    Used both as the pre-flight liveness check before a chat turn and as the
    backing call for the connection "test" endpoint. The transport (streamable
    HTTP or SSE) is inferred from the URL, matching the toolset layer.
    """
    from mcp import ClientSession

    try:
        async with asyncio.timeout(timeout or CONNECT_TIMEOUT_SECS):
            async with (
                _mcp_transport(url, headers) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.list_tools()
    except (Exception, BaseExceptionGroup) as exc:
        if _carries_base_exception(exc):
            raise
        raise McpProbeError(probe_error_message(exc)) from exc
    return [McpToolInfo(name=t.name, description=t.description or "") for t in result.tools]


def _carries_base_exception(exc: BaseException) -> bool:
    """True when *exc* is (or wraps) something that isn't an `Exception`.

    A group carrying a `CancelledError` means the turn was cancelled, not
    that the server is down - swallowing it would keep the run alive.
    """
    if isinstance(exc, BaseExceptionGroup):
        return any(_carries_base_exception(inner) for inner in exc.exceptions)
    return not isinstance(exc, Exception)


def probe_error_message(exc: BaseException) -> str:
    """Human-readable reason for a failed probe.

    The MCP client runs on anyio task groups, so failures surface as nested
    ExceptionGroups ("unhandled errors in a TaskGroup") - unwrap to the root
    cause before showing anything to a user.
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    if isinstance(exc, TimeoutError):
        return f"Connection timed out after {CONNECT_TIMEOUT_SECS:g}s"
    return str(exc) or exc.__class__.__name__


def tool_prefix(name: str) -> str:
    """Connection name → tool prefix, e.g. "github-work" → "github_work"."""
    return re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_") or "mcp"


def prefix_collisions[T](holders: Iterable[tuple[str, T]]) -> dict[str, list[T]]:
    """Which tool prefixes more than one name reduces to, and who holds each.

    Two servers under one prefix emit the same tool names and pydantic-ai raises
    on the duplicate, aborting the turn - so a publish is refused and a run drops
    the loser, and both decide it here rather than each computing it apart (#1442).
    `github`, `GitHub` and `github-` are one prefix; every value lists its holders
    in the order given, the one that keeps the prefix first.
    """
    grouped: dict[str, list[T]] = {}
    for name, holder in holders:
        grouped.setdefault(tool_prefix(name), []).append(holder)
    return {prefix: held for prefix, held in grouped.items() if len(held) > 1}


def _make_toolset(spec: McpServerSpec) -> Any:
    """Build a pydantic-ai toolset for one MCP server.

    Tools are prefixed with the connection name so two servers exposing the
    same tool name can't collide (pydantic-ai raises on duplicates). The
    allowlist filter runs before prefixing, so it compares against the
    unprefixed names the user picked in the UI.

    A tool error the server reports reaches the model as a failed result
    (`tool_error_behavior="failed"`), not as a retry. A retry spends the tool's
    one-attempt budget, and the error after it ends the whole run with
    `UnexpectedModelBehavior` - which is how most failed runs here ended: a
    Notion query the server refused twice took the conversation down, where the
    model reading the refusal could have fixed the query or said it could not.
    Repeats stay bounded by the run's step limit.
    """
    from pydantic_ai.mcp import MCPToolset

    # The in-process client carries the headers itself: the two are exclusive.
    server: Any = MCPToolset(
        spec.url,
        headers=None if spec.in_process else spec.headers or None,
        http_client=_in_process_client(spec.headers) if spec.in_process else None,
        id=f"mcp:{spec.name}",
        init_timeout=CONNECT_TIMEOUT_SECS,
        tool_error_behavior="failed",
    )
    if spec.allowed_tools is not None:
        allowed = set(spec.allowed_tools)
        server = server.filtered(lambda _ctx, tool: tool.name in allowed)
    return ApprovalMarked(server.prefixed(tool_prefix(spec.name)), policy=spec.approval)


NEEDS_APPROVAL = "agenticos_needs_approval"
"""The key `ApprovalMarked` sets on a tool's metadata, and `ApprovalGate` reads (#2060).

Top-level in the metadata, where an MCP server cannot write: what a server
sends lands under `meta` and `annotations`, so it cannot mark its own tools safe.
"""


def needs_approval(tool: ToolDefinition, policy: McpApproval) -> bool:
    """Whether a call to this MCP tool waits for a person, under `policy`.

    `writes` trusts the server's `readOnlyHint` and nothing else: a tool that
    does not say it only reads is treated as one that writes.
    """
    if policy == "all":
        return True
    if policy == "none":
        return False
    annotations = (tool.metadata or {}).get("annotations") or {}
    return annotations.get("readOnlyHint") is not True


@dataclass
class ApprovalMarked(WrapperToolset[Any]):
    """An MCP server's tools, each marked with whether it waits for approval."""

    policy: McpApproval = "writes"

    async def get_tools(self, ctx: RunContext[Any]) -> dict[str, ToolsetTool[Any]]:
        tools = await super().get_tools(ctx)
        return {
            name: replace(
                tool,
                tool_def=replace(
                    tool.tool_def,
                    metadata={
                        **(tool.tool_def.metadata or {}),
                        NEEDS_APPROVAL: needs_approval(tool.tool_def, self.policy),
                    },
                ),
            )
            for name, tool in tools.items()
        }


PLATFORM_MCP_NAME = "agenticos"
"""What this deployment's own server is called in a run, and so its tools' prefix."""

PLATFORM_MCP_PREFIX = tool_prefix(PLATFORM_MCP_NAME)

PLATFORM_MCP_URL = "http://agenticos/mcp"
"""Where the in-process client addresses `/mcp`. The host is never resolved."""


def platform_spec(
    credential: str, *, allowed_tools: list[str] | None, approval: McpApproval
) -> McpServerSpec:
    """This deployment's own MCP server, as the holder of `credential`."""
    return McpServerSpec(
        name=PLATFORM_MCP_NAME,
        url=PLATFORM_MCP_URL,
        headers={"Authorization": f"Bearer {credential}"},
        allowed_tools=allowed_tools,
        approval=approval,
        in_process=True,
    )


def _in_process_client(headers: dict[str, str]) -> Any:
    """An HTTP client whose requests go to this process's API application.

    Imported when a run needs it rather than at module load: the application
    imports the agent layer, so the agent layer reaching for it at import time
    would be a cycle.
    """
    import httpx2

    app = importlib.import_module("app.main").app
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        headers=headers,
        timeout=httpx2.Timeout(300.0, connect=10.0),
    )


def _dedupe_by_prefix(specs: list[McpServerSpec]) -> list[McpServerSpec]:
    """Drop specs whose tool prefix an earlier spec already claimed.

    The defensive net beneath `build_toolsets_for_agent`, which already removes a
    collision and reports it on `unavailable` (#1442): in a real run nothing is
    dropped here. Kept because this is the one function that attaches the toolsets,
    and a duplicate prefix reaching pydantic-ai aborts the whole turn. The first
    spec keeps the prefix, so a deployment-managed server ordered ahead of a user
    connection of the same name wins.
    """
    losers = {
        id(spec)
        for held in prefix_collisions((s.name, s) for s in specs).values()
        for spec in held[1:]
    }
    return [spec for spec in specs if id(spec) not in losers]


async def probe_toolsets(specs: list[McpServerSpec]) -> list[tuple[McpServerSpec, Any | None]]:
    """Every spec paired with its toolset, or `None` where its probe failed.

    Probed concurrently, in the order given. A caller that has to decide
    something about the servers that actually answered - which of two colliding
    prefixes is attached (#1442) - reads this rather than `build_mcp_toolsets`,
    which only says what survived.
    """

    async def _try(spec: McpServerSpec) -> Any | None:
        if spec.in_process:
            # This deployment's own server: there is no remote to be down.
            return _make_toolset(spec)
        try:
            await probe_mcp_server(spec.url, spec.headers)
        except Exception as exc:
            logger.warning(
                "Skipping MCP server %r for this turn: %s", spec.name, probe_error_message(exc)
            )
            return None
        return _make_toolset(spec)

    results = await asyncio.gather(*(_try(spec) for spec in specs))
    return list(zip(specs, results, strict=True))


async def build_mcp_toolsets(specs: list[McpServerSpec]) -> list[Any]:
    """Toolsets for every reachable server in *specs* (probed concurrently)."""
    specs = _dedupe_by_prefix(specs)
    if not specs:
        return []
    return [toolset for _spec, toolset in await probe_toolsets(specs) if toolset is not None]
