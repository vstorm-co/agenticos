"""Every server the public MCP registry knows, mirrored into a table.

The **second** catalog, and the distinction is the whole design.
:mod:`app.services.mcp_catalog` is a hundred entries somebody looked at: the auth
flow works, the description is honest, there is a sentence telling whoever pastes
a credential what kind of credential it is. This is 5,703 entries nobody looked
at, mirrored from `registry.modelcontextprotocol.io` so that a server the curated
list has never heard of can still be found by name instead of by URL.

Three consequences of not being the curated list, all deliberate:

**No token hint.** The registry has no such field, so there is nothing honest to
put in one. A connection made from here shows the publisher's own description and
nothing about its credential.

**No baked logo.** `mcp-logos.generated.ts` inlines a favicon per catalog host,
which at 1.9 KB each would be 10.5 MB of base64 in a module the browser loads.
These fall through to the runtime favicon service that `mcp-catalog.ts` already
keeps for an unknown host - which is exactly what it was written for.

**In a table, not in memory.** The JSON is the *seed*; the read path is
`mcp_registry_servers`, because a file can answer "servers matching 'linear'" and
cannot answer "the fourth page of all of them" without loading 5,703 entries and
slicing them - which is what made the console show a hundred and hide the rest
behind a query. The ranking moved into SQL with it: ranking a page is ranking
whatever that page happened to contain.

The table is deployment-wide and has no `organization_id`. The skill gallery
settled the neighbouring question the other way round - seventy skills seeded per
tenant would be seventy rows nobody asked for in every organization - and the
difference is that a catalog is not tenant data. One global table is one table.

The mirror is a snapshot, not a live proxy: an install must not stop working
because somebody else's registry is down. Fill or refresh it with
`uv run agenticos cmd mcp-registry-sync`.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

from pydantic import TypeAdapter

from app.core import catalog


@dataclass(frozen=True)
class RegistryEntry:
    """One server as the public registry states it.

    `key` is the registry's own reverse-DNS name (`com.example/server`), which is
    unique there and is what a refresh matches on. It is not a catalog key: the
    curated catalog's keys are short words a person chose.
    """

    key: str
    name: str
    description: str
    url: str

    @property
    def host(self) -> str:
        return urlparse(self.url).hostname or ""


REGISTRY: tuple[RegistryEntry, ...] = catalog.load(
    "mcp_registry.json", TypeAdapter(tuple[RegistryEntry, ...])
)


def seed_entries() -> tuple[dict[str, str], ...]:
    """The bundled mirror, as rows for `upsert_many`.

    The shape the repository writes rather than the dataclass, because this
    exists to be inserted: `host` is derived here so the column can be indexed
    and a URL search does not have to parse one per row.
    """
    return tuple(
        {
            "id": entry.key,
            "name": entry.name,
            "description": entry.description,
            "url": entry.url,
            "host": entry.host,
        }
        for entry in REGISTRY
        if entry.host
    )
