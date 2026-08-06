"""The development server survives a worker the kernel kills, and one that wedges.

`uvicorn --reload` survives neither: its reloader watches files and nothing else,
so an OOM-killed worker leaves a zombie, a reloader still politely watching, and
a container reporting `Up` with nothing listening (#308) - and a worker that is
alive but whose event loop has stopped turning is not even that visible (#336).
These pin the decision the supervisor makes about each - replace it, kill and
replace it, or wait for the edit that fixes it - and that the local stack
actually runs the supervisor.
"""

import asyncio
import contextlib
import ctypes
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from multiprocessing import RawValue
from multiprocessing.context import SpawnProcess
from pathlib import Path
from types import FrameType
from typing import Any, Final

import pytest
import yaml
from uvicorn import Config, Server
from uvicorn._subprocess import get_subprocess
from uvicorn.supervisors import ChangeReload
from uvicorn.supervisors.basereload import BaseReload

from cli import reload_supervisor
from cli.reload_supervisor import (
    APP,
    BEAT_INTERVAL,
    NOT_YET_BEATEN,
    WEDGED_AFTER,
    WEDGED_AFTER_ENV_VAR,
    WS_PROTOCOL,
    EventLoopHeartbeat,
    SupervisedReload,
    run_reload_server,
    wedged_after_from_environment,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_COMPOSE = REPO_ROOT / "docker-compose.yml"

# Long enough that no scheduling hiccup on a loaded CI runner reads as a wedge,
# short enough that the test spends a fraction of a second proving one.
A_SHORT_WEDGE: Final = 0.5

# What a spawned worker gets to answer in before the test gives up on it. Long
# because a cold interpreter on a loaded runner is slow, and bounded because the
# regression it guards against is a supervisor that waits for ever.
A_PATIENT_WAIT: Final = 30.0

pytestmark = pytest.mark.anyio


class FakeWorker:
    """Enough of `multiprocessing.Process` for the supervisor's decision."""

    def __init__(self, exitcode: int | None, pid: int = 4242) -> None:
        self.exitcode = exitcode
        self.pid = pid
        self.killed = False

    def kill(self) -> None:
        self.killed = True
        self.exitcode = -signal.SIGKILL

    def join(self) -> None:
        """A killed process is reaped immediately; a fake one has nothing to wait for."""


class BeatingWorker:
    """A stand-in worker: a real event loop running the real heartbeat.

    Module-level and picklable, because `get_subprocess` spawns rather than
    forks - the same reason `EventLoopHeartbeat` is a class and not a closure,
    and the reason this is worth running for real: the shared cell has to
    survive being pickled into a spawned process, which nothing in-process
    proves.

    It catches `SIGTERM` and leaves the loop to act on it, which is what
    `uvicorn.Server.capture_signals` does. Without that the stand-in would die
    on a signal the real worker survives, and the test below would pass against
    a supervisor that hangs in production.
    """

    def __init__(self, heartbeat: EventLoopHeartbeat) -> None:
        self._heartbeat = heartbeat
        self._should_exit = False

    def __call__(self, sockets: list[Any] | None = None) -> None:
        signal.signal(signal.SIGTERM, self._request_exit)
        asyncio.run(self._beat_until_stopped())

    def _request_exit(self, sig: int, frame: FrameType | None) -> None:
        self._should_exit = True

    async def _beat_until_stopped(self) -> None:
        while not self._should_exit:
            await self._heartbeat()
            await asyncio.sleep(0.05)


class RecordingReload(SupervisedReload):
    """Records the replacement rather than spawning a real worker.

    Only the spawn is stubbed - `BaseReload.restart` in the fixture below - so
    `SupervisedReload.restart` itself, and the beat it clears, still run.
    """

    def __init__(self, config: Config, beat: ctypes.c_double, wedged_after: float) -> None:
        super().__init__(
            config,
            target=lambda sockets: None,
            sockets=[],
            beat=beat,
            wedged_after=wedged_after,
        )
        self.replacements = 0


def _record_the_replacement(self: RecordingReload) -> None:
    self.replacements += 1
    self.process = FakeWorker(None, pid=self.process.pid + 1)


@pytest.fixture
def beat() -> ctypes.c_double:
    """The cell the worker stamps its event loop into, as `run_reload_server` makes it."""
    return RawValue("d", NOT_YET_BEATEN)


@pytest.fixture
def wiring(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Everything `run_reload_server` hands the supervisor, without starting anything.

    Captured as one dict rather than asserted piecemeal because the interesting
    property is a relationship between two of the arguments: the cell the
    supervisor reads has to be the cell the worker's heartbeat writes.
    """
    captured: dict[str, Any] = {}

    def capture(self: SupervisedReload, config: Config, **kwargs: Any) -> None:
        captured["config"] = config
        captured.update(kwargs)

    monkeypatch.setattr(Config, "bind_socket", lambda self: None)
    monkeypatch.setattr(SupervisedReload, "__init__", capture)
    monkeypatch.setattr(SupervisedReload, "run", lambda self: None)

    run_reload_server(host="127.0.0.1", port=9999)
    return captured


@pytest.fixture
def supervisor(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, beat: ctypes.c_double
) -> RecordingReload:
    """A supervisor whose file watcher reports no changes, with its log captured.

    Constructing a `Config` applies uvicorn's own logging configuration, under
    which `uvicorn.error` reaches uvicorn's handler rather than the root logger
    `caplog` listens on. The module's logger is swapped for an ordinary one so
    the assertions can be about what was written rather than about handlers.
    """
    monkeypatch.setattr(ChangeReload, "should_restart", lambda self: None)
    monkeypatch.setattr(BaseReload, "restart", _record_the_replacement)
    reloader = RecordingReload(Config(APP, reload=True, ws=WS_PROTOCOL), beat, A_SHORT_WEDGE)
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
    wiring: dict[str, Any],
) -> None:
    """uvicorn's `auto` fails the chat handshake against websockets >=14."""
    config: Config = wiring["config"]

    assert config.ws == "websockets-sansio"
    assert config.should_reload
    assert (config.host, config.port) == ("127.0.0.1", 9999)


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


def test_a_worker_whose_event_loop_stopped_turning_is_replaced(
    supervisor: RecordingReload, beat: ctypes.c_double
) -> None:
    """The whole of #336: this worker is alive, so nothing else would ever act on it."""
    beat.value = time.monotonic() - A_SHORT_WEDGE - 1
    wedged = FakeWorker(None)
    supervisor.process = wedged

    assert supervisor.should_restart() is None
    assert supervisor.replacements == 1
    assert wedged.killed, "SIGTERM never reaches a wedged worker; the replacement would hang"


def test_a_worker_still_beating_is_left_alone(
    supervisor: RecordingReload, beat: ctypes.c_double
) -> None:
    """A slow server is not a wedged one, and replacing it drops requests it was serving."""
    beat.value = time.monotonic()
    supervisor.process = FakeWorker(None)

    assert supervisor.should_restart() is None
    assert supervisor.replacements == 0


def test_a_worker_that_has_not_beaten_yet_is_left_alone(supervisor: RecordingReload) -> None:
    """Booting is not wedging.

    The first beat comes from `main_loop`, which runs only once lifespan startup
    has finished - so a worker importing the application has an empty cell, and
    judging it on that is a restart loop against a cold container.
    """
    supervisor.process = FakeWorker(None)

    assert supervisor.should_restart() is None
    assert supervisor.replacements == 0


def test_a_worker_that_exited_on_its_own_is_not_killed_for_its_stale_beat(
    supervisor: RecordingReload, beat: ctypes.c_double
) -> None:
    """Its beat stops when it exits, and respawning it loops on the same traceback.

    Without the guard, the wedge check would undo the one decision
    `_replace_a_dead_worker` makes deliberately.
    """
    beat.value = time.monotonic() - A_SHORT_WEDGE - 1
    supervisor.process = FakeWorker(1)

    assert supervisor.should_restart() is None
    assert supervisor.replacements == 0


def test_a_replacement_is_not_judged_on_the_beat_of_the_worker_it_replaced(
    supervisor: RecordingReload, beat: ctypes.c_double
) -> None:
    """Otherwise the first replacement inherits a stale cell and is killed on the next poll."""
    beat.value = time.monotonic() - A_SHORT_WEDGE - 1
    supervisor.process = FakeWorker(None)

    supervisor.should_restart()
    supervisor.should_restart()

    assert supervisor.replacements == 1
    assert beat.value == NOT_YET_BEATEN


def test_a_worker_wedging_during_shutdown_is_not_replaced(
    supervisor: RecordingReload, beat: ctypes.c_double
) -> None:
    """A worker stops beating as it shuts down, and its replacement would be an orphan."""
    supervisor.should_exit.set()
    beat.value = time.monotonic() - A_SHORT_WEDGE - 1
    supervisor.process = FakeWorker(None)

    assert supervisor.should_restart() is None
    assert supervisor.replacements == 0


def test_a_last_gasp_beat_from_a_dying_worker_does_not_reach_its_replacement(
    supervisor: RecordingReload, beat: ctypes.c_double, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Server.on_tick` beats before it reads `should_exit`.

    So a worker that has just been sent `SIGTERM` gets one more tick and beats
    one last time, on roughly one restart in ten. Clearing the cell before the
    replacement rather than after would hand that beat to a process still
    importing the application, and kill it fifteen seconds into a cold boot.
    """

    def _beat_on_the_way_out(self: RecordingReload) -> None:
        beat.value = time.monotonic()
        _record_the_replacement(self)

    monkeypatch.setattr(BaseReload, "restart", _beat_on_the_way_out)
    supervisor.process = FakeWorker(-9)

    supervisor.should_restart()

    assert supervisor.replacements == 1
    assert beat.value == NOT_YET_BEATEN


def test_shutting_down_kills_a_wedged_worker_rather_than_waiting_for_it(
    supervisor: RecordingReload, beat: ctypes.c_double, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_replace_a_wedged_worker` steps aside during shutdown, so `shutdown` has to act.

    `BaseReload.shutdown` sends `SIGTERM` and joins without a timeout, and a
    wedged worker never acts on `SIGTERM` - so Ctrl+C would block until Docker
    killed the container ten seconds later.
    """
    stopped: list[bool] = []
    monkeypatch.setattr(BaseReload, "shutdown", lambda self: stopped.append(True))
    wedged = FakeWorker(None)
    supervisor.process = wedged
    beat.value = time.monotonic() - A_SHORT_WEDGE - 1

    supervisor.shutdown()

    assert wedged.killed
    assert stopped == [True]


def test_shutting_down_leaves_a_healthy_worker_to_drain(
    supervisor: RecordingReload, beat: ctypes.c_double, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`SIGTERM` is how in-flight requests finish; escalating always would drop them."""
    monkeypatch.setattr(BaseReload, "shutdown", lambda self: None)
    healthy = FakeWorker(None)
    supervisor.process = healthy
    beat.value = time.monotonic()

    supervisor.shutdown()

    assert not healthy.killed


def test_a_worker_is_not_judged_on_a_poll_the_supervisor_itself_slept_through(
    supervisor: RecordingReload, beat: ctypes.c_double
) -> None:
    """`docker pause`, a frozen cgroup, a Docker Desktop VM after the host slept.

    Monotonic time advances for the supervisor as well, so the worker's silence
    says nothing about the worker. It gets a full window to prove itself, and a
    healthy one takes about a second over it.
    """
    supervisor.process = FakeWorker(None)
    supervisor._polled_at = time.monotonic() - A_SHORT_WEDGE - 1
    beat.value = time.monotonic() - A_SHORT_WEDGE - 1

    assert supervisor.should_restart() is None
    assert supervisor.replacements == 0
    assert beat.value == pytest.approx(time.monotonic(), abs=1)


def test_a_worker_still_wedged_after_the_host_wakes_is_replaced(
    supervisor: RecordingReload, beat: ctypes.c_double
) -> None:
    """Forgiving the frozen window is a reprieve, not an exemption."""
    supervisor.process = FakeWorker(None)
    supervisor._polled_at = time.monotonic() - A_SHORT_WEDGE - 1
    beat.value = time.monotonic() - A_SHORT_WEDGE - 1
    supervisor.should_restart()

    beat.value = time.monotonic() - A_SHORT_WEDGE - 1

    assert supervisor.should_restart() is None
    assert supervisor.replacements == 1


def test_the_wedge_check_can_be_switched_off(
    monkeypatch: pytest.MonkeyPatch, beat: ctypes.c_double
) -> None:
    """A breakpoint blocks the event loop, and no probe can tell that from a deadlock."""
    monkeypatch.setattr(ChangeReload, "should_restart", lambda self: None)
    monkeypatch.setattr(BaseReload, "restart", _record_the_replacement)
    off = RecordingReload(Config(APP, reload=True, ws=WS_PROTOCOL), beat, wedged_after=0)
    off.process = FakeWorker(None)
    beat.value = time.monotonic() - A_SHORT_WEDGE - 1

    assert off.should_restart() is None
    assert off.replacements == 0


async def test_the_heartbeat_stamps_the_cell_the_supervisor_reads(
    beat: ctypes.c_double,
) -> None:
    await EventLoopHeartbeat(beat)()

    assert beat.value == pytest.approx(time.monotonic(), abs=1)


async def test_uvicorn_awaits_the_heartbeat_on_its_own_tick(beat: ctypes.c_double) -> None:
    """The hook belongs to uvicorn, so its contract is worth asserting rather than assuming.

    `on_tick` is the body of `main_loop`. If it stopped awaiting
    `callback_notify` - a rename, a change to what `timeout_notify` means - the
    cell would never fill, every worker would read as wedged, and every test
    that fills the cell by hand would still pass.
    """

    async def nothing(scope: Any, receive: Any, send: Any) -> None:
        """An application the config can load without importing the platform."""

    config = Config(nothing, callback_notify=EventLoopHeartbeat(beat), timeout_notify=BEAT_INTERVAL)
    config.load()

    await Server(config).on_tick(counter=0)

    assert beat.value == pytest.approx(time.monotonic(), abs=1)


def test_the_worker_reports_its_event_loop_through_uvicorns_notify_hook(
    wiring: dict[str, Any],
) -> None:
    """`callback_notify` is awaited by `Server.on_tick`, which is the loop itself.

    A thread answering a pipe - what `Multiprocess` asks - keeps answering while
    the loop is blocked, which is the failure this is for.
    """
    config: Config = wiring["config"]

    assert isinstance(config.callback_notify, EventLoopHeartbeat)
    assert config.timeout_notify == BEAT_INTERVAL


def test_the_worker_and_the_supervisor_share_one_cell(wiring: dict[str, Any]) -> None:
    """Two cells would pass every other test and kill a healthy worker every 15 seconds."""
    heartbeat: EventLoopHeartbeat = wiring["config"].callback_notify

    assert heartbeat._beat is wiring["beat"]


def test_the_beat_cell_carries_no_lock(wiring: dict[str, Any]) -> None:
    """`multiprocessing.Value` here refuses to start the container, and could hang it.

    Its lock is a `SemLock` from the default context, which on Linux is `fork`
    while uvicorn spawns - so the worker never starts and the container
    restart-loops with `A SemLock created in a fork context is being shared with
    a process in a spawn context`. That is invisible on macOS, where the default
    context is already `spawn`, which is why it is asserted here rather than
    left to the spawning test below.

    The lock would be a hazard even where it pickles: this module `SIGKILL`s a
    wedged worker, and one killed while holding the lock leaves it held, so the
    supervisor's next read of the cell would block for ever.
    """
    assert isinstance(wiring["beat"], ctypes.c_double)


def test_the_threshold_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WEDGED_AFTER_ENV_VAR, raising=False)
    assert wedged_after_from_environment() == WEDGED_AFTER

    monkeypatch.setenv(WEDGED_AFTER_ENV_VAR, "0")
    assert wedged_after_from_environment() == 0


def test_a_threshold_that_is_not_a_number_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Falling back to 15 seconds on a typo is how somebody debugs the supervisor instead."""
    monkeypatch.setenv(WEDGED_AFTER_ENV_VAR, "off")

    with pytest.raises(ValueError, match="off"):
        wedged_after_from_environment()


def test_a_worker_stopped_mid_flight_is_killed_and_replaced() -> None:
    """The end of #336, against a process that is genuinely alive and not answering.

    `SIGSTOP` is the cheap way to produce one: the process exists, has no exit
    code, and runs nothing. It is also the case that pins `kill` over
    `terminate`. The worker catches `SIGTERM` and acts on it from the event
    loop, so a wedged one never acts on it at all and the join inside
    `BaseReload.restart` blocks the supervisor for good - a regression that
    would hang this test rather than fail it, which is why the replacement runs
    on a thread the test refuses to wait on indefinitely.
    """
    beat: ctypes.c_double = RawValue("d", NOT_YET_BEATEN)
    config = Config(APP, reload=True, ws=WS_PROTOCOL)
    worker = BeatingWorker(EventLoopHeartbeat(beat))
    supervisor = SupervisedReload(
        config, target=worker, sockets=[], beat=beat, wedged_after=A_SHORT_WEDGE
    )
    supervisor.process = get_subprocess(config, target=worker, sockets=[])
    supervisor.process.start()
    wedged = supervisor.process
    replacing = threading.Thread(target=supervisor._replace_a_wedged_worker, daemon=True)
    try:
        _wait_until_beating(beat)
        os.kill(wedged.pid, signal.SIGSTOP)
        time.sleep(A_SHORT_WEDGE * 2)

        replacing.start()
        replacing.join(timeout=A_PATIENT_WAIT)

        assert not replacing.is_alive(), "the supervisor is stuck on a worker that ignores SIGTERM"
        assert wedged.exitcode == -signal.SIGKILL
        assert supervisor.process is not wedged
        _wait_until_beating(beat)
    finally:
        # The wedged worker goes first and unjoined: a supervisor still stuck on
        # it has to be let go before its thread can finish, and joining a process
        # that thread is already joining is how the cleanup deadlocks in turn.
        _kill(wedged)
        if replacing.ident is not None:
            replacing.join(timeout=A_PATIENT_WAIT)
        _reap(supervisor.process)
        _reap(wedged)


def _kill(process: SpawnProcess) -> None:
    """Send `SIGKILL` to a process that may already be gone, and do not wait for it."""
    with contextlib.suppress(ProcessLookupError):
        os.kill(process.pid, signal.SIGKILL)


def _reap(process: SpawnProcess) -> None:
    """Kill a process and wait for it, a no-op once it has been reaped already."""
    _kill(process)
    process.join()


def _wait_until_beating(beat: ctypes.c_double, timeout: float = A_PATIENT_WAIT) -> None:
    """Block until the worker has reported its event loop at least once."""
    deadline = time.monotonic() + timeout
    while beat.value == NOT_YET_BEATEN:
        assert time.monotonic() < deadline, "the worker never reported a turning event loop"
        time.sleep(0.05)
