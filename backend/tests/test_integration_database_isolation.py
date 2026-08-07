"""Where the integration fixture connects, and that nobody else is there.

Two engines reach the same database: the fixture's, built in
`tests/integration/conftest.py`, and the application's, built at import time in
`app/db/session.py`. Every part of the address they resolve separately is a part
they can disagree about, and both halves of that have now cost a day.

`drop_all` is unconditional, so what makes the suite safe to run twice at once
is a name nobody else uses, plus a guard on what that name may be. Both held
only because the name was constant - which is what made two runs destroy each
other (#189) - so the derivation is asserted rather than assumed. And the
credentials were resolved twice with different fallbacks, which nothing could
see until a test drove the application's engine instead of the fixture's (#485).

These are unit tests on purpose. They have to answer before a database is
touched, and they are the part of the fixture a run without Postgres can still
check.
"""

import os
from pathlib import Path

import pytest

from app.core.config import settings
from tests.conftest import _a_password_is_already_configured
from tests.integration.conftest import _database_url, _refuse_a_real_database


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


def test_the_fixture_addresses_the_database_with_the_settings_it_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fixture must read the address, not resolve one of its own.

    It used to read the environment directly and default the password to
    "postgres" where `app/core/config.py` defaults it to empty. Asserting the
    resolved value cannot catch that - on a machine with a `backend/.env`, and
    in CI, the two agree by luck - so what is pinned here is that the fixture
    carries whatever the settings hold, which fails anywhere if it goes back to
    reading `os.getenv` (#485).
    """
    monkeypatch.setattr(settings, "POSTGRES_USER", "somebody")
    monkeypatch.setattr(settings, "POSTGRES_PASSWORD", "a-password-no-default-invents")

    assert "somebody:a-password-no-default-invents@" in _database_url("agenticos_test")


def test_the_test_suite_has_a_password_to_connect_with() -> None:
    """`app/core/config.py` defaults it to empty, and empty cannot authenticate."""
    assert settings.POSTGRES_PASSWORD


def test_a_checkout_with_no_env_file_is_given_a_password(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The worktree case, which is how every parallel branch here is worked.

    `backend/.env` is untracked, so it does not come across to a new worktree and
    nothing else supplies the credential.
    """
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.chdir(checkout)

    assert not _a_password_is_already_configured()


def test_a_password_somebody_configured_is_not_replaced_by_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Seeding over a real one would swap a working password for a guess.

    The opposite of the database name, which is overridden precisely because a
    developer's own value is the dangerous one.
    """
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".env").write_text("POSTGRES_PASSWORD=somebodys-own-password\n")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.chdir(checkout)

    assert _a_password_is_already_configured()


def test_an_env_file_assigning_nothing_does_not_count_as_a_password(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`env_ignore_empty` discards it, so the settings fall back to empty too."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".env").write_text("POSTGRES_PASSWORD=\n")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.chdir(checkout)

    assert not _a_password_is_already_configured()


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
