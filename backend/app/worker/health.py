"""The worker container's health check: did the last heartbeat reach the database recently?

    python -m app.worker.health

Exits 0 while the health file is younger than `MAX_AGE_SECONDS`. The worker
touches it only after a heartbeat that reached the database, so a worker whose
loop is stuck, or whose database is gone, reads unhealthy - which is the state a
container orchestrator can act on.
"""

import sys
import time
from pathlib import Path

from app.core.config import settings

MAX_AGE_SECONDS = 90.0
"""Six missed heartbeats at the default 15s: a restart in progress, not a slow tick."""


def healthy(path: Path, *, now: float, max_age: float = MAX_AGE_SECONDS) -> bool:
    try:
        return now - path.stat().st_mtime < max_age
    except FileNotFoundError:
        return False


def main() -> int:
    return 0 if healthy(Path(settings.WORKER_HEALTH_FILE), now=time.time()) else 1


if __name__ == "__main__":  # pragma: no cover - the container's probe
    sys.exit(main())
