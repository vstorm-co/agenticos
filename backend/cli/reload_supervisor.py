"""The development server, and the supervision `uvicorn --reload` does not do.

`--reload` starts a *file watcher*, not a process supervisor. Its loop reacts to
a file changing and to a signal arriving, and to nothing else:
`uvicorn.supervisors.basereload.BaseReload.run` never reads
`self.process.exitcode`. So a worker the kernel kills is never noticed. The
reloader keeps watching, the dead worker stays a zombie because nobody waited on
it, and in a container PID 1 is therefore still alive - `docker ps` says `Up`,
the restart policy has nothing to act on, and no port is listening. The health
check does go `unhealthy`, but a column is not a mechanism.

An out-of-memory kill is the realistic way in.

Only the reload path has this hole. `--workers`, which is what production runs,
gets uvicorn's `Multiprocess` supervisor, and its `keep_subprocess_alive` already
polls, reaps and replaces a dead worker twice a second. This module gives the
reload path the same treatment, with one distinction the workers path does not
need:

- **Died from a signal** (`exitcode < 0`). `-9` is the OOM killer; `-15` is a
  `kill` from outside, and a *graceful* shutdown lands here too, because
  `Server.capture_signals` re-raises the signal it just handled cleanly. The
  distinction does not matter: the process is gone, nothing is listening, and no
  edit is coming. Reap and start a replacement.
- **Exited on its own** (`exitcode >= 0`). The application raised on import or
  called `sys.exit`; respawning would loop on the same traceback forever. Reap,
  say so once, and wait for the file change that fixes it - which is the whole
  reason `--reload` exists.

Either way the process is reaped, so the zombies are gone in both cases. Neither
happens once `should_exit` is set: a replacement started while the reloader is
shutting down is a process nothing will ever stop.

## A worker that is wedged rather than dead

Both branches above key off a process that is *gone*. A worker deadlocked on a
lock, spinning in a synchronous call, or blocked on a socket that never answers
has no exit code at all, so the supervisor sees a healthy child and does nothing
while every request times out (#336).

So the worker also says, from its own event loop, that the loop is turning.
uvicorn already has the hook: `Config.callback_notify` is awaited by
`Server.on_tick` once `time.time()` has advanced past `timeout_notify` since the
last beat, which is the integration point systemd's watchdog uses. The callback
stamps `time.time()` into a shared cell - the same wall clock the cadence is
gated on, so the verdict cannot diverge from it (#1080); the supervisor reads
the cell on the same quiet poll as everything else, and replaces a worker whose
loop has not turned for `WEDGED_AFTER` seconds.

Four properties of that choice are the reason for it:

- **It measures liveness, not readiness.** The beat is a callback on an
  otherwise idle timer, so it costs nothing and answers in milliseconds however
  loaded the server is. An HTTP probe against the bound port would have been
  fewer lines, but it traverses the application - so a slow database or a Redis
  outage would read as a wedged worker and the supervisor would restart-loop a
  healthy server against a broken dependency. Killing a worker for being slow is
  worse than ignoring a wedged one.
- **It sees what a pipe ping cannot.** `Multiprocess` asks the worker over a
  pipe, and the answer comes from a dedicated thread - which keeps answering
  while the event loop is blocked, the single most likely way to wedge an async
  server. A beat that originates *on the loop* is exactly the signal that thread
  cannot fake.
- **A wedged worker is killed, not terminated.** `BaseReload.restart` sends
  `SIGTERM` and joins - and the worker *catches* it, as the graceful shutdown
  above says. Acting on it therefore needs the event loop to come round, which
  is the one thing a wedged worker cannot do; a stopped process does not run the
  handler at all and leaves the signal pending. Either way the join never
  returns and the supervisor hangs with it. `SIGKILL` cannot be caught, which is
  what `Multiprocess.keep_subprocess_alive` relies on for a worker it has judged
  hung. `shutdown` needs the same escalation for the same reason, or Ctrl+C on a
  wedged worker blocks until Docker's grace period runs out.
- **A frozen host is not a wedged worker.** `docker pause`, a frozen cgroup and
  a Docker Desktop VM resuming after the host slept all step the wall clock
  forward while *nothing* runs, worker and supervisor alike, so the first poll
  after one reads a beat stamped before the jump and finds a gap that says
  nothing about the worker. Two consecutive silent polls are therefore needed
  rather than one: by the second, a healthy worker has beaten again and the
  verdict clears. The beat and the verdict read the same wall clock uvicorn
  gates the cadence on, so a stalled clock never reads as a wedge on its own
  (#1080).

## The other two stacks, which do not run this module

`docker-compose-dev.yml` is a single unsupervised uvicorn and
`docker-compose-prod.yml` is `--workers 4` under uvicorn's own `Multiprocess`,
so neither has a parent that reads a beat, and neither could grow one without
replacing a supervisor (#358). They are covered from the other side instead:
`app.core.watchdog` makes the same judgement *inside* the worker and kills its
own process, which turns a wedge into the one failure every stack already
handles - a worker that is gone. That watchdog runs here too, and the two are
not one mechanism twice: a process stopped outright (`kill -STOP`, a frozen
cgroup) cannot run its own watchdog and only this supervisor sees it, while a
blocked event loop is exactly what a watchdog on a thread sees.

**What this does not cover**, deliberately:

- **Replacing a worker that wedges before it serves.** `main_loop` - and so the
  first beat - starts only once lifespan startup has finished, so a worker hung
  on a database connect at boot never beats and is never *judged*. Judging it
  would mean a startup grace period long enough to be meaningless on a cold
  container. `shutdown` no longer inherits that gap (#366): it cannot judge such
  a worker either, but it does not have to, because stopping one needs no
  verdict - `SIGTERM`, a second, then `SIGKILL`.
- **A debugger.** A breakpoint blocks the event loop and is indistinguishable
  from a deadlock by construction, so 15 seconds on one wedges the worker and it
  is replaced. `EVENT_LOOP_WEDGED_AFTER=0` turns the whole check off, here and
  in the worker's own watchdog.
- **A worker in uninterruptible sleep.** `SIGKILL` is not delivered to a process
  in `D` state - a dead network mount is the way in - so the join after it hangs
  as `SIGTERM` would have. A bounded join would only move the hang into
  `BaseReload.restart`, which joins again with no timeout, so it is recorded
  here rather than half-fixed.

**This module is its own entrypoint** - `python -m cli.reload_supervisor` - and
imports nothing beyond uvicorn and click on purpose. Reaching it through
`cli.commands` instead would pull `app.main` into the reloader, and the reloader
never serves a request: measured in `agenticos_backend:dev`, importing
`cli.commands` peaks at 464 MB against 28 MB for uvicorn alone. Handing the
process that exists to survive an out-of-memory kill another 436 MB to be killed
for would be an odd way to fix this.
"""

