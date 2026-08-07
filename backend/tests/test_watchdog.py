"""A worker whose event loop stops turning kills itself, so something replaces it.

The dev and production stacks have no supervisor that reads a beat, and
production's pipe ping is answered by a thread that keeps answering while the
loop is blocked (#358). So the worker judges its own loop and turns "wedged",
which nothing handles, into "died from a signal", which every stack does.

Two things make these tests worth their length. A wedge has to be *produced*,
not described - a real synchronous block of a real event loop, because a mocked
clock would pass against a watchdog that reads the wrong one. And the verdict
kills the process it runs in, so the end-to-end proof runs in a subprocess and
reads its exit status.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Final

import pytest

from app.core import watchdog as watchdog_module
from app.core.watchdog import (
    BEAT_INTERVAL,
    CHECKS_BEFORE_WEDGED,
    WEDGED_EXIT_STATUS,
    EventLoopWatchdog,
)

pytestmark = pytest.mark.anyio

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# What the tests that *produce* a wedge run under: short, because blocking a
# real loop for longer than the threshold is the whole cost of the test, and
# blocking for longer than asked only makes the verdict surer.
A_SHORT_WEDGE: Final = 0.3
A_QUICK_BEAT: Final = 0.02

# What the tests that assert *nothing happened* run under. Deliberately much
# longer: a healthy loop on a loaded machine can stall for a noticeable
# fraction of a second, and under a 0.3s threshold that would be judged a wedge
# - a test failing for the load on the runner rather than for the logic.
A_GENEROUS_WEDGE: Final = 3.0

# What the subprocess gets to die in. Bounded because a watchdog that never
# fires is the regression, and it would otherwise hang the suite.
A_PATIENT_WAIT: Final = 30.0


class RecordingStop:
    """The verdict, without carrying it out."""

    def __init__(self) -> None:
        self.fired = threading.Event()

    def __call__(self) -> None:
        self.fired.set()


def _watchdog(stop: RecordingStop, *, wedged_after: float = A_SHORT_WEDGE) -> EventLoopWatchdog:
    return EventLoopWatchdog(
        wedged_after=wedged_after, beat_interval=A_QUICK_BEAT, stop_the_process=stop
    )


async def test_a_blocked_event_loop_is_judged_and_the_worker_is_killed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The failure nothing else in the dev or production stack can see.

    `time.sleep` on the loop's own thread is the wedge: coroutines stop running,
    the process stays alive with no exit code, and a health check would still be
    answered by uvicorn's pong thread. The watchdog is on a thread of its own for
    exactly this reason - a coroutine cannot notice that coroutines have stopped.
    """
    caplog.set_level(logging.CRITICAL, logger=watchdog_module.__name__)
    stop = RecordingStop()
    watchdog = _watchdog(stop)
    watchdog.start()
    try:
        await asyncio.sleep(A_QUICK_BEAT * 2)

        # Suppressed below, because blocking the event loop is the failure under
        # test: the lint rule describes the bug this line has to produce.
        time.sleep(A_SHORT_WEDGE + A_QUICK_BEAT * CHECKS_BEFORE_WEDGED * 2)  # noqa: ASYNC251

        assert stop.fired.wait(A_PATIENT_WAIT), "a loop that stopped turning was not judged"
    finally:
        watchdog.stop()
    assert "Stopping this worker so it is replaced" in caplog.text


async def test_a_turning_event_loop_is_left_alone() -> None:
    """The expensive mistake is the other one: killing a worker that is fine."""
    stop = RecordingStop()
    watchdog = _watchdog(stop, wedged_after=A_GENEROUS_WEDGE)
    watchdog.start()
    try:
        await asyncio.sleep(A_GENEROUS_WEDGE / 3)
    finally:
        watchdog.stop()

    assert not stop.fired.is_set()


