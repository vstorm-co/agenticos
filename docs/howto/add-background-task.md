# How to: Add a Background Task

Background work runs outside the request-response cycle. This project uses
**Prefect** for anything scheduled or long-running, and `app/core/background.py`
for work a request hands over.

## Step-by-Step

### 1. Create the task
```python
# app/worker/tasks/notifications.py
from uuid import UUID

from prefect import flow

from app.db.session import get_db_context
from app.repositories import notification_repo


@flow(name="send-notification", log_prints=True)
async def send_notification_flow(notification_id: str) -> dict:
    """Send a notification that a request has already written."""
    # A flow opens its own session: the request's is long gone by now.
    async with get_db_context() as db:
        notification = await notification_repo.get_by_id(db, UUID(notification_id))
        if notification is None:
            # Reachable, and the whole reason for `spawn_after_commit` below.
            raise ValueError(f"notification {notification_id} not found")
        print(f"Sending {notification.title} on {notification.channel}")
    return {"status": "sent", "notification_id": notification_id}
```

The flow takes an **id and reads the row**, which is the shape almost every real
flow has and the reason the handover below matters. A flow that only prints its
arguments would work either way and would teach nothing.

### 2. Call it from a service

!!! danger "Work that reads a row this request wrote takes `spawn_after_commit`"

    `spawn` creates the task at once and the loop starts it before the request
    commits, so the flow opens its own session and cannot see the row it was
    given the id of - an upload that answered `processing` and stayed that way
    ([#417](https://github.com/vstorm-co/agenticos/issues/417)). A bare
    `asyncio.create_task` has that problem *and* loses the exception, because
    nothing holds a reference to the task or reads its result.

```python
from app.core.background import spawn, spawn_after_commit
from app.worker.tasks.notifications import send_notification_flow
from app.worker.tasks.reports import nightly_digest_flow

# A row this request just wrote. The flow reads it by id, so the task must not
# start before the commit that makes it readable.
spawn_after_commit(
    self.db,
    send_notification_flow(str(notification.id)),
    name=f"notify:{notification.id}",
)

# Work that reads nothing this request wrote can start immediately.
spawn(nightly_digest_flow(), name="digest:nightly")
```

Both keep a reference to the task so it is not garbage-collected mid-flight, and
both log a failure with the `name` you gave them - which is the only context that
error will ever carry, so be specific.

### 3. Add scheduling (optional)

A schedule fires with **fixed** parameters, so the flow it names has to be one
that needs none — `send_notification_flow` above takes the id of a row somebody
wrote and there is no such id at nine in the morning. Register the flow that goes
looking for its own work:

```python
from prefect.client.schemas.schedules import CronSchedule

from app.worker.tasks.reports import nightly_digest_flow

deployments.append(await nightly_digest_flow.ato_deployment(
    name="daily-digest",
    schedules=[CronSchedule(cron="0 9 * * *")],  # Daily at 9 AM
))
```

### 4. Run the worker

```bash
# The prefect-server + prefect-runner containers start with `make dev`.
# To run the runner directly (registers deployments + polls for work):
uv run --directory backend python -m app.worker.prefect_app
# Prefect UI: http://localhost:4200
```

!!! warning "A short schedule is cheap to add but not free"

    At most `PREFECT_RUNNER_LIMIT` runs execute at once (default 5) and the rest
    queue. Every run is a process that imports the whole application, so prefer
    the longest interval that still answers the question.

The interval also decides how much work is waiting after downtime.