import logging
import os
import time
from collections.abc import Callable
from ctypes import c_double
from multiprocessing import RawValue
from pathlib import Path
from socket import socket
from typing import Final

import click
from uvicorn import Config, Server

# The reload supervisor uvicorn's own `main.run` uses: `WatchFilesReload`, or
# `StatReload` where watchfiles is missing. `uvicorn[standard]` ships watchfiles.
from uvicorn.supervisors import ChangeReload

# uvicorn's `auto` picks the legacy websockets implementation, which fails the
# handshake against websockets >=14 with an HTTP 500. The dashboard chat is a
# WebSocket, so `auto` means no chat at all. The other two compose files pass
# `--ws websockets-sansio` on their own command lines for the same reason;
# `docker-compose.yml` and `agenticos server run` read it from here instead.
WS_PROTOCOL: Final = "websockets-sansio"

APP: Final = "app.main:app"

# How often the worker's event loop says it is turning, as uvicorn's
# `timeout_notify`. `Server.on_tick` runs ten times a second and notifies on the
# first tick past this many seconds, so a beat lands every one to two seconds.
BEAT_INTERVAL: Final = 1

# How long a worker may go without a beat before it is judged wedged. It is
# fifteen missed beats rather than a couple, because the cost of the two
# mistakes is not symmetric: replacing a wedged worker late costs seconds on a
# laptop, and replacing a healthy one early drops in-flight requests. Fifteen
# seconds of an event loop not turning is not load - a loaded loop still runs a
# timer callback in milliseconds - it is blocked, stopped or deadlocked. It also
# leaves room for the beat's own jitter: the beat and the verdict both read
# `time.time()`, the clock uvicorn gates the cadence on (#1080), so a wall-clock
# step moves the beat and the reading together rather than only one of them - but
# a forward step still stretches the gap by its size until the next beat lands,
# and fifteen seconds absorbs that where two would not. The supervisor notices
# within `WEDGED_AFTER` plus the two polls `POLLS_BEFORE_WEDGED` costs, so about
# twenty-five seconds, against the ninety a container health check takes to reach
# a verdict nothing acts on.
WEDGED_AFTER: Final = 15.0