async def test_an_awaited_slow_dependency_is_not_a_wedge() -> None:
    """Liveness, not readiness - the argument settled in #336 and inherited here.

    A lifespan waiting on a database that is not up yet, or an agent run waiting
    on a model provider, keeps the loop turning. Judging that would restart-loop
    a healthy server against a broken dependency, which is worse than ignoring a
    wedged one.
    """
    stop = RecordingStop()
    watchdog = _watchdog(stop, wedged_after=A_GENEROUS_WEDGE)
    watchdog.start()
    try:
        await asyncio.sleep(A_GENEROUS_WEDGE / 3)  # an await, not a block
    finally:
        watchdog.stop()

    assert not stop.fired.is_set()


def test_one_silent_check_is_a_reprieve_rather_than_a_verdict() -> None:
    """`docker pause` and a laptop waking from sleep stop the watchdog too.

    Both advance the monotonic clock while nothing runs, so the first check
    after one reads a stale stamp that says nothing about the loop. By the next
    check a healthy loop has stamped again.
    """
    watchdog = _watchdog(RecordingStop())
    watchdog._last_beat = time.monotonic() - A_SHORT_WEDGE - 1

    assert watchdog._silent_for() is None
    assert watchdog._silent_for() == pytest.approx(A_SHORT_WEDGE + 1, abs=1)


def test_a_beat_between_two_silent_checks_clears_the_verdict() -> None:
    """The reprieve has to reset, or two silences a minute apart would add up."""
    watchdog = _watchdog(RecordingStop())
    watchdog._last_beat = time.monotonic() - A_SHORT_WEDGE - 1
    assert watchdog._silent_for() is None

    watchdog._last_beat = time.monotonic()
    assert watchdog._silent_for() is None

    watchdog._last_beat = time.monotonic() - A_SHORT_WEDGE - 1
    assert watchdog._silent_for() is None, "the count did not start again after a beat"


async def test_the_check_can_be_switched_off(caplog: pytest.LogCaptureFixture) -> None:
    """A breakpoint blocks the event loop, and no probe can tell that from a deadlock."""
    caplog.set_level(logging.INFO, logger=watchdog_module.__name__)
    stop = RecordingStop()
    watchdog = _watchdog(stop, wedged_after=0)
    watchdog.start()
    try:
        time.sleep(A_SHORT_WEDGE * 2)  # noqa: ASYNC251 - the wedge is the point, see above
        await asyncio.sleep(0)
    finally:
        watchdog.stop()

    assert not stop.fired.is_set()
    assert "Event loop watchdog disabled" in caplog.text


async def test_the_loop_keeps_stamping_for_as_long_as_it_is_watched() -> None:
    """One stamp would pass every test above and kill the worker a minute in.

    The beat re-arms itself, so what is asserted is the second one: a chain that
    stops after the first is a watchdog that judges every healthy worker.
    """
    watchdog = _watchdog(RecordingStop(), wedged_after=A_GENEROUS_WEDGE)
    watchdog.start()
    try:
        first = watchdog._last_beat
        # Fifty intervals, not one: a loop that cannot run a timer callback in a
        # second is not a loaded machine, it is the failure under test.
        await asyncio.sleep(A_QUICK_BEAT * 50)
        second = watchdog._last_beat
    finally:
        watchdog.stop()

    assert second > first, "the beat chain stopped after the first stamp"


async def test_stopping_ends_the_beat_and_the_thread() -> None:
    """Nothing left running after the lifespan: no timer on a closing loop, no thread.

    A slower beat than the other tests use, because `stop` waits two intervals
    for the thread and the assertion below is about what it found - twenty
    milliseconds is not a wait a loaded machine can be held to.
    """
    watchdog = EventLoopWatchdog(
        wedged_after=A_GENEROUS_WEDGE, beat_interval=0.5, stop_the_process=RecordingStop()
    )
    watchdog.start()
    watching = watchdog._watching
    assert watching is not None

    watchdog.stop()

    assert not watching.is_alive()
    assert watchdog._next_beat is not None
    assert watchdog._next_beat.cancelled()


