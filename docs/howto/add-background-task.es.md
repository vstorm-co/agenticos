---
source_sha: "957a4208f188"
---

# Añade una tarea en segundo plano { #add-a-background-task }

El trabajo que dura más que una petición es un **job** en la tabla
`background_jobs`: un servicio lo encola en su propia transacción, y un worker
(`python -m app.worker`) lo recoge, lo ejecuta y anota cómo terminó. La misma
tabla guarda los jobs recurrentes del despliegue. `app/core/background.py` queda
para el trabajo pequeño y sin garantías que una petición entrega a su propio
proceso.

Un job es duradero donde una tarea en el bucle de la API no lo es. Sobrevive a
un reinicio, se reintenta con esperas crecientes, y un job que mata a su worker
- también por falta de memoria - ya ha gastado su intento, así que no puede
entrar en bucle. Lo que hizo aparece en la página Background jobs.

## Paso a paso { #step-by-step }

### 1. Declara el job { #1-declare-the-job }

Un tipo de job se declara en `app/worker/jobs.py`: su payload, su pool, sus
intentos, su tiempo límite y su prioridad. El módulo solo importa Pydantic, de
modo que el servicio que encola el job nunca importa el código que lo ejecuta.

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

Un payload lleva **identificadores y valores simples**, nunca una fila ni una
sesión. El job lee la fila cuando se ejecuta y en ese momento recupera los
permisos que necesita: para cuando un worker lo recoge, la fila puede haber
cambiado y quien lo pidió puede haber perdido el acceso.

Elige el pool según lo que gasta el job:

| Pool | Para qué | Cómo se ejecuta |
|---|---|---|
| `agent` | Runs de agents y disparos de triggers: largos, esperan a los modelos | En el bucle del worker, `WORKER_AGENT_CONCURRENCY` a la vez |
| `ingest` | Parseo y embeddings: mucha CPU y memoria | Un job por proceso hijo, bajo `WORKER_INGEST_MEMORY_MB` |
| `system` | Barridos, limpiezas, informes: cortos | En el bucle del worker, `WORKER_SYSTEM_CONCURRENCY` a la vez |

### 2. Escribe el handler y enlázalo { #2-write-the-handler-and-bind-it }

```python
# app/worker/tasks/notification_tasks.py
async def send_notification(job: SendNotification) -> None:
    async with get_worker_db_context() as db:
        notification = await notification_repo.get_by_id(db, job.notification_id)
        if notification is None:
            return  # deleted since it was queued: nothing left to send
        await NotificationDelivery(db).send(notification)
```

Enlázalo a su tipo en `production()` en `app/worker/handlers.py`:

```python
Handler(jobs.SEND_NOTIFICATION, notification_tasks.send_notification),
```

Una excepción hace fallar el intento, y el job se reintenta hasta
`max_attempts`; su tipo, su mensaje y los últimos frames quedan en la fila del
job. Un payload que ya no valida, o un tipo que ningún worker conoce, falla de
inmediato y sin reintentos: solo volvería a fallar igual. Un handler puede
devolver un modelo de Pydantic, que se guarda como resultado del job.

### 3. Encólalo desde un servicio { #3-queue-it-from-a-service }

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

El job se escribe en la transacción de la petición, así que existe exactamente
cuando existe la fila que nombra: una petición revertida no encola nada, y una
confirmada despierta a los workers del pool mediante `NOTIFY` solo cuando la
fila ya se puede leer. Esa era la carrera de
[#417](https://github.com/vstorm-co/agenticos/issues/417), cerrada por la propia
construcción y no por `spawn_after_commit`.

Tres opciones deciden cómo se comportan las copias de un job:

- `dedupe_key` mantiene como mucho una copia encolada. Con `dedupe_active=True`,
  también una copia en ejecución descarta la nueva: una sincronización que ya
  está en marcha hace innecesaria una segunda petición.
- `concurrency_key` deja que las copias esperen en cola, pero las ejecuta de una
  en una, como dos sincronizaciones de la misma fuente.
- `run_after` retrasa el primer intento.

### 4. Prográmalo (opcional) { #4-schedule-it-optional }

Un job recurrente se declara en `SCHEDULES` en `app/worker/schedules.py`. Su
payload es un `Tick`, que nombra la ocurrencia para la que se disparó, de modo
que un job que cubre un periodo - un informe semanal - sabe de qué periodo se
trata:

```python
Schedule("send-digest", jobs.SEND_DIGEST, timedelta(days=1)),
```

Cada programación es un intervalo sobre una cuadrícula fija, guardada en
`background_schedules`, así que tras un reinicio se sigue donde lo dejó el
último worker. Dos ajustes deciden qué hace una ocurrencia incómoda:

- **`misfire`**, para una que llega más tarde que `grace` (un minuto): `latest`
  dispara una vez por todo el retraso acumulado, `skip` espera a la siguiente.
  Nada se dispara nunca una vez por cada ocurrencia perdida.
- **`overlap`**, para una que llega mientras el job anterior está en cola o en
  ejecución: `skip` la descarta, `queue` deja que una espere detrás, `allow` la
  ejecuta a la vez.

Los barridos sobre el estado actual se quedan con los valores por defecto,
`latest` y `skip`. Un job cuyo run cubre un periodo propio, como los informes de
uso, lleva `overlap=QUEUE`, para que una semana lenta no sea una semana cuyo
informe no recibe nadie.

### 5. Arranca el worker { #5-run-the-worker }

```bash
make dev                                   # API, worker, frontend, Postgres, Redis
uv run --directory backend python -m app.worker   # the worker on its own
```

`WORKER_POOLS` limita los pools que atiende un worker, de modo que un despliegue
puede ejecutar la ingesta en un host más grande. Todos los workers ejecutan las
programaciones; su recogida toma cada programación vencida una sola vez, por
muchos workers que hagan tic en el mismo instante.

## Cuando algo sale mal { #when-something-goes-wrong }

Un job que ha matado a su worker cinco veces seguidas pausa su **tipo**: ningún
worker lo recoge hasta que el propietario del despliegue lo reanuda en la página
Background jobs, y cada propietario recibe un aviso en la aplicación y por
correo. Desde esa página, un job muerto se puede reintentar y uno encolado,
cancelar. Cada acción queda auditada.

!!! note "Cuándo `spawn_after_commit` sigue siendo la opción correcta"

    El trabajo cuya pérdida en un reinicio no perjudica a nadie - una caché que se
    precalienta, un aviso de algo que también se ve en otro sitio - puede seguir
    yendo a `spawn_after_commit`. Se ejecuta en el propio bucle de la API, así que
    mantenlo corto y haz que todo lo que tenga que ocurrir sea un job.

## Pruebas { #testing }

Ejecuta el handler de un job directamente en una prueba unitaria; es una
corrutina corriente. El encolado y la recogida se prueban contra la base de
datos real en `backend/tests/integration/test_background_job_queue.py`, y un
worker al que se mata de verdad en
`backend/tests/integration/test_worker_runtime.py`: empieza por ahí cuando un
cambio toca la propia cola.
