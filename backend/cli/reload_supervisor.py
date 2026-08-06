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
`Server.on_tick` every `timeout_notify` seconds, which is the integration point
systemd's watchdog uses. The callback stamps `time.monotonic()` into a shared
cell; the supervisor reads the cell on the same quiet poll as everything else,
and replaces a worker whose loop has not turned for `WEDGED_AFTER` seconds.

Three properties of that choice are the reason for it:

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
  hung.

**What this does not cover**, deliberately:

- **A worker that wedges before it serves.** `main_loop` - and so the first beat
  - starts only once lifespan startup has finished, so a worker hung on a
  database connect at boot never beats and is never judged. Judging it would
  mean a startup grace period long enough to be meaningless on a cold container.
- **The dev and production stacks.** Neither runs this module: `docker-compose-dev.yml`
  is a single unsupervised uvicorn and `docker-compose-prod.yml` is `--workers`,
  where uvicorn's own `Multiprocess` pings over the pipe described above.
- **A debugger.** A breakpoint blocks the event loop and is indistinguishable
  from a deadlock by construction, so 15 seconds on one wedges the worker and it
  is replaced. `RELOAD_WEDGED_AFTER=0` turns the whole check off.

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
from multiprocessing import Value
from pathlib import Path
from socket import socket
from typing import TYPE_CHECKING, Final

import click
from uvicorn import Config, Server

# The reload supervisor uvicorn's own `main.run` uses: `WatchFilesReload`, or
# `StatReload` where watchfiles is missing. `uvicorn[standard]` ships watchfiles.
from uvicorn.supervisors import ChangeReload

if TYPE_CHECKING:
    # Generic to the type checker and a plain class at runtime, so every
    # annotation of it has to be quoted.
    from multiprocessing.sharedctypes import Synchronized

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
# timer callback in milliseconds - it is blocked, stopped or deadlocked. The
# supervisor notices within `WEDGED_AFTER` plus one poll, so about twenty
# seconds, against the ninety a container health check takes to reach a verdict
# nothing acts on.
WEDGED_AFTER: Final = 15.0

# Seconds without a beat before a worker is replaced, `0` to switch the check
# off - which is what somebody sitting on a breakpoint wants, a stopped event
# loop being indistinguishable from a deadlock.
WEDGED_AFTER_ENV_VAR: Final = "RELOAD_WEDGED_AFTER"

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
    """

    def __init__(self, beat: "Synchronized[float]") -> None:
        self._beat = beat

    async def __call__(self) -> None:
        self._beat.value = time.monotonic()


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
        beat: "Synchronized[float]",
        wedged_after: float = WEDGED_AFTER,
    ) -> None:
        super().__init__(config, target, sockets)
        # The pid whose ordinary exit has already been reported, so the "waiting
        # for a change" line is written once rather than on every poll.
        self._reported_pid: int | None = None
        self._beat = beat
        self._wedged_after = wedged_after

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
        """
        self._beat.value = NOT_YET_BEATEN
        super().restart()

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

    def _replace_a_wedged_worker(self) -> None:
        """Replace a worker that is running but whose event loop has stopped turning.

        Judged only on a worker that is still running and has beaten at least
        once: a worker that has exited is `_replace_a_dead_worker`'s decision,
        and one that exited on its own is deliberately waiting for a file change
        rather than for a supervisor to respawn it onto the same traceback.
        """
        if self._wedged_after <= 0 or self.should_exit.is_set():
            # Switched off, or the reloader is on its way out and a replacement
            # would outlive the supervisor meant to stop it - the same guard
            # `_replace_a_dead_worker` opens with, for the same reason.
            return

        if self.process.exitcode is not None:
            return

        beat = self._beat.value
        if beat == NOT_YET_BEATEN:
            return

        silent_for = time.monotonic() - beat
        if silent_for < self._wedged_after:
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
    """Read `RELOAD_WEDGED_AFTER`, the one knob on the wedge check.

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
    beat: Synchronized[float] = Value("d", NOT_YET_BEATEN)
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