# Consecutive silent polls before the worker is replaced. Two, not one, because
# `docker pause`, a frozen cgroup and a Docker Desktop VM resuming after the host
# slept all step the wall clock forward while *nothing* runs - supervisor
# included - so the first poll after one of those reads a beat stamped before the
# jump and finds a gap that says nothing about the worker. By the next poll a
# healthy worker has beaten again, about a second having passed, and the verdict
# clears; a wedged one fails both. The reprieve costs one poll of detection, and
# it is deliberately not measured as a gap in the supervisor's own polling:
# watchfiles ticks every five seconds or so, so any threshold below that would
# have compared a poll gap against a smaller number, judged every poll a freeze,
# and switched the check off in silence.
POLLS_BEFORE_WEDGED: Final = 2

# Seconds without a beat before a worker is replaced, `0` or below to switch the
# check off - which is what somebody sitting on a breakpoint wants, a stopped
# event loop being indistinguishable from a deadlock. The same variable is read
# by `app.core.watchdog`, which judges the same event loop from inside the
# worker on the two stacks that have no supervisor at all - one number, so
# switching the check off for a breakpoint switches off both judges rather than
# leaving the in-process one to kill the debugging session.
WEDGED_AFTER_ENV_VAR: Final = "EVENT_LOOP_WEDGED_AFTER"

# How long `shutdown` waits for a worker to act on `SIGTERM` before killing it.
#
# Two numbers, because "has not stopped yet" means different things either side
# of the first beat. A worker that has served drains what it is holding -
# in-flight requests, and the background tasks `app.core.background.drain`
# waits on - so the wait has to cover that; eight seconds does, and stays inside
# Docker's ten-second grace so the container exits because the supervisor
# stopped it rather than because Docker gave up on it. A worker that has never
# beaten never finished lifespan startup, so it is holding nothing and has
# nothing to drain: all the wait buys there is the moment it takes to notice a
# signal, and the rest of it is the hang #366 filed - Ctrl+C against a Postgres
# that is down, waiting out a grace period for a worker that will never answer.
STOP_GRACE: Final = 8.0
STOP_GRACE_BEFORE_THE_FIRST_BEAT: Final = 1.0

# The value of the shared cell before the worker's first beat. A worker is
# judged only once it has beaten at least once, so a slow boot is never mistaken
# for a wedge.
NOT_YET_BEATEN: Final = 0.0

logger = logging.getLogger("uvicorn.error")


