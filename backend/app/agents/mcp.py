"""MCP server toolsets for published agents.

Servers arrive here as uniform :class:`McpServerSpec` entries, resolved from
the connections an agent's spec names (see
:func:`app.services.mcp_connection.build_toolsets_for_agent`).

Each spec is probed with a short `tools/list` round-trip before the turn;
unreachable servers are skipped (with a warning) instead of failing the chat,
because pydantic-ai enters every toolset when the run starts and a dead
server would otherwise abort the whole turn. A server that answered a probe in
the last :data:`ANSWERED_FOR` seconds is not probed again: a conversation's
every turn used to pay a second connection and a second `tools/list` per server
for an answer it had a minute ago. Such a server is attached through
:class:`AnsweredRecently`, which leaves it out of the turn if it has gone down
since, so skipping the probe never turns an outage back into a failed turn.

The transport (streamable HTTP or SSE) is inferred from each server's URL, so
SSE-only servers such as Atlassian/Jira work alongside streamable-HTTP ones.
"""

import asyncio
import hashlib
import importlib
import json
import logging
import re
import time
from collections.abc import AsyncGenerator, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx2

# At import, not on the first turn: `pydantic_ai.mcp` brings in fastmcp's client,
# and lazily that was a few hundred milliseconds - seconds on a host short of CPU -
# inside the first chat turn each process served, before the model was asked.
from pydantic_ai.mcp import MCPToolset, infer_transport_type_from_url
from pydantic_ai.messages import InstructionPart
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.toolsets import WrapperToolset
from pydantic_ai.toolsets.abstract import ToolsetTool

from app.agents.spec import McpApproval
from app.core.config import settings
from app.core.sanitize import validate_webhook_url

logger = logging.getLogger(__name__)

# How long a server gets to accept a connection, and an OAuth request to answer.
# A constant rather than a setting: the right value is a property of the
# protocol round-trip, not of a deployment, and no installation ever tuned it.
CONNECT_TIMEOUT_SECS = 3.0

HANDSHAKE_TIMEOUT_SECS = 10.0
"""How long a probe's whole session may take: `initialize`, `initialized` and `tools/list`.

Apart from the connect timeout because a server can be slow per request without
being down. One that checks every request's token at its identity provider - an
OAuth proxy in front of GitHub or Microsoft Entra - spends about a second on
each, and a probe is three or four requests, so a single 3s budget left it out
of every turn although it answered every request. A host that does not accept
the connection still fails within :data:`CONNECT_TIMEOUT_SECS`; one that accepts
and then hangs holds a turn for this long.

A run's own `initialize` keeps :data:`CONNECT_TIMEOUT_SECS`. It is one request,
which such a server answers within it, and a server that answered a probe in
the last :data:`ANSWERED_FOR` seconds is entered without another - so one that
went down in that window still fails a turn in seconds, not in this budget.
"""

ANSWERED_FOR = 120.0
"""How long, in seconds, a server that answered its probe is taken to be up without another.

Long enough to cover a conversation's back-and-forth, short enough that a server
which went down is re-probed - and so reported as unavailable to the model -
within a couple of minutes rather than silently left out turn after turn.
"""

_answered: dict[str, float] = {}
"""When each server last answered a probe, by :func:`_answer_key`. Process-local."""


def _answer_key(spec: McpServerSpec) -> str:
    """Who answered: the address and the credential, hashed so the memo holds no token."""
    material = json.dumps([spec.url, sorted(spec.headers.items())])
    return hashlib.sha256(material.encode()).hexdigest()


def _note_answer(key: str) -> None:
    now = time.monotonic()
    for stale in [k for k, at in _answered.items() if now - at >= ANSWERED_FOR]:
        del _answered[stale]
    _answered[key] = now


def _answered_recently(key: str) -> bool:
    at = _answered.get(key)
    return at is not None and time.monotonic() - at < ANSWERED_FOR


class McpProbeError(Exception):
    """A failed liveness probe, with its root cause already unwrapped.

    The MCP client runs on anyio task groups, so a failure surfaces as a
    (possibly `BaseException`-carrying) group that `except Exception`
    would miss. :func:`probe_mcp_server` collapses those into this type so
    every caller can handle a dead server with a plain `except Exception`.
    """


