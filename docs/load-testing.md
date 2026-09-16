# Load and resilience testing

AgenticOS streams, runs background work and holds sockets open, and none of that
says anything about how much of it one deployment can do at once. Asynchronous
code is not a capacity result, and a green unit suite is not a load test. So
there is a suite that measures it, in `loadtest/`, and this page is what it
measures, what it calls a pass, and how to run it again.

The numbers a run produces belong to the machine it ran on. Nothing here proves
NFA-006's thousand-user architecture target, and a single run on one host proves
NFA-001's latency target only for that host — both are noted where they touch a
threshold rather than quietly claimed.

## The workload

A deployment's traffic is mostly people reading lists, some of them talking to an
agent, a few uploading a document, and a trickle of events firing routines nobody
is watching. The mix says that in numbers:

| Workload | Share | What one request is |
|---|---|---|
| `api_read` | 45% | An authenticated list — agents, runs, conversations |
| `chat_stream` | 20% | A chat turn over the WebSocket, one in five cancelled part-way |
| `agent_run` | 15% | `POST /agents/{id}/run` — the same runner without a socket |
| `rag_query` | 12% | Retrieval: one embedding, one vector search |
| `ingest` | 5% | A document uploaded, which this API accepts and a worker indexes |
| `trigger_fire` | 3% | A signed webhook delivery firing a routine |

The shares are in `loadtest/scenario.py`, they are one line each, and they are
the part of this to disagree with. A deployment whose traffic looks different
edits them and re-runs; what must not happen is a number quoted from a mix
nobody looked at.

### Arrival rate, not a worker pool

Requests are offered on a **schedule**. A closed loop of N workers, each waiting
for its predecessor, reduces its own arrival rate exactly when the server slows
down — so a server that has fallen over reports comfortable latencies and a
throughput that quietly halved. An open arrival model keeps offering work at the
stated rate and lets the queue grow, which is the thing under test.

Which workload each request is comes from a low-discrepancy sequence rather than
a die, so two runs at the same rate issue the same number of uploads and any
difference between them is the platform's.

### The phases

| Phase | Seconds | Offered per second | What it is for |
|---|---|---|---|
| `ramp` | 60 | 4 | A cold cache is not steady state |
| `sustain` | 180 | 12 | **Every threshold is judged against this one** |
| `burst` | 45 | 36 | Three times the rate, which is what a fan-out looks like |
| `recover` | 60 | 12 | A platform that recovers and one that stays degraded look identical during the burst |

## What counts as a pass

These thresholds are **proposed, not agreed**. NFA-004's acceptance asks for
agreed ones; stating them here gives a run a verdict instead of a wall of
numbers, and makes the conversation about a specific figure rather than about
whether there should be one. Nothing here is a commitment made on anybody's
behalf.

| Workload | Metric | Limit | Why there |
|---|---|---|---|
| `api_read` | p95 | 300 ms | One query behind a permission check; above this is queueing, not work |
| `api_read` | error rate | 0.1% | Room for a recycled connection and nothing else |
| `chat_stream` | p95 first token | 1500 ms | The platform's share: socket, auth, spec, capabilities, run row |
| `chat_stream` | error rate | 1% | A dropped socket costs a person their answer |
| `agent_run` | p95 | 5000 ms | The whole run path against the stub, end to end |
| `rag_query` | p95 | 1200 ms | What this bounds is pgvector and the pool in front of it |
| `ingest` | error rate | 0% | An upload accepted and then lost is the worst failure here |
| `trigger_fire` | error rate | 0% | A 2xx has taken responsibility for the event |

Each is judged per workload on purpose. One number over a mixed run describes
nothing: an upload and a list are not the same request.

A workload that produced no samples reads as **not measured**, never as a pass.
A run that skipped a scenario and reported green for it is the failure the whole
file exists to avoid.

## The model is a stub, and slow on purpose

`loadtest/stub_model.py` serves the Chat Completions API and an embeddings
endpoint, with a first-token delay and a per-token pace the run states. A load
test whose model answers instantly measures a platform under a workload that
cannot exist: every real provider takes hundreds of milliseconds, and how much
concurrency a deployment holds is decided by how long a run keeps its resources
while waiting.

It can also be told to misbehave — `--error-rate` refuses that share with a 500
and `--timeout-rate` holds them open — which is the resilience half of NFA-004.
What the platform does when its provider fails is a property of the platform, and
it cannot be measured against a provider that is behaving.

Nothing in a default run touches a paid provider. The embeddings are the stub's
too, reached the way a keyless Ollama endpoint is, so a deployment with no
provider key at all can still be measured. An end-to-end measurement against a
real provider is a deliberate act: point the fixture's model profile at it, and
expect the provider's own latency and rate limits in the numbers.

## Running it

Four things have to be in place, and `run.py` refuses to start without any of
them rather than measuring a deployment that cannot do the work:

1. a migrated database and Redis;
2. the stub model answering, **at an address the API can reach** — see below;
3. the fixture — `make load-seed`, once;
4. Prefect, if the `trigger_fire` workload is to mean anything. Without it a
   webhook is accepted and its dispatch fails, which the report shows as 500s on
   that workload rather than hiding.

### Where the stub has to listen

The *API* calls the stub, not the driver, so the address seeded into the model
profile has to work from wherever the API runs. Two topologies:

