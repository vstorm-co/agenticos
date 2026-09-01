"""Filling and refreshing the mirrored MCP registry.

The table `0070_mcp_registry_servers` creates is empty, and the console falls
back to the curated catalog alone until this has run - which is what it did
before the table existed, so an install that never syncs is no worse off.

Two sources, and the default is the offline one. `--fetch` reads
`registry.modelcontextprotocol.io` live, which is how the mirror is refreshed
between deploys; without it the bundled snapshot is used, which is what makes a
first sync deterministic and possible on a box with no outbound access.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlparse

import click
import httpx

from app.commands import command, error, info, success
from app.db.session import get_db_context
from app.repositories import mcp_registry_server_repo
from app.services.mcp_catalog import CATALOG
from app.services.mcp_registry import seed_entries

REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0/servers"


def _curated_hosts() -> set[str]:
    """Hosts the curated catalog already covers, which the mirror must not repeat.

    Kept out of the table rather than filtered on every read: a duplicate would
    put one server on the list twice - once with a token hint and a brand mark,
    once without - and the curated row is the one to keep. Excluded here because
    this is where the two lists meet; the bundled snapshot was already generated
    this way, and a `--fetch` refresh would otherwise reintroduce them.
    """
    return {urlparse(entry.url).hostname or "" for entry in CATALOG if entry.url} - {""}


BATCH = 500
"""Rows per statement.

One statement for 5,703 rows builds a single enormous query; one per row is 5,703
round trips. Five hundred is neither, and it is what makes progress visible on a
sync somebody is watching.
"""

PAGE_LIMIT = 400
"""Pages the live fetch will walk before giving up.

The registry has answered 500 partway through pagination, so a fetch that never
terminates is a real shape rather than a hypothetical one. Whatever was collected
before the failure is still written - a partial refresh is better than none, and
`synced_at` is what keeps it honest about which rows it touched.
"""


async def _fetch_live() -> list[dict[str, str]]:
    """Every active server with a hosted https endpoint, from the live registry.

    Only `isLatest` and `active` records, only a `remotes` entry with an https
    URL, and never a URL holding a `{placeholder}` - that is a shape rather than
    an address, and pasting one produces a request to a hostname with braces in
    it.
    """
    found: dict[str, dict[str, str]] = {}
    curated = _curated_hosts()
    cursor: str | None = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for page in range(PAGE_LIMIT):
            params = {"limit": "100"}
            if cursor:
                params["cursor"] = cursor
            try:
                response = await client.get(f"{REGISTRY_URL}?{urlencode(params)}")
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                error(f"Registry fetch stopped on page {page + 1}: {type(exc).__name__}")
                break
            for record in payload.get("servers") or []:
                entry = _row(record)
                if entry is not None and entry["host"] not in curated:
                    found[entry["id"]] = entry
            cursor = (payload.get("metadata") or {}).get("nextCursor")
            if not cursor:
                break
            if (page + 1) % 20 == 0:
                info(f"  {len(found)} servers so far...")
    return list(found.values())


def _row(record: dict[str, Any]) -> dict[str, str] | None:
    meta = (record.get("_meta") or {}).get("io.modelcontextprotocol.registry/official") or {}
    if not (meta.get("isLatest") and meta.get("status") == "active"):
        return None
    server = record.get("server") or {}
    url = next(
        (
            remote.get("url", "")
            for remote in (server.get("remotes") or [])
            if (remote.get("url") or "").startswith("https://") and "{" not in remote["url"]
        ),
        "",
    )
    key = (server.get("name") or "").strip()
    name = (server.get("title") or server.get("name") or "").strip()
    host = urlparse(url).hostname or ""
    if not (url and key and name and host):
        return None
    return {
        "id": key[:255],
        "name": name[:255],
        "description": " ".join((server.get("description") or "").split())[:200],
        "url": url[:1024],
        "host": host[:255],
    }


@command("mcp-registry-sync", help="Fill or refresh the mirrored MCP registry")
@click.option(
    "--fetch",
    is_flag=True,
    help="Read the live registry instead of the bundled snapshot.",
)
@click.option(
    "--prune/--no-prune",
    default=True,
    help="Remove rows this sync did not touch - servers the registry no longer lists.",
)
def mcp_registry_sync(fetch: bool, prune: bool) -> None:
    """Write the registry mirror into `mcp_registry_servers`.

    Idempotent: a second run stamps `synced_at` and changes nothing else unless
    upstream did. Pruning is what removes a delisted server - without it the
    mirror only grows and a dead endpoint stays offerable for ever - and it is
    keyed on `synced_at` rather than on a diff of five thousand ids.
    """

    async def _run() -> None:
        started = datetime.now(UTC)
        entries = await _fetch_live() if fetch else list(seed_entries())
        if not entries:
            error("Nothing to write - the source returned no servers.")
            raise SystemExit(1)

        written = 0
        async with get_db_context() as db:
            for start in range(0, len(entries), BATCH):
                written += await mcp_registry_server_repo.upsert_many(
                    db, entries[start : start + BATCH]
                )
                info(f"  {written}/{len(entries)}")
            removed = await mcp_registry_server_repo.delete_stale(db, started) if prune else 0
            total = await mcp_registry_server_repo.count(db)

        success(f"Mirrored {written} servers ({total} in the table).")
        if removed:
            info(f"Removed {removed} the registry no longer lists.")

    asyncio.run(_run())
