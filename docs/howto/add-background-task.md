# How to: Add a Background Task

## Overview

Background tasks run asynchronously outside the request-response cycle. Your project uses **prefect** as the task queue.

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

### 2. Call it from your API

```python
# In any route or service:
import asyncio

from app.worker.tasks.notifications import send_notification_flow

# Fire and forget — runs the flow in the background (tracked in the Prefect UI)
asyncio.create_task(send_notification_flow("user_123", "Your order is ready!"))
```

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
