"""The development server survives a worker the kernel kills.

`uvicorn --reload` does not: its reloader watches files and nothing else, so an
OOM-killed worker leaves a zombie, a reloader still politely watching, and a
container reporting `Up` with nothing listening (#308). These pin the decision
the supervisor makes about a worker that is gone - replace it, or wait for the
edit that fixes it - and that the local stack actually runs the supervisor.
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from uvicorn import Config
from uvicorn.supervisors import ChangeReload

from cli import reload_supervisor
from cli.reload_supervisor import APP, WS_PROTOCOL, SupervisedReload, run_reload_server

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_COMPOSE = REPO_ROOT / "docker-compose.yml"


class FakeWorker:
    """Enough of `multiprocessing.Process` for the supervisor's decision."""

    def __init__(self, exitcode: int | None, pid: int = 4242) -> None:
        self.exitcode = exitcode
        self.pid = pid


class RecordingReload(SupervisedReload):
    """Records the replacement rather than spawning a real worker."""

    def __init__(self, config: Config) -> None:
        super().__init__(config, target=lambda sockets: None, sockets=[])
        self.replacements = 0

    def restart(self) -> None:
        self.replacements += 1
        self.process = FakeWorker(None, pid=self.process.pid + 1)


@pytest.fixture
def supervisor(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> RecordingReload:
    """A supervisor whose file watcher reports no changes, with its log captured.

    Constructing a `Config` applies uvicorn's own logging configuration, under
    which `uvicorn.error` reaches uvicorn's handler rather than the root logger
    `caplog` listens on. The module's logger is swapped for an ordinary one so
    the assertions can be about what was written rather than about handlers.
    """
    monkeypatch.setattr(ChangeReload, "should_restart", lambda self: None)
    reloader = RecordingReload(Config(APP, reload=True, ws=WS_PROTOCOL))
    monkeypatch.setattr(reload_supervisor, "logger", logging.getLogger("tests.reload_supervisor"))
    caplog.set_level(logging.ERROR, logger="tests.reload_supervisor")
    return reloader


def test_a_worker_killed_by_a_signal_is_replaced(supervisor: RecordingReload) -> None:
    """`-9` is what the OOM killer leaves behind, and no edit is coming to fix it."""
    supervisor.process = FakeWorker(-9)

    assert supervisor.should_restart() is None
    assert supervisor.replacements == 1
    assert supervisor.process.exitcode is None


def test_a_worker_that_exited_on_its_own_is_not_replaced(supervisor: RecordingReload) -> None:
    """An import error would otherwise respawn forever on the same traceback."""
    supervisor.process = FakeWorker(1)

    assert supervisor.should_restart() is None
    assert supervisor.replacements == 0


def test_a_running_worker_is_left_alone(
    supervisor: RecordingReload, caplog: pytest.LogCaptureFixture
) -> None:
    """The expensive way to get this wrong is to restart a worker that is fine.

    `exitcode` answers `None` while the process runs, and a supervisor that
    treated that as death would replace the server on every poll - every five
    seconds, for ever. Worth a test even though it asserts that nothing
    happened.
    """
    worker = FakeWorker(None)
    supervisor.process = worker

    assert supervisor.should_restart() is None
    assert supervisor.replacements == 0
    assert supervisor.process is worker
    assert caplog.records == []


def test_an_ordinary_exit_is_reported_once_rather_than_every_poll(
    supervisor: RecordingReload, caplog: pytest.LogCaptureFixture
) -> None:
    supervisor.process = FakeWorker(1)

    for _ in range(3):
        supervisor.should_restart()

    assert [r.getMessage() for r in caplog.records].count(
        "Server process [4242] exited with code 1. Waiting for a file change."
    ) == 1


def test_a_second_worker_dying_is_reported_again(
    supervisor: RecordingReload, caplog: pytest.LogCaptureFixture
) -> None:
    """Reporting once is per worker, not once for the life of the reloader."""
    supervisor.process = FakeWorker(1, pid=1)
    supervisor.should_restart()
    supervisor.process = FakeWorker(1, pid=2)
    supervisor.should_restart()

    assert len(caplog.records) == 2


def test_a_file_change_still_reloads(
    supervisor: RecordingReload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reload loop is unchanged; supervision only runs on a quiet poll."""
    changed = [Path("app/main.py")]
    monkeypatch.setattr(ChangeReload, "should_restart", lambda self: changed)
    supervisor.process = FakeWorker(None)

    assert supervisor.should_restart() == changed
    assert supervisor.replacements == 0


def test_a_change_the_reload_filter_rejects_does_not_skip_supervision(
    supervisor: RecordingReload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`[]` is not a change, and reading it as one would strand a dead worker.

    `WatchFilesReload.should_restart` filters after watchfiles yields, so a
    write to a non-Python file inside a watched directory answers `[]` rather
    than `None`. The local stack mounts `media_data` under the watched `/app`,
    so ingestion alone produces these - and a supervisor that took each one for
    a reload would postpone noticing a dead worker for as long as they kept
    arriving.
    """
    monkeypatch.setattr(ChangeReload, "should_restart", lambda self: [])
    supervisor.process = FakeWorker(-9)

    assert supervisor.should_restart() is None
    assert supervisor.replacements == 1


def test_a_worker_dying_during_shutdown_is_not_replaced(
    supervisor: RecordingReload,
) -> None:
    """A replacement started while the reloader is leaving is an orphan.

    Uvicorn re-raises a signal it handled gracefully, so a worker that shut
    down cleanly on SIGTERM reports `-15` and is otherwise indistinguishable
    from one the kernel killed. `should_exit` is what tells them apart.
    """
    supervisor.should_exit.set()
    supervisor.process = FakeWorker(-15)

    assert supervisor.should_restart() is None
    assert supervisor.replacements == 0


def test_the_development_server_keeps_the_sansio_websocket_implementation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """uvicorn's `auto` fails the chat handshake against websockets >=14."""
    captured: list[Config] = []
    monkeypatch.setattr(Config, "bind_socket", lambda self: None)
    monkeypatch.setattr(
        SupervisedReload, "__init__", lambda self, config, **kw: captured.append(config)
    )
    monkeypatch.setattr(SupervisedReload, "run", lambda self: None)

    run_reload_server(host="127.0.0.1", port=9999)

    assert captured[0].ws == "websockets-sansio"
    assert captured[0].should_reload
    assert (captured[0].host, captured[0].port) == ("127.0.0.1", 9999)


def test_the_entrypoint_does_not_drag_the_application_into_the_reloader() -> None:
    """The reloader serves no request, so it should hold no application.

    `cli/reload_supervisor.py` explains what going through `cli.commands`
    instead would cost. A convenience import of anything under `app.` would
    quietly undo it.
    """
    probe = "import cli.reload_supervisor, sys; print(any(m == 'app' or m.startswith('app.') for m in sys.modules))"
    loaded = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT / "backend",
        capture_output=True,
        text=True,
        check=True,
    )

    assert loaded.stdout.strip() == "False"


def test_the_local_stack_runs_the_supervisor_and_not_uvicorns_own_reloader() -> None:
    """The whole of #308 is that `uvicorn --reload` was PID 1 of this container.

    `cli.reload_supervisor` and not `cli.commands server run --reload`: the
    latter imports `app.main`, which would carry the entire application inside
    a reloader that never serves a request - on a fix about surviving an
    out-of-memory kill.
    """
    compose: dict[str, Any] = yaml.safe_load(LOCAL_COMPOSE.read_text())
    command = compose["services"]["app"]["command"]

    assert command.split() == [
        "python",
        "-m",
        "cli.reload_supervisor",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
