"""The one paged list, where the curated catalog joins the mirrored registry.

The join is the part worth testing against a real database, and specifically the
page boundary: 99 curated rows and a page size of 50 means page two ends 49 rows
into the catalog and page three starts one row in - so an off-by-one here skips a
server or shows it twice, on a list where nobody would notice which.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
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
        for index in range((len(mcp_catalog.CATALOG) + 40 + 49) // 50):
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


class TestConnectedRegistryIdentities:
    @pytest.mark.parametrize(
        ("first_path", "second_path"),
        [
            ("/Finance/mcp", "/finance/mcp"),
            ("/mcp?tenant=Finance", "/mcp?tenant=finance"),
            ("/mcp?token=value/", "/mcp?token=value"),
        ],
    )
    async def test_url_matching_preserves_path_and_query_identity(
        self, db: AsyncSession, first_path: str, second_path: str
    ) -> None:
        await repo.upsert_many(
            db,
            [
                {
                    "id": f"mirror/account-{index}",
                    "name": f"Account {index}",
                    "description": "",
                    "url": f" HTTPS://GATEWAY.EXAMPLE.TEST{path} ",
                    "host": "gateway.example.test",
                }
                for index, path in enumerate((first_path, second_path))
            ],
        )

        found = await repo.for_connections(
            db,
            keys=set(),
            urls={f"https://gateway.example.test{second_path}"},
            names=set(),
        )

        assert [server.id for server in found] == ["mirror/account-1"]

    async def test_a_registry_key_resolves_without_matching_the_publisher_name(
        self, db: AsyncSession
    ) -> None:
        await repo.upsert_many(
            db,
            [
                {
                    "id": "com.example/opaque-service",
                    "name": "Publisher Display Name",
                    "description": "A service with an unrelated description.",
                    "url": "https://unrelated.example.test/mcp",
                    "host": "unrelated.example.test",
                },
                {
                    "id": "com.example/opaque-service-extra",
                    "name": "Another Display Name",
                    "description": "A second unrelated service.",
                    "url": "https://second.example.test/mcp",
                    "host": "second.example.test",
                },
            ],
        )

        found = await mcp_listing.page(db, query="com.example/opaque-service", limit=10)

        assert found.total == 1
        assert [server.key for server in found.items] == ["com.example/opaque-service"]

    async def test_only_requested_account_identities_are_resolved(self, db: AsyncSession) -> None:
        await _mirror(db, 120)
        await repo.upsert_many(
            db,
            [
                {
                    "id": "mirror/normalized",
                    "name": "Normalized",
                    "description": "",
                    "url": "  HTTPS://INTERNAL.EXAMPLE.TEST/mcp///  ",
                    "host": "internal.example.test",
                }
            ],
        )

        found = await repo.for_connections(
            db,
            keys={"mirror/0119"},
            urls={"https://internal.example.test/mcp"},
            names={"mirror/0060"},
        )

        assert [server.id for server in found] == [
            "mirror/normalized",
            "mirror/0060",
            "mirror/0119",
        ]

    async def test_multiple_matching_account_identities_resolve_one_server(
        self, db: AsyncSession
    ) -> None:
        await _mirror(db, 2)

        found = await repo.for_connections(
            db,
            keys={"mirror/0001"},
            urls={"https://mcp1.example.test/mcp"},
            names={"mirror/0001"},
        )

        assert [server.id for server in found] == ["mirror/0001"]

    async def test_an_empty_account_list_never_queries_the_mirror(self) -> None:
        db = AsyncMock(spec=AsyncSession)

        assert await repo.for_connections(db, keys=set(), urls=set(), names=set()) == []

        db.execute.assert_not_called()

    async def test_unknown_account_identities_resolve_nothing(self, db: AsyncSession) -> None:
        await _mirror(db, 2)

        assert (
            await repo.for_connections(
                db,
                keys={"missing/key"},
                urls={"https://missing.example.test/mcp"},
                names={"Mirrored 0001"},
            )
            == []
        )

    async def test_exclusion_is_applied_before_counting_and_paging(self, db: AsyncSession) -> None:
        await _mirror(db, 120)
        excluded = {f"mirror/{index:04}" for index in range(65)}

        first, first_total = await repo.search(db, excluded_ids=excluded, limit=50)
        second, second_total = await repo.search(db, excluded_ids=excluded, skip=50, limit=50)

        assert first_total == second_total == 55
        assert len(first) == 50
        assert len(second) == 5
        assert [server.id for server, _check in first + second] == [
            f"mirror/{index:04}" for index in range(65, 120)
        ]

    async def test_exclusion_preserves_search_category_and_auth_filters(
        self, db: AsyncSession
    ) -> None:
        await repo.upsert_many(
            db,
            [
                {
                    "id": f"mirror/{name}",
                    "name": f"Payments {name}",
                    "description": "",
                    "url": f"https://{name}.example.test/mcp",
                    "host": f"{name}.example.test",
                    "category": category,
                }
                for name, category in [
                    ("connected", "finance"),
                    ("available", "finance"),
                    ("other", "development"),
                ]
            ],
        )
        await check_repo.upsert_many(
            db,
            [
                {
                    "key": f"mirror/{name}",
                    "source": "registry",
                    "outcome": "sign_in",
                    "auth": "oauth",
                    "tools": None,
                    "read_only_tools": None,
                    "duplicate_of": None,
                    "checked_at": datetime.now(UTC),
                }
                for name in ["connected", "available", "other"]
            ],
        )

        found, total = await repo.search(
            db,
            query="payments",
            category="finance",
            auth="oauth",
            excluded_ids={"mirror/connected"},
        )

        assert total == 1
        assert [server.id for server, _check in found] == ["mirror/available"]


async def test_exact_registry_identity_ranks_before_related_names_in_a_bounded_lookup(
    db: AsyncSession,
) -> None:
    target = "registry/target"
    await repo.upsert_many(
        db,
        [
            {
                "id": target if index == 12 else f"related/{index}",
                "name": "Z target" if index == 12 else f"{target} alternative {index}",
                "description": "",
                "url": f"https://server{index}.example.test/mcp",
                "host": f"server{index}.example.test",
            }
            for index in range(13)
        ],
    )

    rows, total = await repo.search(db, query=target, limit=10)

    assert total == 13
    assert rows[0][0].id == target
    assert len(rows) == 10


async def test_same_named_registry_servers_keep_a_stable_order_between_pages(
    db: AsyncSession,
) -> None:
    ids = [f"same-name/{index:02}" for index in range(12)]
    await repo.upsert_many(
        db,
        [
            {
                "id": key,
                "name": "Same service",
                "description": "",
                "url": f"https://server{index}.example.test/mcp",
                "host": f"server{index}.example.test",
            }
            for index, key in enumerate(reversed(ids))
        ],
    )
    first, first_total = await repo.search(db, limit=7)
    second, second_total = await repo.search(db, skip=7, limit=7)

    assert first_total == second_total == 12
    assert [row.id for row, _check in first + second] == ids


@pytest.mark.parametrize(
    "query", ["ai.alpic.alpix/Alpix", "ai.alpic.alpix/alpix", "AI.ALPIC.ALPIX/ALPIX"]
)
async def test_registry_key_matching_and_ranking_ignore_case(db: AsyncSession, query: str) -> None:
    key = "ai.alpic.alpix/Alpix"
    await repo.upsert_many(
        db,
        [
            {
                "id": key,
                "name": "Alpix",
                "description": "Tools",
                "url": "https://alpix.example.test/mcp",
                "host": "alpix.example.test",
            },
            {
                "id": "related/one",
                "name": f"{query} alternative",
                "description": "Tools",
                "url": "https://other.example.test/mcp",
                "host": "other.example.test",
            },
        ],
    )

    rows, total = await repo.search(db, query=query, limit=1)

    assert total == 2
    assert rows[0][0].id == key


async def test_registry_pruning_keeps_a_persisted_account_and_its_saved_key(
    db: AsyncSession,
) -> None:
    user = User(email=f"mcp-{uuid4().hex}@example.test", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(name="MCP workspace", slug=uuid4().hex, created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    key = "registry/retired-fixture"
    connection = McpConnection(
        user_id=user.id,
        scope="user",
        name="saved-account",
        catalog_key=key,
        url="https://retired.example.test/mcp",
        auth_type="bearer",
    )
    db.add(connection)
    await db.flush()
    await repo.upsert_many(
        db,
        [
            {
                "id": key,
                "name": "Retired service",
                "description": "",
                "url": connection.url,
                "host": "retired.example.test",
            }
        ],
    )
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    before = await mcp_listing.page(db, ctx=ctx, query=key, state="connected")
    assert before.items[0].key == key and not before.items[0].custom

    assert await repo.delete_stale(db, datetime.now(UTC) + timedelta(seconds=1)) == 1
    after = await mcp_listing.page(db, ctx=ctx, query=key, state="connected")

    assert after.total == 1
    assert after.items[0].key == key
    assert after.items[0].connection_ids == (connection.id,)
    assert after.items[0].custom