class EventLoopHeartbeat:
    """The worker's end of the liveness signal, awaited on its own event loop.

    Passed to the worker as `Config.callback_notify`, which means it is pickled
    into the spawned process along with the shared cell it writes to - allowed
    because the pickling happens while the child is being spawned, which is the
    one time `multiprocessing` permits a shared value to cross.

    **The stamp is `time.time()`, not `time.monotonic()`, and that is the whole
    of #1080.** uvicorn does not call this on a fixed cadence: `Server.on_tick`
    beats only when `time.time() - last_notified > timeout_notify`, so *when* a
    beat happens is governed by the wall clock. The verdict has to read the same
    clock the cadence runs on, or the two diverge: on Docker Desktop's VM the
    wall clock can stall for tens of seconds relative to the monotonic clock
    while the loop keeps serving, and a monotonic verdict then read that stalled
    beat as a wedge and killed a healthy worker. Wall on both sides cannot
    diverge from itself - a stalled wall clock stalls the cadence and the verdict
    together, so the reading stays near zero.

    `RawValue` and not `Value`, on two counts. `Value`'s lock is a `SemLock` from
    the *default* context, which on Linux is `fork` - and uvicorn spawns, so
    handing the worker one raises `A SemLock created in a fork context is being
    shared with a process in a spawn context` and the container restart-loops
    before it serves a request. That is not a macOS symptom, where the default
    context is already `spawn`, so it appears first in CI or in Docker. And a
    lock here would be a hazard even where it pickles: a worker killed while
    holding it - which is exactly what this module does to a wedged one - leaves
    it held for good, and the supervisor's next read of the cell hangs forever.
    One aligned 8-byte double, one writer, one reader, no lock to lose.
    """

    def __init__(self, beat: c_double) -> None:
        self._beat = beat

    async def __call__(self) -> None:
        self._beat.value = time.time()


