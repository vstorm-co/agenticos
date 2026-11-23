"""The operator judges finished skill checks again from the runs they kept."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from click.testing import CliRunner

from app.commands.skill_checks import _run, skill_checks_rejudge
from app.schemas.skill_check import RejudgedChecks

pytestmark = pytest.mark.anyio
PATH = "app.commands.skill_checks"


@asynccontextmanager
async def session():
    yield object()


async def test_each_check_an_older_rule_judged_is_judged_again_from_its_runs(capsys) -> None:
    org, first, second, attempt, counted = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    runs = [uuid4(), uuid4()]
    found = [(org, first, runs), (org, second, runs[:1])]
    with (
        patch(f"{PATH}.get_db_context", session),
        patch(
            f"{PATH}.skill_check_repo.judged_before_families", AsyncMock(return_value=found)
        ) as listed,
        patch(
            f"{PATH}.skill_improvement_repo.checked_iterations",
            AsyncMock(return_value=[(org, attempt), (org, counted)]),
        ),
        patch(
            f"{PATH}.SkillCheckService.recompute_after_review",
            AsyncMock(return_value=RejudgedChecks(judged=1)),
        ) as judged,
        patch(
            f"{PATH}.SkillImprovementService.recount_check_cost",
            AsyncMock(side_effect=[True, False]),
        ) as recount,
    ):
        await _run([first])

    assert listed.call_args.kwargs == {"check_ids": [first]}
    assert [call.args for call in judged.call_args_list] == [(org, runs), (org, runs[:1])]
    assert [call.args for call in recount.call_args_list] == [(org, attempt), (org, counted)]
    output = capsys.readouterr().out
    assert f"Judged check {first} again from 2 stage run(s)." in output
    assert f"Counted the judge in session attempt {attempt}." in output
    assert f"attempt {counted}" not in output
    assert "2 check(s) judged again, 1 attempt(s) recounted, 0 agent(s) skipped." in output


async def test_nothing_to_judge_again_says_so(capsys) -> None:
    with (
        patch(f"{PATH}.get_db_context", session),
        patch(f"{PATH}.skill_check_repo.judged_before_families", AsyncMock(return_value=[])),
        patch(
            f"{PATH}.skill_improvement_repo.checked_iterations",
            AsyncMock(return_value=[(uuid4(), uuid4())]),
        ),
        patch(
            f"{PATH}.SkillCheckService.recompute_after_review",
            AsyncMock(return_value=RejudgedChecks(judged=1)),
        ) as judged,
        patch(f"{PATH}.SkillImprovementService.recount_check_cost", AsyncMock(return_value=False)),
    ):
        await _run([])

    judged.assert_not_called()
    assert "No finished check or session attempt" in capsys.readouterr().out


def test_the_command_passes_every_check_it_was_given() -> None:
    first, second = uuid4(), uuid4()
    with patch(f"{PATH}._run", AsyncMock()) as run:
        result = CliRunner().invoke(
            skill_checks_rejudge, ["--check", str(first), "--check", str(second)]
        )

    assert result.exit_code == 0, result.output
    assert run.call_args.args == ((first, second),)


async def test_checks_without_original_access_are_reported_as_skipped(capsys) -> None:
    org, check = uuid4(), uuid4()
    with (
        patch(f"{PATH}.get_db_context", session),
        patch(
            f"{PATH}.skill_check_repo.judged_before_families",
            AsyncMock(return_value=[(org, check, [uuid4()])]),
        ),
        patch(f"{PATH}.skill_improvement_repo.checked_iterations", AsyncMock(return_value=[])),
        patch(
            f"{PATH}.SkillCheckService.recompute_after_review",
            AsyncMock(return_value=RejudgedChecks(skipped=1)),
        ),
    ):
        await _run([])
    output = capsys.readouterr().out
    assert f"Judged check {check}" not in output
    assert f"Skipped 1 agent(s) of check {check}" in output
    assert "0 check(s) judged again, 0 attempt(s) recounted, 1 agent(s) skipped." in output
