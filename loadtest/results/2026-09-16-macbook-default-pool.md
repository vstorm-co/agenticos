# Load and resilience run — 2026-09-16, default pool

- **Machine** — macOS-26.5-arm64-arm-64bit · arm64 · Python 3.12.9
- **Topology** — one uvicorn worker on the host, Postgres 17 + pgvector and Redis in containers, Prefect server and runner on the host, the load stub model local; DB_POOL_SIZE and DB_MAX_OVERFLOW at their defaults (5 + 10); RATE_LIMIT_RUN_PER_MINUTE raised so the limiter does not bound the experiment; the collection holds 40 documents in 160 vectors
- **Duration** — 378s over 4 phases
- **Requests** — 4740 offered, 4740 recorded, 1537 failed
- **Driver** — up to 3240 concurrent sockets; **1 dispatches were late**, worst by 73ms

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

Throughput: **12.0 requests a second** completed
inside the window, against 12.0 a second offered. The two
diverge when the deployment is behind, which is the point of showing both.

| Workload | Calls | Failed | Error rate | p50 ms | p95 ms | p99 ms | Worst ms |
|---|---|---|---|---|---|---|---|
| `agent_run` | 325 | 0 | 0.00% | 898 | 1083 | 1156 | 1424 |
| `api_read` | 973 | 0 | 0.00% | 23 | 73 | 150 | 494 |
| `chat_stream` | 430 | 0 | 0.00% | 964 | 1175 | 1237 | 1341 |
| `ingest` | 109 | 0 | 0.00% | 51 | 66 | 132 | 382 |
| `rag_query` | 258 | 0 | 0.00% | 51 | 105 | 190 | 296 |
| `trigger_fire` | 65 | 0 | 0.00% | 48 | 89 | 2242 | 2242 |

Time to first token, which is the half of a stream a person feels:

| Workload | Streams | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| `chat_stream` | 430 | 505 | 663 | 748 |

No request failed.


## The recovery phase

The same rate as `sustain`, offered after the burst. A deployment that came
back and one that stayed degraded are identical during the burst and differ
only here.

| Workload | Calls | Failed | Error rate | p50 ms | p95 ms | p99 ms | Worst ms |
|---|---|---|---|---|---|---|---|
| `agent_run` | 107 | 81 | 75.70% | 54784 | 59242 | 59904 | 59904 |
| `api_read` | 325 | 238 | 73.23% | 25635 | 29254 | 29776 | 29776 |
| `chat_stream` | 144 | 144 | 100.00% | 0 | 0 | 0 | 0 |
| `ingest` | 35 | 27 | 77.14% | 52744 | 58729 | 58729 | 58729 |
| `rag_query` | 88 | 64 | 72.73% | 53650 | 59020 | 59609 | 59609 |
| `trigger_fire` | 21 | 14 | 66.67% | 25341 | 28030 | 28030 | 28030 |

### What failed

| Workload | Reason | Count |
|---|---|---|
| `agent_run` | HTTP 500 | 81 |
| `api_read` | HTTP 500 | 227 |
| `api_read` | timed out | 9 |
| `api_read` | ReadError | 2 |
| `chat_stream` | timed out | 144 |
| `ingest` | HTTP 500 | 25 |
| `ingest` | timed out | 2 |
| `rag_query` | HTTP 500 | 60 |
| `rag_query` | ReadError | 2 |
| `rag_query` | timed out | 2 |
| `trigger_fire` | HTTP 500 | 14 |

## The whole run, every phase together

