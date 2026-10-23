"""Checking that the servers the catalog offers still answer, and what they ask for (#2103).

The catalog is two lists - a hundred curated entries and 5,703 mirrored from the
public registry - and neither was ever called. A member who picks a dead or
mislabelled server decides the platform does not work, so each listing is called
the way a connection would call it, without a credential, and what it did is
recorded per listing:

- it answered the MCP handshake and listed its tools (`open`);
- it refused, and publishes OAuth metadata, so a person signs in (`sign_in`);
- it refused without that metadata, so it takes a key or token (`token`);
- nothing answered (`unreachable`), something answered that is not an MCP server
  (`broken`), or the address points inside a network (`refused`).

A mirrored listing that is the same server as another one is a `duplicate` and
is not called at all. The console stops offering mirrored listings in the last
four outcomes, and marks a listing that answered as checked, with the date.

Unauthenticated on purpose. The check has no account at any of these services,
and the question it answers - does this address speak MCP, and how does it want
to be signed into - is the one a person meets before they have connected
anything. Whether a server's tools work once signed in is the connection's own
test, which already exists.
"""

import asyncio
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx2
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import mcp_oauth
from app.agents.mcp import McpToolInfo, probe_mcp_server, validate_mcp_url
from app.core import catalog
from app.core.config import settings
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import UrlRefusedError
from app.db.models.mcp_server_check import CheckOutcome
from app.repositories import mcp_registry_server_repo, mcp_server_check_repo
from app.services.mcp_catalog import CATALOG, CatalogAuth, CatalogEntry

__all__ = [
    "SNAPSHOT",
    "CheckRow",
    "Probe",
    "auth_found",
    "check_listings",
    "duplicates",
    "probe_listing",
    "report_markdown",
    "seed_snapshot",
    "verified",
    "write_checks",
]

SNAPSHOT = "mcp_checks.json"
"""The bundled result of the last check run before a release, under `app/core/catalog/`."""

Source = Literal["catalog", "registry"]


_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": settings.PROJECT_NAME, "version": "1.0"},
    },
}
_ACCEPT = "application/json, text/event-stream"
_REDIRECT_HOPS = 3
_BATCH = 500
"""Rows per statement: Postgres takes at most 32,767 parameters, seven a row here."""
_RETRY_AFTER_S = 1.0

_AUTH_OF: Mapping[CheckOutcome, str] = {
    CheckOutcome.OPEN: CatalogAuth.NONE.value,
    CheckOutcome.SIGN_IN: CatalogAuth.OAUTH.value,
    CheckOutcome.TOKEN: CatalogAuth.TOKEN.value,
}


@dataclass(frozen=True)
class Probe:
    """What calling one listing found.

    `detail` is for the operator's report and nowhere else: it can hold a status
    line or a transport error from somebody else's server, which is not text the
    console shows anybody.
    """

    outcome: CheckOutcome
    tools: tuple[McpToolInfo, ...] | None = None
    detail: str = ""

    @property
    def auth(self) -> str | None:
        return auth_found(self.outcome)


def auth_found(outcome: CheckOutcome) -> str | None:
    """What a server that answered this way asks for, as the catalog spells it."""
    return _AUTH_OF.get(outcome)


def verified(outcome: str | None, *, declared: str | None = None) -> bool:
    """Whether a listing's last check makes it safe to offer as working.

    A server that answered in any of the three ways is reachable. A curated entry
    is held to one more thing: one that promises sign-in must have published the
    metadata sign-in needs, or the button it shows is the one that fails. A
    curated `token` entry that answered `open` or `sign_in` is not contradicted -
    a server may accept a key and publish OAuth beside it.
    """
    if outcome not in _AUTH_OF:
        return False
    return not (declared == CatalogAuth.OAUTH.value and outcome != CheckOutcome.SIGN_IN)


def _same_server(url: str) -> str:
    """A URL as two listings of one server would both spell it."""
    parsed = urlparse(url.strip())
    return f"{(parsed.hostname or '').lower()}{parsed.path.rstrip('/')}"


