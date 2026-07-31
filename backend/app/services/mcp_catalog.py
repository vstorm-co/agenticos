"""A curated catalog of MCP servers an organization can connect in one click.

MCP is the platform's answer to "we cannot write a connector for everything":
a client points at a server and its tools appear in the Builder with no code on
our side. But a picker that starts empty and asks for a URL is a picker nobody
uses, so the common servers are listed here with the metadata needed to connect
them.

This is deliberately a hand-maintained list rather than a mirror of the public
registry. Each entry is a small promise - that we have looked at the server, that
the auth flow works, that the description is honest - and a mirrored registry
cannot make that promise. Adding an entry is cheap; the URL is what varies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import TypeAdapter

from app.core import catalog


class CatalogAuth(StrEnum):
    """How a server authenticates, which is the only thing that really varies."""

    NONE = "none"
    TOKEN = "token"
    OAUTH = "oauth"


@dataclass(frozen=True)
class CatalogEntry:
    """One connectable server."""

    key: str
    name: str
    description: str
    category: str
    auth: CatalogAuth
    # Where the server lives. Empty when the client hosts it themselves and must
    # supply the URL - self-hosted databases, internal services.
    url: str = ""
    docs_url: str = ""
    # What to tell the person pasting a credential. Generic instructions are the
    # main reason token setup fails.
    token_hint: str = ""
    # The brand mark to draw, as `BrandIcon` names them. Empty falls back to a
    # monogram, which is a deliberate look rather than a missing one - every
    # icon set is finite and this catalog is not.
    icon: str = ""


# Loaded from data rather than written out here: the entries are pure metadata,
# and `catalog.load` validates every field against `CatalogEntry` at import -
# a malformed entry refuses to start the app instead of vanishing from the
# picker. The file lives beside the other deployment catalogs and the custom
# icons that may accompany an entry.
CATALOG: tuple[CatalogEntry, ...] = catalog.load(
    "mcp_servers.json", TypeAdapter(tuple[CatalogEntry, ...])
)

BY_KEY: dict[str, CatalogEntry] = {entry.key: entry for entry in CATALOG}


def get_entry(key: str) -> CatalogEntry | None:
    return BY_KEY.get(key)
