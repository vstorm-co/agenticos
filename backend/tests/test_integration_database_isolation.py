"""What keeps two integration runs on one machine out of each other's tables.

`tests/integration/conftest.py` calls `drop_all` unconditionally, so everything
that makes the suite safe to run twice at once is a name: one nobody else uses,
and a guard on what that name is allowed to be. Both used to hold only because
the name was constant, which is exactly what made two runs destroy each other
(#189) - so the derivation is asserted here rather than assumed.

These are unit tests on purpose. The guard has to answer before a database is
touched, and it is the one part of the fixture a run without Postgres can still
check.
"""

import os

import pytest

from app.core.config import settings
from tests.integration.conftest import _refuse_a_real_database


def test_the_database_this_process_uses_is_named_after_this_process() -> None:
    """A constant name is the whole defect: two runs then share one database.

    The pid is what a second run cannot collide with, and it also separates
    `pytest-xdist` workers, which are processes of their own.
    """
    assert os.environ["POSTGRES_DB"].endswith(f"_p{os.getpid()}")


def test_the_application_settings_name_the_database_the_fixture_creates() -> None:
    """Otherwise an un-overridden `get_db_session` reaches a different database.

    The engine in `app/db/session.py` is built at import time from these
    settings, so the name has to be derived before `app.core.config` is read -
    which is why it happens at the top of `tests/conftest.py` and not in a
    fixture.
    """
    assert os.environ["POSTGRES_DB"] == settings.POSTGRES_DB
    assert settings.DATABASE_URL.endswith(f"/{os.environ['POSTGRES_DB']}")


def test_the_name_this_process_derived_is_one_the_guard_accepts() -> None:
    """The suffix must not push the name past what the guard allows."""
    _refuse_a_real_database(os.environ["POSTGRES_DB"])


def test_a_database_without_test_or_ci_in_its_name_is_refused() -> None:
    with pytest.raises(RuntimeError, match="Refusing to run integration tests"):
        _refuse_a_real_database("agenticos")


def test_a_name_that_is_not_a_plain_identifier_is_refused() -> None:
    """The name reaches `CREATE DATABASE` as text, so it is checked as text."""
    with pytest.raises(RuntimeError, match="plain identifier"):
        _refuse_a_real_database('agenticos_test"; DROP DATABASE agenticos; --')
