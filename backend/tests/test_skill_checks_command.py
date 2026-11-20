"""The operator judges finished skill checks again from the runs they kept."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from click.testing import CliRunner

from app.commands.skill_checks import _run, skill_checks_rejudge

pytestmark = pytest.mark.anyio
PATH = "app.commands.skill_checks"


@asynccontextmanager
async def session():
    yield object()


async def test_each_check_an_older_rule_judged_is_judged_again_from_its_runs(capsys) -> None:
    org, first, second = uuid4(), uuid4(), uuid4()
    runs = [uuid4(), uuid4()]
    found = [(org, first, runs), (org, second, runs[:1])]
    with (
        patch(f"{PATH}.get_db_context", session),
        patch(
            f"{PATH}.skill_check_repo.judged_before_families", AsyncMock(return_value=found)
        ) as listed,
        patch(f"{PATH}.SkillCheckService.recompute_after_review", AsyncMock()) as judged,
    ):
        await _run([first])

    assert listed.call_args.kwargs == {"check_ids": [first]}
    assert [call.args for call in judged.call_args_list] == [(org, runs), (org, runs[:1])]
    output = capsys.readouterr().out
    assert f"Judged check {first} again from 2 stage run(s)." in output
    assert "2 check(s) judged again." in output


async def test_nothing_to_judge_again_says_so(capsys) -> None:
    with (
        patch(f"{PATH}.get_db_context", session),
        patch(f"{PATH}.skill_check_repo.judged_before_families", AsyncMock(return_value=[])),
        patch(f"{PATH}.SkillCheckService.recompute_after_review", AsyncMock()) as judged,
    ):
        await _run([])

    judged.assert_not_called()
    assert "No finished check" in capsys.readouterr().out


def test_the_command_passes_every_check_it_was_given() -> None:
    first, second = uuid4(), uuid4()
    with patch(f"{PATH}._run", AsyncMock()) as run:
        result = CliRunner().invoke(
            skill_checks_rejudge, ["--check", str(first), "--check", str(second)]
        )

    assert result.exit_code == 0, result.output
    assert run.call_args.args == ((first, second),)
