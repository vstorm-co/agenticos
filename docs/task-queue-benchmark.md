# The background-job benchmark

Until 1.9.0, every background job in AgenticOS ran on Prefect, which started a
new Python process for each run. On 18 October 2026 about 1,650 late runs piled
up on a host that was already losing CPU to steal, and the site went down. Before
replacing Prefect we ran ten engines, in seventeen configurations, through the
same workloads, measured the same way. This page covers what was measured,
what decided the choice and what the numbers do not show. The harness is
`experiments/task-queues` at commit `a239dfdd7` on the `spike/task-queue-benchmark`
branch, and every run's raw events are there too.

## What was compared { #what-was-compared }

| Variant | Engine | How it runs work |
|---|---|---|
| `prefect-serve` | Prefect 3 `serve`, limit 5; also tried with limit 20, and with Prefect's database on Postgres | A new Python process per run: AgenticOS before 1.9.0 |
| `prefect-tasks` | Prefect background tasks | A long-lived task worker |
| `celery-prefork`, `celery-threads` | Celery 5.6 and Beat, on Redis | A pool of processes, or of threads |
| `taskiq` | Taskiq on Redis Streams, with its scheduler | Async, one event loop per process |
| `dramatiq` | Dramatiq on Redis | Processes times threads |
| `saq` | SAQ on Redis | Async, one event loop per process |
| `procrastinate` | Procrastinate 3.10 on Postgres | Async, one event loop |
| `pgqueuer` | PgQueuer 1.6.0 on Postgres | Async, one event loop |
| `dbos`, `dbos-poll100` | DBOS 3.3.0 on Postgres; `-poll100` polls every 0.1 s instead of 1 s | Durable workflows |
| `hatchet`, `hatchet-fair` | Hatchet Lite on Postgres; `-fair` rotates between organizations | Async worker slots |
| `pgqueue`, `pgqueue-fair` | A plain Postgres queue: `SKIP LOCKED`, `LISTEN/NOTIFY`, leases | Async slots; `-fair` claims in turn across organizations |

Every task process first imports the real AgenticOS application. That import is
the cost Prefect paid on every run, so a benchmark without it would hide the cost
under study. Workers got 3 CPUs and 4 GB, the production host's share for
background work. A service an engine brings, such as Prefect's server or Hatchet's
engine, got its own limits, and its CPU and memory count as part of that engine's
cost.

## The scenarios { #the-scenarios }

- **`workflow`**: 50 runs of 10 sequential light steps, started at once. Each step
  makes a database round trip and queues the next one. It measures the engine's
  overhead per hop.
- **`mix`**: 5 minutes of model calls (2 a second, each waiting 2 to 10 s) and PDF
  parsing (one every 2 s, about 1 s of CPU each), plus the engine's own one-minute
  scheduled sweep. It measures how waiting work and CPU work share the workers,
  and how regular the schedule is.
- **`tenants`**: one organization queues 1,000 jobs at once, while another sends
  one job a second for 90 s. 20 s in, every worker is killed and started again 10 s
  later. It measures fairness, and what a crash costs.
- **`oom`**: one job grows its memory until the kernel kills its worker at 1 GB,
  while 210 ordinary jobs run beside it. A dead worker restarts after 3 s, the run
  is watched for 240 s, and every engine that has a retry limit is set to 3
  attempts.

Every task writes a `started` and a `finished` row, and the submitter an
`enqueued` row, to one Postgres table on one clock. Waits, gaps between steps, and
lost and duplicated jobs all come from those rows. The driver samples `docker
stats` once a second and reads Postgres's WAL counter before and after.

## Overhead per step { #overhead-per-step }

| Variant | Hop p50 | Hop p95 | Steps a second | Workers' peak memory |
|---|---|---|---|---|
| `taskiq` | 0.01 s | 0.02 s | 948 | 184 MB |
| `saq` | 0.01 s | 0.05 s | 818 | 564 MB |
| `dramatiq` | 0.02 s | 0.05 s | 1,338 | 583 MB |
| `pgqueue` | 0.03 s | 0.06 s | 506 | 288 MB |
| `pgqueuer` | 0.03 s | 0.08 s | 609 | 584 MB |
| `procrastinate` | 0.05 s | 0.06 s | 829 | 294 MB |
| `celery-prefork` | 0.05 s | 0.13 s | 485 | 1,294 MB |
| `hatchet` | 0.42 s | 0.82 s | 92 | 642 MB |
| `dbos-poll100` | 0.56 s | 1.11 s | 71 | 601 MB |
| `dbos` | 2.51 s | 3.12 s | 19 | 1,488 MB |
| `prefect-tasks` | 2.60 s | 6.82 s | 11 | 861 MB |
| `prefect-serve` | 218 s | 246 s | 0.2 | 1,736 MB |

`prefect-serve` did not finish: after 20 minutes it had completed 273 of the 500
steps. Raising its limit to 20 processes completed none, because 20 copies of the
application did not fit in 4 GB. From `dbos-poll100` down, every engine adds at
least half a second to every step of a workflow.

## Waiting work beside CPU work { #waiting-work-beside-cpu-work }

| Variant | Model call wait p50 | Model call wait p95 | Sweep's latest start |
|---|---|---|---|
| `taskiq` | 0.00 s | 0.01 s | 0.0 s |
| `pgqueue` | 0.01 s | 0.57 s | 0.0 s |
| `pgqueuer` | 0.01 s | 0.41 s | 0.6 s |
| `celery-threads` | 0.01 s | 0.04 s | 0.0 s |
| `hatchet` | 0.01 s | 0.27 s | 1.0 s |
| `procrastinate` | 0.01 s | 0.61 s | 29.4 s |
| `dbos` | 0.60 s | 1.48 s | 3.7 s |
| `prefect-tasks` | 0.10 s | 2.15 s | No sweep ran |
| `celery-prefork` | 148 s | 279 s | 63.1 s |

