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

import re
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


_CATEGORY_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "observability",
        (
            "monitoring",
            "observability",
            "logs",
            "logging",
            "tracing",
            "metrics",
            "alerting",
            "incident",
            "incidents",
            "apm",
            "uptime",
        ),
    ),
    (
        "finance",
        (
            "payment",
            "payments",
            "invoice",
            "invoices",
            "invoicing",
            "accounting",
            "finance",
            "financial",
            "banking",
            "bank",
            "crypto",
            "blockchain",
            "trading",
            "stocks",
            "tax",
            "expenses",
            "billing",
            "wallet",
            "defi",
        ),
    ),
    (
        "commerce",
        (
            "e-commerce",
            "ecommerce",
            "shop",
            "store",
            "storefront",
            "checkout",
            "retail",
            "orders",
            "products",
        ),
    ),
    (
        "marketing",
        (
            "marketing",
            "seo",
            "ads",
            "advertising",
            "campaign",
            "campaigns",
            "newsletter",
            "social media",
            "keywords",
            "brand",
        ),
    ),
    (
        "sales",
        (
            "crm",
            "sales",
            "leads",
            "lead",
            "prospects",
            "prospecting",
            "deals",
            "outreach",
            "pipeline",
        ),
    ),
    (
        "support",
        ("helpdesk", "help desk", "customer support", "support tickets", "customer service"),
    ),
    ("analytics", ("analytics", "dashboards", "insights", "reporting", "kpi", "kpis")),
    (
        "data",
        (
            "database",
            "databases",
            "sql",
            "postgres",
            "postgresql",
            "mysql",
            "warehouse",
            "dataset",
            "datasets",
            "vector",
            "query",
            "queries",
            "bigquery",
            "snowflake",
        ),
    ),
    (
        "development",
        (
            "github",
            "gitlab",
            "code",
            "coding",
            "developer",
            "developers",
            "deploy",
            "deployment",
            "devops",
            "kubernetes",
            "docker",
            "repository",
            "repositories",
            "infrastructure",
            "cloud",
            "testing",
            "sdk",
        ),
    ),
    ("design", ("design", "figma", "ui", "ux", "prototype", "diagram", "diagrams")),
    (
        "media",
        (
            "video",
            "videos",
            "audio",
            "image",
            "images",
            "music",
            "podcast",
            "speech",
            "voice",
            "photo",
            "photos",
        ),
    ),
    (
        "communication",
        (
            "email",
            "mail",
            "inbox",
            "chat",
            "messaging",
            "sms",
            "whatsapp",
            "telegram",
            "discord",
            "slack",
            "meetings",
        ),
    ),
    (
        "project-management",
        ("project", "projects", "task", "tasks", "issues", "jira", "kanban", "sprint", "tickets"),
    ),
    (
        "knowledge",
        ("documentation", "docs", "knowledge", "wiki", "notes", "research", "papers"),
    ),
    (
        "productivity",
        (
            "calendar",
            "scheduling",
            "schedule",
            "documents",
            "spreadsheet",
            "spreadsheets",
            "forms",
            "productivity",
        ),
    ),
    ("storage", ("storage", "files", "file", "drive", "s3", "upload", "uploads")),
    (
        "automation",
        (
            "automation",
            "automate",
            "workflow",
            "workflows",
            "browser",
            "scraping",
            "scrape",
            "crawl",
            "crawling",
            "integrations",
        ),
    ),
)
_CATEGORY_PATTERNS = tuple(
    (category, re.compile(r"\b(?:" + "|".join(map(re.escape, words)) + r")\b"))
    for category, words in _CATEGORY_WORDS
)


def categorise(name: str, description: str) -> str:
    """The curated catalog's category a listing reads as, or `other`.

    Counted rather than first-matched: "Search the Stripe docs for payment
    errors" mentions observability, finance and knowledge, and the category it
    mentions most is the one it is about. A tie goes to the earlier, narrower
    category in the table, so `incident tickets` reads as observability rather
    than project management. A listing that names nothing in the table is
    `other`: a wrong category hides a server under a heading somebody skips,
    where `other` only fails to help.
    """
    text = f"{name} {description}".casefold()
    best, best_hits = "other", 0
    for category, pattern in _CATEGORY_PATTERNS:
        hits = len(pattern.findall(text))
        if hits > best_hits:
            best, best_hits = category, hits
    return best


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
            "category": categorise(entry.name, entry.description),
        }
        for entry in REGISTRY
        if entry.host
    )
