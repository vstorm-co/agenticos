"""The worker's own judgement of its event loop, for the stacks with no supervisor.

`cli/reload_supervisor.py` watches the local stack's worker from the process
that spawned it. The other two stacks have no such parent (#358):

| Stack | Worker is gone | Event loop has stopped turning |
|---|---|---|
| `docker-compose.yml` | the reload supervisor replaces it | the supervisor reads its beat |
| `docker-compose-dev.yml` | PID 1 exits, `restart:` acts | **nothing, before this** |
| `docker-compose-prod.yml` | `Multiprocess` replaces it | **nothing, before this** |

Production's cover is narrower than it looks. `Multiprocess.keep_subprocess_alive`
does ping each worker and kill one that does not answer within
`timeout_worker_healthcheck` - but the answer comes from `Process.always_pong`,
a dedicated thread. A thread keeps answering while the event loop is blocked,
which is the single most likely way to wedge an async server, so the one stack
with cover has cover against the least likely case.

## Why the worker judges itself

Every stack already handles a worker that is **gone**: uvicorn's `Multiprocess`
replaces it twice a second, the reload supervisor replaces it on its next poll,
and a dev container whose PID 1 exits is restarted by Docker. Nothing handles a
worker that is **stuck**, and each stack would need a different mechanism to
learn how.

So this does not teach three supervisors a new verdict. It turns the failure
none of them handles into the one all of them do: the worker watches its own
event loop from a thread and, when the loop has stopped turning, ends its own
process. One mechanism, three correct outcomes, and no supervisor is replaced -
which matters most in production, where PID 1 is the process whose job is to
survive whatever took the worker down.

What was rejected, and why:

- **A `Multiprocess` subclass with a beat per worker**, i.e. the reload
  supervisor's design moved to production. `Multiprocess` constructs `Process`
  at four sites (`init_processes`, `restart_all`, `keep_subprocess_alive`,
  `handle_ttin`), none of them a factory, so a subclass means either copying
  four upstream methods or rebinding a module global. Either way it replaces
  the supervisor that serves real traffic, and `restart_all`'s readiness check
  is recent upstream work we would then own.
- **Answering the pipe ping from the event loop** - a `Process` subclass whose
  `pong` waits for a beat. It fixes exactly the defect #358 names and is the
  most tempting of the three, but it needs the same four call sites, and it
  makes `timeout_worker_healthcheck` the wedge threshold - the same number
  `wait_until_ready` and `restart_all` use, so a threshold long enough to be
  safe would slow a `SIGHUP` restart and dead-worker detection with it.
- **`--workers 2` on the dev stack**, to buy it uvicorn's supervisor. A second
  interpreter on a small box for cover against a *stopped* PID 1, which the
  kernel makes unreachable anyway: it drops `SIGSTOP` sent to a PID namespace's
  init from inside it (#333 hit that).
- **An HTTP probe, or `autoheal` on the health check.** A probe traverses the
  application, so a slow database restart-loops a healthy server - readiness,
  not liveness. `autoheal` wants the Docker socket, which is root-equivalent
  and deliberately confined to `sandboxd`. Both were settled in #336 and #357.

## What it cannot see, and what sees that instead

A watchdog inside the process cannot judge a process that is not running at all:
`kill -STOP`, a frozen cgroup, `docker pause`. That is not a gap, because a
stopped worker is one every stack's existing mechanism already catches - the
pipe ping goes unanswered in production, and the beat goes stale in the local
supervisor. The two judges have complementary blind spots rather than being one
mechanism twice, which is why the reload supervisor keeps its own check.

Nor can it see a thread-starving C call: an extension that holds the GIL
without releasing it stops this thread too. Every realistic wedge - a deadlock
on a lock, a synchronous socket read, `time.sleep` in a handler, a blocking
driver call - releases the GIL or is pure Python, and both let the watchdog
run.

**Startup is not watched**, only serving and shutdown. A synchronous call that
blocks the loop while the application is coming up would be judged on every
attempt, and a restart loop against a cold container is a worse failure than
the slow boot it would be reporting. That is the window #357 declined to judge
for the same reason, and this does not re-open it.

`EVENT_LOOP_WEDGED_AFTER=0` switches it off, which is what a breakpoint needs: a
stopped event loop is exactly what this is looking for, and no probe can tell a
debugger from a deadlock. The reload supervisor reads the same variable, so one
number switches off both judges rather than leaving this one to kill the
debugging session the other was told to allow.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# How often the loop stamps that it is turning, and how often the thread reads
# the stamp. A second is far below any threshold worth setting and costs one
# timer callback on an otherwise idle loop.
BEAT_INTERVAL = 1.0

# Consecutive silent checks before the verdict, for the reason
# `POLLS_BEFORE_WEDGED` gives in `cli/reload_supervisor.py`: `docker pause`, a
# frozen cgroup and a laptop waking from sleep advance the monotonic clock while
# nothing runs - the watchdog thread included - so the first check after a thaw
# reads a stale stamp that says nothing about the loop. By the next check, a
# second later, a healthy loop has stamped again and the verdict clears.
CHECKS_BEFORE_WEDGED = 2

# What a worker exits with when it cannot signal itself - see
# `_stop_this_process`. `128 + SIGKILL`, which is what a shell and
# `docker inspect` report for a process the kernel killed, so the two routes out
# of a wedge read the same from outside. Written out rather than computed from
# `signal.SIGKILL`, which does not exist on Windows: this module is imported by
# `app.main` on every platform, and only the branch that signals is POSIX-only.
WEDGED_EXIT_STATUS = 137


def _stop_this_process() -> None:
    """End this process from a thread inside it, whatever position it holds.

    Not `SIGTERM`: uvicorn catches it and acts on it from the event loop, which
    is the one thing a wedged worker cannot do, so it would be taken and never
    acted on. Not `sys.exit` either - that raises in this thread and leaves the
    process running. `SIGKILL` cannot be caught, and what it leaves behind is a
    worker that died from a signal, which every supervisor here already
    replaces.

    **Unless the worker is PID 1**, which it is on the dev stack. The kernel
    does not deliver a signal to a PID namespace's init from inside that
    namespace unless init installed a handler for it, and `SIGKILL` cannot be
    handled - so the signal is silently dropped and the container stays `Up`
    with its loop still blocked. That is not a hypothesis: the first version of
    this logged its verdict inside a real `docker-compose-dev.yml`-shaped
    container and then went on serving nothing. `os._exit` is the equivalent
    there. It is not a signal, so there is nothing to drop, and PID 1 exiting
    is exactly what a restart policy acts on.

    The status is `137` for the same reason a shell reports it: it is what this
    process would have carried had the signal been delivered.
    """
    if os.getpid() == 1:
        os._exit(WEDGED_EXIT_STATUS)
    else:
        os.kill(os.getpid(), signal.SIGKILL)


class EventLoopWatchdog:
    """Stamps the event loop from the loop, and reads the stamp from a thread.

    The two halves have to be on different schedulers or the check proves
    nothing: a coroutine cannot notice that coroutines have stopped running.
    A thread can, and the same property that makes uvicorn's pipe-pong thread a
    bad liveness *answer* makes it a good liveness *judge* - it keeps running
    while the loop does not.

    The stamp is a plain `float` written by one and read by the other. No lock:
    an aligned attribute assignment is atomic under the GIL, and a lock here
    would be the hazard the reload supervisor's `RawValue` docstring describes,
    one process further in - held by a thread that is about to `SIGKILL` the
    process it is held in.

    The loop's half is a self-rescheduling `call_later`, not a task. There is
    therefore nothing for `app.core.background` to hold a reference to and
    nothing to drain at shutdown: the loop owns the callback, cancelling the
    handle ends the chain, and a timer callback is a more direct statement that
    the loop is scheduling than a coroutine that also has to be scheduled.
    """

    def __init__(
        self,
        *,
        wedged_after: float,
        beat_interval: float = BEAT_INTERVAL,
        stop_the_process: Callable[[], None] = _stop_this_process,
    ) -> None:
        self._wedged_after = wedged_after
        self._beat_interval = beat_interval
        self._stop_the_process = stop_the_process
        self._last_beat = time.monotonic()
        self._silent_checks = 0
        self._stopping = threading.Event()
        self._watching: threading.Thread | None = None
        self._next_beat: asyncio.TimerHandle | None = None

    def start(self) -> None:
        """Begin stamping and watching, unless the check is switched off.

        Called at the *end* of lifespan startup, so the window watched is the
        same one `Config.callback_notify` gives the reload supervisor: serving,
        and then shutdown. Watching startup too would be two lines earlier and
        is deliberately not done - a synchronous call that blocks the loop for
        the threshold during boot would be killed on every attempt, and a
        restart loop against a cold container is a worse failure than the slow
        boot it would be reporting. #357 declined to judge that window for the
        same reason, and this does not re-open it.

        Raises:
            RuntimeError: if there is no running event loop to watch.
        """
        if self._wedged_after <= 0:
            logger.info("Event loop watchdog disabled")
            return
        self._last_beat = time.monotonic()
        self._schedule_a_beat(asyncio.get_running_loop())
        self._watching = threading.Thread(
            target=self._watch, name="event-loop-watchdog", daemon=True
        )
        self._watching.start()

    def stop(self) -> None:
        """Stop watching, and wait for the thread to notice.

        Called at the very end of the lifespan's shutdown rather than the start
        of it, so a shutdown that wedges - a driver that never returns, a
        connection pool that will not close - is still judged rather than
        hanging the container until Docker's grace period runs out.
        """
        if self._next_beat is not None:
            self._next_beat.cancel()
        self._stopping.set()
        if self._watching is not None:
            self._watching.join(timeout=self._beat_interval * 2)

    def _schedule_a_beat(self, loop: asyncio.AbstractEventLoop) -> None:
        """Arm the next stamp. The loop is carried rather than stored, so there is one owner."""
        self._next_beat = loop.call_later(self._beat_interval, self._beat, loop)

    def _beat(self, loop: asyncio.AbstractEventLoop) -> None:
        """The loop saying it is turning, by having run this at all."""
        self._last_beat = time.monotonic()
        self._schedule_a_beat(loop)

    def _watch(self) -> None:
        """The thread: check on every interval until the verdict or the stop."""
        while not self._stopping.wait(self._beat_interval):
            silent_for = self._silent_for()
            if silent_for is None:
                continue
            logger.critical(
                "Event loop has not turned for %.0fs. Stopping this worker so it is replaced.",
                silent_for,
            )
            self._stop_the_process()
            return

    def _silent_for(self) -> float | None:
        """How long the loop has been silent, if that is a verdict rather than a reading.

        `None` while the loop is turning, and for the first silent check, which
        is a reprieve rather than a verdict - see `CHECKS_BEFORE_WEDGED`.
        """
        silent_for = time.monotonic() - self._last_beat
        if silent_for < self._wedged_after:
            self._silent_checks = 0
            return None
        self._silent_checks += 1
        if self._silent_checks < CHECKS_BEFORE_WEDGED:
            return None
        return silent_for
