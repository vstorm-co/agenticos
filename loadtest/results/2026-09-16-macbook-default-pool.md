# Load and resilience run — 2026-09-16

- **Machine** — macOS-26.5-arm64-arm-64bit · arm64 · Python 3.12.9
- **Topology** — one uvicorn worker on the host, Postgres 17 + pgvector and Redis in containers, Prefect server and runner on the host, the load stub model local; RATE_LIMIT_RUN_PER_MINUTE raised so the limiter does not bound the experiment
- **Duration** — 436s over 4 phases
- **Requests** — 4544 offered, 1310 failed

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
| `agent_run` | 325 | 0 | 0.00% | 952 | 1248 | 1613 | 2319 |
| `api_read` | 973 | 0 | 0.00% | 31 | 138 | 467 | 724 |
| `chat_stream` | 430 | 0 | 0.00% | 1010 | 1515 | 2049 | 2421 |
| `ingest` | 109 | 0 | 0.00% | 59 | 211 | 867 | 1274 |
| `rag_query` | 258 | 0 | 0.00% | 58 | 268 | 630 | 793 |
| `trigger_fire` | 65 | 0 | 0.00% | 52 | 129 | 1885 | 1885 |

Time to first token, which is the half of a stream a person feels:

| Workload | Streams | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| `chat_stream` | 430 | 544 | 881 | 1272 |

No request failed.


## The whole run, every phase together

| Workload | Calls | Failed | Error rate | p50 ms | p95 ms | p99 ms | Worst ms |
|---|---|---|---|---|---|---|---|
| `agent_run` | 663 | 198 | 29.86% | 1014 | 57513 | 84477 | 142116 |
| `api_read` | 2040 | 436 | 21.37% | 51 | 89617 | 115097 | 129578 |
| `chat_stream` | 948 | 416 | 43.88% | 1031 | 6579 | 63169 | 72979 |
| `ingest` | 220 | 69 | 31.36% | 64 | 57408 | 107959 | 140841 |
| `rag_query` | 535 | 162 | 30.28% | 68 | 57007 | 114301 | 125719 |
| `trigger_fire` | 138 | 29 | 21.01% | 64 | 100848 | 118516 | 125623 |

### What failed

| Workload | Reason | Count |
|---|---|---|
| `agent_run` | HTTP 500 | 152 |
| `agent_run` | ReadError | 46 |
| `api_read` | HTTP 500 | 297 |
| `api_read` | ReadError | 126 |
| `api_read` | timed out | 13 |
| `chat_stream` | timed out | 381 |
| `chat_stream` | the socket answered an error frame | 29 |
| `chat_stream` | ConnectionClosedError | 6 |
| `ingest` | HTTP 500 | 60 |
| `ingest` | ReadError | 8 |
| `ingest` | timed out | 1 |
| `rag_query` | HTTP 500 | 131 |
| `rag_query` | ReadError | 26 |
| `rag_query` | timed out | 5 |
| `trigger_fire` | HTTP 500 | 20 |
| `trigger_fire` | ReadError | 8 |
| `trigger_fire` | timed out | 1 |

## The machine while it ran

- Peak CPU **99%** of one core; peak resident memory **588 MB**, finishing at **154 MB**.
- Peak database connections **27**, of which **7** executing at once.

## Against the proposed thresholds

These are **proposed**, not agreed - see `docs/load-testing.md`. The sample
count is beside each one because a tail described by four requests is not a
finding.

| Workload | Metric | Limit | Measured | Samples | |
|---|---|---|---|---|---|
| `api_read` | p95 | 300.00 ms | 137.71 ms | 973 | pass |
| `api_read` | error_rate | 0.10% | 0.00% | 973 | pass |
| `chat_stream` | first_token_p95 | 1500.00 ms | 881.37 ms | 430 | pass |
| `chat_stream` | error_rate | 1.00% | 0.00% | 430 | pass |
| `agent_run` | p95 | 5000.00 ms | 1247.87 ms | 325 | pass |
| `rag_query` | p95 | 1200.00 ms | 268.39 ms | 258 | pass |
| `ingest` | error_rate | 0.00% | 0.00% | 109 | pass |
| `trigger_fire` | error_rate | 0.00% | 0.00% | 65 | pass |

## What this run found

Written by hand after the run; everything above it is the report the harness
printed.

**The sustained rate is comfortable and the burst is not.** At 12 requests a
second this deployment answers every one of them, well inside each proposed
threshold. At 36 it collapses: about three in ten requests fail, across every
workload at once, with tails over two minutes.

**The cause is the connection pool, and it is not ambiguous.** The API log holds
**5132** `sqlalchemy.exc.TimeoutError`, each of them
`QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout
30.00`. `DB_POOL_SIZE` is 5 and `DB_MAX_OVERFLOW` 10, so one worker may hold
fifteen connections; a mix in which a run holds one for about a second saturates
that at somewhere between 12 and 36 arrivals a second, and every request after
that waits the full thirty seconds before failing. The 500s, the read errors and
the timed-out sockets are all the same event seen from different workloads.

**It is not CPU.** Peak was 99% of *one* core on a machine with ten, because
there was one uvicorn worker. Memory peaked at 588 MB and finished at 154 MB, so
nothing accumulated.

**The recovery phase is the good news.** Once the offered rate returned to 12 the
deployment came back rather than staying degraded — the queue drained and the
failures stopped, which is what the phase exists to tell apart.

The companion run, `2026-09-16-macbook-pool-raised.md`, changes exactly one thing
and is the evidence for the recommendation.