| The API runs | Bind | Seed |
|---|---|---|
| On this host (`uv run uvicorn …`) | `127.0.0.1` (the default) | `http://127.0.0.1:4020` (the default) |
| In the Compose stack (`make dev`) | `LOAD_STUB_BIND=0.0.0.0` | `LOAD_STUB_URL=http://host.docker.internal:4020` |

Loopback inside the `app` container is the container, not the host, so the second
row is not optional there — and getting it wrong fails preflight with a message
about an empty collection rather than about an address, because the embeddings
never reach the stub either.

```bash
make load-stub-model                       # terminal one
make load-seed                             # once
make load-test API_PID=$(pgrep -f uvicorn | head -1) \
  DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/agenticos \
  > loadtest/results/$(date +%F)-thismachine.md
```

`API_PID` and `DATABASE_URL` are optional. Without them the run measures requests
and **names the probes it could not take** in the report, rather than printing
zeros for them.

The fixture file holds **no credential**. The run signs in for itself with
`--email` and `--password` (the seeded defaults), so no bearer token is written
to disk and a fixture seeded yesterday still runs today — an expiring token in a
file was both a secret at rest and a run that refused for no good reason.

Two settings are worth raising for a capacity run, and the report's topology line
should say when they were:

- **`RATE_LIMIT_RUN_PER_MINUTE`**. The limit is per caller and the driver is one
  identity standing in for many, so at its default of 30 the experiment measures
  the limiter rather than the platform.
- **`UVICORN_WORKERS`**, if the question is about the host rather than about one
  worker.

`--scale 0.1` shortens every phase and changes nothing else, for checking the
harness itself. Shortening a run by lowering its *rate* would be a different
experiment wearing the same name.

`--connections` bounds the driver's own sockets, and defaults to the scenario's
peak rate times the slowest request — 3240 for the shipped phases. A cap below
that turns an open-arrival run into a closed one during the burst, exactly when
it matters: requests queue inside the client, and some of the latency the report
shows is the driver's own.

## Reading the report

Four sections, in the order the questions get asked: what was run, what happened
during `sustain`, what happened during `recover`, and whether it passed. The
verdict is last on purpose — a verdict at the top invites somebody to read only
that, and the sample counts underneath it are what say whether a tail is a
finding or three requests.

The header carries two numbers worth checking before anything else. **Offered
against recorded** must match: every offered request leaves a sample, succeeded
or failed, including one abandoned when the run ended, and a shortfall means the
error rates are computed over a denominator smaller than the load — the report
says so in a banner and calls itself unusable. **Late dispatches** is the driver
admitting it fell behind its own schedule and became part of the measurement.

Throughput is shown twice for the sustained phase: completions that landed inside
the window, and requests offered during it. They diverge when the deployment is
behind, which is the only time the number is interesting.

Percentiles are **nearest-rank**, not interpolated: an interpolated p99 over
ninety samples is a number between two measurements that nothing observed. And
latency is measured over **successful** requests only. A request refused in 3 ms
is not a fast request, and letting it into the distribution is how a run that
fell over reports its best percentiles ever; the failures are counted separately
and named.

CPU is a difference of the process's cumulative CPU time across each sampling
interval, not `ps`'s `%CPU` — procps defines that as CPU time over the process's
whole lifetime and says outright that it is not utilization, so sampling it would
average away the short saturation a burst is meant to cause. The resolution is
therefore the granularity of `ps`'s clock over the sampling interval, which on
Linux is one second in two.

## What this suite does not measure

Stated rather than left to be discovered:

- **Worker throughput.** The `ingest` and `trigger_fire` workloads measure
  *admission* — the API answers 202 and hands the work to a flow. How fast the
  worker drains that queue is a measurement where the worker is, and it is not
  claimed here.
- **Anything about a real provider.** Every latency in a default run is the
  platform's plus the stub's stated delay.
- **The console.** The frontend is not exercised; these are API paths.
- **A cluster.** One deployment, one database. NFA-006's target is architectural
  and a single-host run says nothing about it either way.

## The measured runs

Committed under `loadtest/results/`, each with the machine, the topology and the
date at the top, because a number without those is not a result.

Two runs are committed so far, on the same machine, differing in one setting:

| | `2026-09-16-macbook-default-pool.md` | `2026-09-16-macbook-pool-raised.md` |
|---|---|---|
| Pool | 5 + 10 overflow (the defaults) | 20 + 30 overflow |
| Sustained 12/s | every threshold met, no failures | every threshold met |
| Whole run, burst included | **1537 of 4740 failed**, 6559 pool timeouts | 13 failed, no pool timeout at all |
| **After the burst** | **66–100% still failing** | **no failures; latency draining** |

The finding, and the reason there are two: **the connection pool is the binding
constraint on this workload, not CPU.** Both runs peaked around 90% of *one* core
on a ten-core machine, because there was one worker. So the order to raise things
in is the pool, then `UVICORN_WORKERS` — and their product has to stay under the
database's `max_connections`, since one worker already peaked at 84 of the
default 100.

The recovery row is the one to read first. With the default pool, a request that
cannot get a connection waits the full `DB_POOL_TIMEOUT` of thirty seconds, so
the backlog outlives the burst that created it and the deployment is still
failing at a rate it handled comfortably ten minutes earlier. Each result file
carries the whole reasoning.
