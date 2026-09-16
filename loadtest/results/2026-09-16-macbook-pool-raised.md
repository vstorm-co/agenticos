# Load and resilience run — 2026-09-16, pool raised

- **Machine** — macOS-26.5-arm64-arm-64bit · arm64 · Python 3.12.9
- **Topology** — one uvicorn worker on the host with DB_POOL_SIZE=20 and DB_MAX_OVERFLOW=30 (50 connections), Postgres 17 + pgvector and Redis in containers, Prefect server and runner on the host, the load stub model local; RATE_LIMIT_RUN_PER_MINUTE raised so the limiter does not bound the experiment; the collection holds 40 documents in 160 vectors
- **Duration** — 346s over 4 phases
- **Requests** — 4740 offered, 4740 recorded, 13 failed
- **Driver** — up to 3240 concurrent sockets; **1 dispatches were late**, worst by 300ms

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
| `agent_run` | 325 | 0 | 0.00% | 901 | 1090 | 1165 | 1293 |
| `api_read` | 973 | 0 | 0.00% | 25 | 78 | 124 | 314 |
| `chat_stream` | 430 | 0 | 0.00% | 976 | 1161 | 1243 | 1304 |
| `ingest` | 109 | 0 | 0.00% | 52 | 74 | 187 | 202 |
| `rag_query` | 258 | 0 | 0.00% | 54 | 130 | 275 | 295 |
| `trigger_fire` | 65 | 0 | 0.00% | 47 | 57 | 64 | 64 |

Time to first token, which is the half of a stream a person feels:

| Workload | Streams | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| `chat_stream` | 430 | 512 | 664 | 735 |

No request failed.


## The recovery phase

The same rate as `sustain`, offered after the burst. A deployment that came
back and one that stayed degraded are identical during the burst and differ
only here.

| Workload | Calls | Failed | Error rate | p50 ms | p95 ms | p99 ms | Worst ms |
|---|---|---|---|---|---|---|---|
| `agent_run` | 107 | 0 | 0.00% | 1023 | 7589 | 10286 | 10934 |
| `api_read` | 325 | 0 | 0.00% | 40 | 2169 | 5702 | 8082 |
| `chat_stream` | 144 | 0 | 0.00% | 1081 | 11562 | 15072 | 15462 |
| `ingest` | 35 | 0 | 0.00% | 61 | 5949 | 7297 | 7297 |
| `rag_query` | 88 | 0 | 0.00% | 67 | 5442 | 7850 | 7850 |
| `trigger_fire` | 21 | 0 | 0.00% | 55 | 4582 | 8719 | 8719 |

No request failed.


## The whole run, every phase together

| Workload | Calls | Failed | Error rate | p50 ms | p95 ms | p99 ms | Worst ms |
|---|---|---|---|---|---|---|---|
| `agent_run` | 710 | 0 | 0.00% | 1022 | 10587 | 16037 | 24388 |
| `api_read` | 2134 | 0 | 0.00% | 40 | 4023 | 10199 | 20646 |
| `chat_stream` | 948 | 13 | 1.37% | 1083 | 21741 | 28788 | 35559 |
| `ingest` | 236 | 0 | 0.00% | 64 | 8986 | 14464 | 20837 |
| `rag_query` | 570 | 0 | 0.00% | 68 | 8367 | 13221 | 17264 |
| `trigger_fire` | 142 | 0 | 0.00% | 54 | 5910 | 8384 | 8719 |

### What failed

| Workload | Reason | Count |
|---|---|---|
| `chat_stream` | timed out | 13 |

## The machine while it ran

- Peak CPU **94%** of one core; peak resident memory **600 MB**, finishing at **241 MB**.
- Peak database connections **84**, of which **14** executing at once.

## Against the proposed thresholds

These are **proposed**, not agreed - see `docs/load-testing.md`. The sample
count is beside each one because a tail described by four requests is not a
finding.

| Workload | Metric | Limit | Measured | Samples | |
|---|---|---|---|---|---|
| `api_read` | p95 | 300.00 ms | 78.18 ms | 973 | pass |
| `api_read` | error_rate | 0.10% | 0.00% | 973 | pass |
| `chat_stream` | first_token_p95 | 1500.00 ms | 664.14 ms | 430 | pass |
| `chat_stream` | error_rate | 1.00% | 0.00% | 430 | pass |
| `agent_run` | p95 | 5000.00 ms | 1089.62 ms | 325 | pass |
| `rag_query` | p95 | 1200.00 ms | 129.90 ms | 258 | pass |
| `ingest` | error_rate | 0.00% | 0.00% | 109 | pass |
| `trigger_fire` | error_rate | 0.00% | 0.00% | 65 | pass |

## What this run found

Written by hand after the run; everything above it is the report the harness
printed. The only difference from `2026-09-16-macbook-default-pool.md` is
`DB_POOL_SIZE=20` and `DB_MAX_OVERFLOW=30` — fifty connections instead of
fifteen. Nothing else changed: same machine, same mix, same rates, same stub,
same 40-document collection.

**The burst stops being a failure.** 13 requests failed out of 4740 — 0.3%, all
of them chat sockets that timed out — against 1537 before. The API log holds no
`QueuePool` timeout at all, where the previous run held 6559.

**And it recovers.** The recovery phase has **no failures at all**: after three
times the offered rate, at the same rate it was comfortable at before, everything
is answered. Latency is still elevated there — `api_read` p95 at 2.2 s against
73 ms during `sustain` — so the backlog is real and draining, which is what
recovery looks like as opposed to what collapse looks like.

### The recommendation

1. **Raise `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` before anything else.** On this
   workload they are the binding constraint, and the defaults (5 and 10) are
   sized for a laptop rather than for a deployment serving people.
2. **Then raise `UVICORN_WORKERS`.** One worker saturated one core on a
   ten-core machine in both runs. Capacity per host is workers × the per-worker
   rate, not the rate above.
3. **Keep the product of the two under the database's `max_connections`.** This
   run peaked at **84** connections from one worker; Postgres allows 100 by
   default, so two such workers would exhaust it and the failure would look
   exactly like the first run. Either size the pool as
   `max_connections / workers` with headroom, or put PgBouncer in front.

### What this does not establish

A rate, not a user count: NFA-006's thousand-user target is architectural and one
host says nothing about it. And every latency here is the platform's plus the
stub's stated delay — a real provider adds its own, which is why the thresholds
are written against the stub.