class SupervisedReload(ChangeReload):
    """A `--reload` reloader that notices a worker that died, and one that wedged.

    `ChangeReload` polls for changes with a timeout rather than blocking
    forever, so overriding `should_restart` is enough to get a periodic tick:
    `WatchFilesReload` passes `yield_on_timeout=True` with watchfiles' 5s
    `rust_timeout`, and the fallback `StatReload` polls at `reload_delay`.
    Detection therefore costs at most about five seconds, against the three
    failed health checks - ninety seconds - that a container restart would take.
    """

    def __init__(
        self,
        config: Config,
        target: Callable[[list[socket] | None], None],
        sockets: list[socket],
        *,
        beat: c_double,
        wedged_after: float = WEDGED_AFTER,
    ) -> None:
        super().__init__(config, target, sockets)
        # The pid whose ordinary exit has already been reported, so the "waiting
        # for a change" line is written once rather than on every poll.
        self._reported_pid: int | None = None
        self._beat = beat
        self._wedged_after = wedged_after
        # Consecutive polls that have found the worker silent. One is not a
        # verdict; `POLLS_BEFORE_WEDGED` explains why.
        self._silent_polls = 0

    def should_restart(self) -> list[Path] | None:
        # `if changes`, not `is not None`: a change to a file the reload filter
        # rejects yields `[]`, which `BaseReload.run` treats as no change at
        # all. Reading it as one would skip supervision for that tick - and the
        # local stack mounts `media_data` inside the watched directory, so
        # ingestion writing a file is enough to produce a steady drip of them.
        changes = super().should_restart()
        if changes:
            return changes
        self._replace_a_dead_worker()
        self._replace_a_wedged_worker()
        return None

    def restart(self) -> None:
        """Replace the worker, and forget the beat the previous one left behind.

        Every replacement - a file change, a dead worker, a wedged one - arrives
        here, and every one of them starts a worker that has not beaten yet.
        Leaving the old worker's beat in the cell would have the new one judged
        on it and killed on the next poll.

        The cell is cleared *after* the replacement, not before. `Server.on_tick`
        awaits `callback_notify` before it checks `should_exit`, so a worker sent
        `SIGTERM` inside the second before its next beat is due gets one more
        tick and beats one last time. Clearing first would hand that beat to the
        replacement, which is then judged on it while it is still importing the
        application. `BaseReload.restart` joins the old worker before it spawns
        the new one, so by the time this line runs the last gasp has landed and
        there is nothing left to write the cell but the replacement - which
        cannot, until lifespan startup finishes seconds later.
        """
        super().restart()
        self._beat.value = NOT_YET_BEATEN

    def shutdown(self) -> None:
        """Stop the worker, and stop waiting on one that is never going to stop.

        `BaseReload.shutdown` sends `SIGTERM` and joins without a timeout, which
        for a worker whose event loop has stopped turning is a hang: the worker
        catches `SIGTERM` and acts on it *from the loop*, so Ctrl+C or
        `docker compose stop` blocks until the ten-second grace period runs out
        and Docker kills the container. This is not delegated for that reason,
        which costs the socket close and the log line below.

        Three cases, and the difference between the last two is the whole of
        #366:

        - **Judged wedged**, i.e. it beat and then went silent. Killed outright.
          There is one shot at this, so the verdict is the instantaneous one -
          `POLLS_BEFORE_WEDGED` cannot apply to a decision taken once, so a
          healthy worker whose host has just thawed is killed rather than
          drained. Dropping the requests in flight beats hanging the terminal,
          and it is the trade Docker's own `SIGKILL` makes ten seconds later.
        - **Beating.** `SIGTERM`, and `STOP_GRACE` to drain.
        - **Never beaten.** `_silent_for` answers `None` for a worker that has
          not beaten at all, because the first beat only lands once lifespan
          startup has finished - so a worker hung *before* it serves, on a
          Postgres that is not up or a `PREFECT_API_URL` that does not answer,
          is the one case the wedge verdict cannot see. It gets `SIGTERM` and a
          second, because it never started serving and so is holding nothing
          worth draining, and then the same `SIGKILL`.

        The escalation is not a timeout that hides a hang: it says which of the
        two it killed, so a worker that never ran its event loop is still
        reported as one rather than as a slow shutdown.

        What delegating also carried was `BaseReload.shutdown`'s Windows branch,
        which sets `should_exit` instead of terminating. It is not reproduced:
        this module is PID 1 of a Linux container and the entrypoint of
        `agenticos server run --reload`, and a branch nothing here can exercise
        is a branch that rots. On Windows the worker is terminated rather than
        asked, which is what `Multiprocess` does there anyway.
        """
        silent_for = self._silent_for()
        if silent_for is not None:
            logger.error(
                "Server process [%s] has not run its event loop for %.0fs. Killing it rather than waiting.",
                self.process.pid,
                silent_for,
            )
            self.process.kill()
        else:
            self.process.terminate()

        never_beaten = self._beat.value == NOT_YET_BEATEN
        grace = STOP_GRACE_BEFORE_THE_FIRST_BEAT if never_beaten else STOP_GRACE
        self.process.join(timeout=grace)
        if self.process.exitcode is None:
            if never_beaten:
                logger.error(
                    "Server process [%s] never ran its event loop and ignored SIGTERM for %.0fs. Killing it.",
                    self.process.pid,
                    grace,
                )
            else:
                logger.error(
                    "Server process [%s] did not finish draining in %.0fs. Killing it.",
                    self.process.pid,
                    grace,
                )
            self.process.kill()
            self.process.join()

        for sock in self.sockets:
            sock.close()
        logger.info("Stopping reloader process [%s]", self.pid)

    def _replace_a_dead_worker(self) -> None:
        """Reap a worker that is gone, and replace it if a signal took it.

        Reading `exitcode` is what clears the zombie: the property calls
        `Popen.poll()`, which is a `waitpid` with `WNOHANG`. It answers `None`
        while the worker is running.
        """
        exitcode = self.process.exitcode
        if exitcode is None or self.should_exit.is_set():
            # Nothing to do, or the reloader is on its way out and a fresh
            # worker would outlive the supervisor meant to stop it. This is the
            # same guard `Multiprocess.keep_subprocess_alive` opens with.
            return

        pid = self.process.pid
        if exitcode < 0:
            logger.error(
                "Server process [%s] died from signal %s. Starting a replacement.",
                pid,
                -exitcode,
            )
            # `restart` terminates, joins and respawns. Terminating a process
            # that has already exited is a no-op, so this is the whole job.
            self.restart()
            return

        if pid != self._reported_pid:
            self._reported_pid = pid
            logger.error(
                "Server process [%s] exited with code %s. Waiting for a file change.",
                pid,
                exitcode,
            )

    def _silent_for(self) -> float | None:
        """How long the worker's event loop has been silent, if that is a verdict.

        `None` means there is nothing to judge, which covers four cases and not
        only the obvious one: the check is switched off; the worker is not
        running, so a worker that exited on its own stays waiting for the file
        change that fixes it rather than being respawned onto the same
        traceback; the worker has not beaten yet, so a slow boot is not a wedge;
        or it beat recently enough.
        """
        if self._wedged_after <= 0 or self.process.exitcode is not None:
            return None

        beat = self._beat.value
        if beat == NOT_YET_BEATEN:
            return None

        # `time.time()`, matching the clock the beat is stamped with and the one
        # uvicorn gates the beat's cadence on (#1080). A monotonic verdict here
        # read a wall-clock stall - the loop still serving - as a wedge.
        silent_for = time.time() - beat
        return silent_for if silent_for >= self._wedged_after else None

    def _replace_a_wedged_worker(self) -> None:
        """Replace a worker that is running but whose event loop has stopped turning."""
        if self.should_exit.is_set():
            # The reloader is on its way out and a replacement would outlive the
            # supervisor meant to stop it - the same guard
            # `_replace_a_dead_worker` opens with, for the same reason. Stopping
            # a worker that is wedged is `shutdown`'s job, not this one's.
            return

        silent_for = self._silent_for()
        if silent_for is None:
            self._silent_polls = 0
            return

        self._silent_polls += 1
        if self._silent_polls < POLLS_BEFORE_WEDGED:
            return

        logger.error(
            "Server process [%s] has not run its event loop for %.0fs. Killing it and starting a replacement.",
            self.process.pid,
            silent_for,
        )
        # `SIGKILL`, and not the `SIGTERM` that `restart` would send on its own:
        # the worker catches `SIGTERM` and acts on it from the event loop, so a
        # wedged one never acts on it and the join inside `restart` would hang
        # here forever. Killing first makes that join the no-op it needs to be.
        self.process.kill()
        self.process.join()
        self.restart()


