"""The one paged list, where the curated catalog joins the mirrored registry.

The join is the part worth testing against a real database, and specifically the
page boundary: 99 curated rows and a page size of 50 means page two ends 49 rows
into the catalog and page three starts one row in - so an off-by-one here skips a
server or shows it twice, on a list where nobody would notice which.
"""

from __future__ import annotations

import pytest

from app.repositories import mcp_registry_server_repo as repo
from app.services import mcp_catalog, mcp_listing

pytestmark = pytest.mark.anyio


async def _mirror(db, count: int) -> None:
    await repo.upsert_many(
        db,
        [
            {
                "id": f"mirror/{n:04}",
                "name": f"Mirrored {n:04}",
                "description": "From the registry.",
                "url": f"https://mcp{n}.example.test/mcp",
                "host": f"mcp{n}.example.test",
            }
            for n in range(count)
        ],
    )


class TestTheJoin:
    async def test_the_first_page_is_curated(self, db):
        await _mirror(db, 40)

        found = await mcp_listing.page(db, limit=50)

        assert all(server.reviewed for server in found.items)

    async def test_the_total_counts_both_sources(self, db):
        await _mirror(db, 40)

        found = await mcp_listing.page(db, limit=5)

        assert found.total == len(mcp_catalog.CATALOG) + 40
        assert found.registry_total == 40

    async def test_a_page_spanning_the_boundary_neither_skips_nor_repeats(self, db):
        """The off-by-one this exists for: with 99 curated rows and 50 to a page,
        page two holds the last 49 of them plus the mirror's first."""
        await _mirror(db, 40)
        seen: list[str] = []
        for index in range(4):
            found = await mcp_listing.page(db, skip=index * 50, limit=50)
            seen += [server.key for server in found.items]

        assert len(seen) == len(set(seen)), "a server appeared on two pages"
        assert len(seen) == len(mcp_catalog.CATALOG) + 40

    async def test_a_mirrored_row_says_nobody_reviewed_it(self, db):
        await _mirror(db, 2)

        found = await mcp_listing.page(db, skip=len(mcp_catalog.CATALOG), limit=50)

        assert found.items
        assert all(server.reviewed is False for server in found.items)
        assert all(server.token_hint is None for server in found.items)


class TestFiltering:
    async def test_a_query_reaches_both_sources(self, db):
        await repo.upsert_many(
            db,
            [
                {
                    "id": "mirror/notion",
                    "name": "Notion Sidecar",
                    "description": "",
                    "url": "https://mcp.side.test/mcp",
                    "host": "mcp.side.test",
                }
            ],
        )

        found = await mcp_listing.page(db, query="notion")

        keys = [server.key for server in found.items]
        assert "notion" in keys, "the curated entry"
        assert "mirror/notion" in keys, "the mirrored one"

    async def test_a_category_asks_for_catalog_entries_only(self, db):
        """The mirror has no categories, so answering with mirror rows would put
        uncategorised servers under a heading that says otherwise."""
        await _mirror(db, 40)

        found = await mcp_listing.page(db, category="development")

        assert found.items
        assert all(server.category == "development" for server in found.items)
        assert found.total == len(mcp_catalog.matching("", category="development"))