| Workload | Calls | Failed | Error rate | p50 ms | p95 ms | p99 ms | Worst ms |
|---|---|---|---|---|---|---|---|
| `agent_run` | 710 | 224 | 31.55% | 949 | 56130 | 58836 | 59904 |
| `api_read` | 2134 | 641 | 30.04% | 28 | 27475 | 29932 | 30366 |
| `chat_stream` | 948 | 382 | 40.30% | 986 | 6936 | 64027 | 65938 |
| `ingest` | 236 | 74 | 31.36% | 55 | 52744 | 58729 | 58748 |
| `rag_query` | 570 | 176 | 30.88% | 54 | 55379 | 58070 | 59609 |
| `trigger_fire` | 142 | 40 | 28.17% | 53 | 27926 | 29566 | 30064 |

### What failed

| Workload | Reason | Count |
|---|---|---|
| `agent_run` | HTTP 500 | 224 |
| `api_read` | HTTP 500 | 597 |
| `api_read` | timed out | 42 |
| `api_read` | ReadError | 2 |
| `chat_stream` | timed out | 370 |
| `chat_stream` | the socket answered an error frame | 8 |
| `chat_stream` | ConnectionClosedError | 4 |
| `ingest` | HTTP 500 | 68 |
| `ingest` | timed out | 6 |
| `rag_query` | HTTP 500 | 164 |
| `rag_query` | timed out | 10 |
| `rag_query` | ReadError | 2 |
| `trigger_fire` | HTTP 500 | 37 |
| `trigger_fire` | timed out | 3 |

## The machine while it ran

- Peak CPU **90%** of one core; peak resident memory **660 MB**, finishing at **580 MB**.
- Peak database connections **26**, of which **6** executing at once.

## Against the proposed thresholds

These are **proposed**, not agreed - see `docs/load-testing.md`. The sample
count is beside each one because a tail described by four requests is not a
finding.

| Workload | Metric | Limit | Measured | Samples | |
|---|---|---|---|---|---|
| `api_read` | p95 | 300.00 ms | 73.34 ms | 973 | pass |
| `api_read` | error_rate | 0.10% | 0.00% | 973 | pass |
| `chat_stream` | first_token_p95 | 1500.00 ms | 662.99 ms | 430 | pass |
| `chat_stream` | error_rate | 1.00% | 0.00% | 430 | pass |
| `agent_run` | p95 | 5000.00 ms | 1082.51 ms | 325 | pass |
| `rag_query` | p95 | 1200.00 ms | 104.82 ms | 258 | pass |
| `ingest` | error_rate | 0.00% | 0.00% | 109 | pass |
| `trigger_fire` | error_rate | 0.00% | 0.00% | 65 | pass |

## What this run found

Written by hand after the run; everything above it is the report the harness
printed.

**The sustained rate is comfortable.** At 12 requests a second this deployment
answers every one of them, inside every proposed threshold, with no failures at
all.

**The burst breaks it, and it does not come back.** The recovery phase is the
finding: after the burst, at the *same* rate it was comfortable at ten minutes
earlier, 66% to 100% of requests still fail and every chat socket times out. This
is not a deployment that absorbed a spike; it is one that was still on the floor
a minute later. 1537 of 4740 requests failed across the run.

**The cause is the connection pool, and it is not ambiguous.** The API log holds
**6559** `sqlalchemy.exc.TimeoutError`, each of them `QueuePool limit of size 5
overflow 10 reached, connection timed out, timeout 30.00`. `DB_POOL_SIZE` is 5
and `DB_MAX_OVERFLOW` 10, so one worker may hold fifteen connections; a mix in
which a run holds one for about a second saturates that between 12 and 36
arrivals a second, and every request after that waits the full thirty seconds
before failing. Waiting thirty seconds is also why it does not recover: the
backlog outlives the burst that created it.

**It is not CPU.** Peak was 90% of *one* core on a machine with ten, because
there was one uvicorn worker. Peak database connections reached 26 — the pool and
its overflow, plus the seeding session — which is the ceiling being hit rather
than the database being busy.

Memory peaked at 660 MB and finished at 580 MB, which is the backlog still held
rather than a leak.

The companion run, `2026-09-16-macbook-pool-raised.md`, changes exactly one thing
and is the evidence for the recommendation.
