---
source_sha: 1b7f3c282f31
---

# Einen Hintergrund-Task hinzufügen { #add-a-background-task }

Hintergrundarbeit läuft außerhalb des Request-Response-Zyklus. Dieses Projekt
nutzt **Prefect** für alles Geplante oder Langlaufende und
`app/core/background.py` für Arbeit, die eine Anfrage übergibt.

## Schritt für Schritt { #step-by-step }

### 1. Den Task anlegen { #1-create-the-task }
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

Der Flow nimmt eine **Id entgegen und liest die Zeile**, was die Form ist, die
fast jeder echte Flow hat, und der Grund, warum die Übergabe weiter unten wichtig
ist. Ein Flow, der nur seine Argumente ausgibt, würde in beiden Fällen
funktionieren und nichts lehren.

### 2. Ihn aus einem Service aufrufen { #2-call-it-from-a-service }

!!! danger "Arbeit, die eine Zeile liest, die diese Anfrage geschrieben hat, nimmt `spawn_after_commit`"

    `spawn` erzeugt den Task sofort, und die Schleife startet ihn, bevor die
    Anfrage committet; der Flow öffnet also seine eigene Session und kann die
    Zeile nicht sehen, deren Id er bekommen hat - ein Upload, der `processing`
    antwortete und dabei blieb
    ([#417](https://github.com/vstorm-co/agenticos/issues/417)). Ein nacktes
    `asyncio.create_task` hat dieses Problem *und* verliert die Exception, weil
    nichts eine Referenz auf den Task hält oder sein Ergebnis liest.

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

Beide halten eine Referenz auf den Task, damit er nicht mitten im Flug von der Garbage
Collection eingesammelt wird, und beide loggen einen Fehlschlag mit dem `name`, den Sie
ihnen gegeben haben - der einzige Kontext, den dieser Fehler je tragen wird, seien
Sie also konkret.

### 3. Einen Zeitplan ergänzen (optional) { #3-add-scheduling-optional }

Ein Zeitplan feuert mit **festen** Parametern, der Flow, den er nennt, muss also
einer sein, der keine braucht — `send_notification_flow` oben nimmt die Id einer
Zeile entgegen, die jemand geschrieben hat, und um neun Uhr morgens gibt es keine
solche Id. Registrieren Sie den Flow, der sich seine Arbeit selbst sucht:

```python
from prefect.client.schemas.schedules import CronSchedule

from app.worker.tasks.reports import nightly_digest_flow

deployments.append(await nightly_digest_flow.ato_deployment(
    name="daily-digest",
    schedules=[CronSchedule(cron="0 9 * * *")],  # Daily at 9 AM
))
```

### 4. Den Worker starten { #4-run-the-worker }

```bash
# The prefect-server + prefect-runner containers start with `make dev`.
# To run the runner directly (registers deployments + polls for work):
uv run --directory backend python -m app.worker.prefect_app
# Prefect UI: http://localhost:4200
```

!!! warning "Ein kurzer Zeitplan ist billig hinzugefügt, aber nicht umsonst"

    Höchstens `PREFECT_RUNNER_LIMIT` Runs laufen gleichzeitig (Voreinstellung 5),
    der Rest wartet in der Warteschlange. Jeder Run ist ein Prozess, der die
    ganze Anwendung importiert, wählen Sie also das längste Intervall, das die
    Frage noch beantwortet.

Das Intervall entscheidet auch darüber, wie viel Arbeit sich nach einer Ausfallzeit
angesammelt hat.
