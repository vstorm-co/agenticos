"""The operator asks how much of an organization's input is tool output sent again."""

import json
from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from click.testing import CliRunner

from app.commands.tool_output_report import tool_output_report
from app.core.exceptions import NotFoundError
from app.services.tool_output_report import ToolOutputReportService

PATH = "app.commands.tool_output_report"
ORG = uuid4()


@asynccontextmanager
async def session():
    yield object()


def _empty_report():
    return ToolOutputReportService._assemble(
        ORG,
        started_from=date(2026, 11, 1),
        ended=date(2026, 11, 22),
        include_eval=True,
        include_tests=False,
        top=5,
        runs=[],
        calls={},
        requests={},
        turns={},
        versions={},
        inherited={},
        parked=set(),
    )


def _invoke(*extra: str, build: AsyncMock):
    with (
        patch(f"{PATH}.get_db_context", session),
        patch(f"{PATH}.ToolOutputReportService.build", build),
    ):
        return CliRunner().invoke(
            tool_output_report,
            ["--org", str(ORG), "--from", "2026-11-01", "--to", "2026-11-22", *extra],
        )


def test_the_window_and_filters_reach_the_report_and_it_prints_as_text() -> None:
    build = AsyncMock(return_value=_empty_report())

    result = _invoke("--include-eval", "--top", "5", build=build)

    assert result.exit_code == 0, result.output
    assert build.await_args.args == (ORG,)
    assert build.await_args.kwargs == {
        "started_from": date(2026, 11, 1),
        "ended": date(2026, 11, 22),
        "include_eval": True,
        "include_tests": False,
        "top": 5,
    }
    assert "No runs in this window." in result.output


def test_json_prints_the_same_report_as_json() -> None:
    result = _invoke("--json", build=AsyncMock(return_value=_empty_report()))

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["organization_id"] == str(ORG)


def test_a_refusal_is_reported_as_the_command_failing() -> None:
    refused = AsyncMock(side_effect=NotFoundError(message="Organization not found"))

    result = _invoke(build=refused)

    assert result.exit_code == 1
    assert "Organization not found" in result.output


def test_a_date_that_is_not_a_day_is_refused() -> None:
    result = CliRunner().invoke(
        tool_output_report, ["--org", str(ORG), "--from", "yesterday", "--to", "2026-11-22"]
    )

    assert result.exit_code == 2
