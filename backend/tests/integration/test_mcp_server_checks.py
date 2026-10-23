"""What the catalog check recorded, as rows in a real Postgres (#2103)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.mcp_server_check import McpServerCheck
from app.repositories import mcp_server_check_repo as repo

pytestmark = pytest.mark.anyio

_EARLIER = datetime(2026, 10, 1, tzinfo=UTC)
_NOW = datetime(2026, 10, 12, tzinfo=UTC)


def _row(key: str, outcome: str, at: datetime = _NOW) -> dict[str, object]:
    return {
        "key": key,
        "source": "registry",
        "outcome": outcome,
        "auth": None,
        "tools": 3,
        "read_only_tools": 2,
        "duplicate_of": None,
        "checked_at": at,
    }


async def test_a_newer_check_replaces_the_older_one(db):
    await repo.upsert_many(db, [_row("a/1", "broken", _EARLIER)])
    await repo.upsert_many(db, [_row("a/1", "sign_in")])

    found = await repo.get_many(db, ["a/1", "never/checked"])

    assert list(found) == ["a/1"]
    assert found["a/1"].outcome == "sign_in"
    assert (found["a/1"].tools, found["a/1"].read_only_tools) == (3, 2)
    assert await repo.count(db) == 1


async def test_a_snapshot_never_overwrites_a_deployments_own_check(db):
    await repo.upsert_many(db, [_row("a/1", "open")])

    written = await repo.insert_missing(db, [_row("a/1", "broken", _EARLIER), _row("b/1", "token")])

    found = await repo.get_many(db, ["a/1", "b/1"])
    assert written == 1
    assert (found["a/1"].outcome, found["b/1"].outcome) == ("open", "token")


async def test_a_full_run_forgets_listings_it_did_not_reach(db):
    await repo.upsert_many(db, [_row("gone/1", "open", _EARLIER), _row("kept/1", "open")])

    assert await repo.delete_stale(db, _NOW - timedelta(days=1)) == 1
    assert list(await repo.get_many(db, ["gone/1", "kept/1"])) == ["kept/1"]


async def test_nothing_to_write_or_read_is_no_query(db):
    assert await repo.upsert_many(db, []) == 0
    assert await repo.insert_missing(db, []) == 0
    assert await repo.get_many(db, []) == {}


def test_the_row_names_its_listing():
    assert "a/1" in repr(McpServerCheck(key="a/1", outcome="open"))
