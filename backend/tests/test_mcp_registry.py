"""The bundled registry mirror, which is the seed the table is filled from.

Reading is the repository's job now and is tested against a real database in
`tests/integration/test_mcp_registry_table.py` - a `LIKE`, an `ORDER BY` over a
`CASE` and an `ON CONFLICT` are three things a mocked session cannot answer.

What is left here is the file: 5,703 entries that have to be insertable, because
a row that violates a column length or carries a URL template is a row somebody
tries to connect to.
"""

from __future__ import annotations

from app.db.models.mcp_registry_server import McpRegistryServer
from app.services import mcp_registry


class TestTheShippedMirror:
    def test_it_loads_and_is_not_small(self):
        assert len(mcp_registry.REGISTRY) > 1000

    def test_every_entry_has_an_https_url_a_name_and_a_host(self):
        for entry in mcp_registry.REGISTRY:
            assert entry.url.startswith("https://")
            assert entry.name
            assert entry.host

    def test_keys_are_unique_so_an_upsert_matches_one_row(self):
        keys = [entry.key for entry in mcp_registry.REGISTRY]
        assert len(keys) == len(set(keys))

    def test_no_entry_carries_a_url_template(self):
        """`{studio}-{game}.example` is a shape, not an address. Pasting one
        produces a request to a hostname with braces in it."""
        for entry in mcp_registry.REGISTRY:
            assert "{" not in entry.url

    def test_the_host_property_is_the_urls_host(self):
        entry = mcp_registry.REGISTRY[0]

        assert entry.host in entry.url


class TestWhatIsSeeded:
    def test_every_mirrored_entry_becomes_a_row(self):
        assert len(mcp_registry.seed_entries()) == len([e for e in mcp_registry.REGISTRY if e.host])

    def test_a_row_carries_exactly_the_columns_the_table_has(self):
        """A key the model does not have makes `upsert_many` raise on the first
        batch, five thousand rows into a sync somebody is watching."""
        columns = {column.name for column in McpRegistryServer.__table__.columns}
        for row in mcp_registry.seed_entries()[:50]:
            assert set(row) <= columns

    def test_the_host_is_derived_rather_than_left_to_the_query(self):
        """Stored so the column can be indexed: a `LIKE` against a substring of
        `url` cannot use one."""
        for row in mcp_registry.seed_entries()[:50]:
            assert row["host"]
            assert row["host"] in row["url"]

    def test_nothing_exceeds_the_column_it_goes_in(self):
        limits = {
            column.name: column.type.length
            for column in McpRegistryServer.__table__.columns
            if getattr(column.type, "length", None)
        }
        for row in mcp_registry.seed_entries():
            for field, value in row.items():
                cap = limits.get(field)
                if cap is not None:
                    assert len(value) <= cap, f"{field} of {row['id']} is {len(value)}"
