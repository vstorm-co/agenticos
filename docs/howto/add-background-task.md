# Add a background task

Work that outlives a request is a **job** in the `background_jobs` table: a
service queues it in its own transaction, and a worker (`python -m app.worker`)
claims it, runs it and writes down how it ended. The same table carries the
deployment's recurring jobs. `app/core/background.py` remains for the small,
best-effort work a request hands to its own process.

A job is durable where a task on the API's loop is not. It survives a restart,
it is retried with backoff, and a job that kills its worker - an out-of-memory
kill included - has already spent the attempt, so it cannot loop. What it did is
on the Background jobs page.

## Step by step

### 1. Declare the job

A job kind is declared in `app/worker/jobs.py`: its payload, its pool, its
attempts, its timeout and its priority. The module imports Pydantic and nothing
else, so the service that queues the job never imports the code that runs it.

```python
# app/worker/jobs.py
class SendNotification(Payload):
    notification_id: UUID


SEND_NOTIFICATION = Task(
    kind="send-notification",
    payload_type=SendNotification,
    pool=Pool.SYSTEM,
    max_attempts=3,
    timeout=timedelta(minutes=5),
    priority=Priority.INTERACTIVE,
)
```

A payload carries **identifiers and primitives**, never a row or a session. The
job reads the row when it runs, and re-establishes whatever authority it needs
then: by the time a worker claims it, the row may have changed and the person
who asked may no longer be allowed to.

Pick the pool by what the job spends:

| Pool | For | How it runs |
|---|---|---|
| `agent` | Agent runs and trigger fires: long, waiting on models | On the worker's loop, `WORKER_AGENT_CONCURRENCY` at once |
| `ingest` | Parsing and embedding: CPU and memory heavy | One job per child process, under `WORKER_INGEST_MEMORY_MB` |
| `system` | Sweeps, cleanups, reports: short | On the worker's loop, `WORKER_SYSTEM_CONCURRENCY` at once |

### 2. Write the handler and bind it

```python
# app/worker/tasks/notification_tasks.py
async def send_notification(job: SendNotification) -> None:
    async with get_worker_db_context() as db:
        notification = await notification_repo.get_by_id(db, job.notification_id)
        if notification is None:
            return  # deleted since it was queued: nothing left to send
        await NotificationDelivery(db).send(notification)
```

Bind it to its kind in `production()` in `app/worker/handlers.py`:

```python
Handler(jobs.SEND_NOTIFICATION, notification_tasks.send_notification),
```

An exception fails the attempt, and the job is retried until `max_attempts`;
its type, message and last frames go on the job's row. A payload that no longer
validates, or a kind no worker knows, fails at once with no retry - it would
only fail the same way again. A handler can return a Pydantic model, which is
kept as the job's result.

### 3. Queue it from a service

```python
from app.services.background_jobs import enqueue
from app.worker.jobs import SEND_NOTIFICATION, SendNotification

await enqueue(
    self.db,
    SEND_NOTIFICATION,
    SendNotification(notification_id=notification.id),
    organization_id=notification.organization_id,
)
```

The job is written in the request's transaction, so it exists exactly when the
row it names does: a rolled-back request queues nothing, and a committed one
wakes the pool's workers through `NOTIFY` once the row is there to read. That is
the race [#417](https://github.com/vstorm-co/agenticos/issues/417) was, closed
by construction rather than by `spawn_after_commit`.

Three options shape how copies of a job behave:

- `dedupe_key` keeps at most one queued copy. With `dedupe_active=True`, a
  running copy also drops the new one - a sync already in progress makes a
  second request for it redundant.
- `concurrency_key` lets copies queue but runs them one at a time, such as two
  syncs of one source.
- `run_after` delays the first attempt.

### 4. Schedule it (optional)

A recurring job is declared in `SCHEDULES` in `app/worker/schedules.py`. Its
payload is a `Tick`, which names the occurrence it was fired for, so a job
covering a period - a weekly report - knows which period:

```python
Schedule("send-digest", jobs.SEND_DIGEST, timedelta(days=1)),
```

Every schedule is an interval on a fixed grid, kept in `background_schedules`,
so a restart picks up where the last worker left off. Two settings decide what
an awkward occurrence does:

- **`misfire`**, for one later than `grace` (a minute): `latest` fires once for
  the whole backlog, `skip` waits for the next. Nothing ever fires once per
  missed occurrence.
- **`overlap`**, for one that arrives while the previous job is queued or
  running: `skip` drops it, `queue` lets one wait behind it, `allow` runs it
  alongside.

Sweep over current state with the defaults, `latest` and `skip`. A job whose
run covers a period of its own, like the usage reports, takes `overlap=QUEUE`, so
a slow week is not a week nobody is sent.

### 5. Run the worker

```bash
make dev                                   # API, worker, frontend, Postgres, Redis
uv run --directory backend python -m app.worker   # the worker on its own
```

`WORKER_POOLS` limits which pools a worker serves, so a deployment can run
ingestion on a bigger host. Every worker runs the schedules; their claim takes
each due schedule once however many workers tick at the same instant.

## When something goes wrong

A job that killed its worker five times in a row pauses its **kind**: no worker
claims it until the deployment's owner resumes it on the Background jobs page,
and every owner is told in the app and by email. A dead job can be retried from
that page, and a queued one cancelled. Each action is audited.

!!! note "When `spawn_after_commit` is still the right call"

    Work that may be lost on a restart without harm - a cache warmed, a
    notification of something that is also visible elsewhere - can still go to
    `spawn_after_commit`. It runs on the API's own loop, so keep it short and
    let anything that must happen be a job.

## Testing

Run a job's handler directly in a unit test; it is a plain coroutine. Queueing
and claiming are tested against the real database in
`backend/tests/integration/test_background_job_queue.py`, and a worker that is
killed for real in `backend/tests/integration/test_worker_runtime.py` - start
there when a change touches the queue itself.
