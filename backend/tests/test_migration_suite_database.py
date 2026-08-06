"""What decides whether the migration suite runs, skips, or refuses to skip.

`tests/test_migrations.py` is the only thing in this repository that applies the
whole chain to an empty database and rolls it back again, and for the whole of its
life it did none of that: it skipped unless a database called
`agenticos_migrations_test` already existed, and nothing ever created one, so on a
runner it skipped every time and the build was green anyway (#234).

The module now creates its own database, which leaves one decision worth asserting
directly: which absence of a server is a skip and which is a failure. These are
unit tests for the same reason `test_integration_database_isolation.py` is - the
decision has to be made before anything is created, and it is the part a machine
with no Postgres can still check.
"""

from __future__ import annotations

import os

import pytest

from tests import test_migrations
from tests.integration.conftest import _refuse_a_real_database


def test_the_database_this_module_uses_is_named_after_this_process() -> None:
    """The module drops the database it names, so no two runs may share a name.

    A constant name is #189 again: two runs on one machine - two worktrees, or a
    `make test` beside this one - dropping and recreating each other's database
    mid-upgrade, and reporting failures belonging to neither.
    """
    assert test_migrations.MIGRATION_DATABASE.endswith(f"_p{os.getpid()}")


def test_the_name_this_module_uses_would_survive_the_integration_guard() -> None:
    """Held to the same bar, from the module that already states it.

    Nothing derives this name from the environment, which is why it is a literal
    rather than a guarded value - but "obviously a test database, and a plain
    identifier" is the property that makes an unconditional drop safe either way.
    """
    _refuse_a_real_database(test_migrations.MIGRATION_DATABASE)


def test_the_alembic_subprocesses_are_pointed_at_that_database() -> None:
    """`downgrade base` empties whatever it reaches, so this is the whole guard."""
    assert test_migrations._env()["POSTGRES_DB"] == test_migrations.MIGRATION_DATABASE


def test_a_server_that_answers_is_neither_skipped_nor_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(test_migrations, "_server_answers", lambda url: True)
    test_migrations._demand_a_server("postgresql://nowhere/postgres")


def test_no_server_on_a_laptop_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    """`make test` on a machine without Docker still runs everything else."""
    monkeypatch.setattr(test_migrations, "_server_answers", lambda url: False)
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(pytest.skip.Exception, match="make docker-db"):
        test_migrations._demand_a_server("postgresql://nowhere/postgres")


def test_no_server_in_ci_fails_rather_than_skipping(monkeypatch: pytest.MonkeyPatch) -> None:
    """The skip that hid #234 for this module's entire life.

    CI declares a Postgres service container, so an unreachable server there is a
    service that did not start - not an environment that cannot answer. Skipping
    then reports a green build over a chain nobody applied, and looks identical in
    the log to the laptop case above.
    """
    monkeypatch.setattr(test_migrations, "_server_answers", lambda url: False)
    monkeypatch.setenv("CI", "true")
    with pytest.raises(RuntimeError, match="refusing to skip the migration suite"):
        test_migrations._demand_a_server("postgresql://nowhere/postgres")
