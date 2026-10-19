# Task-queue benchmark

Which engine should run AgenticOS's background work once workflows (#1925) multiply
it? This directory runs the same workloads against every candidate and measures them
the same way. The findings, with the method and every figure, are in
[report/index.html](report/index.html), a self-contained page; the issue is #2219.

## What is compared

| Variant | Engine | How it runs work |
|---|---|---|
| `prefect-serve` | Prefect 3 `serve`, limit 5 | a new Python process per run - **AgenticOS today** |
| `prefect-serve-20` | the same, limit 20 | more concurrent processes |
| `prefect-serve-pg` | the same, Prefect's database on Postgres | #2212 |
| `prefect-tasks` | Prefect background tasks | a long-lived task worker |
| `celery-prefork` | Celery 5.6 + Beat, Redis | a fixed pool of processes |
| `celery-threads` | Celery 5.6 + Beat, Redis | a pool of threads, an event loop each |
| `taskiq` | Taskiq + Redis Streams + its scheduler | async, a loop per process |
| `dramatiq` | Dramatiq + Redis, AsyncIO middleware | processes x threads |
| `saq` | SAQ on Redis | async, a loop per process |
| `procrastinate` | Procrastinate on Postgres | async, one loop |
| `hatchet` / `hatchet-fair` | Hatchet (hatchet-lite on Postgres) | async worker slots; `-fair` adds `GROUP_ROUND_ROBIN` per tenant |
| `pgqueue` / `pgqueue-fair` | a plain Postgres queue (`SKIP LOCKED`, `LISTEN/NOTIFY`, leases) | async slots; `-fair` claims round-robin across tenants |

Every task process imports the real AgenticOS application first (`bench/heavy.py`):
that import is what Prefect's process-per-run pays on every run, so a benchmark
without it would hide the cost under study.

## The three scenarios

1. **`workflow`** - 50 runs of 10 sequential light steps, started at once. Each step
   does a database round trip and submits the next, as the #1925 dispatcher does.
   Measures the engine's overhead per hop.
2. **`mix`** - 5 minutes of Poisson arrivals: model calls (2 req/s, each waiting 2-10 s)
   and PDF ingestion (0.5 req/s, real PyMuPDF parsing, ~1 s of CPU), plus the
   engine's own one-minute scheduled sweep. Measures how waiting work and CPU work
   share the workers, and how regular the scheduler is.
3. **`tenants`** - one organization floods 1,000 jobs at once; another sends one job
   a second for 90 s; 20 s in, every worker is `SIGKILL`ed and started again 10 s
   later. Measures fairness (the small organization's wait) and what a crash costs
   (lost, duplicated and re-executed jobs, and the longest stall).

## The budget

Workers get 3 CPUs and 4 GB, the production VPS's share for background work. The
services an engine brings - Prefect's server, Hatchet's engine - get their own
limits, and are measured: their CPU and memory are part of the engine's cost.
Postgres (2 CPUs, 1 GB) and Valkey (1 CPU, 512 MB) are shared.

## How it is measured

Every task writes `started` and `finished` rows, and the submitter an `enqueued` row,
to one Postgres table on one clock. Queue wait, run time, the gap between workflow
steps, lost work (never finished) and duplicate work (finished twice) come from
those rows. The driver samples `docker stats` for every container once a second and
reads Postgres's commit and WAL counters before and after.

## Running it

```bash
# The worker image: the real backend plus every engine.
docker build -f backend/Dockerfile -t agenticos-backend:bench-base .   # from the repo root
cd experiments/task-queues
docker build -t tqbench:latest .

./run.sh hatchet workflow     # one variant, one scenario, on a fresh project
./matrix.sh                   # everything; a few hours
python3 -m bench.report results > results/TABLES.md
python3 -m bench.site results report/template.html > report/index.html
```

## Limits of the method

- One machine (Docker Desktop on Apple silicon). Absolute numbers will differ on the
  VPS; the comparison between engines is the point. CPU steal on the VPS (#2214)
  makes every process start slower, which only widens the gap for process-per-run.
- Each engine runs in its idiomatic production configuration under the same CPU and
  memory budget, not with identical concurrency: a process pool and an async loop
  do not have a common unit. The report states each configuration.
- One run per cell. The spread between engines is wide enough for one run to rank
  them; where two are close, the report says so rather than picking a winner.
