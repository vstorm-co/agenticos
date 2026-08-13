"""Where a `@flow` call in this suite sends its API requests, which is nowhere.

`tests/conftest.py` seeds `PREFECT_API_URL` empty before anything imports Prefect,
because Prefect resolves its own settings from `backend/.env` - the file `make dev`
needs, pointing at `localhost:4200`. A suite that reads it makes every `@flow` call
depend on a server nobody started (#536).

Most of these assert the consequence - what Prefect resolved - because a variable set
too late, or set in a shape the dotenv source outranks, leaves the URL in place while
looking correct. The last pins the shape itself, which is the half nothing else can
see: on CI there is no `.env`, so every resolved value below is what it would be with
no seed at all.
"""

import os
import tempfile
from pathlib import Path

from prefect.settings import get_current_settings


def test_the_suite_points_prefect_at_no_server() -> None:
    """Otherwise a `@flow` call reaches for whatever `backend/.env` names.

    Asserting the resolved setting is what makes the check mean anything: the
    variable is set before `app.core.config` is imported, and Prefect's own dotenv
    source holds the URL that would answer if it were merely unset.
    """
    assert not get_current_settings().api.url


def test_the_suite_leaves_prefect_a_server_it_can_start_for_itself() -> None:
    """With no URL and no ephemeral server, a `@flow` call retries for 75s and fails.

    Which is the bug in a slower shape, so `tests/conftest.py` names the mode the
    fallback needs rather than leaving it to Prefect's default.
    """
    assert get_current_settings().server.ephemeral.enabled


def test_that_server_keeps_its_state_out_of_the_developers_own_prefect_home() -> None:
    """A flow run here would otherwise be written to `~/.prefect/prefect.db`.

    Which is a developer's own Prefect data, and the file a locally run
    `prefect server` has open - the same reason the Postgres name in
    `tests/conftest.py` is a test database rather than whatever `.env` says.
    """
    home = get_current_settings().home

    assert home != Path.home() / ".prefect"
    assert home == Path(tempfile.gettempdir()) / "agenticos-prefect-test"


def test_that_server_is_given_longer_than_prefect_would_allow_it() -> None:
    """Its 20 seconds is a cold start with nothing to spare, not headroom.

    The server migrates a SQLite database under `PREFECT_HOME` before it answers,
    which is about six seconds against a home nothing has written yet and about
    nine on a CI runner. Asserted against the number `tests/conftest.py` chose
    rather than against Prefect's default, which would hold for a value that
    bought nothing.
    """
    assert get_current_settings().server.ephemeral.startup_timeout_seconds >= 90


def test_the_url_is_emptied_rather_than_removed() -> None:
    """Removing it hands the question back to `backend/.env`, which is the defect.

    An unset variable is not an answer to a dotenv source; an empty assignment
    outranks it.
    """
    assert os.environ["PREFECT_API_URL"] == ""
