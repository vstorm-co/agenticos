"""Run one scenario against one backend and write what happened.

    python -m bench.driver --backend celery --scenario workflow --label celery-prefork-s1

The driver submits jobs through the backend's own client, samples every container
of the compose project once a second, and when the scenario is over writes
`results/<label>.json` (settings, timings, resource samples, Postgres counters) and
`results/<label>.events.csv` (every job and event) for `bench.report` to read.
"""

import argparse
import asyncio
import csv
import importlib
import json
import os
import random
import threading
import time
from typing import Any

import asyncpg
import docker

from bench import config, events, workload

BACKENDS = {
    "pgqueue": "bench.backends.pgqueue",
    "celery": "bench.backends.celery_app",
    "taskiq": "bench.backends.taskiq_app",
    "dramatiq": "bench.backends.dramatiq_app",
    "saq": "bench.backends.saq_app",
    "procrastinate": "bench.backends.procrastinate_app",
    "pgqueuer": "bench.backends.pgqueuer_app",
    "dbos": "bench.backends.dbos_app",
    "hatchet": "bench.backends.hatchet_app",
    "prefect-serve": "bench.backends.prefect_serve",
    "prefect-tasks": "bench.backends.prefect_tasks",
}

PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "tqbench")
RESULTS = os.environ.get("BENCH_RESULTS_DIR", "/results")