def _allowed_hosts() -> frozenset[str]:
    """`MCP_ALLOWED_HOSTS`, spelled the way `urlparse` spells a host.

    Each entry is trimmed and lower-cased, a leading `[` and a trailing `]` are
    dropped (each on its own, for an IPv6 address listed with brackets), and a
    blank entry is skipped rather than read as a host. Nothing else is
    folded: not a trailing dot, a port or a glob, so an entry matches one host
    spelled exactly that way. Read on every call, so a test's monkeypatch is
    seen and there is nothing to invalidate.
    """
    hosts = (
        entry.strip().removeprefix("[").removesuffix("]").lower()
        for entry in settings.MCP_ALLOWED_HOSTS
    )
    return frozenset(host for host in hosts if host)


def trusted_hosts_for(server_url: str) -> frozenset[str]:
    """The listed hosts the OAuth flow for the connection at *server_url* may reach.

    All of `MCP_ALLOWED_HOSTS` when the connection's own host is on it, and none
    otherwise. Its discovery documents name the addresses the flow fetches, so
    the decision is made from the URL the connection was saved with, never from
    an address a server named. That keeps a public server from aiming its token
    endpoint at a listed host. A flow that began at a listed host may reach the
    others: a member could already save a connection to any of them, so they
    open nothing new. A URL `urlparse` cannot read trusts nothing; the guard
    that checks it next writes the refusal.

    Each host is in the set twice when its spellings differ: as `urlparse`
    reads a URL a server wrote, and as httpx2 sends it, a name IDNA-encoded.
    The pinned client checks the URL httpx2 built, so a listed `täst.internal`
    has to match `xn--tst-qla.internal` there.
    """
    try:
        host = urlparse(server_url).hostname
    except ValueError:
        return frozenset()
    listed = _allowed_hosts()
    spellings = listed | {_on_the_wire(entry) for entry in listed}
    if host is None or _on_the_wire(host) not in spellings:
        return frozenset()
    return spellings


def _on_the_wire(host: str) -> str:
    """*host* as httpx2 puts it in a request: a name IDNA-encoded, an address as written.

    httpx2's own encoder rather than the `idna` codec, which is IDNA 2003 and
    spells `straße` differently. A host it cannot encode is kept as typed and
    matches nothing it would send.
    """
    try:
        return httpx2.URL(scheme="http", host=host).raw_host.decode("ascii")
    except httpx2.InvalidURL:
        return host


async def validate_mcp_url(url: str, *, honour_allowlist: bool = False) -> str:
    """SSRF-check a URL before we talk to it (same policy as webhooks).

    For a URL an operator typed: the connection's own address, and the consent
    URL the OAuth flow hands to somebody's browser rather than fetching. Runs
    in a thread because validation resolves DNS.

    Everything the OAuth flow *fetches* is chosen by the remote server, so it
    goes through :class:`app.core.pinned_http.PinnedAsyncClient` instead, which
    connects to the address it checked rather than handing the name back to be
    resolved again (#860).

    Args:
        url: The URL to check; http or https.
        honour_allowlist: Pass `True` only for a connection's own address, as
            `mcp_connection._checked_url` checks it. A host on
            `MCP_ALLOWED_HOSTS` then skips the address check and is not
            resolved. A URL a remote server chose keeps the strict default.

    Returns:
        The URL, unchanged.

    Raises:
        SSRFBlockedError: If the URL is blocked by SSRF protection.
        UrlRefusedError: If the URL is malformed.
    """
    trusted = _allowed_hosts() if honour_allowlist else frozenset()
    return await asyncio.to_thread(validate_webhook_url, url, trusted_hosts=trusted)


@dataclass(frozen=True)
class McpToolInfo:
    """One tool advertised by an MCP server (for the /test endpoint and UI)."""

    name: str
    description: str
    read_only: bool = False
    """Whether the server marks the tool `readOnlyHint` - the same signal the
    `writes` approval policy trusts, so the console shows which tools a binding
    would stop for. Absent is a write: a hint nobody gave promises nothing."""