A model call spends nearly all its time waiting, so an engine that holds a whole
process for each call queues the next ones behind it: `celery-prefork` made calls
wait more than two minutes. Postgres itself used 3 to 6% of a CPU under
`pgqueue`, `pgqueuer` and `dbos`. DBOS wrote 2.3 times the WAL of `pgqueue`
(4.4 MB against 1.9 MB), because each of its workflows is several rows of
status and steps.

## A flood and a crash { #a-flood-and-a-crash }

| Variant | Lost | Duplicated | Small organization's wait p95 | Longest stall |
|---|---|---|---|---|
| `pgqueue` | 0 | 0 | 11.1 s | 17.5 s |
| `pgqueuer` | 0 | 0 | 11.0 s | 16.8 s |
| `taskiq` | 0 | 0 | 12.0 s | 17.5 s |
| `procrastinate` | 0 | 0 | 14.0 s | 20.4 s |
| `dbos-poll100` | 0 | 0 | 14.1 s | 18.3 s |
| `hatchet-fair` | 0 | 0 | 18.3 s | 24.0 s |
| `dbos` | 0 | 0 | 64.8 s | 18.8 s |
| `celery-prefork` | 0 | 0 | 50.3 s | 39.5 s |
| `saq` | 0 | 0 | 10.0 s | 551.5 s |
| `pgqueue-fair` | 0 | 137 | 10.1 s | 15.4 s |

No engine in the table lost a job; `prefect-tasks` still had two jobs unfinished
when its run timed out. Most engines ran one job a second time: the job a killed
worker had held, which any queue that hands a dead worker's job back has to do.
The `pgqueue-fair` prototype finished 137 jobs twice. Its round-robin claim is not
what shipped, and the duplicates are why. SAQ left jobs held by the killed workers
for more than nine minutes before taking them back.

## The job that kills its worker { #the-job-that-kills-its-worker }

This is the scenario that decided the choice. In an earlier production incident,
in another project on Celery, a job killed by the out-of-memory killer started
again and again, and its failure was never written down. The new queue had to
do neither.

| Variant | Starts of the job in 240 s | What happened | Ordinary jobs |
|---|---|---|---|
| `pgqueue` | 3 | Marked `dead` after its third attempt, with the failure recorded by the sweeper | All finished |
| `dbos` | 3 | `MAX_RECOVERY_ATTEMPTS_EXCEEDED`, recorded by the restarted process | All finished |
| `procrastinate` | 4 | Started again every minute; the documented stalled-job recipe counts attempts but limits nothing | All finished |
| `taskiq` | 5 | Started again every 60 s; the container never died, because its process manager restarts the child, so nothing outside could see it | All finished |
| `pgqueuer` | 8 | Taken again each time its heartbeat lapsed, without counting an attempt; 7 workers killed | All finished |

DBOS stopped at 3 too, but a second probe found the other forbidden outcome. When
a worker died holding three jobs and came back as a new container, as it does on
every deploy, the three were still `PENDING` under the old executor's id 120 s
later. The new process does not see them. DBOS Conductor detects a dead executor,
but it is licensed separately for commercial self-hosting. Celery was not run
through this scenario. Its documentation describes both failures: a message
returns without a delivery limit, or the job is lost silently.

## What shipped { #what-shipped }

1.9.0 replaced Prefect with the plain Postgres queue (`pgqueue`) and long-lived
asyncio workers. It counts an attempt when a job is claimed, not when it
finishes. Every worker also runs a rescuer: when one dies, the next to rescue -
a surviving worker, or the dead one restarted - finds its expired lease and
records the death, however the worker died. Oban, River and Solid Queue use the
same rule.

Ingestion also runs in child processes under a memory watchdog, so one heavy
document does not take its worker down. [Dispatching background work from a
request](architecture.md#dispatching-background-work-from-a-request) shows how
code queues a job, and [Scale beyond one host](scaling.md#more-workers) shows how
to add workers.

Per-organization fairness is left as it was measured. The plain queue gave the
small organization nearly the same p95 as the round-robin prototype (11.1 s
against 10.1 s), without its duplicates.

## What the numbers do not say { #what-the-numbers-do-not-say }

- **One machine.** All runs were on Docker Desktop on Apple silicon. Absolute
  numbers differ on a server. CPU steal on a shared host slows every process
  start, which only widens the gap for process-per-run.
- **One run for each cell.** The gaps between engines are wide enough for one run
  to rank them. Where two engines are close, such as `pgqueue` and `pgqueuer` on
  overhead, the tables do not say that either is faster.
- **Each engine in its usual configuration.** Every engine had the same CPU and
  memory budget, not the same concurrency, because a process pool and an event
  loop share no unit. Another setting can change a count, and the OOM counts
  especially.
- **A harness bug, corrected.** The first Procrastinate run of `tenants` lost a
  job, because the harness called a method that 3.10 no longer has. That was our
  bug, not Procrastinate's. The rerun above finished all 1,090 jobs.

## Run it again { #run-it-again }

```bash
# From the repository root, at the measured commit.
git switch --detach a239dfdd7
docker build -f backend/Dockerfile -t agenticos-backend:bench-base .
cd experiments/task-queues
docker build -t tqbench:latest .
./run.sh pgqueue oom          # one variant, one scenario, on a fresh project
./matrix.sh                   # every cell; a few hours
python3 -m bench.report results > results/TABLES.md
```

The [load suite](load-testing.md) answers a different question: how much one
deployment of AgenticOS can serve, rather than which engine should run its jobs.
