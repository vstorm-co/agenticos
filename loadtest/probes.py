"""What the machine was doing while the run happened.

Latency without resource numbers describes a symptom and not a cause: a p99 that
climbed during the burst is a different finding depending on whether the worker
was at ninety per cent of a core, waiting on a connection, or neither. So a run
samples three things beside its own requests.

Every probe is **optional and says so**. A run on a machine where the API is in a
container the driver cannot see, or against a database it holds no credential
for, is still a run - it reports the samples it has and names the ones it could
not take, rather than refusing to start or, worse, printing zeros.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ResourceSample:
    """One moment of the process under test."""

    at: float
    cpu_percent: float
    rss_mb: float


@dataclass(frozen=True)
class PoolSample:
    """One moment of the database's own view of its callers."""

    at: float
    connections: int
    active: int


@dataclass
class Probes:
    """What was sampled, and what could not be."""

    resources: list[ResourceSample] = field(default_factory=list)
    pools: list[PoolSample] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)

    def note_unavailable(self, what: str) -> None:
        if what not in self.unavailable:
            self.unavailable.append(what)


def cpu_seconds(text: str) -> float | None:
    """`ps`'s cumulative CPU time, as seconds.

    Two spellings to read: procps prints `[[DD-]HH:]MM:SS` and BSD `ps` on macOS
    prints `MM:SS.ss`. Both are parsed the same way - split on colons, take the
    day part off the front if there is one - because the difference is only where
    the sub-second digits are.
    """
    raw = text.strip()
    if not raw:
        return None
    days = 0.0
    if "-" in raw:
        head, _, raw = raw.partition("-")
        try:
            days = float(head)
        except ValueError:
            return None
    clock = 0.0
    try:
        for part in raw.split(":"):
            clock = clock * 60 + float(part)
    except ValueError:
        return None
    return days * 86400 + clock


def process_snapshot(pid: int) -> tuple[float, float] | None:
    """Cumulative CPU seconds and resident megabytes for one process, through `ps`.

    `ps` rather than `psutil`: this harness adds no dependency to the backend,
    and what is wanted here is a number a person could have read themselves.

    **Cumulative time, not `%cpu`.** procps defines `%CPU` as CPU time over the
    process's whole lifetime and says outright that it is not real utilization,
    so sampling it repeatedly gives a lifetime average that flattens exactly the
    short saturation a burst is meant to produce. The caller differences these
    against the wall clock instead, which is utilization.
    """
    binary = shutil.which("ps")
    if binary is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - a literal argv, no shell
            [binary, "-o", "time=,rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    fields = result.stdout.split()
    if len(fields) != 2:
        return None
    seconds = cpu_seconds(fields[0])
    if seconds is None:
        return None
    try:
        return seconds, float(fields[1]) / 1024
    except ValueError:
        return None


_POOL_QUERY = """
SELECT count(*)::int AS total,
       count(*) FILTER (WHERE state = 'active')::int AS active
FROM pg_stat_activity
WHERE datname = current_database()
"""
"""What the database says about its own callers.

Asked of Postgres rather than of the application because the application does not
publish it: there is no metrics endpoint here, and a pool saturating is exactly
the thing that stops the application answering questions about itself. Opt-in
through `--database-url`, so a driver with no credential is a driver that cannot
be pointed at a production database by accident.
"""


async def pool_snapshot(connection: object) -> PoolSample | None:
    """Connections open on this database, and how many are executing."""
    fetch = getattr(connection, "fetchrow", None)
    if fetch is None:
        return None
    try:
        row = await fetch(_POOL_QUERY)
    except Exception:
        return None
    if row is None:
        return None
    return PoolSample(at=0.0, connections=int(row["total"]), active=int(row["active"]))


async def sample_forever(
    probes: Probes,
    *,
    pid: int | None,
    database_url: str | None,
    started: float,
    every_seconds: float,
    stop: asyncio.Event,
) -> None:
    """Sample the process and the database on a fixed interval until the run stops.

    A task rather than a thread, and it does almost nothing: `ps` is a few
    milliseconds, the pool query is one row, and this wakes twice a second at
    most - so the measurement's own cost stays far below what it measures.

    Each probe is missed independently. A run with no `--api-pid` still records
    pool saturation, and a run with no `--database-url` still records CPU.
    """
    connection = await _connect(probes, database_url)
    if pid is None:
        probes.note_unavailable("process CPU and memory: pass --api-pid")
    loop = asyncio.get_running_loop()
    previous: tuple[float, float] | None = None
    try:
        while not stop.is_set():
            at = loop.time() - started
            if pid is not None:
                sample = await asyncio.to_thread(process_snapshot, pid)
                if sample is None:
                    probes.note_unavailable(f"process CPU and memory: pid {pid} is not readable")
                    pid = None
                else:
                    used, rss = sample
                    if previous is not None:
                        before_at, before_used = previous
                        span = at - before_at
                        if span > 0:
                            probes.resources.append(
                                ResourceSample(
                                    at=at,
                                    cpu_percent=(used - before_used) / span * 100,
                                    rss_mb=rss,
                                )
                            )
                    else:
                        # The first reading has nothing to difference against, so
                        # it contributes memory only - recording it with a zero
                        # CPU would put a dip in the series that never happened.
                        probes.resources.append(ResourceSample(at=at, cpu_percent=-1.0, rss_mb=rss))
                    previous = (at, used)
            if connection is not None:
                pool = await pool_snapshot(connection)
                if pool is None:
                    probes.note_unavailable("database connections: the query was refused")
                    connection = None
                else:
                    probes.pools.append(
                        PoolSample(at=at, connections=pool.connections, active=pool.active)
                    )
            try:
                await asyncio.wait_for(stop.wait(), timeout=every_seconds)
            except TimeoutError:
                continue
    finally:
        close = getattr(connection, "close", None)
        if close is not None:
            await close()


async def _connect(probes: Probes, database_url: str | None) -> object | None:
    """An asyncpg connection for the pool probe, or None with the reason recorded."""
    if database_url is None:
        probes.note_unavailable("database connections: pass --database-url")
        return None
    try:
        import asyncpg
    except ImportError:  # pragma: no cover - asyncpg is a backend dependency
        probes.note_unavailable("database connections: asyncpg is not installed")
        return None
    try:
        return await asyncpg.connect(database_url)
    except Exception as failure:
        probes.note_unavailable(f"database connections: {type(failure).__name__}")
        return None


def peak_pool(samples: list[PoolSample]) -> tuple[int, int]:
    """The most connections the database held, and the most executing at once."""
    if not samples:
        return 0, 0
    return (
        max(sample.connections for sample in samples),
        max(sample.active for sample in samples),
    )


def summarize(samples: list[ResourceSample]) -> tuple[float, float, float]:
    """Peak CPU, peak resident memory and the memory it finished on.

    The last of the three is the one that answers "did this leak": a run whose
    memory climbed through the burst and stayed there afterwards looks identical
    to one that recovered, in every number except this.

    A CPU of `-1` marks the first reading, which had nothing to difference
    against; it is skipped rather than counted as an idle moment.
    """
    if not samples:
        return 0.0, 0.0, 0.0
    measured = [sample.cpu_percent for sample in samples if sample.cpu_percent >= 0]
    return (
        max(measured) if measured else 0.0,
        max(sample.rss_mb for sample in samples),
        samples[-1].rss_mb,
    )
