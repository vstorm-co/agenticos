"""`0301_workflow_loop_scope` rewrites stored JSONB graphs on real PostgreSQL (#2770).

The conversion itself is covered without a database in
`tests/test_workflow_loop_scope_migration.py`; this runs the revision's own
`upgrade()`/`downgrade()` - its `LIKE` filter over `jsonb::text` and its `CAST`
back to `jsonb` - over the three columns that hold a graph. The tables are bare
stand-ins in a scratch schema, so no organization or workflow has to exist.
"""

import importlib.util
import json
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.anyio

_TABLES = (
    ("workflows", "draft_graph"),
    ("workflow_versions", "graph"),
    ("workflow_runs", "draft_graph_snapshot"),
)


def _migration() -> ModuleType:
    path = Path(__file__).parents[2] / "alembic/versions/0301_workflow_loop_scope.py"
    spec = importlib.util.spec_from_file_location("workflow_loop_scope_migration_rows", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_graph() -> tuple[dict[str, Any], dict[str, str]]:
    ids = {name: str(uuid.uuid4()) for name in ("entry", "loop", "item", "step")}

    def edge(source: str, port: str, target: str) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "source_node_id": ids[source],
            "source_port": port,
            "target_node_id": ids[target],
            "target_port": "in",
        }

    graph = {
        "entry_node_id": ids["entry"],
        "nodes": [
            {"id": ids["entry"], "definition_id": "core.input"},
            {"id": ids["loop"], "definition_id": "control.foreach"},
            {"id": ids["item"], "definition_id": "loop.item"},
            {"id": ids["step"], "definition_id": "data.map"},
        ],
        "edges": [
            edge("entry", "out", "loop"),
            edge("loop", "body", "item"),
            edge("loop", "body", "step"),
        ],
        "bindings": [],
        "scopes": [],
    }
    return graph, ids


def _run(connection: Connection, migrate: Any) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        migrate()


async def test_every_stored_graph_is_rewritten_and_written_back(engine: AsyncEngine):
    migration = _migration()
    legacy, ids = _legacy_graph()
    untouched = {"entry_node_id": ids["entry"], "nodes": [], "edges": []}
    schema = f"loop_scope_{uuid.uuid4().hex[:8]}"
    async with engine.connect() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET search_path TO "{schema}"'))
        for table, column in _TABLES:
            await connection.execute(text(f"CREATE TABLE {table} (id uuid, {column} jsonb)"))
            for graph in (legacy, untouched, None):
                await connection.execute(
                    text(f"INSERT INTO {table} VALUES (:id, CAST(:graph AS jsonb))"),  # noqa: S608
                    {
                        "id": uuid.uuid4(),
                        "graph": None if graph is None else json.dumps(graph),
                    },
                )

        await connection.run_sync(_run, migration.upgrade)
        for table, column in _TABLES:
            select = text(f"SELECT {column} FROM {table}")  # noqa: S608 - the fixed names above
            rows = (await connection.execute(select)).scalars()
            graphs = [graph for graph in rows if graph is not None]
            assert untouched in graphs
            upgraded = next(graph for graph in graphs if graph != untouched)
            scopes = {node["id"]: node.get("scope_id") for node in upgraded["nodes"]}
            assert scopes[ids["item"]] == ids["loop"] and scopes[ids["step"]] == ids["loop"]
            assert [(e["source_node_id"], e["source_port"]) for e in upgraded["edges"]] == [
                (ids["entry"], "out"),
                (ids["item"], "out"),
            ]

        await connection.run_sync(_run, migration.downgrade)
        for table, column in _TABLES:
            select = text(f"SELECT {column} FROM {table}")  # noqa: S608 - the fixed names above
            rows = (await connection.execute(select)).scalars()
            restored = next(graph for graph in rows if graph is not None and graph != untouched)
            assert all("scope_id" not in node for node in restored["nodes"])
            assert (ids["loop"], "body", ids["item"]) in {
                (e["source_node_id"], e["source_port"], e["target_node_id"])
                for e in restored["edges"]
            }
        await connection.rollback()
