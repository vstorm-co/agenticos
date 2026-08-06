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

**This module is its own entrypoint** - `python -m cli.reload_supervisor` - and
imports nothing beyond uvicorn and click on purpose. Reaching it through
`cli.commands` instead would pull `app.main` into the reloader, and the reloader
never serves a request: measured in `agenticos_backend:dev`, importing
`cli.commands` peaks at 464 MB against 28 MB for uvicorn alone. Handing the
process that exists to survive an out-of-memory kill another 436 MB to be killed
for would be an odd way to fix this.
"""

import logging
from collections.abc import Callable
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

logger = logging.getLogger("uvicorn.error")


class SupervisedReload(ChangeReload):
    """A `--reload` reloader that also notices a worker that died.

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
    ) -> None:
        super().__init__(config, target, sockets)
        # The pid whose ordinary exit has already been reported, so the "waiting
        # for a change" line is written once rather than on every poll.
        self._reported_pid: int | None = None

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
        return None

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


def run_reload_server(*, host: str, port: int) -> None:
    """Run the development server under `SupervisedReload`.

    The wiring is `uvicorn.main.run`'s own reload branch, with the supervisor
    swapped: bind the socket in the parent so a replacement worker inherits a
    port that never stopped being bound.
    """
    config = Config(APP, host=host, port=port, reload=True, ws=WS_PROTOCOL)
    server = Server(config=config)
    SupervisedReload(config, target=server.run, sockets=[config.bind_socket()]).run()


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8000, type=int, help="Port to bind to")
def main(host: str, port: int) -> None:
    """Run the development server with a supervised reloader."""
    run_reload_server(host=host, port=port)


if __name__ == "__main__":
    main()
