# Scale beyond one host

The shipped path is [one host with Docker Compose](deploy.md). This page is for
the step after it: a managed Postgres, several API hosts, workers of their own,
or several deployments side by side. It says what each part needs when it moves,
and what the platform does not do yet, so a plan is built on what runs.

Measure first. One host of the [recommended size](deploy.md#sizing-the-host)
carries a team of a few dozen, and most slowness on a small host is CPU steal or
an undersized pool rather than a missing replica. The
[load suite](load-testing.md) runs the same workload against any deployment.

## What holds state, and what does not { #what-holds-state-and-what-does-not }

| Part | What it keeps | How it grows |
|---|---|---|
| API (`app`) | Nothing of its own. Sessions, presence, running chat turns and the live-update feed are in Postgres and Redis | More uvicorn workers, then more hosts behind a load balancer |
| Worker | Nothing. Jobs, leases and schedules are rows in Postgres | More processes, on any host, with the pools split between them |
| Console (`frontend`) | The branding it caches for five minutes | More instances |
| Postgres | Everything durable: organizations, agents, conversations, vectors, the job queue | A bigger instance, or a managed one |
| Redis (Valkey) | A cache and its pub/sub channels, rebuilt after a restart | One instance that every host shares |
| Uploaded files | A volume on the host, or a bucket | A bucket once more than one host reads or writes them |
| Sandbox service | The sandboxes agents run commands in | Its own host, see [Agent workspaces](configuration.md#running-the-service-on-another-host) |

## One database per deployment { #one-database-per-deployment }

Every organization on a deployment shares one Postgres database, and every
query is scoped by organization. The vectors of every knowledge base are in it
too, through pgvector, and so is the job queue. `POSTGRES_DB` names the only
database a deployment uses: there is no separate vector database, no read
replica and no sharding by organization.

Several databases therefore means several deployments. That is the answer for
data that must stay in one region, for a business unit with administrators of
its own, and for a tenant whose load should not reach the others. Each
deployment has its own hostnames, `SECRET_KEY` and `VAULT_MASTER_KEY`, and
nothing is shared between them at runtime.

They can share infrastructure. Two deployments on one Postgres server need
their own databases (`POSTGRES_DB`), and on one Redis their own `REDIS_DB`
numbers, so that rate-limit buckets and cached answers stay apart. A bucket is
one per deployment as well. An agent moves between them as its spec: export it
as YAML on one (`GET /agents/{id}/spec.yaml`), and import it into an agent on
the other.

## An external Postgres { #an-external-postgres }

A managed or self-run Postgres works when it has these:

- **PostgreSQL 16 with pgvector.** Managed services list it as the `vector`
  extension. The platform creates it the first time a collection is written to,
  so the connecting role needs `CREATE` on the database, or an administrator
  creates it beforehand. The same applies to `pg_stat_statements`, which a
  migration adds where it may and skips with a notice where it may not.
- **An encrypted connection** for a database on another host. See
  [Encrypted connections](configuration.md#encrypted-connections-tls): the
  override has to reach `app`, `migrate` and `worker`, because the compose files
  pin the host in each of them.
- **Migrations run once.** The `migrate` service applies them before the API
  starts. With several hosts, run it from one deploy rather than from each.

After a managed failover, the first request in each process that meets a
dropped connection fails, and the pool then discards every connection older
than it. The engines do not ping a connection before using it, because that
would cost every checkout a round trip.

### Counting connections { #counting-connections }

Size `max_connections` before anything else, or Postgres refuses connections with
"too many clients" before a pool can queue or shed the load.

Each API process opens two pools of `DB_POOL_SIZE + DB_MAX_OVERFLOW`, 15 each
by default: one for requests and one for vector searches, which run inside a
request that already holds a connection. A worker process opens the same two,
plus a short-lived connection for each job it is running. Each ingest child is a
process of its own, and the job it runs writes its vectors through an engine of
its own with the default pool of 15, closed when the job ends. Knowledge
searches made by an agent connect once per search, without a pool.

```text
max_connections ≥ API hosts × UVICORN_WORKERS × 30
                + worker processes × 30
                + ingest children × 15
                + headroom for migrations and an administrator's session
```

Two API hosts with four uvicorn workers each and two workers with one ingest
child each come to 330, so 400 is a sensible setting. These are ceilings: an
idle deployment holds far fewer. The production compose file sets 200 for one
host.

### PgBouncer { #pgbouncer }

Only in session mode. Transaction pooling breaks two things the platform relies
on: asyncpg's prepared statements, which no setting here turns off, and the
session-level advisory lock that keeps one sync source from running twice at
once. Session mode caps how many server connections exist but saves little
else, so sizing the pools against `max_connections` is usually the better
lever.

## More API hosts { #more-api-hosts }

Put a load balancer in front that passes WebSockets: the console's live updates
and chat use `/api/v1/ws/*`. Sticky sessions are not needed. A person whose
socket reconnects to another host follows a running turn through Redis, and
presence and rate limits are kept there too.

Every host needs:

- **The same secrets.** `SECRET_KEY` signs tokens that any host must verify, and
  `VAULT_MASTER_KEY` decrypts every stored credential.
- **The bucket.** With `FILE_STORAGE_BACKEND=local`, a file uploaded through one
  host is not on the other, and the worker that parses it may be on neither.
  Use `s3` (see [Uploaded files at rest](configuration.md#uploaded-files-at-rest)).
- **The same Redis**, as one instance or one endpoint in front of a primary.
  The client is not cluster-aware, so Redis Cluster is not supported.
- **`RATE_LIMIT_TRUST_FORWARDED_FOR`** once the load balancer is the only thing
  that reaches the hosts, or every visitor shares the balancer's bucket.

A chat turn runs in the API process that accepted it, not in a worker, so the
API hosts carry the chat load and `UVICORN_WORKERS` is sized for it as
[on one host](deploy.md#sizing-the-host).

Several console instances are fine. The branding they cache is per instance: an
administrator's change shows at once on the instance that saved it and within
five minutes on the others.

## More workers { #more-workers }

Run as many worker processes as the work needs, on any hosts. They claim jobs
with `SKIP LOCKED`, so no two run the same job, and any of them fires a due
schedule. A worker that dies gives its jobs back within `WORKER_LEASE_SECONDS`.

Split the pools when parsing competes with agent runs. `WORKER_POOLS=agent,system`
on one set of processes and `WORKER_POOLS=ingest` on hosts with memory to spare
keep a large upload from delaying a routine. The health probe and
`agenticos cmd doctor` report a pool that no live worker serves. The
[Background work](configuration.md#background-work) settings size each process.

## Redis { #redis }

Every API host and worker uses the same Redis: it carries the live-update feed,
presence, running turns and rate limits between them. It is a cache, so a
restart loses nothing durable. Live updates reconnect, and a person following a
running turn sees the answer in the transcript when it lands rather than frame
by frame.

## Measure before you add hosts { #measure-before-you-add-hosts }

- **`agenticos cmd doctor`** says which Postgres and Redis each connection
  reached, whether it was encrypted, and whether the workers are alive.
- **`pg_stat_statements`** shows which statements cost the database most.
- **Logfire**, with `LOGFIRE_ENVIRONMENT` set per deployment, separates one
  deployment's traces from another's (see
  [Observability](configuration.md#observability-logfire)).
- **The [load suite](load-testing.md)**, run before and after a change, says
  whether it helped.

## What it does not do yet { #what-it-does-not-do-yet }

- Read replicas, or a vector database of its own.
- Sharding organizations across databases within one deployment.
- PgBouncer in transaction mode, or Redis Cluster.
- Kubernetes manifests. The images are the same ones the compose files run, and
  each service carries its own health check, so a cluster runs them with the
  environment this page describes.
