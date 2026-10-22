"""The one paged list, where the curated catalog joins the mirrored registry.

The join is the part worth testing against a real database, and specifically the
page boundary: 99 curated rows and a page size of 50 means page two ends 49 rows
into the catalog and page three starts one row in - so an off-by-one here skips a
server or shows it twice, on a list where nobody would notice which.
"""

from datetime import UTC, datetime

import pytest

from app.repositories import mcp_registry_server_repo as repo
from app.repositories import mcp_server_check_repo as check_repo
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

    async def test_the_mirror_says_how_many_it_holds(self, db):
        """What the unpaged catalog route reports beside the curated list."""
        await _mirror(db, 3)

        assert await mcp_listing.mirror_size(db) == 3

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

    async def test_a_category_reaches_the_mirror_through_its_inferred_category(self, db):
        """Each mirrored listing gets a category at sync (#2103), so a category no
        longer narrows to the curated hundred."""
        await _mirror(db, 3)
        await repo.upsert_many(
            db,
            [
                {
                    "id": "mirror/ci",
                    "name": "CI Runner",
                    "description": "",
                    "url": "https://ci.example.test/mcp",
                    "host": "ci.example.test",
                    "category": "development",
                }
            ],
        )

        found = await mcp_listing.page(db, category="development", limit=100)

        assert all(server.category == "development" for server in found.items)
        assert "mirror/ci" in [server.key for server in found.items]
        assert found.total == len(mcp_catalog.matching("", category="development")) + 1

    async def test_an_auth_filter_keeps_curated_entries_that_declare_it(self, db):
        found = await mcp_listing.page(db, auth="none", limit=100)

        assert found.items
        assert all(server.auth == "none" for server in found.items)


class TestWhatTheCheckFound:
    """What `agenticos cmd mcp-catalog-check` recorded, on the row the console draws (#2103)."""

    @staticmethod
    async def _checked(
        db,
        key: str,
        source: str,
        outcome: str,
        auth: str | None,
        tools: tuple[int, int] | None = None,
    ):
        await check_repo.upsert_many(
            db,
            [
                {
                    "key": key,
                    "source": source,
                    "outcome": outcome,
                    "auth": auth,
                    "tools": None if tools is None else tools[0],
                    "read_only_tools": None if tools is None else tools[1],
                    "duplicate_of": None,
                    "checked_at": datetime.now(UTC),
                }
            ],
        )

    async def test_a_curated_entry_that_answered_as_promised_is_verified(self, db):
        await self._checked(db, "github", "catalog", "sign_in", "oauth", (2, 1))

        (github,) = [s for s in await mcp_listing.curated(db) if s.key == "github"]

        assert github.verified
        assert github.check is not None
        assert (github.check.tools, github.check.read_only_tools) == (2, 1)

    async def test_a_curated_sign_in_that_did_not_offer_one_is_not_verified(self, db):
        oauth_entry = next(e for e in mcp_catalog.CATALOG if e.auth.value == "oauth" and e.url)
        await self._checked(db, oauth_entry.key, "catalog", "token", "token")

        (entry,) = [s for s in await mcp_listing.curated(db) if s.key == oauth_entry.key]

        assert not entry.verified
        assert entry.check is not None and entry.check.tools is None

    async def test_a_mirrored_listing_wears_the_auth_its_check_found(self, db):
        await _mirror(db, 2)
        await self._checked(db, "mirror/0000", "registry", "open", "none")

        found = await mcp_listing.page(db, skip=len(mcp_catalog.CATALOG), limit=50)
        by_key = {server.key: server for server in found.items}

        assert by_key["mirror/0000"].auth == "none"
        assert by_key["mirror/0000"].verified
        assert by_key["mirror/0001"].auth == "token", "unchecked keeps the old guess"
        assert not by_key["mirror/0001"].verified