def wedged_after_from_environment() -> float:
    """Read `EVENT_LOOP_WEDGED_AFTER`, the one knob on the wedge check.

    Seconds without a beat before the worker is replaced; `0` switches the check
    off entirely, which is what a breakpoint needs. A value that is not a number
    raises rather than falling back to the default: a typo that silently
    restores 15 seconds is how somebody ends up debugging the supervisor.
    """
    return float(os.environ.get(WEDGED_AFTER_ENV_VAR, WEDGED_AFTER))


def run_reload_server(*, host: str, port: int) -> None:
    """Run the development server under `SupervisedReload`.

    The wiring is `uvicorn.main.run`'s own reload branch, with the supervisor
    swapped: bind the socket in the parent so a replacement worker inherits a
    port that never stopped being bound, and hand the worker the heartbeat it
    reports its event loop through.
    """
    beat: c_double = RawValue("d", NOT_YET_BEATEN)
    config = Config(
        APP,
        host=host,
        port=port,
        reload=True,
        ws=WS_PROTOCOL,
        callback_notify=EventLoopHeartbeat(beat),
        timeout_notify=BEAT_INTERVAL,
    )
    server = Server(config=config)
    SupervisedReload(
        config,
        target=server.run,
        sockets=[config.bind_socket()],
        beat=beat,
        wedged_after=wedged_after_from_environment(),
    ).run()


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8000, type=int, help="Port to bind to")
def main(host: str, port: int) -> None:
    """Run the development server with a supervised reloader."""
    run_reload_server(host=host, port=port)


if __name__ == "__main__":
    main()
