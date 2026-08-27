# How to: Add a Background Task

Background work runs outside the request-response cycle. This project uses
**Prefect** for anything scheduled or long-running, and `app/core/background.py`
for work a request hands over.

## Step-by-Step

### 1. Create the task
```python
# app/worker/tasks/notifications.py
from prefect import flow


@flow(name="send-notification", log_prints=True)
async def send_notification_flow(user_id: str, message: str) -> dict:
    """Send a notification to a user."""
    # Your async logic here
    print(f"Sending to {user_id}: {message}")
    return {"status": "sent", "user_id": user_id}
```

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

# In a service, handing over work about a row this request just wrote:
spawn_after_commit(
    self.db,
    send_notification_flow(str(notification.id), "Your order is ready!"),
    name=f"notify:{notification.id}",
)

# Work that reads nothing this request wrote can start immediately:
spawn(send_notification_flow("broadcast", "Nightly digest"), name="notify:digest")
```

Both keep a reference to the task so it is not garbage-collected mid-flight, and
both log a failure with the `name` you gave them - which is the only context that
error will ever carry, so be specific.

### 3. Add scheduling (optional)
In `app/worker/prefect_app.py`, register a scheduled deployment in `main()`:
```python
from prefect.client.schemas.schedules import CronSchedule

from app.worker.tasks.notifications import send_notification_flow

deployments.append(await send_notification_flow.ato_deployment(
    name="daily-digest",
    parameters={"user_id": "broadcast", "message": "Daily digest"},
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
