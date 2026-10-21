"""`agenticos cmd mcp-catalog-check`: which run prunes, and what it writes (#2103)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

from app.commands import mcp_audit as cmd
from app.db.models.mcp_server_check import CheckOutcome
from app.services.mcp_audit import CheckRow

_ROWS = [
    CheckRow("github", "catalog", CheckOutcome.SIGN_IN, datetime(2026, 10, 12, tzinfo=UTC)),
    CheckRow("com.x/y", "registry", CheckOutcome.BROKEN, datetime(2026, 10, 12, tzinfo=UTC)),
]


@pytest.fixture(autouse=True)
def _session(monkeypatch):
    @asynccontextmanager
    async def session() -> AsyncGenerator[object]:
        yield object()

    monkeypatch.setattr(cmd, "get_db_context", session)


@pytest.fixture
def run(monkeypatch):
    checked = AsyncMock(return_value=_ROWS)
    written = AsyncMock(return_value=len(_ROWS))
    monkeypatch.setattr(cmd.mcp_audit, "check_listings", checked)
    monkeypatch.setattr(cmd.mcp_audit, "write_checks", written)
    return checked, written


def test_a_full_run_checks_both_lists_and_prunes(run):
    checked, written = run

    result = CliRunner().invoke(cmd.mcp_catalog_check, [])

    assert result.exit_code == 0, result.output
    assert checked.await_args.kwargs["sources"] == frozenset({"catalog", "registry"})
    assert written.await_args.kwargs["prune"] is True
    assert "broken 1, sign_in 1" in result.output


def test_a_partial_run_prunes_nothing(run):
    _checked, written = run

    CliRunner().invoke(cmd.mcp_catalog_check, ["--source", "registry", "--limit", "5"])

    assert written.await_args.kwargs["prune"] is False


def test_it_writes_a_report_and_a_snapshot(run, monkeypatch, tmp_path):
    snapshot = tmp_path / "mcp_checks.json"
    monkeypatch.setattr(cmd.mcp_audit, "write_snapshot", lambda rows: snapshot)
    report = tmp_path / "report.md"

    result = CliRunner().invoke(cmd.mcp_catalog_check, ["--report", str(report), "--snapshot"])

    assert result.exit_code == 0, result.output
    assert report.read_text().startswith("# MCP catalog check")
    assert report.with_suffix(".json").exists()
    assert str(snapshot) in result.output


def test_a_partial_run_writes_no_snapshot(run, monkeypatch):
    def refuse(_rows):
        raise AssertionError("a partial run must not overwrite the bundled snapshot")

    monkeypatch.setattr(cmd.mcp_audit, "write_snapshot", refuse)

    result = CliRunner().invoke(cmd.mcp_catalog_check, ["--source", "catalog", "--snapshot"])

    assert result.exit_code == 0, result.output
    assert "only from a full run" in result.output
