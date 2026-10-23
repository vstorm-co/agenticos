---
name: background-task
description: Add or change work that runs outside the request/response cycle — document ingestion, syncs, trigger fires, reports, cleanups, scheduled jobs — or debug a job that died, looped or never ran. Use when something is slow or must survive a restart, when adding a periodic job, when touching app/worker/, and before reaching for asyncio.create_task (which drops work silently in this codebase's exact failure mode).
---

# Background work — the job queue, and one in-process handoff

**Read `docs/howto/add-background-task.md`.** Jobs are rows in `background_jobs`
(PostgreSQL); `python -m app.worker` claims and runs them. Kinds are declared
in `app/worker/jobs.py`, handlers live in `app/worker/tasks/` and are bound in
`app/worker/handlers.py`, schedules are in `app/worker/schedules.py`.
`docs/configuration.md#background-work` has the settings and the memory model.

## Pick the right one

| | Use for | Survives a restart |
|---|---|---|
| **A job** (`enqueue`) | Ingestion, syncs, fires, reports, anything scheduled, retryable or long | Yes |
| **`spawn_after_commit()`** from `app/core/background.py` | Short best-effort work on the API's loop that reads a row this unit of work wrote | **No** |
| **`spawn()`**, same module | The same, when it reads nothing the request wrote | **No** |
| Inline | Fast, transactional work the response depends on | n/a |

```python
# AgentTriggerService.queue_fire, as it is
from app.services.background_jobs import enqueue
from app.worker.jobs import FIRE_TRIGGER, FireTrigger

await enqueue(
    self.db,
    FIRE_TRIGGER,
    FireTrigger(trigger_id=trigger_id, event_context=event_context, claimed_at=claimed_at),
    organization_id=organization_id,
)
```

**Queue in the caller's transaction, from a service.** The job row commits with
the rows it names and `NOTIFY` fires only on commit, so the #417 race (a task
that started before the commit and could not see its row) cannot happen.
`spawn_after_commit` is still right for work that may be lost on a restart
without harm; anything that must happen is a job.

**Never bare `asyncio.create_task`.** The event loop holds it only weakly, and an
exception in a discarded task is never retrieved. `app/core/background.py`
fixes both; `drain(timeout=30.0)` is its shutdown counterpart, and a CLI command
that spawns work must call it before returning.

`app/worker/background/channel.py` is the older in-process fallback for channel
work, dispatched with `fire_and_forget(coro, *, label=...)`: no retry, no
persistence. Do not add to it.

## Add a job kind

1. Declare a `Payload` and a `Task` in `app/worker/jobs.py` — pool, attempts,
   timeout, priority. Attempts follow one rule: 3 by default, 2 for ingestion,
   1 for a scheduled sweep (its next tick is its retry) and for an API run.
2. Write the handler in `app/worker/tasks/<area>_tasks.py`; it opens its own
   session (`get_worker_db_context`) and may return a Pydantic model as the
   job's result.
3. Bind it in `production()` in `app/worker/handlers.py`. A sweep that takes no
   payload is wrapped with `_each_tick`.
4. Queue it from a service with `enqueue`, or add a `Schedule` to `SCHEDULES`.
   `test_every_declared_schedule_names_a_task_the_worker_knows` fails a schedule
   with no handler.

Pick the pool by what the job spends: `agent` for model-bound runs, `ingest` for
parsing and embedding (each job in a child process under a memory watchdog),
`system` for short sweeps.

## Rules

- **The attempt is spent at the claim.** A job that kills its process - OOM,
  `SIGKILL` - has used one, so it cannot loop. Never move the increment out of
  the claim (`_CLAIM` in `app/repositories/background_job.py`). This is a hard
  requirement, measured against five other engines in #2219.
- **Fence every write.** A job is settled with the `attempts` it was claimed
  with; a worker whose lease was taken over writes nothing and the takeover is
  counted as `lease_lost`. Handlers that charge money or send mail must be safe
  to run twice anyway: a lost lease means it may have.
- **Serializable payloads only** — ids and primitives, never ORM objects. The
  handler re-reads the row and re-establishes authority (`ApiKeyService.context_for_key`
  for a key, active membership for a person): by then it may be gone.
- **Heavy imports inside the handler module**, not in `jobs.py`, so the API
  that queues never imports the parser that runs.
- **Record what was spent even when the job fails.** Embedding spend goes to
  `ingestion_spend`; a cost that lands only on success is a budget with a hole.
- **No ambient tenant in a worker.** A job that touches an org-scoped resource
  carries the organization id in its payload; `organization_id` on `enqueue` is
  only for the panel's filter.
- **`dedupe_key` / `dedupe_active` / `concurrency_key`** instead of checking
  for a running job by hand - the partial unique indexes make them race-free.

## Debugging

- **Admin → Background jobs** shows every job's attempts and last error, the
  workers alive, the paused kinds and the schedules. `agenticos cmd doctor`
  fails when no worker has beaten for two minutes, a minute schedule stopped
  firing, or a kind is paused.
- A kind paused by the breaker (`WORKER_BREAKER_DEATHS` worker deaths in a row)
  stays paused until an owner resumes it; fix the cause first.
- Tests: `tests/integration/test_background_job_queue.py`,
  `tests/integration/test_worker_runtime.py` (real kills),
  `tests/test_worker_child_pool.py`; misbehaving test kinds are in
  `tests/worker_handlers.py`. See `docs/testing.md#the-workers-tests`.
