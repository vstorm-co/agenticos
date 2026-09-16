# Load and resilience run — 2026-09-16, pool raised

- **Machine** — macOS-26.5-arm64-arm-64bit · arm64 · Python 3.12.9
- **Topology** — one uvicorn worker on the host with DB_POOL_SIZE=20 and DB_MAX_OVERFLOW=30 (50 connections), Postgres 17 + pgvector and Redis in containers, Prefect server and runner on the host, the load stub model local; RATE_LIMIT_RUN_PER_MINUTE raised so the limiter does not bound the experiment
- **Duration** — 346s over 4 phases
- **Requests** — 4740 offered, 11 failed

## The workload

| Workload | Share | What it is |
|---|---|---|
| `api_read` | 45% | Authenticated list reads - agents, runs, conversations. The console's own traffic and the bulk of any deployment's request count. |
| `chat_stream` | 20% | A chat turn over the WebSocket, streamed. One in five of these is cancelled part-way, because a person changing their mind mid-answer is ordinary and the socket teardown is what it exercises. |
| `agent_run` | 15% | POST /agents/{id}/run - the non-streaming API path another system uses. Same runner, same budget check, same rows, no socket. |
| `rag_query` | 12% | Retrieval against a seeded collection: one embedding, one vector search. |
| `ingest` | 5% | A small document uploaded into the collection. Rarer than the rest by a long way, and the most expensive thing in the mix per request. |
| `trigger_fire` | 3% | A webhook firing a routine. What is measured is admission - the run it dispatches belongs to the worker, and this suite does not claim its latency. |

| Phase | Seconds | Offered per second | Why |
|---|---|---|---|
| `ramp` | 60 | 4 | Arrival climbs to the sustained rate, so a cold cache is not measured as steady state. |
| `sustain` | 180 | 12 | The number every threshold is judged against. Long enough for a pool to settle. |
| `burst` | 45 | 36 | Three times the sustained rate, which is what a scheduled fan-out looks like. |
| `recover` | 60 | 12 | Back to the sustained rate. A platform that recovers and one that stays degraded look identical during the burst and different here. |

## The sustained phase

Every threshold is judged against this one.

Throughput: **12.0 requests a second** completed.

| Workload | Calls | Failed | Error rate | p50 ms | p95 ms | p99 ms | Worst ms |
|---|---|---|---|---|---|---|---|
| `agent_run` | 325 | 0 | 0.00% | 910 | 1111 | 1192 | 1380 |
| `api_read` | 973 | 0 | 0.00% | 21 | 66 | 141 | 534 |
| `chat_stream` | 430 | 0 | 0.00% | 967 | 1119 | 1219 | 1579 |
| `ingest` | 109 | 0 | 0.00% | 49 | 68 | 81 | 233 |
| `rag_query` | 258 | 0 | 0.00% | 54 | 95 | 177 | 412 |
| `trigger_fire` | 65 | 0 | 0.00% | 43 | 72 | 2163 | 2163 |

Time to first token, which is the half of a stream a person feels:

| Workload | Streams | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| `chat_stream` | 430 | 508 | 636 | 733 |

No request failed.


## The whole run, every phase together

| Workload | Calls | Failed | Error rate | p50 ms | p95 ms | p99 ms | Worst ms |
|---|---|---|---|---|---|---|---|
| `agent_run` | 710 | 0 | 0.00% | 1018 | 9402 | 13258 | 18990 |
| `api_read` | 2134 | 0 | 0.00% | 35 | 4339 | 10980 | 21175 |
| `chat_stream` | 948 | 11 | 1.16% | 1060 | 21743 | 29570 | 35972 |
| `ingest` | 236 | 0 | 0.00% | 61 | 7364 | 15047 | 17756 |
| `rag_query` | 570 | 0 | 0.00% | 66 | 7998 | 13505 | 25936 |
| `trigger_fire` | 142 | 0 | 0.00% | 53 | 3877 | 9092 | 13666 |

### What failed

| Workload | Reason | Count |
|---|---|---|
| `chat_stream` | timed out | 11 |

## The machine while it ran

- Peak CPU **99%** of one core; peak resident memory **598 MB**, finishing at **565 MB**.
- Peak database connections **92**, of which **19** executing at once.

## Against the proposed thresholds

These are **proposed**, not agreed - see `docs/load-testing.md`. The sample
count is beside each one because a tail described by four requests is not a
finding.

| Workload | Metric | Limit | Measured | Samples | |
|---|---|---|---|---|---|
| `api_read` | p95 | 300.00 ms | 65.88 ms | 973 | pass |
| `api_read` | error_rate | 0.10% | 0.00% | 973 | pass |
| `chat_stream` | first_token_p95 | 1500.00 ms | 636.09 ms | 430 | pass |
| `chat_stream` | error_rate | 1.00% | 0.00% | 430 | pass |
| `agent_run` | p95 | 5000.00 ms | 1110.75 ms | 325 | pass |
| `rag_query` | p95 | 1200.00 ms | 94.96 ms | 258 | pass |
| `ingest` | error_rate | 0.00% | 0.00% | 109 | pass |
| `trigger_fire` | error_rate | 0.00% | 0.00% | 65 | pass |

## What this run found

Written by hand after the run; everything above it is the report the harness
printed. The only difference from `2026-09-16-macbook-default-pool.md` is
`DB_POOL_SIZE=20` and `DB_MAX_OVERFLOW=30` — fifty connections instead of
fifteen. Nothing else changed: same machine, same mix, same rates, same stub.

**The burst stops being a failure.** Across the whole run, including the 36/s
phase, 11 requests failed out of 4740 — 0.2%, all of them chat sockets that timed
out — against 30% before. The API log holds no `QueuePool` timeout at all, where
the previous run held 5132.

**And the sustained phase gets faster.** `api_read` p95 falls from 138 ms to 66
ms and `rag_query` p95 from 268 ms to 95 ms, at the same offered rate: the
default pool was already queueing at 12 requests a second, just not enough to
fail.

### The recommendation

1. **Raise `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` before anything else.** On this
   workload they are the binding constraint, and the defaults (5 and 10) are
   sized for a laptop rather than for a deployment serving people.
2. **Then raise `UVICORN_WORKERS`.** One worker saturated one core on a
   ten-core machine in both runs. Capacity per host is workers × the per-worker
   rate, not the rate above.
3. **Keep the product of the two under the database's `max_connections`.** This
   run peaked at **92** connections from one worker; Postgres allows 100 by
   default, so four workers at this pool size would exhaust it and the failure
   would look exactly like the first run. Either size the pool as
   `max_connections / workers` with headroom, or put PgBouncer in front.

### What this does not establish

A rate, not a user count: NFA-006's thousand-user target is architectural and one
host says nothing about it. And every latency here is the platform's plus the
stub's stated delay — a real provider adds its own, which is why the thresholds
are written against the stub.
