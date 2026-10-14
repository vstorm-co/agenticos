"""Migration `0109_embed_dictation`: `allow_voice` rewritten as `dictation`, and back.

The rewrite lives only in the migration's SQL, and a mistake in it fails
silently: the config schema ignores unknown keys, so a page whose row kept
`allow_voice` would lose its microphone with nothing said. So the statements run
here against real PostgreSQL JSONB - on a scratch database holding only the one
table they touch, which is all `upgrade()` and `downgrade()` read - rather than
being trusted to match the `mode="before"` validator they mirror.
"""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, create_engine, text

from app.core.config import settings

SCRATCH_DATABASE = f"agenticos_embed_dictation_test_p{os.getpid()}"
_MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0109_embed_dictation.py"


def _url(database: str) -> str:
    return f"{settings.DATABASE_URL_SYNC.rsplit('/', 1)[0]}/{database}"


def _outside_a_transaction(url: str, statement: str) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(statement)
    finally:
        engine.dispose()


def _server_reachable(url: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect():
            return True
    except Exception:
        return False
    finally:
        engine.dispose()


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("embed_dictation_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    maintenance = _url("postgres")
    if not _server_reachable(maintenance):
        pytest.skip("No database reachable - start one with `make docker-db`")
    drop = f'DROP DATABASE IF EXISTS "{SCRATCH_DATABASE}" WITH (FORCE)'
    _outside_a_transaction(maintenance, drop)
    _outside_a_transaction(maintenance, f'CREATE DATABASE "{SCRATCH_DATABASE}"')
    scratch = create_engine(_url(SCRATCH_DATABASE))
    try:
        with scratch.begin() as connection:
            connection.execute(
                text("CREATE TABLE agent_embeds (id int PRIMARY KEY, kind text, config jsonb)")
            )
        yield scratch
    finally:
        scratch.dispose()
        _outside_a_transaction(maintenance, drop)


def _run(engine: Engine, direction: str, rows: dict[int, tuple[str, dict]]) -> dict[int, dict]:
    """Load `rows`, run one direction of the migration, and read the configs back."""
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM agent_embeds"))
        for row_id, (kind, config) in rows.items():
            connection.execute(
                text("INSERT INTO agent_embeds VALUES (:id, :kind, CAST(:config AS jsonb))"),
                {"id": row_id, "kind": kind, "config": json.dumps(config)},
            )
        with Operations.context(MigrationContext.configure(connection)):
            getattr(_migration(), direction)()
        found = connection.execute(text("SELECT id, config FROM agent_embeds")).all()
    return {row.id: row.config for row in found}


def test_upgrade_reads_allow_voice_as_the_dictation_it_meant(engine: Engine) -> None:
    after = _run(
        engine,
        "upgrade",
        {
            1: ("page", {"kind": "page", "title": "Help", "allow_voice": True}),
            2: ("page", {"kind": "page", "allow_voice": False}),
            3: ("page", {"kind": "page", "title": "No key"}),
            4: ("page", {"kind": "page", "allow_voice": True, "dictation": "server"}),
            5: ("widget", {"kind": "widget", "title": "Hi"}),
        },
    )

    assert after[1] == {"kind": "page", "title": "Help", "dictation": "browser"}
    assert after[2] == {"kind": "page", "dictation": "off"}
    assert after[3] == {"kind": "page", "title": "No key"}
    assert after[4] == {"kind": "page", "dictation": "server"}
    assert after[5] == {"kind": "widget", "title": "Hi"}


def test_upgrade_run_twice_changes_nothing_the_second_time(engine: Engine) -> None:
    once = _run(engine, "upgrade", {1: ("page", {"kind": "page", "allow_voice": True})})

    twice = _run(engine, "upgrade", {1: ("page", once[1])})

    assert twice == once


def test_downgrade_says_browser_and_nothing_and_never_a_vendor_nobody_chose(
    engine: Engine,
) -> None:
    """A page on `server` goes back to no microphone, not to the browser's
    recogniser; a widget had no voice before and only loses the key."""
    after = _run(
        engine,
        "downgrade",
        {
            1: ("page", {"kind": "page", "dictation": "browser"}),
            2: ("page", {"kind": "page", "dictation": "server"}),
            3: ("page", {"kind": "page", "dictation": "off"}),
            4: ("widget", {"kind": "widget", "dictation": "server"}),
            5: ("page", {"kind": "page", "title": "No key"}),
        },
    )

    assert after[1] == {"kind": "page", "allow_voice": True}
    assert after[2] == {"kind": "page", "allow_voice": False}
    assert after[3] == {"kind": "page", "allow_voice": False}
    assert after[4] == {"kind": "widget"}
    # Without a `dictation` key the comparison is NULL; the old field is a
    # boolean, so it goes back as `false` rather than as a JSON null.
    assert after[5] == {"kind": "page", "title": "No key", "allow_voice": False}
