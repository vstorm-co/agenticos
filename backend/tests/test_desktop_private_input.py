"""Private desktop text does not enter audit argv, child env or wrapper errors."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from pydantic_ai.workspaces import CommandResult

from app.agents.capabilities.computer_use import _backends
from app.agents.capabilities.computer_use._actions import TypeText
from app.agents.capabilities.computer_use._backends import ComputerError, SandboxComputer, xdotool

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("failure", [False, True])
def test_real_wrapper_consumes_input_before_spawning_and_never_prints_child_errors(
    tmp_path: Path, failure: bool
):
    report = tmp_path / "child-report.json"
    executable = tmp_path / "xdotool"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json,os,pathlib,sys\n"
        f"pathlib.Path({str(report)!r}).write_text(json.dumps({{'text':sys.stdin.read(),'has_input_env':'AGENTICOS_DESKTOP_INPUT_TEXT' in os.environ,'argv':sys.argv[1:]}}))\n"
        "print('private child error must not escape',file=sys.stderr)\n"
        f"sys.exit({7 if failure else 0})\n"
    )
    executable.chmod(0o700)
    text = "private input: Zażółć '; $(never-execute)\nnext line"
    argv = xdotool(TypeText(text=text))
    assert argv is not None and text not in " ".join(argv)
    result = subprocess.run(
        [sys.executable, *argv[1:]],
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
            _backends._PRIVATE_TEXT_ENV: text,
        },
        capture_output=True,
        check=False,
    )
    saved = json.loads(report.read_text())
    assert saved == {
        "text": text,
        "has_input_env": False,
        "argv": ["type", "--clearmodifiers", "--file", "-"],
    }
    assert result.returncode == (7 if failure else 0)
    assert result.stdout == b"" and result.stderr == b""


async def test_text_stays_out_of_audited_commands_and_reflected_provider_failure():
    workspace = AsyncMock()
    secret = "do not reflect this private input"
    workspace.run.return_value = CommandResult(stdout=secret, stderr=secret, exit_code=7)
    computer = SandboxComputer(workspace)
    with pytest.raises(ComputerError) as caught:
        await computer.perform(TypeText(text=secret))
    call = workspace.run.await_args
    assert secret not in " ".join(call.args[0])
    assert call.kwargs["env"] == {"DISPLAY": ":0", _backends._PRIVATE_TEXT_ENV: secret}
    assert secret not in str(caught.value)
    assert "exit 7" in str(caught.value)


@pytest.mark.parametrize("text", ["null\x00byte", "surrogate\ud800"])
async def test_invalid_process_input_is_refused_before_workspace_io(text):
    workspace = AsyncMock()
    with pytest.raises(ComputerError if "\x00" in text else ValidationError):
        await SandboxComputer(workspace).perform(TypeText(text=text))
    workspace.run.assert_not_awaited()
