---
name: background-task
description: Add or change work that runs outside the request/response cycle — document ingestion, MCP refresh, reports, cleanups, scheduled jobs — or debug a task that vanished with nothing in the logs. Use when something is slow or fire-and-forget, when adding a periodic job, and before reaching for asyncio.create_task (which drops work silently in this codebase's exact failure mode).
---

# Background work — Prefect, and one in-process handoff

**Read `docs/howto/add-background-task.md`.** Flows live in
`backend/app/worker/tasks/` (`rag_tasks.py`, `mcp_tasks.py`, `report_tasks.py`);
deployments are registered in `app/worker/prefect_app.py`.

## Pick the right one

| | Use for | Survives a restart |
|---|---|---|
| **Prefect flow** | Ingestion, syncs, reports, anything scheduled or retryable | Yes |
| **`spawn()`** from `app/core/background.py` | The in-process handoff between "the request is answered" and "the slow part finishes" | **No** |
| **`spawn_after_commit()`**, same module | The same handoff, when the work reads a row this unit of work wrote | **No** |
| Inline | Fast, transactional work the response depends on | n/a |

```python
from app.core.background import spawn, spawn_after_commit

spawn(send_the_slow_thing(user_id), name="notify-owner")

# Reads a row the caller has just written, so it waits for the commit.
spawn_after_commit(self.db, ingest_document_flow(rag_document_id=str(doc.id)), name=...)
```

**A flow that reads its own row by id takes `spawn_after_commit`.** `spawn`
creates the task at once and the loop starts it at the next suspension point,
which inside a request is well before the commit — so the flow opens its own
session, cannot see the uncommitted row, and stops. That is #417: an upload
answered `{"status": "processing"}` that stayed that way. `spawn_after_commit`
queues the coroutine on the session and the session starts it two statements
after `commit()`; a session that rolls back closes it instead, with a warning.
Works from a route, a WebSocket handler, the CLI or a worker, because the queue
belongs to the session rather than to a response.

`drain(timeout=30.0)` is the shutdown counterpart — in-flight tasks get a chance to
finish rather than being cut off mid-write. A **CLI** command that dispatches work
must call it before returning: `asyncio.run` cancels whatever is still pending, so
without it the command kills the sync it just reported starting.

**Never bare `asyncio.create_task`.** The event loop holds it only weakly: drop the
reference and the task can be garbage-collected mid-flight — the classic symptom is an
ingestion that works under load and vanishes when the system is idle, with nothing in
the logs. Worse, an exception inside a discarded task is never retrieved, so a flow
that raises fails completely silently.

`app/core/background.py` fixes both once: it holds a strong reference until the task
finishes and attaches a done-callback that surfaces whatever went wrong. It is in the
gated platform layer at 100%. Use it, or use Prefect.

`app/worker/background/` (channel, rag) is the older FastAPI-BackgroundTasks fallback,
dispatched with its own `fire_and_forget(coro, *, label=...)`: in-process, no retry, no
persistence, and CPU-bound work there starves the event loop. Prefer `spawn` for new
code and Prefect for anything that must survive a restart.

## Add a flow

```python
from prefect import flow

@flow(name="ingest-document", log_prints=True)
async def ingest_document_flow(document_id: str) -> dict[str, Any]: ...
```

1. Define it in `app/worker/tasks/<area>.py`.
2. **Dispatch from a service, not a route.** Business logic stays in `services/`;
   enqueue at the end of the unit of work.
3. Schedule it, if periodic, with a `CronSchedule`/`IntervalSchedule` deployment in
   `app/worker/prefect_app.py`.
4. Verify: `prefect-server` and `prefect-runner` start with `make dev`; runs are at
   <http://localhost:4200>. `PREFECT_API_URL` points at the self-hosted server, or a
   Cloud workspace plus `PREFECT_API_KEY`.

## Rules

- **Serializable args only** — ids and primitives, never ORM objects or a session.
  Re-fetch inside the flow with a fresh session.
- **Idempotent** where possible. A retry must not double-charge, double-index or
  double-send.
- **Heavy imports inside the function**, to keep the API import-light.
- **Record what was spent even when the flow fails.** Embedding spend goes to
  `ingestion_spend` (which carries `cost_is_partial` for models the price snapshot does
  not know). A cost that only lands on success is a budget with a hole in it.
- A flow that touches an org-scoped resource still needs the organization id — there is
  no ambient tenant in a worker.
