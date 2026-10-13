---
source_sha: "1b7f3c282f31"
---

# Añade una tarea en segundo plano { #add-a-background-task }

El trabajo en segundo plano corre fuera del ciclo petición-respuesta. Este
proyecto usa **Prefect** para todo lo programado o de larga duración, y
`app/core/background.py` para el trabajo que una petición entrega.

## Paso a paso { #step-by-step }

### 1. Crea la tarea { #1-create-the-task }
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

El flow recibe un **id y lee la fila**, que es la forma que tiene casi todo flow
real y el motivo por el que importa la entrega de más abajo. Un flow que solo
imprimiera sus argumentos funcionaría de cualquiera de las dos maneras y no
enseñaría nada.

### 2. Llámalo desde un servicio { #2-call-it-from-a-service }

!!! danger "El trabajo que lee una fila escrita por esta petición se lanza con `spawn_after_commit`"

    `spawn` crea la tarea de inmediato y el bucle la arranca antes de que la
    petición haga commit, así que el flow abre su propia sesión y no puede ver
    la fila cuyo id recibió: una subida que respondía `processing` y se quedaba
    así ([#417](https://github.com/vstorm-co/agenticos/issues/417)). Un
    `asyncio.create_task` pelado tiene ese problema *y además* pierde la
    excepción, porque nada guarda una referencia a la tarea ni lee su resultado.

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

Ambos guardan una referencia a la tarea para que el recolector de basura no se la
lleve a medio vuelo, y ambos registran un fallo con el `name` que les hayas
dado: el único contexto que ese error llevará nunca, así que sé concreto.

### 3. Añade una programación (opcional) { #3-add-scheduling-optional }

Una programación se dispara con parámetros **fijos**, así que el flow que nombra
tiene que ser uno que no necesite ninguno: `send_notification_flow`, más arriba,
recibe el id de una fila que alguien escribió, y a las nueve de la mañana no
existe tal id. Registra el flow que sale a buscar su propio trabajo:

```python
from prefect.client.schemas.schedules import CronSchedule

from app.worker.tasks.reports import nightly_digest_flow

deployments.append(await nightly_digest_flow.ato_deployment(
    name="daily-digest",
    schedules=[CronSchedule(cron="0 9 * * *")],  # Daily at 9 AM
))
```

### 4. Arranca el worker { #4-run-the-worker }

```bash
# The prefect-server + prefect-runner containers start with `make dev`.
# To run the runner directly (registers deployments + polls for work):
uv run --directory backend python -m app.worker.prefect_app
# Prefect UI: http://localhost:4200
```

!!! warning "Una programación corta es barata de añadir, pero no gratis"

    Como mucho se ejecutan a la vez `PREFECT_RUNNER_LIMIT` runs (5 por defecto) y
    el resto hace cola. Cada run es un proceso que importa la aplicación entera,
    así que prefiere el intervalo más largo que siga respondiendo a la pregunta.

El intervalo decide también cuánto trabajo queda esperando tras una caída.
