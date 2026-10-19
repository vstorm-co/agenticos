"""A queue in Postgres itself: `SKIP LOCKED` claims, `LISTEN/NOTIFY` wake-ups, leases.

The shape #1925's dispatch outbox already has, generalised: a row per job, claimed
by one worker under a lease it renews while it works. A worker killed mid-job leaves
its lease to lapse, and the next claim takes the job again - at-least-once, like the
outbox. `NOTIFY` only shortens the wait; every worker also polls, so a missed
notification (a reconnect, a restart) costs a second, not the job.

`BENCH_FAIR=1` claims round-robin across tenants instead of oldest-first: the next
job comes from the tenant served longest ago, so one tenant's flood cannot starve
another's single job.
"""

import asyncio
import json
import os
import time
from typing import Any

import asyncpg

from bench import config, workload
from bench import heavy as _heavy  # noqa: F401 - the real application's import cost

LEASE_SECONDS = 30
# Attempts a job may have before it is left dead; 0 keeps retrying for ever. Counted
# at claim, so a job that kills its worker spends one too.
MAX_ATTEMPTS = int(os.environ.get("BENCH_MAX_ATTEMPTS", "0"))
FAIR = os.environ.get("BENCH_FAIR", "0") == "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS pgq_jobs (
    id bigserial PRIMARY KEY,
    tenant text NOT NULL,
    payload jsonb NOT NULL,
    locked_until timestamptz,
    attempts int NOT NULL DEFAULT 0,
    done boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS pgq_ready ON pgq_jobs (id) WHERE NOT done;
CREATE TABLE IF NOT EXISTS pgq_tenants (tenant text PRIMARY KEY, last_claimed timestamptz);
"""

_CLAIM_FIFO = """
UPDATE pgq_jobs SET locked_until = now() + make_interval(secs => $1), attempts = attempts + 1
WHERE id = (
    SELECT id FROM pgq_jobs
    WHERE NOT done AND (locked_until IS NULL OR locked_until < now())
      AND ($2 = 0 OR attempts < $2)
    ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
)
RETURNING id, tenant, payload
"""

# The head job of every tenant with work, then the tenant served longest ago.
_CLAIM_FAIR = """
WITH heads AS (
    SELECT DISTINCT ON (tenant) id, tenant FROM pgq_jobs
    WHERE NOT done AND (locked_until IS NULL OR locked_until < now())
      AND ($2 = 0 OR attempts < $2)
    ORDER BY tenant, id
), pick AS (
    SELECT h.id FROM heads h LEFT JOIN pgq_tenants t USING (tenant)
    ORDER BY t.last_claimed NULLS FIRST, h.id
    LIMIT 1
), locked AS (
    SELECT j.id FROM pgq_jobs j JOIN pick USING (id) FOR UPDATE OF j SKIP LOCKED
)
UPDATE pgq_jobs SET locked_until = now() + make_interval(secs => $1), attempts = attempts + 1
WHERE id = (SELECT id FROM locked)
RETURNING id, tenant, payload
"""


async def _conn() -> asyncpg.Connection:
    return await asyncpg.connect(config.POSTGRES_DSN)


_submit_pool: asyncpg.Pool | None = None


async def submit(job: dict[str, Any]) -> None:
    global _submit_pool
    if _submit_pool is None:
        _submit_pool = await asyncpg.create_pool(config.POSTGRES_DSN, min_size=1, max_size=4)
    async with _submit_pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO pgq_jobs (tenant, payload) VALUES ($1, $2)", job["tenant"], json.dumps(job)
        )
        await conn.execute("NOTIFY pgq")


async def setup() -> None:
    conn = await _conn()
    try:
        await conn.execute(SCHEMA)
    finally:
        await conn.close()


async def _claim(pool: asyncpg.Pool) -> tuple[int, dict[str, Any]] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_CLAIM_FAIR if FAIR else _CLAIM_FIFO, LEASE_SECONDS, MAX_ATTEMPTS)
        if row is None:
            return None
        if FAIR:
            await conn.execute(
                "INSERT INTO pgq_tenants (tenant, last_claimed) VALUES ($1, now()) "
                "ON CONFLICT (tenant) DO UPDATE SET last_claimed = now()",
                row["tenant"],
            )
        return row["id"], json.loads(row["payload"])


async def _slot(pool: asyncpg.Pool, wake: asyncio.Event) -> None:
    while True:
        claimed = await _claim(pool)
        if claimed is None:
            wake.clear()
            try:
                await asyncio.wait_for(wake.wait(), timeout=1.0)
            except TimeoutError:
                pass
            continue
        job_id, job = claimed
        await workload.run(job, submit)
        await pool.execute("UPDATE pgq_jobs SET done = true WHERE id = $1", job_id)


async def _scheduler(pool: asyncpg.Pool) -> None:
    """Fire the sweep on the leader only: an advisory lock decides which worker that is."""
    async with pool.acquire() as conn:
        while not await conn.fetchval("SELECT pg_try_advisory_lock(424242)"):
            await asyncio.sleep(5)
        next_tick = time.time()
        while True:
            next_tick += config.SWEEP_SECONDS
            await asyncio.sleep(max(0.0, next_tick - time.time()))
            job = workload.new_job(config.RUN_LABEL, "sweep", "system")
            await workload._record_child(job)
            await submit(job)


async def serve() -> None:
    await setup()
    pool = await asyncpg.create_pool(config.POSTGRES_DSN, min_size=2, max_size=config.CONCURRENCY + 4)
    wake = asyncio.Event()
    listener = await _conn()
    await listener.add_listener("pgq", lambda *_: wake.set())
    tasks = [asyncio.create_task(_slot(pool, wake)) for _ in range(config.CONCURRENCY)]
    tasks.append(asyncio.create_task(_scheduler(pool)))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(serve())
