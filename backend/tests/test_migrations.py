"""Migration tests - verify Alembic upgrade/downgrade cycle.

These tests ensure that:
1. All migrations can be applied (upgrade head)
2. All migrations can be rolled back (downgrade base)
3. The upgrade/downgrade cycle is idempotent

**They run against a database of their own, and that is not a nicety.**
`downgrade base` drops every table. These tests used to inherit whatever
`POSTGRES_DB` resolved to - which, in a checkout with a populated `.env`, is the
developer's working database. An ordinary `pytest` run emptied it: model tables
gone, `alembic_version` recreated by the upgrade that followed, and nothing in
the output to say so. The name below is the fix, and it is passed explicitly to
each subprocess rather than left to the environment to get right.
"""

import os
import subprocess
import sys

import pytest

# Owned by this module alone. Not the integration suite's database either: that
# one builds its schema from the models with `create_all`, and alembic finds
# those tables already present and fails on the first `CREATE TABLE`.
MIGRATION_DATABASE = "agenticos_migrations_test"


def _env() -> dict[str, str]:
    """The environment each alembic subprocess runs in.

    `POSTGRES_DB` is forced rather than defaulted: a default is something an
    outer environment can override, and what it would override is the guard
    that keeps `downgrade base` away from a real database.
    """
    return {**os.environ, "POSTGRES_DB": MIGRATION_DATABASE}


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        cwd=".",
        env=_env(),
        timeout=120,
    )


def _db_available() -> bool:
    """Whether this module's own database exists and answers.

    Created by hand or by `make test-migrations`; skipped rather than created
    here, because creating a database is a privileged act and a test module is
    the wrong place to perform one silently.
    """
    return _alembic("current").returncode == 0


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="No live database available - skipping migration tests",
)


class TestMigrations:
    """Test Alembic migration integrity."""

    def test_upgrade_head(self):
        """Test that all migrations can be applied successfully."""
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, f"Migration upgrade failed:\n{result.stderr}"

    def test_downgrade_base(self):
        """Test that all migrations can be rolled back."""
        # First upgrade to head
        up = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            cwd=".",
            env=_env(),
        )
        assert up.returncode == 0, f"Migration upgrade failed:\n{up.stderr}"

        # Then downgrade to base
        down = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "base"],
            capture_output=True,
            text=True,
            cwd=".",
            env=_env(),
        )
        assert down.returncode == 0, f"Migration downgrade failed:\n{down.stderr}"

    def test_upgrade_downgrade_cycle(self):
        """Test that upgrade → downgrade → upgrade produces consistent state."""
        for action, target in (("upgrade", "head"), ("downgrade", "base"), ("upgrade", "head")):
            result = _alembic(action, target)
            assert result.returncode == 0, f"alembic {action} {target} failed:\n{result.stderr}"

    def test_current_matches_head(self):
        """Test that current migration revision matches head after upgrade."""
        # Upgrade to head first
        up = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            cwd=".",
            env=_env(),
        )
        assert up.returncode == 0, f"Migration upgrade failed:\n{up.stderr}"

        # Check if there are any migration revisions
        heads = subprocess.run(
            [sys.executable, "-m", "alembic", "heads"],
            capture_output=True,
            text=True,
            cwd=".",
        )
        assert heads.returncode == 0

        if not heads.stdout.strip():
            pytest.skip("No migration revisions found - nothing to verify")

        # Check current
        result = _alembic("current")
        assert result.returncode == 0
        assert "(head)" in result.stdout, (
            f"Current revision is not at head:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
