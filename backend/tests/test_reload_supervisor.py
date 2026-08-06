"""The development server survives a worker the kernel kills.

`uvicorn --reload` does not: its reloader watches files and nothing else, so an
OOM-killed worker leaves a zombie, a reloader still politely watching, and a
container reporting `Up` with nothing listening (#308). These pin the decision
the supervisor makes about a worker that is gone - replace it, or wait for the
edit that fixes it - and that the local stack actually runs the supervisor.
"""

import logging
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


def test_a_running_worker_is_left_alone(supervisor: RecordingReload) -> None:
    supervisor.process = FakeWorker(None)

    assert supervisor.should_restart() is None
    assert supervisor.replacements == 0


def test_an_ordinary_exit_is_reported_once_rather_than_every_poll(
    supervisor: RecordingReload, caplog: pytest.LogCaptureFixture
) -> None:
    supervisor.process = FakeWorker(1)

    for _ in range(3):
        supervisor.should_restart()

    assert [r.getMessage() for r in caplog.records].count(
        "Server process [4242] exited with code 1. Waiting for a file change."
    ) == 1


def test_a_file_change_still_reloads(
    supervisor: RecordingReload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reload loop is unchanged; supervision only runs on a quiet poll."""
    changed = [Path("app/main.py")]
    monkeypatch.setattr(ChangeReload, "should_restart", lambda self: changed)
    supervisor.process = FakeWorker(None)

    assert supervisor.should_restart() == changed
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

    run_reload_server(host="0.0.0.0", port=8000)

    assert captured[0].ws == "websockets-sansio"
    assert captured[0].should_reload


def test_the_local_stack_does_not_run_uvicorns_unsupervised_reloader() -> None:
    """The whole of #308 is that `uvicorn --reload` is PID 1 of this container."""
    compose: dict[str, Any] = yaml.safe_load(LOCAL_COMPOSE.read_text())
    command = compose["services"]["app"]["command"]

    assert command.split() == [
        "python",
        "-m",
        "cli.commands",
        "server",
        "run",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--reload",
    ]