def duplicates(listings: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Each listing that repeats another, mapped to the one kept.

    `listings` is `(key, url)`. Of several listings at one address the shortest
    key is kept - `com.acme/acme` over `com.acme/acme-mcp-server-remote` - and the
    key itself breaks a tie, so the answer does not depend on the order rows came
    back in.
    """
    groups: dict[str, list[str]] = {}
    for key, url in listings:
        groups.setdefault(_same_server(url), []).append(key)
    repeated: dict[str, str] = {}
    for keys in groups.values():
        kept, *rest = sorted(keys, key=lambda key: (len(key), key))
        repeated.update(dict.fromkeys(rest, kept))
    return repeated


async def _ask(client: PinnedAsyncClient, url: str) -> httpx2.Response:
    """POST `initialize` to *url*, following a redirect a few checked hops at most.

    `/mcp` answering `307 /mcp/` is common enough that refusing to follow would
    call working servers broken; each hop goes back through the pinned client, so
    a redirect cannot reach an address the first request could not.
    """
    request = client.build_request("POST", url, json=_INITIALIZE, headers={"Accept": _ACCEPT})
    retried = False
    for _ in range(_REDIRECT_HOPS + 1):
        response = await client.send(request)
        if response.status_code >= 500 and not retried:
            # Once, after a beat: a gateway answering 502 one minute and 401 the
            # next (Microsoft's did, twice in one run) is not a dead server, and a
            # mirrored listing marked dead is one the console stops offering.
            retried = True
            await asyncio.sleep(_RETRY_AFTER_S)
            continue
        if not response.is_redirect or response.next_request is None:
            return response
        request = response.next_request
    return response


async def _resolves(url: str) -> bool:
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        await asyncio.get_running_loop().getaddrinfo(host, None)
    except OSError, UnicodeError:
        # `UnicodeError`: the IDNA codec refuses an empty or over-long label
        # before any query is made (#2352).
        return False
    return True


async def _publishes_oauth(url: str) -> bool:
    try:
        await mcp_oauth.discover(url)
    except mcp_oauth.OAuthError:
        return False
    return True


def _speaks_mcp(response: httpx2.Response) -> bool:
    """Whether a 2xx answer to `initialize` is an MCP server's, not a web page's."""
    kind = response.headers.get("content-type", "")
    if kind.startswith("text/event-stream"):
        return True
    if not kind.startswith("application/json"):
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and isinstance(body.get("result"), dict)


async def probe_listing(
    url: str, *, timeout: float, transport: httpx2.AsyncBaseTransport | None = None
) -> Probe:
    """Call one listed server the way a first connection would, with no credential.

    Never raises for anything the server did: every failure is an outcome, so a
    sweep over thousands of listings records each one rather than stopping at the
    first that misbehaves. Cancellation still propagates.

    `transport` replaces the network for a test, as `PinnedAsyncClient` allows.
    """
    # A name that does not resolve is a server that is gone, not one the guard
    # refused: told apart here, before the guard reports both the same way.
    if not await _resolves(url):
        return Probe(CheckOutcome.UNREACHABLE, detail="the host name does not resolve")
    try:
        async with PinnedAsyncClient(
            timeout=httpx2.Timeout(timeout, connect=timeout), transport=transport
        ) as client:
            response = await _ask(client, url)
    except UrlRefusedError:
        return Probe(CheckOutcome.REFUSED, detail="address refused by the outbound guard")
    except (httpx2.HTTPError, httpx2.InvalidURL) as exc:
        return Probe(CheckOutcome.UNREACHABLE, detail=type(exc).__name__)

    if response.status_code in (401, 403):
        if await _publishes_oauth(url):
            return Probe(CheckOutcome.SIGN_IN, detail=f"HTTP {response.status_code}")
        return Probe(CheckOutcome.TOKEN, detail=f"HTTP {response.status_code}")
    if not (response.is_success and _speaks_mcp(response)):
        return Probe(CheckOutcome.BROKEN, detail=f"HTTP {response.status_code}")

    # The handshake answered without a credential; listing the tools is what says
    # whether the rest of the server does too. The MCP client resolves the name
    # again, so this probe checks the address again first. A connection's test
    # does not: its URL was checked once, when the connection was saved.
    try:
        await validate_mcp_url(url)
        tools = await probe_mcp_server(url, timeout=timeout)
    except UrlRefusedError:
        return Probe(CheckOutcome.REFUSED, detail="address refused by the outbound guard")
    except Exception as exc:  # `probe_mcp_server` raises only McpProbeError or cancellation
        return Probe(CheckOutcome.OPEN, detail=f"handshake only: {exc}")
    return Probe(CheckOutcome.OPEN, tools=tuple(tools))


async def probe_many(
    listings: Iterable[tuple[str, str]], *, concurrency: int, timeout: float
) -> dict[str, Probe]:
    """Probe every `(key, url)`, a bounded number at a time.

    Each probe is also bounded as a whole - a server can accept a connection and
    then trickle a response forever - by three of its own timeouts: the request,
    the OAuth discovery after a refusal, and the tool listing after a handshake.
    """
    gate = asyncio.Semaphore(concurrency)

    async def one(url: str) -> Probe:
        async with gate:
            try:
                async with asyncio.timeout(timeout * 3):
                    return await probe_listing(url, timeout=timeout)
            except TimeoutError:
                return Probe(CheckOutcome.UNREACHABLE, detail="timed out")

    pending = {key: asyncio.ensure_future(one(url)) for key, url in listings}
    try:
        await asyncio.gather(*pending.values())
    finally:
        for task in pending.values():
            task.cancel()
    return {key: task.result() for key, task in pending.items()}


def curated_listings(catalog: Iterable[CatalogEntry]) -> tuple[list[tuple[str, str]], list[str]]:
    """The curated entries a check can call, and the keys of those it cannot.

    An entry with no URL is a server the client runs or is issued per account -
    there is no address to call until somebody connects one.
    """
    callable_: list[tuple[str, str]] = []
    hosted_elsewhere: list[str] = []
    for entry in catalog:
        if entry.url:
            callable_.append((entry.key, entry.url))
        else:
            hosted_elsewhere.append(entry.key)
    return callable_, hosted_elsewhere


@dataclass(frozen=True)
class ToolCheck:
    name: str
    read_only: bool


@dataclass(frozen=True)
class CheckRow:
    """One listing's result, as the table, the snapshot and the report all hold it."""

    key: str
    source: Source
    outcome: CheckOutcome
    checked_at: datetime
    auth: str | None = None
    tools: tuple[ToolCheck, ...] | None = None
    duplicate_of: str | None = None
    detail: str = ""
    """For the operator's report only - never stored where the console reads it."""

    def stored(self) -> StoredCheck:
        """The row the table and the bundled snapshot hold: counts, no detail."""
        return StoredCheck(
            key=self.key,
            source=self.source,
            outcome=self.outcome,
            auth=self.auth,
            tools=None if self.tools is None else len(self.tools),
            read_only_tools=(
                None if self.tools is None else sum(tool.read_only for tool in self.tools)
            ),
            duplicate_of=self.duplicate_of,
            checked_at=self.checked_at,
        )


@dataclass(frozen=True)
class StoredCheck:
    """One listing's result as `mcp_server_checks` holds it."""

    key: str
    source: Source
    outcome: CheckOutcome
    checked_at: datetime
    auth: str | None = None
    tools: int | None = None
    read_only_tools: int | None = None
    duplicate_of: str | None = None

    def values(self) -> dict[str, Any]:
        return {**asdict(self), "outcome": self.outcome.value}


def _row(key: str, source: Source, probe: Probe, at: datetime) -> CheckRow:
    tools = (
        None
        if probe.tools is None
        else tuple(ToolCheck(name=tool.name, read_only=tool.read_only) for tool in probe.tools)
    )
    return CheckRow(
        key=key,
        source=source,
        outcome=probe.outcome,
        checked_at=at,
        auth=probe.auth,
        tools=tools,
        detail=probe.detail,
    )


async def check_listings(
    db: AsyncSession,
    *,
    sources: frozenset[Source],
    limit: int | None,
    concurrency: int,
    timeout: float,
) -> list[CheckRow]:
    """Call every listing in `sources` and say what each one did.

    The registry's duplicates are found over the whole mirror, so a listing kept
    in place of another is the same one whatever `limit` takes; `limit` then
    narrows which of the rest are called, for a quick look at a few.
    """
    at = datetime.now(UTC)
    rows: list[CheckRow] = []
    to_call: list[tuple[str, str, Source]] = []
    if "catalog" in sources:
        hosted, elsewhere = curated_listings(CATALOG)
        rows += [CheckRow(key, "catalog", CheckOutcome.SELF_HOSTED, at) for key in elsewhere]
        to_call += [(key, url, "catalog") for key, url in hosted]
    if "registry" in sources:
        mirrored = await mcp_registry_server_repo.listings(db)
        repeated = duplicates(mirrored)
        rows += [
            CheckRow(key, "registry", CheckOutcome.DUPLICATE, at, duplicate_of=kept)
            for key, kept in repeated.items()
        ]
        rest: list[tuple[str, str, Source]] = [
            (key, url, "registry") for key, url in mirrored if key not in repeated
        ]
        to_call += rest if limit is None else rest[:limit]
    probes = await probe_many(
        [(key, url) for key, url, _ in to_call], concurrency=concurrency, timeout=timeout
    )
    rows += [_row(key, source, probes[key], at) for key, _url, source in to_call]
    return rows


async def write_checks(db: AsyncSession, rows: Iterable[CheckRow], *, prune: bool) -> int:
    """Record these results; with `prune`, drop checks of listings this run did not reach."""
    stored = [row.stored().values() for row in rows]
    for start in range(0, len(stored), _BATCH):
        await mcp_server_check_repo.upsert_many(db, stored[start : start + _BATCH])
    if prune and stored:
        await mcp_server_check_repo.delete_stale(db, min(row["checked_at"] for row in stored))
    return len(stored)


_SNAPSHOT_ROWS: TypeAdapter[tuple[StoredCheck, ...]] = TypeAdapter(tuple[StoredCheck, ...])
_REPORT_ROWS: TypeAdapter[tuple[CheckRow, ...]] = TypeAdapter(tuple[CheckRow, ...])


def snapshot_json(rows: Iterable[CheckRow]) -> str:
    """The rows as the bundled snapshot holds them, one per line in a stable order.

    One line each, so a re-check before the next release diffs as the listings
    whose result changed rather than as a reformatted file.
    """
    kept = sorted((row.stored() for row in rows), key=lambda row: (row.source, row.key))
    # Empty fields left out: most listings have no tools counted or duplicate
    # named, and writing every null is a third of the file.
    lines = [
        json.dumps(
            {key: value for key, value in row.items() if value is not None},
            separators=(",", ":"),
            ensure_ascii=False,
        )
        for row in _SNAPSHOT_ROWS.dump_python(tuple(kept), mode="json")
    ]
    return "[\n" + ",\n".join(lines) + "\n]\n"


async def seed_snapshot(db: AsyncSession) -> int:
    """Seed the bundled check results for listings this deployment has not checked.

    A deployment that ran its own check keeps it: what a release shipped is older.
    """
    stored = [row.values() for row in catalog.load(SNAPSHOT, _SNAPSHOT_ROWS)]
    seeded = 0
    for start in range(0, len(stored), _BATCH):
        seeded += await mcp_server_check_repo.insert_missing(db, stored[start : start + _BATCH])
    return seeded


def report_markdown(rows: Iterable[CheckRow]) -> str:
    """What the run found, for whoever keeps the catalog.

    Every curated entry is listed, because each one is a promise somebody made and a
    failure there is a finding to act on. The registry is summarised by outcome,
    with every listing that was not offered any more named in the JSON beside it.
    """
    rows = list(rows)
    curated = sorted((row for row in rows if row.source == "catalog"), key=lambda row: row.key)
    mirrored = [row for row in rows if row.source == "registry"]
    declared = {entry.key: entry.auth.value for entry in CATALOG}
    lines = ["# MCP catalog check", ""]
    if rows:
        lines += [f"Checked {min(row.checked_at for row in rows):%Y-%m-%d %H:%M} UTC.", ""]
    for title, part in (("Curated", curated), ("Registry", mirrored)):
        if not part:
            continue
        counted = Counter(row.outcome.value for row in part)
        summary = ", ".join(f"{outcome} {count}" for outcome, count in sorted(counted.items()))
        lines += [f"## {title}: {len(part)}", "", summary, ""]
    if curated:
        lines += [
            "## Curated entries",
            "",
            "| Key | Declared | Found | Tools (read-only) | Verified | Detail |",
            "|---|---|---|---|---|---|",
        ]
        for row in curated:
            tools = (
                ""
                if row.tools is None
                else (f"{len(row.tools)} ({sum(tool.read_only for tool in row.tools)})")
            )
            ok = verified(row.outcome, declared=declared.get(row.key))
            lines.append(
                f"| {row.key} | {declared.get(row.key, '')} | {row.outcome.value} | {tools} "
                f"| {'yes' if ok else 'no'} | {row.detail} |"
            )
        lines.append("")
    return "\n".join(lines)


def report_json(rows: Iterable[CheckRow]) -> str:
    """Every row with its detail, for a reader who wants more than the summary."""
    return json.dumps(
        _REPORT_ROWS.dump_python(tuple(rows), mode="json"), indent=1, ensure_ascii=False
    )


def write_snapshot(rows: Iterable[CheckRow], path: Path | None = None) -> Path:
    """Write the bundled snapshot - by default, the file `seed_snapshot` reads."""
    target = path or Path(catalog.__file__).parent / SNAPSHOT
    target.write_text(snapshot_json(rows), encoding="utf-8")
    return target
