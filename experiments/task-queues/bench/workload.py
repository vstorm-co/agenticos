"""What a task does - identical for every backend.

* `step`: one workflow node - a database round trip and a sliver of CPU, then the
  next step of its chain is submitted, the way the #1925 dispatcher advances a graph.
* `agent`: a model call, which is waiting: 2-10 s on an `await`, then a write.
* `parse`: document ingestion - PyMuPDF extracting every page of a real PDF, which is
  CPU, then a write.
* `sweep`: a scheduled tick - one query.
* `burst`: one tenant's flood item - a short wait.

`submit_next` is the backend's own submit, handed in, so a chain advances through
the same path a client uses.
"""

import asyncio
import glob
import hashlib
import json
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

from bench import config, events

Submit = Callable[[dict[str, Any]], Awaitable[None]]


def new_job(
    run_label: str,
    kind: str,
    tenant: str,
    *,
    chain_id: str | None = None,
    step: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job_id = f"{run_label}:{kind}:{tenant}:{chain_id or ''}:{step if step is not None else ''}:{os.urandom(4).hex()}"
    return {
        "job_id": job_id,
        "run_label": run_label,
        "kind": kind,
        "tenant": tenant,
        "chain_id": chain_id,
        "step": step,
        "enqueued_at": time.time(),
        **(extra or {}),
    }


async def _record_child(job: dict[str, Any]) -> None:
    pool = await events._pool()
    await pool.execute(
        "INSERT INTO bench_jobs (job_id, run_label, kind, tenant, chain_id, step, enqueued_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (job_id) DO NOTHING",
        job["job_id"],
        job["run_label"],
        job["kind"],
        job["tenant"],
        job.get("chain_id"),
        job.get("step"),
        job["enqueued_at"],
    )


def _pdfs() -> list[str]:
    return sorted(glob.glob(os.path.join(config.SAMPLES_DIR, "*.pdf")))


def _parse_pdf(path: str) -> str:
    import pymupdf

    with pymupdf.open(path) as document:
        text = "".join(page.get_text() for page in document)
    return hashlib.sha256(text.encode()).hexdigest()


async def run(job: dict[str, Any], submit_next: Submit | None = None) -> None:
    """Do `job`'s work between its `started` and `finished` events."""
    job_id = job["job_id"]
    await events.mark(job_id, "started")
    kind = job["kind"]
    if kind == "step":
        pool = await events._pool()
        await pool.execute("SELECT pg_sleep(0)")
        hashlib.sha256(json.dumps(job).encode()).hexdigest()
        steps = int(job.get("steps", 10))
        step = int(job["step"])
        if step + 1 < steps and submit_next is not None:
            child = new_job(
                job["run_label"],
                "step",
                job["tenant"],
                chain_id=job["chain_id"],
                step=step + 1,
                extra={"steps": steps},
            )
            await _record_child(child)
            await submit_next(child)
    elif kind == "agent":
        await asyncio.sleep(float(job.get("wait", 5.0)))
    elif kind == "parse":
        pdfs = _pdfs()
        path = pdfs[int(job.get("doc", 0)) % len(pdfs)]
        # Parsing is CPU and blocks the loop, exactly as a parser called inline does.
        # Several passes stand in for the chunking a real ingestion does after it.
        for _ in range(int(job.get("passes", 6))):
            _parse_pdf(path)
    elif kind == "sweep":
        pool = await events._pool()
        await pool.fetchval("SELECT count(*) FROM bench_jobs WHERE run_label = $1", job["run_label"])
    elif kind == "burst":
        await asyncio.sleep(float(job.get("wait", 0.2)))
    await events.mark(job_id, "finished")


async def sweep() -> None:
    """What a backend's scheduler fires: a sweep job made and run on the spot.

    A scheduled tick has no submitter, so it records itself; its `enqueued_at` is
    the moment the scheduler's tick reached the worker. The driver measures the
    scheduler by the gaps between consecutive ticks, not by queue wait.
    """
    job = new_job(config.RUN_LABEL, "sweep", "system")
    await _record_child(job)
    await run(job)