@dataclass(frozen=True)
class McpServerSpec:
    """Transport-level description of one MCP server to attach to a run."""

    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    # None = expose every tool the server offers.
    allowed_tools: list[str] | None = None
    approval: McpApproval = "none"
    # Whether the server's `initialize` instructions join the agent's (the
    # connection's own opt-in; Pydantic AI leaves them out by default).
    include_instructions: bool = False
    # Which account this is, as its person reads it, where that is a question:
    # a labelled connection, or one of several accounts on one service. Shown
    # beside the call on an approval, so "Send mail" says from which mailbox.
    account: str | None = None
    # This deployment's own server (`/mcp`), reached through the application in
    # this process rather than over the network - never probed, never dialled out.
    in_process: bool = False
    # The organization's connection row this server is, so a call can be
    # recorded against it. None for a member's own connection and for `/mcp`.
    connection_id: UUID | None = None
    # Tools, by the name the server gives them, that never wait for approval
    # whatever `approval` says. Only this deployment's own server names any.
    ungated: frozenset[str] = frozenset()


@asynccontextmanager
async def _mcp_transport(
    url: str, headers: dict[str, str] | None, *, timeout: float
) -> AsyncGenerator[tuple[Any, Any]]:
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
    if infer_transport_type_from_url(url) == "sse":
        from mcp.client.sse import sse_client

        async with sse_client(url, headers=headers or None, timeout=CONNECT_TIMEOUT_SECS) as (
            read,
            write,
        ):
            yield read, write
    else:
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        limits = httpx2.Timeout(timeout, connect=CONNECT_TIMEOUT_SECS)
        async with (
            create_mcp_http_client(headers=headers or None, timeout=limits) as http_client,
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

    budget = timeout or HANDSHAKE_TIMEOUT_SECS
    try:
        async with asyncio.timeout(budget):
            async with (
                _mcp_transport(url, headers, timeout=budget) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.list_tools()
    except (Exception, BaseExceptionGroup) as exc:
        if _carries_base_exception(exc):
            raise
        raise McpProbeError(probe_error_message(exc, timeout=budget)) from exc
    return [
        McpToolInfo(
            name=t.name,
            description=t.description or "",
            read_only=bool(t.annotations and t.annotations.read_only_hint is True),
        )
        for t in result.tools
    ]


def _carries_base_exception(exc: BaseException) -> bool:
    """True when *exc* is (or wraps) something that isn't an `Exception`.

    A group carrying a `CancelledError` means the turn was cancelled, not
    that the server is down - swallowing it would keep the run alive.
    """
    if isinstance(exc, BaseExceptionGroup):
        return any(_carries_base_exception(inner) for inner in exc.exceptions)
    return not isinstance(exc, Exception)


def probe_error_message(exc: BaseException, *, timeout: float | None = None) -> str:
    """Human-readable reason for a failed probe.

    The MCP client runs on anyio task groups, so failures surface as nested
    ExceptionGroups ("unhandled errors in a TaskGroup") - unwrap to the root
    cause before showing anything to a user.
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    if isinstance(exc, httpx2.ConnectTimeout):
        return f"Connection timed out after {CONNECT_TIMEOUT_SECS:g}s"
    if isinstance(exc, TimeoutError):
        return f"The server timed out after {timeout or HANDSHAKE_TIMEOUT_SECS:g}s"
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
    # The in-process client carries the headers itself: the two are exclusive.
    server: Any = MCPToolset(
        spec.url,
        headers=None if spec.in_process else spec.headers or None,
        http_client=_in_process_client(spec.headers) if spec.in_process else None,
        id=f"mcp:{spec.name}",
        init_timeout=CONNECT_TIMEOUT_SECS,
        tool_error_behavior="failed",
        include_instructions=spec.include_instructions,
    )
    if spec.allowed_tools is not None:
        allowed = set(spec.allowed_tools)
        server = server.filtered(lambda _ctx, tool: tool.name in allowed)
    prefix = tool_prefix(spec.name)
    return ApprovalMarked(
        FittedNames(server.prefixed(prefix)),
        policy=spec.approval,
        account=spec.account,
        ungated=frozenset(f"{prefix}_{name}" for name in spec.ungated),
    )


TOOL_NAME_LIMIT = 64
"""The longest tool name the providers accept: OpenAI's limit, and the tightest of them."""

_NAME_REFUSED = re.compile(r"[^a-zA-Z0-9_-]")
"""What a provider refuses in a tool name: anything beyond letters, digits, `_` and `-`."""


def fitted_tool_name(name: str) -> str:
    """`name` as a provider accepts it: refused characters replaced, cut to the limit.

    A name that had to change ends in eight hex digits of a hash of the original,
    so two long names sharing their first 55 characters stay two tools.
    """
    if len(name) <= TOOL_NAME_LIMIT and not _NAME_REFUSED.search(name):
        return name
    digest = hashlib.sha256(name.encode()).hexdigest()[:8]
    return f"{_NAME_REFUSED.sub('_', name)[: TOOL_NAME_LIMIT - 9]}_{digest}"


@dataclass
class FittedNames(WrapperToolset[Any]):
    """An MCP server's prefixed tools, under names every provider accepts.

    The prefix and a server's own name add up: a 50-character tool behind a
    20-character connection name is past the 64 a provider allows, and one such
    name makes it refuse the whole request - every tool of every server, for the
    rest of the conversation. The model sees the fitted name; the server is called
    by the real one.
    """

    original: dict[str, str] = field(default_factory=dict, init=False)

    async def get_tools(self, ctx: RunContext[Any]) -> dict[str, ToolsetTool[Any]]:
        tools = await super().get_tools(ctx)
        fitted: dict[str, ToolsetTool[Any]] = {}
        for name, tool in tools.items():
            short = fitted_tool_name(name)
            if short == name:
                fitted[name] = tool
                continue
            self.original[short] = name
            fitted[short] = replace(tool, toolset=self, tool_def=replace(tool.tool_def, name=short))
        return fitted

    async def call_tool(
        self, name: str, tool_args: dict[str, Any], ctx: RunContext[Any], tool: ToolsetTool[Any]
    ) -> Any:
        real = self.original.get(name, name)
        ctx = replace(ctx, tool_name=real)
        tool = replace(tool, tool_def=replace(tool.tool_def, name=real))
        return await super().call_tool(real, tool_args, ctx, tool)


ACCOUNT = "agenticos_account"
"""The key `ApprovalMarked` puts the binding's account under, for an approval to name it.

Top-level in the metadata for the reason `NEEDS_APPROVAL` is: a server cannot write
there, so it cannot claim to be another account.
"""

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

    policy: McpApproval = "none"
    account: str | None = None
    ungated: frozenset[str] = frozenset()

    async def get_tools(self, ctx: RunContext[Any]) -> dict[str, ToolsetTool[Any]]:
        tools = await super().get_tools(ctx)
        named = {} if self.account is None else {ACCOUNT: self.account}
        return {
            name: replace(
                tool,
                tool_def=replace(
                    tool.tool_def,
                    metadata={
                        **(tool.tool_def.metadata or {}),
                        NEEDS_APPROVAL: name not in self.ungated
                        and needs_approval(tool.tool_def, self.policy),
                        **named,
                    },
                ),
            )
            for name, tool in tools.items()
        }


@dataclass
class ToolOrigins(WrapperToolset[Any]):
    """An organization server's tools, each noted in `seen` as having come from it.

    `seen` is one mapping shared by every server of a run, filled as the run
    lists its tools: the exact name the model calls, mapped to the connection
    that serves it, so the transcript records the call against that connection
    rather than inferring it from a prefix another connection may share (#2072).
    """

    connection_id: UUID
    seen: dict[str, UUID]

    async def get_tools(self, ctx: RunContext[Any]) -> dict[str, ToolsetTool[Any]]:
        tools = await super().get_tools(ctx)
        self.seen.update(dict.fromkeys(tools, self.connection_id))
        return tools


def unreachable_briefing(server: str, *, binding: str | None, held_by: str | None = None) -> str:
    """What the model is told about a bound server that did not answer this turn.

    Told nothing, the model reads the missing tools as an empty answer and
    reports "no data". The failure may be a timeout, a refused token or a
    protocol error, so the text promises neither that a retry works nor that it
    does not. `held_by` is another binding attached under the same prefix.
    """
    named = f"{server} server ({binding})" if binding else f"{server} server"
    prefix = tool_prefix(server)
    attached = (
        f"so none of its {prefix}_* tools are attached"
        if held_by is None
        else f"so it is not attached; the {prefix}_* tools that are attached belong to "
        f"{held_by}, and what they return comes from that account, not this one"
    )
    return (
        f"The {named} is not available this turn: it did not answer, or refused the "
        f"connection, when the turn started, {attached}. If asked for anything that "
        f"needs it, say it could not be reached just now - trying again may work, and "
        "if it keeps failing the connection needs checking. Do not answer as though it "
        "returned nothing, and do not guess what it would have said."
    )


@dataclass
class AnsweredRecently(WrapperToolset[Any]):
    """A server attached on a recent probe's word, left out of the turn if it is down now.

    Entering is where pydantic-ai connects, so a server that stopped answering
    since its probe fails here; the turn goes on without its tools, as it would
    have had the probe run, and the memo is dropped so the next turn probes again.
    The probe's own failure is briefed by the turn that ran it; this one happens
    after that briefing was written, so the toolset briefs it itself.
    """

    name: str = ""
    key: str = ""
    down: bool = field(default=False, init=False)

    async def __aenter__(self) -> AnsweredRecently:
        if self.down:
            return self
        try:
            await self.wrapped.__aenter__()
        except (Exception, BaseExceptionGroup) as exc:
            if _carries_base_exception(exc):
                raise
            logger.warning(
                "Skipping MCP server %r for this turn: %s", self.name, probe_error_message(exc)
            )
            _answered.pop(self.key, None)
            self.down = True
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        if self.down:
            return None
        return await self.wrapped.__aexit__(*args)

    async def get_tools(self, ctx: RunContext[Any]) -> dict[str, ToolsetTool[Any]]:
        if self.down:
            return {}
        return await super().get_tools(ctx)

    async def get_instructions(
        self, ctx: RunContext[Any]
    ) -> str | InstructionPart | Sequence[str | InstructionPart] | None:
        if self.down:
            return unreachable_briefing(self.name, binding=None)
        return await super().get_instructions(ctx)


PLATFORM_MCP_NAME = "agenticos"
"""What this deployment's own server is called in a run, and so its tools' prefix."""

PLATFORM_MCP_PREFIX = tool_prefix(PLATFORM_MCP_NAME)

PLATFORM_UNGATED_TOOLS = frozenset({"set_my_language"})
"""The platform's writes that never wait for approval - `platform_mcp._tools.UNGATED`.

Named again rather than imported: the platform's server imports the application,
which imports this layer.
"""

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
        ungated=PLATFORM_UNGATED_TOOLS,
    )


def _in_process_client(headers: dict[str, str]) -> Any:
    """An HTTP client whose requests go to this process's API application.

    Imported when a run needs it rather than at module load: the application
    imports the agent layer, so the agent layer reaching for it at import time
    would be a cycle.
    """
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
        key = _answer_key(spec)
        if _answered_recently(key):
            return AnsweredRecently(_make_toolset(spec), name=spec.name, key=key)
        try:
            await probe_mcp_server(spec.url, spec.headers)
        except Exception as exc:
            logger.warning(
                "Skipping MCP server %r for this turn: %s", spec.name, probe_error_message(exc)
            )
            return None
        _note_answer(key)
        return _make_toolset(spec)

    results = await asyncio.gather(*(_try(spec) for spec in specs))
    return list(zip(specs, results, strict=True))


async def build_mcp_toolsets(specs: list[McpServerSpec]) -> list[Any]:
    """Toolsets for every reachable server in *specs* (probed concurrently)."""
    specs = _dedupe_by_prefix(specs)
    if not specs:
        return []
    return [toolset for _spec, toolset in await probe_toolsets(specs) if toolset is not None]
