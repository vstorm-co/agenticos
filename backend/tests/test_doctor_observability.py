"""`doctor`'s two observability lines, and what production prints (#2228).

Until 2026-10-19 prod sent no traces and had no `pg_stat_statements`, so a slow
deployment had to be diagnosed from raw container logs. Neither is a failure -
a managed database may not preload the library, and tracing is a choice - but
both must be said out loud rather than discovered during an incident.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import ProgrammingError

from app.commands.doctor import _query_statistics, _tracing
from app.core.config import settings
from app.core.logfire_setup import setup_logfire

pytestmark = pytest.mark.anyio


class _Savepoint:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


def _session(execute: MagicMock) -> MagicMock:
    db = MagicMock()
    db.begin_nested = MagicMock(return_value=_Savepoint())
    db.execute = execute
    return db


class TestQueryStatistics:
    async def test_a_recording_extension_is_healthy(self) -> None:
        async def execute(_statement: object) -> None:
            return None

        status, detail = await _query_statistics(_session(MagicMock(side_effect=execute)))

        assert status == "healthy"
        assert "pg_stat_statements" in detail

    async def test_a_missing_extension_is_reported_not_failed(self) -> None:
        """A provisioning script runs `doctor`; exiting non-zero on an optional
        library would break it. The reason is the database's own first line."""
        missing = ProgrammingError(
            "SELECT 1 FROM pg_stat_statements LIMIT 1",
            {},
            Exception('relation "pg_stat_statements" does not exist\nLINE 1: ...'),
        )

        async def execute(_statement: object) -> None:
            raise missing

        status, detail = await _query_statistics(_session(MagicMock(side_effect=execute)))

        assert status == "unconfigured"
        assert (
            detail
            == 'pg_stat_statements unavailable - relation "pg_stat_statements" does not exist'
        )


class TestTracing:
    def test_a_token_names_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "LOGFIRE_TOKEN", "pylf_test")
        monkeypatch.setattr(settings, "LOGFIRE_ENVIRONMENT", "production")

        assert _tracing() == ("healthy", "Logfire, environment production")

    @pytest.mark.parametrize("console", [False, True])
    def test_no_token_reports_missing_export_even_with_console_spans(
        self, monkeypatch: pytest.MonkeyPatch, console: bool
    ) -> None:
        monkeypatch.setattr(settings, "LOGFIRE_TOKEN", None)
        monkeypatch.setattr(settings, "LOGFIRE_CONSOLE", console)

        status, detail = _tracing()

        assert status == "unconfigured"
        assert detail == "LOGFIRE_TOKEN is unset - no request, query or run is exported to Logfire"


class TestTheConsoleExporter:
    @pytest.mark.parametrize("environment", ["local", "development", "staging", "production"])
    @pytest.mark.parametrize("enabled", [False, True])
    def test_console_spans_require_explicit_opt_in(
        self, monkeypatch: pytest.MonkeyPatch, environment: str, enabled: bool
    ) -> None:
        monkeypatch.setattr(settings, "ENVIRONMENT", environment)
        monkeypatch.setattr(settings, "LOGFIRE_CONSOLE", enabled)
        with patch("app.core.logfire_setup.logfire") as logfire:
            setup_logfire()

        assert logfire.configure.call_args.kwargs["console"] is (None if enabled else False)
