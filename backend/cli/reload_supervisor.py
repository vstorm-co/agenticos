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

- **Killed by a signal** (`exitcode < 0`, so `-9` for the OOM killer). The code
  is fine and nobody is coming to edit it. Reap and start a replacement.
- **Exited on its own** (`exitcode >= 0`). The application raised on import or
  called `sys.exit`; respawning would loop on the same traceback forever. Reap,
  say so once, and wait for the file change that fixes it - which is the whole
  reason `--reload` exists.

Either way the process is reaped, so the zombies are gone in both cases.
"""

import logging
from pathlib import Path
from socket import socket
from typing import Final

from uvicorn import Config, Server
from uvicorn.supervisors import ChangeReload

# uvicorn's `auto` picks the legacy websockets implementation, which fails the
# handshake against websockets >=14 with an HTTP 500. The dashboard chat is a
# WebSocket, so `auto` means no chat at all. Every compose file passes this for
# the same reason; the development server reads it from here.
WS_PROTOCOL: Final = "websockets-sansio"

APP: Final = "app.main:app"

logger = logging.getLogger("uvicorn.error")


class SupervisedReload(ChangeReload):
    """A `--reload` reloader that also notices a worker the kernel killed.

    `ChangeReload` polls for changes with a timeout rather than blocking
    forever, so overriding `should_restart` is enough to get a periodic tick:
    `WatchFilesReload` passes `yield_on_timeout=True` with watchfiles' 5s
    `rust_timeout`, and the fallback `StatReload` polls at `reload_delay`.
    Detection therefore costs at most about five seconds, against the three
    failed health checks - ninety seconds - that a container restart would take.
    """

    def __init__(self, config: Config, target: object, sockets: list[socket]) -> None:
        super().__init__(config, target, sockets)
        # The pid whose ordinary exit has already been reported, so the "waiting
        # for a change" line is written once rather than on every poll.
        self._reported_pid: int | None = None

    def should_restart(self) -> list[Path] | None:
        changes = super().should_restart()
        if changes is not None:
            return changes
        self._replace_a_killed_worker()
        return None

    def _replace_a_killed_worker(self) -> None:
        """Reap a worker that is gone, and replace it if it was killed.

        Reading `exitcode` is what clears the zombie: the property calls
        `Popen.poll()`, which is a `waitpid` with `WNOHANG`. It answers `None`
        while the worker is running.
        """
        exitcode = self.process.exitcode
        if exitcode is None:
            return

        pid = self.process.pid
        if exitcode < 0:
            logger.error(
                "Server process [%s] was killed by signal %s. Starting a replacement.",
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
