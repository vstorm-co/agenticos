"""The registry mirror as a table, asked of a real Postgres.

Every question here is one a mocked session cannot answer. `ILIKE` matching, an
`ORDER BY` over a `CASE`, `ON CONFLICT DO UPDATE`, and `OFFSET`/`LIMIT` producing
pages that neither skip nor repeat a row are all the database's behaviour rather
than this repository's.

The paging is the reason the table exists. 5,703 entries in memory could answer
"servers matching 'linear'" and could not answer "the fourth page of all of
them" without loading the lot and slicing it, so the console showed the curated
hundred and hid the rest behind a query - which reads as a catalog of a hundred.
"""

from __future__ import annotations

from datetime import UTC, datetime

import anyio
import pytest

from app.repositories import mcp_registry_server_repo as repo

pytestmark = pytest.mark.anyio


def _row(key: str, name: str, *, description: str = "", host: str = "mcp.example.test"):
    return {
        "id": key,
        "name": name,
        "description": description,
        "url": f"https://{host}/mcp",
        "host": host,
    }


async def _seed(db, *rows: dict[str, str]) -> None:
    await repo.upsert_many(db, list(rows))


class TestWritingTheMirror:
    async def test_a_sync_writes_every_row(self, db):
        await _seed(db, _row("a/1", "Alpha"), _row("b/2", "Beta"))

        assert await repo.count(db) == 2

    async def test_a_second_sync_updates_rather_than_duplicating(self, db):
        """Idempotent, which is what makes a refresh safe to run on a schedule."""
        await _seed(db, _row("a/1", "Alpha"))
        await _seed(db, _row("a/1", "Alpha Renamed"))

        assert await repo.count(db) == 1
        found = await repo.get(db, "a/1")
        assert found is not None and found.name == "Alpha Renamed"

    async def test_an_empty_batch_writes_nothing_rather_than_raising(self, db):
        assert await repo.upsert_many(db, []) == 0

    async def test_a_row_an_earlier_sync_wrote_and_this_one_did_not_is_pruned(self, db):
        """A server the registry stopped listing has to leave, or the mirror only
        grows and a dead endpoint stays offerable for ever.

        The cutoff is taken *between* the two writes, which is what the command
        does - it records the time before it starts and prunes anything older.
        The sleep is what makes the two stamps distinguishable: both writes land
        in the same millisecond otherwise and the cutoff is after both.
        """
        await _seed(db, _row("gone/1", "Delisted"))
        await anyio.sleep(0.05)
        cutoff = datetime.now(UTC)
        await anyio.sleep(0.05)
        await _seed(db, _row("kept/1", "Still There"))

        removed = await repo.delete_stale(db, cutoff)

        assert removed == 1
        assert await repo.get(db, "gone/1") is None
        assert await repo.get(db, "kept/1") is not None


class TestReadingIt:
    async def test_a_blank_query_is_every_row_paged(self, db):
        """The whole point of the table: "all of them" is an answer a listing can
        give, which the in-memory version could not."""
        await _seed(db, *[_row(f"k/{n}", f"Server {n:03}") for n in range(120)])

        page, total = await repo.search(db, limit=50)

        assert total == 120
        assert len(page) == 50

    async def test_pages_neither_skip_nor_repeat(self, db):
        await _seed(db, *[_row(f"k/{n}", f"Server {n:03}") for n in range(30)])

        first, _ = await repo.search(db, limit=10)
        second, _ = await repo.search(db, skip=10, limit=10)
        third, _ = await repo.search(db, skip=20, limit=10)

        ids = [row.id for row in first + second + third]
        assert len(ids) == 30
        assert len(set(ids)) == 30

    async def test_a_query_matches_name_description_and_host(self, db):
        await _seed(
            db,
            _row("n/1", "Notion"),
            _row("d/1", "Aggregator", description="talks to Notion"),
            _row("h/1", "Mystery", host="mcp.notion.com"),
            _row("x/1", "Unrelated"),
        )

        _, total = await repo.search(db, query="notion")

        assert total == 3

    async def test_matching_is_case_insensitive(self, db):
        await _seed(db, _row("n/1", "Notion"))

        _, total = await repo.search(db, query="NOTION")

        assert total == 1

    async def test_the_total_counts_matches_rather_than_the_page(self, db):
        """A pager has to say how many pages there are, and a page cannot count
        what it does not hold."""
        await _seed(db, *[_row(f"k/{n}", f"Widget {n:03}") for n in range(75)])

        page, total = await repo.search(db, query="widget", limit=10)

        assert len(page) == 10
        assert total == 75


class TestTheRanking:
    async def test_the_server_actually_called_that_comes_first(self, db):
        """A single "contains" pass answered "linear" with somebody's
        scientific-linear-algebra server."""
        await _seed(
            db,
            _row("a/1", "scientific-linear-algebra-tools"),
            _row("b/1", "Linear"),
        )

        page, _ = await repo.search(db, query="linear")

        assert page[0].name == "Linear"

    async def test_a_name_match_beats_a_description_match(self, db):
        await _seed(
            db,
            _row("a/1", "Some Aggregator", description="works with Linear and Jira"),
            _row("b/1", "Linear Sync"),
        )

        page, _ = await repo.search(db, query="linear")

        assert [row.name for row in page] == ["Linear Sync", "Some Aggregator"]

    async def test_the_shorter_name_wins_inside_a_band(self, db):
        await _seed(db, _row("a/1", "Sweden Payments (Stripe)"), _row("b/1", "Stripe"))

        page, _ = await repo.search(db, query="stripe")

        assert page[0].name == "Stripe"

    async def test_the_order_is_total_so_a_page_boundary_is_stable(self, db):
        """Two rows with the same band and the same name length must still order
        the same way twice, or page two repeats what page one showed."""
        await _seed(db, _row("a/1", "Alpha"), _row("b/1", "Bravo"), _row("c/1", "Delta"))

        first, _ = await repo.search(db, query="a", limit=2)
        again, _ = await repo.search(db, query="a", limit=2)

        assert [row.id for row in first] == [row.id for row in again]


class TestWhatBootstrapDoes:
    """Filling the mirror is part of first-time setup, not a thing to know about.

    An empty table is not visibly wrong: `/mcp` shows the curated hundred and
    looks complete, so the 5,703 mirrored servers were reachable only by somebody
    who knew to run `agenticos cmd mcp-registry-sync`.
    """

    async def test_it_fills_an_empty_mirror(self, db):
        from app.commands.bootstrap import _resolve_mcp_mirror

        await _resolve_mcp_mirror(db)

        assert await repo.count(db) > 1000

    async def test_it_leaves_a_filled_one_alone(self, db):
        """A re-run of bootstrap must not spend seconds rewriting five thousand
        rows that have not changed; refreshing is the sync command's job."""
        from app.commands.bootstrap import _resolve_mcp_mirror

        await _seed(db, _row("mine/1", "Only Mine"))
        await _resolve_mcp_mirror(db)

        assert await repo.count(db) == 1
