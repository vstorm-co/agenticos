"""The snapshot `0071_mcp_connection_catalog_key` backfills from.

A data migration that matches on URLs cannot fail loudly: a key whose URL was
mistyped simply leaves those rows `NULL`, which is indistinguishable from a
self-hosted server - and a `NULL` key is exactly the bug the migration exists to
fix, so the failure hides inside the fix. The snapshot is frozen on purpose (a
migration must read the same in a year), so what is checked is that it was
faithful to the catalog on the day it was written.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from app.services.mcp_catalog import CATALOG

REVISION = Path(__file__).resolve().parents[1] / "alembic" / "versions"
REVISION = REVISION / "0071_mcp_connection_catalog_key.py"


def _migration() -> ModuleType:
    """The revision as a module. Alembic loads these by path; so does this."""
    spec = importlib.util.spec_from_file_location("mcp_catalog_key_backfill", REVISION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_snapshot_row_names_a_catalog_entry_and_its_url() -> None:
    """A typo here is silent: those connections keep a null key, the agent
    reports the service as not connected, and the person connects a second
    account for a service they already had."""
    live = {entry.key: entry.url for entry in CATALOG if entry.url}

    assert dict(_migration().CATALOG_URLS) == live


def test_the_snapshot_holds_each_service_once() -> None:
    """Two rows for one key would run two updates, the second matching nothing -
    a mistake that reads as a working backfill."""
    keys = [key for key, _url in _migration().CATALOG_URLS]

    assert len(keys) == len(set(keys))


def test_the_match_ignores_a_trailing_slash() -> None:
    """The connect dialog seeds the catalog URL into an editable field, so
    `.../mcp/` and `.../mcp` are the same account saved twice over."""
    module = _migration()
    stripped = {url.rstrip("/") for _key, url in module.CATALOG_URLS}

    assert "https://mcp.vercel.com" in stripped, "the catalog holds one with a trailing slash"
    assert not any(url.endswith("/") for url in stripped)