class Sampler(threading.Thread):
    """Every container in the project, once a second: CPU %, memory."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.client = docker.from_env()
        self.samples: list[dict[str, Any]] = []
        self.stop = threading.Event()

    def _one(self, container: Any) -> None:
        for stat in container.stats(stream=True, decode=True):
            if self.stop.is_set():
                return
            cpu = stat.get("cpu_stats", {})
            pre = stat.get("precpu_stats", {})
            cpu_delta = cpu.get("cpu_usage", {}).get("total_usage", 0) - pre.get("cpu_usage", {}).get(
                "total_usage", 0
            )
            sys_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
            cpus = cpu.get("online_cpus") or 1
            pct = (cpu_delta / sys_delta) * cpus * 100 if sys_delta > 0 else 0.0
            mem = stat.get("memory_stats", {})
            used = mem.get("usage", 0) - mem.get("stats", {}).get("inactive_file", 0)
            self.samples.append(
                {"t": time.time(), "container": container.name, "cpu": round(pct, 1), "mem_mb": round(used / 2**20, 1)}
            )

    def run(self) -> None:
        mine = self.client.containers.list(filters={"label": f"com.docker.compose.project={PROJECT}"})
        threads = [
            threading.Thread(target=self._one, args=(c,), daemon=True)
            for c in mine
            if "driver" not in c.name
        ]
        for thread in threads:
            thread.start()
        self.stop.wait()


async def _pg_counters(conn: asyncpg.Connection) -> dict[str, Any]:
    row = await conn.fetchrow(
        "SELECT sum(xact_commit) AS commits, sum(xact_rollback) AS rollbacks, "
        "sum(tup_inserted) AS inserted, sum(tup_updated) AS updated, sum(tup_deleted) AS deleted, "
        "pg_current_wal_lsn() AS lsn FROM pg_stat_database"
    )
    return dict(row)


async def _wait_done(conn: asyncpg.Connection, label: str, expected: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        finished = await conn.fetchval(
            "SELECT count(DISTINCT e.job_id) FROM bench_events e JOIN bench_jobs j USING (job_id) "
            "WHERE j.run_label = $1 AND e.event = 'finished' AND j.kind <> 'sweep'",
            label,
        )
        if finished >= expected:
            return True
        await asyncio.sleep(1)
    return False


async def scenario_workflow(submit: Any, conn: asyncpg.Connection, label: str, args: Any) -> int:
    """S1: `chains` workflow runs of `steps` sequential light steps each, all started at once."""
    firsts = [
        workload.new_job(label, "step", f"org-{i % 5}", chain_id=f"c{i}", step=0, extra={"steps": args.steps})
        for i in range(args.chains)
    ]
    await events.record_enqueued(conn, firsts)
    await asyncio.gather(*(submit(job) for job in firsts))
    return args.chains * args.steps


async def scenario_mix(submit: Any, conn: asyncpg.Connection, label: str, args: Any) -> int:
    """S2: for `duration` s, model calls (2-10 s waits) and PDF ingestion arrive as Poisson streams."""
    rng = random.Random(42)
    submitted = 0
    started = time.time()
    next_agent = started
    next_parse = started
    while time.time() - started < args.duration:
        now = time.time()
        batch = []
        while next_agent <= now:
            batch.append(workload.new_job(label, "agent", f"org-{rng.randrange(5)}", extra={"wait": rng.uniform(2, 10)}))
            next_agent += rng.expovariate(args.agent_rate)
        while next_parse <= now:
            batch.append(workload.new_job(label, "parse", f"org-{rng.randrange(5)}", extra={"doc": rng.randrange(6)}))
            next_parse += rng.expovariate(args.parse_rate)
        if batch:
            await events.record_enqueued(conn, batch)
            await asyncio.gather(*(submit(job) for job in batch))
            submitted += len(batch)
        await asyncio.sleep(0.05)
    return submitted


async def scenario_tenants(submit: Any, conn: asyncpg.Connection, label: str, args: Any) -> int:
    """S3: tenant A floods `flood` jobs at once; tenant B sends one a second; a worker is killed mid-flood."""
    flood = [workload.new_job(label, "burst", "org-flood", extra={"wait": 0.2}) for _ in range(args.flood)]
    await events.record_enqueued(conn, flood)
    for i in range(0, len(flood), 200):
        await asyncio.gather(*(submit(job) for job in flood[i : i + 200]))
    client = docker.from_env()
    workers = [
        c
        for c in client.containers.list(filters={"label": f"com.docker.compose.project={PROJECT}"})
        if c.labels.get("com.docker.compose.service", "").startswith("w-")
    ]
    started = time.time()
    killed = restarted = None
    submitted = len(flood)
    for i in range(args.trickle):
        job = workload.new_job(label, "burst", "org-small", extra={"wait": 0.2})
        await events.record_enqueued(conn, [job])
        await submit(job)
        submitted += 1
        elapsed = time.time() - started
        if args.kill and killed is None and elapsed >= args.kill_at:
            for worker in workers:
                worker.kill(signal="SIGKILL")
            killed = time.time()
        if killed is not None and restarted is None and time.time() - killed >= args.down_for:
            for worker in workers:
                worker.start()
            restarted = time.time()
        await asyncio.sleep(max(0.0, (i + 1) - (time.time() - started)))
    args.killed_at, args.restarted_at = killed, restarted
    return submitted


async def scenario_oom(submit: Any, conn: asyncpg.Connection, label: str, args: Any) -> int:
    """S4: one job eats memory until the kernel kills its worker; ordinary jobs keep coming.

    The driver stands in for a container restart policy: a worker that exits is
    started again three seconds later, for the whole scenario. What a safe engine
    does is give up on the job after its attempts; an unsafe one hands it out again
    for ever, and every hand-out kills a worker.
    """
    hog = workload.new_job(label, "hog", "org-hog")
    await events.record_enqueued(conn, [hog])
    await submit(hog)
    client = docker.from_env()
    started = time.time()
    deaths = oom_kills = 0
    exited_at: dict[str, float] = {}
    submitted = 0
    next_job = started
    while time.time() - started < args.duration:
        now = time.time()
        if now >= next_job and now - started < args.duration - 30:
            job = workload.new_job(label, "burst", "org-small", extra={"wait": 0.2})
            await events.record_enqueued(conn, [job])
            try:
                await submit(job)
            except Exception:
                pass  # a submit while every worker is down is the engine's broker to absorb
            submitted += 1
            next_job += 1
        for worker in client.containers.list(all=True, filters={"label": f"com.docker.compose.project={PROJECT}"}):
            if not worker.labels.get("com.docker.compose.service", "").startswith("w-"):
                continue
            if worker.status == "exited":
                if worker.id not in exited_at:
                    exited_at[worker.id] = now
                    deaths += 1
                    oom_kills += int(bool(worker.attrs["State"].get("OOMKilled")))
                elif now - exited_at[worker.id] >= 3:
                    worker.start()
                    del exited_at[worker.id]
        await asyncio.sleep(0.5)
    args.worker_deaths, args.oom_kills = deaths, oom_kills
    return submitted


async def scenario_probe(submit: Any, conn: asyncpg.Connection, label: str, args: Any) -> int:
    """One one-step job, submitted the moment the workers start: cold start plus first job."""
    job = workload.new_job(label, "step", "org-0", chain_id="probe", step=0, extra={"steps": 1})
    await events.record_enqueued(conn, [job])
    # A backend that registers on start (Prefect's deployment, Hatchet's workflow)
    # refuses a submission until it has: retried, since that wait is cold start too.
    deadline = time.time() + 300
    while True:
        try:
            await submit(job)
            return 1
        except Exception:
            if time.time() > deadline:
                raise
            await asyncio.sleep(1)


def _parse_docker_time(stamp: str) -> float:
    """Docker's RFC 3339 with nanoseconds, as epoch seconds."""
    from datetime import datetime

    head, _, rest = stamp.partition(".")
    fraction = rest.rstrip("Z")[:6]
    return datetime.fromisoformat(f"{head}.{fraction}+00:00").timestamp()


