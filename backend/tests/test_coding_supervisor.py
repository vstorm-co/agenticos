"""A lost worker cannot leave a native coding process using a personal account."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.agents.capabilities.coding_agent._harness import _SUPERVISE, Invocation, TaskFiles


@pytest.mark.parametrize("timed_out", [False, True])
def test_supervisor_reaps_descendants_and_records_the_actual_outcome(
    tmp_path: Path, timed_out: bool
) -> None:
    marker = tmp_path / "escaped"
    descendant = (
        "import time; from pathlib import Path; time.sleep(0.6); "
        f"Path({str(marker)!r}).write_text('leaked')"
    )
    code = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {descendant!r}]); "
        + ("time.sleep(10)" if timed_out else "sys.exit(7)")
    )
    status = tmp_path / "exit"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _SUPERVISE,
            str(tmp_path / "events"),
            str(tmp_path / "errors"),
            str(status),
            "0.15",
            sys.executable,
            "-c",
            code,
        ],
        start_new_session=True,
    )
    try:
        assert process.wait(timeout=3) == -signal.SIGKILL
        assert status.read_text() == ("124" if timed_out else "7")
        time.sleep(0.7)
        assert not marker.exists(), "A detached child survived the task's supervisor"
        assert not status.with_suffix(".part").exists()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)


def test_supervised_launch_passes_a_deadline_without_putting_credentials_on_the_command() -> None:
    command = Invocation(
        ["codex", "exec", "a quoted ' task"], {"API_KEY": "private-token"}, supervised=True
    )
    line = command.detached_line(TaskFiles("events", "errors", "status"), timeout_seconds=30)
    assert "private-token" not in line and "API_KEY" not in line
    assert "python3" in line and "setsid nohup" in line
    assert "30" in line


def test_an_organization_sandbox_keeps_its_shell_only_launcher() -> None:
    command = Invocation(["codex", "exec", "Inspect"], {})
    line = command.detached_line(TaskFiles("events", "errors", "status"), timeout_seconds=30)
    assert line.startswith("setsid nohup sh -c ")
    assert "python3" not in line


def test_auth_read_preserves_failure_status_while_removing_the_temporary_home(
    tmp_path: Path,
) -> None:
    from app.agents.capabilities.coding_agent._toolset import HOME_ENV, READ_AUTH

    home = tmp_path / "auth"
    home.mkdir()
    result = subprocess.run(
        ["/bin/sh", "-c", READ_AUTH], env={**os.environ, HOME_ENV: str(home)}, capture_output=True
    )
    assert result.returncode != 0 and result.stdout == b""
    assert not home.exists()