def test_stopping_a_watchdog_that_was_never_started_is_harmless() -> None:
    """The lifespan's shutdown runs whatever its startup did, including the switched-off case."""
    watchdog = _watchdog(RecordingStop(), wedged_after=0)

    watchdog.stop()

    assert watchdog._watching is None


def test_the_verdict_is_a_signal_the_worker_cannot_catch(monkeypatch: pytest.MonkeyPatch) -> None:
    """`SIGTERM` is acted on from the event loop, which is the thing that has stopped.

    So it would be taken and never acted on, and the worker would sit there
    wedged with a signal pending. `SIGKILL` cannot be caught, and what it leaves
    is a worker that died from a signal - which every stack already replaces.
    """
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(watchdog_module.os, "kill", lambda pid, sig: sent.append((pid, sig)))

    watchdog_module._stop_this_process()

    assert sent == [(os.getpid(), signal.SIGKILL)]


def test_a_worker_that_is_pid_1_exits_rather_than_signalling_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The kernel drops a signal sent to a PID namespace's init from inside it.

    Which is the dev stack, where the server *is* PID 1. This is not theory: the
    first version of this logged its verdict inside a real container shaped like
    `docker-compose-dev.yml` and then carried on serving nothing, because
    `SIGKILL` was never delivered. `os._exit` is not a signal, so there is
    nothing to drop, and a container whose PID 1 exits is one the restart policy
    acts on.
    """
    exited: list[int] = []
    monkeypatch.setattr(watchdog_module.os, "getpid", lambda: 1)
    monkeypatch.setattr(watchdog_module.os, "_exit", lambda status: exited.append(status))
    monkeypatch.setattr(
        watchdog_module.os,
        "kill",
        lambda pid, sig: pytest.fail("PID 1 cannot signal itself, and the kernel says so quietly"),
    )

    watchdog_module._stop_this_process()

    # 137, not "whatever the constant says": it is what `docker inspect` shows
    # for a process the kernel killed, and the two routes out of a wedge have to
    # read the same from outside the container.
    assert exited == [128 + int(signal.SIGKILL)]
    assert WEDGED_EXIT_STATUS == 137


def test_the_default_interval_is_far_below_any_useful_threshold() -> None:
    """A beat slower than the threshold would judge every worker on its own jitter."""
    assert BEAT_INTERVAL * CHECKS_BEFORE_WEDGED < 15.0


# The whole mechanism, in a process that really dies: a real asyncio loop, a
# real watchdog, a real block, and a real `SIGKILL` from inside. Everything
# above stubs the kill, which is the one part production depends on.
A_WORKER_THAT_WEDGES = """
import asyncio
import time

from app.core.watchdog import EventLoopWatchdog


async def main() -> None:
    watchdog = EventLoopWatchdog(wedged_after=0.5, beat_interval=0.05)
    watchdog.start()
    await asyncio.sleep(0.3)
    # The event loop stops turning here, and never turns again. Nothing in this
    # process is going to stop it - that is the point.
    while True:
        time.sleep(60)


asyncio.run(main())
"""


def test_a_worker_that_wedges_for_real_dies_of_it() -> None:
    """#358's bar, end to end: no supervisor involved, and the process is gone.

    That exit status is the whole design. `-9` is what
    `Multiprocess.keep_subprocess_alive` replaces twice a second in production,
    what `SupervisedReload._replace_a_dead_worker` replaces locally, and what
    takes the dev stack's PID 1 down so `restart: unless-stopped` acts. None of
    those three needed to learn anything new.
    """
    worker = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(A_WORKER_THAT_WEDGES)],
        cwd=BACKEND_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        worker.wait(timeout=A_PATIENT_WAIT)
    except subprocess.TimeoutExpired:  # pragma: no cover - the regression, not the path
        worker.kill()
        pytest.fail("a wedged worker outlived its own watchdog")
    finally:
        worker.stderr.close() if worker.stderr else None

    assert worker.returncode == -signal.SIGKILL