SCENARIOS = {
    "workflow": scenario_workflow,
    "mix": scenario_mix,
    "tenants": scenario_tenants,
    "probe": scenario_probe,
    "oom": scenario_oom,
}


async def main(args: Any) -> None:
    module = importlib.import_module(BACKENDS[args.backend])
    conn = await asyncpg.connect(config.POSTGRES_DSN)
    await events.ensure_schema(conn)
    if hasattr(module, "setup"):
        await module.setup()
    if args.scenario == "setup":
        await conn.close()
        return
    sampler = Sampler()
    sampler.start()
    before = await _pg_counters(conn)
    started = time.time()
    expected = await SCENARIOS[args.scenario](module.submit, conn, args.label, args)
    submitted_at = time.time()
    done = await _wait_done(conn, args.label, expected, args.timeout)
    ended = time.time()
    # Late sweeps and the scheduler's last tick are part of the picture too.
    await asyncio.sleep(2)
    after = await _pg_counters(conn)
    sampler.stop.set()
    wal = await conn.fetchval("SELECT pg_wal_lsn_diff($1, $2)", after["lsn"], before["lsn"])

    rows = await conn.fetch(
        "SELECT j.job_id, j.kind, j.tenant, j.chain_id, j.step, j.enqueued_at, e.event, e.at, e.worker "
        "FROM bench_jobs j LEFT JOIN bench_events e USING (job_id) WHERE j.run_label = $1 ORDER BY e.at",
        args.label,
    )
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, f"{args.label}.events.csv"), "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["job_id", "kind", "tenant", "chain_id", "step", "enqueued_at", "event", "at", "worker"])
        for row in rows:
            writer.writerow(list(row.values()))
    workers_started = []
    for container in docker.from_env().containers.list(
        filters={"label": f"com.docker.compose.project={PROJECT}"}
    ):
        if container.labels.get("com.docker.compose.service", "").startswith("w-"):
            stamp = container.attrs["State"]["StartedAt"]
            workers_started.append(_parse_docker_time(stamp))
    result = {
        "label": args.label,
        "workers_started_at": max(workers_started) if workers_started else None,
        "backend": args.backend,
        "variant": args.variant,
        "scenario": args.scenario,
        "settings": {k: v for k, v in vars(args).items() if isinstance(v, (int, float, str, bool, type(None)))},
        "concurrency": config.CONCURRENCY,
        "expected_jobs": expected,
        "completed": done,
        "started_at": started,
        "submitted_at": submitted_at,
        "ended_at": ended,
        "pg": {
            "commits": int(after["commits"] - before["commits"]),
            "rollbacks": int(after["rollbacks"] - before["rollbacks"]),
            "inserted": int(after["inserted"] - before["inserted"]),
            "updated": int(after["updated"] - before["updated"]),
            "deleted": int(after["deleted"] - before["deleted"]),
            "wal_bytes": int(wal),
        },
        "samples": sampler.samples,
    }
    with open(os.path.join(RESULTS, f"{args.label}.json"), "w") as handle:
        json.dump(result, handle)
    await conn.close()
    print(json.dumps({"label": args.label, "completed": done, "seconds": round(ended - started, 1)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True, choices=sorted(BACKENDS))
    parser.add_argument("--variant", default="")
    parser.add_argument("--scenario", required=True, choices=sorted(SCENARIOS) + ["setup"])
    parser.add_argument("--label", required=True)
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--chains", type=int, default=50)
    parser.add_argument("--steps", type=int, default=10)
    parser.add_argument("--duration", type=float, default=300)
    parser.add_argument("--agent-rate", type=float, default=2.0)
    parser.add_argument("--parse-rate", type=float, default=0.5)
    parser.add_argument("--flood", type=int, default=1000)
    parser.add_argument("--trickle", type=int, default=90)
    parser.add_argument("--kill", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--kill-at", type=float, default=20)
    parser.add_argument("--down-for", type=float, default=10)
    asyncio.run(main(parser.parse_args()))
