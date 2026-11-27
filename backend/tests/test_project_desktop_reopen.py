"""Fresh Project admissions reset GUI launchers without replacing their workspace."""

import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.capabilities.computer_use._backends import _desktop_start
from app.services import conversation_environment_project_files as mounts
from app.services import conversation_environment_runtime as runtime
from tests.test_conversation_environment_runtime import case as runtime_case

case = runtime_case


@pytest.mark.parametrize(
    ("reset", "live", "stop", "expected", "status"),
    [
        (False, True, "remove", "old", 0),
        (True, True, "remove", "new", 0),
        (True, False, "remove", "new", 0),
        (True, True, "fail", "old", 1),
        (True, True, "stuck", "old", 1),
    ],
)
def test_gui_startup_replaces_only_explicitly_retired_session(
    tmp_path: Path, reset: bool, live: bool, stop: str, expected: str, status: int
) -> None:
    session = tmp_path / "session"
    inherited = tmp_path / "inherited"
    if live:
        session.touch()
    inherited.write_text("old")
    display_state = tmp_path / "display"
    display_state.touch()
    harness = r"""
pgrep() { test -f "$SESSION"; }
python3() {
    test "$STOP" != fail || return 1
    test "$STOP" = stuck || /bin/rm -f "$SESSION" "$DISPLAY_STATE"
    test "$STOP" != stuck
}
xdpyinfo() { test -f "$DISPLAY_STATE"; }
Xvfb() { touch "$DISPLAY_STATE"; }
rm() { return 0; }
xdotool() { return 0; }
scrot() { return 0; }
sleep() { /bin/sleep 0.01; }
seq() { echo 1 2 3; }
setsid() { "$@"; }
nohup() { "$@"; }
dbus-launch() { shift; "$@"; }
startxfce4() { printf %s "$PROJECT_DIR" > "$INHERITED"; touch "$SESSION"; }
"""
    completed = subprocess.run(
        ["/bin/bash", "-c", harness + _desktop_start(1024, 768, reset_session=reset)],
        env={
            **os.environ,
            "SESSION": str(session),
            "INHERITED": str(inherited),
            "DISPLAY_STATE": str(display_state),
            "STOP": stop,
            "PROJECT_DIR": "new",
        },
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert completed.returncode == status
    assert inherited.read_text() == expected


@pytest.mark.anyio
@pytest.mark.parametrize("mounted", [False, True])
async def test_only_new_project_admission_resets_gui_under_physical_lease(
    case, monkeypatch: pytest.MonkeyPatch, mounted: bool
) -> None:
    lease = uuid4() if mounted else None
    monkeypatch.setattr(mounts, "prepare", AsyncMock(return_value=lease))

    async def start(_workspace, *, width: int, height: int, reset_session: bool):
        assert [event for event, _ in case.calls] == ["acquired"]
        assert reset_session is mounted
        assert width == case.desktop.config.screen_width
        assert height == case.desktop.config.screen_height
        return case.computer

    runtime.open_sandbox_desktop.side_effect = start
    await runtime.provision(case.desktop, case.payload, case.store, case.drive)
    assert [event for event, _ in case.calls] == ["acquired", "released"]
    case.close.assert_awaited_once()
