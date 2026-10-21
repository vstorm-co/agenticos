---
source_sha: "957a4208f188"
---

# Einen Hintergrund-Task hinzufügen { #add-a-background-task }

Arbeit, die länger dauert als eine Anfrage, ist ein **Job** in der Tabelle
`background_jobs`: Ein Service reiht ihn in seiner eigenen Transaktion ein, und
ein Worker (`python -m app.worker`) holt ihn ab, führt ihn aus und hält fest, wie
er endete. Dieselbe Tabelle trägt die wiederkehrenden Jobs des Deployments.
`app/core/background.py` bleibt für die kleine Arbeit ohne Garantie, die eine
Anfrage an ihren eigenen Prozess übergibt.

Ein Job ist dauerhaft, wo ein Task auf der Event-Loop der API es nicht ist. Er
übersteht einen Neustart, wird mit wachsendem Abstand wiederholt, und ein Job,
der seinen Worker umbringt - auch durch einen Out-of-Memory-Kill -, hat den
Versuch bereits verbraucht und kann sich daher nicht im Kreis drehen. Was er
getan hat, steht auf der Seite Background jobs.

## Schritt für Schritt { #step-by-step }

### 1. Den Job deklarieren { #1-declare-the-job }

Eine Job-Art wird in `app/worker/jobs.py` deklariert: ihr Payload, ihr Pool, ihre
Versuche, ihr Zeitlimit und ihre Priorität. Das Modul importiert nur Pydantic,
sodass der Service, der den Job einreiht, nie den Code importiert, der ihn
ausführt.

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

Ein Payload trägt **Kennungen und einfache Werte**, nie eine Zeile oder eine
Session. Der Job liest die Zeile erst, wenn er läuft, und stellt dann die Rechte
wieder her, die er braucht: Bis ein Worker ihn abholt, kann sich die Zeile
geändert haben, und wer ihn angefordert hat, darf es vielleicht nicht mehr.

Wählen Sie den Pool danach, was der Job verbraucht:

| Pool | Wofür | Wie er läuft |
|---|---|---|
| `agent` | Runs von Agents und ausgelöste Trigger: lang, warten auf Modelle | Auf der Loop des Workers, `WORKER_AGENT_CONCURRENCY` gleichzeitig |
| `ingest` | Parsen und Embeddings: viel CPU und Speicher | Ein Job pro Kindprozess, unter `WORKER_INGEST_MEMORY_MB` |
| `system` | Aufräumläufe, Bereinigungen, Berichte: kurz | Auf der Loop des Workers, `WORKER_SYSTEM_CONCURRENCY` gleichzeitig |

### 2. Den Handler schreiben und binden { #2-write-the-handler-and-bind-it }

```python
# app/worker/tasks/notification_tasks.py
async def send_notification(job: SendNotification) -> None:
    async with get_worker_db_context() as db:
        notification = await notification_repo.get_by_id(db, job.notification_id)
        if notification is None:
            return  # deleted since it was queued: nothing left to send
        await NotificationDelivery(db).send(notification)
```

Binden Sie ihn in `production()` in `app/worker/handlers.py` an seine Art:

```python
Handler(jobs.SEND_NOTIFICATION, notification_tasks.send_notification),
```

Eine Exception lässt den Versuch scheitern, und der Job wird bis `max_attempts`
wiederholt; Typ, Meldung und die letzten Frames landen in der Zeile des Jobs.
Ein Payload, der sich nicht mehr validieren lässt, oder eine Art, die kein Worker
kennt, scheitert sofort und ohne Wiederholung - er würde nur auf dieselbe Weise
erneut scheitern. Ein Handler kann ein Pydantic-Modell zurückgeben, das als
Ergebnis des Jobs gespeichert wird.

### 3. Ihn aus einem Service einreihen { #3-queue-it-from-a-service }

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

Der Job wird in der Transaktion der Anfrage geschrieben, er existiert also genau
dann, wenn die Zeile existiert, die er nennt: Eine zurückgerollte Anfrage reiht
nichts ein, und eine committete weckt die Worker des Pools per `NOTIFY` erst,
wenn die Zeile lesbar ist. Das war das Wettrennen aus
[#417](https://github.com/vstorm-co/agenticos/issues/417), geschlossen durch die
Konstruktion statt durch `spawn_after_commit`.

Drei Optionen bestimmen, wie sich Kopien eines Jobs verhalten:

- `dedupe_key` hält höchstens eine eingereihte Kopie. Mit `dedupe_active=True`
  verwirft auch eine laufende Kopie die neue - ein Sync, der bereits läuft, macht
  eine zweite Anforderung überflüssig.
- `concurrency_key` lässt Kopien warten, führt sie aber nacheinander aus, etwa
  zwei Syncs derselben Quelle.
- `run_after` verzögert den ersten Versuch.

### 4. Ihn planen (optional) { #4-schedule-it-optional }

Ein wiederkehrender Job wird in `SCHEDULES` in `app/worker/schedules.py`
deklariert. Sein Payload ist ein `Tick`, der das Vorkommen nennt, für das er
ausgelöst wurde, sodass ein Job über einen Zeitraum - ein Wochenbericht - weiß,
welcher Zeitraum gemeint ist:

```python
Schedule("send-digest", jobs.SEND_DIGEST, timedelta(days=1)),
```

Jeder Zeitplan ist ein Intervall auf einem festen Raster, das in
`background_schedules` liegt; nach einem Neustart geht es dort weiter, wo der
letzte Worker aufgehört hat. Zwei Einstellungen bestimmen, was ein ungünstiges
Vorkommen tut:

- **`misfire`**, für eines, das mehr als `grace` (eine Minute) zu spät kommt:
  `latest` löst einmal für den ganzen Rückstand aus, `skip` wartet auf das
  nächste. Nichts wird je einmal pro verpasstem Vorkommen ausgelöst.
- **`overlap`**, für eines, das eintrifft, während der vorige Job wartet oder
  läuft: `skip` verwirft es, `queue` lässt eines dahinter warten, `allow` führt
  es parallel aus.

Aufräumläufe über den aktuellen Zustand bleiben bei den Vorgaben `latest` und
`skip`. Ein Job, dessen Run einen eigenen Zeitraum abdeckt, wie die
Nutzungsberichte, bekommt `overlap=QUEUE`, damit eine langsame Woche keine Woche
wird, deren Bericht niemand erhält.

### 5. Den Worker starten { #5-run-the-worker }

```bash
make dev                                   # API, worker, frontend, Postgres, Redis
uv run --directory backend python -m app.worker   # the worker on its own
```

`WORKER_POOLS` begrenzt, welche Pools ein Worker bedient, sodass ein Deployment
Ingestion auf einem größeren Host laufen lassen kann. Jeder Worker führt die
Zeitpläne aus; ihr Abholen nimmt jeden fälligen Zeitplan genau einmal, egal wie
viele Worker im selben Moment ticken.

## Wenn etwas schiefgeht { #when-something-goes-wrong }

Ein Job, der seinen Worker fünfmal hintereinander umgebracht hat, pausiert seine
**Art**: Kein Worker holt sie ab, bis der Eigentümer des Deployments sie auf der
Seite Background jobs fortsetzt, und jeder Eigentümer erfährt es in der App und
per E-Mail. Ein toter Job lässt sich dort erneut versuchen, ein eingereihter
abbrechen. Jede dieser Aktionen wird auditiert.

!!! note "Wann `spawn_after_commit` weiterhin richtig ist"

    Arbeit, deren Verlust bei einem Neustart niemandem schadet - ein Cache, der
    vorgewärmt wird, eine Benachrichtigung über etwas, das auch anderswo sichtbar
    ist -, kann weiterhin an `spawn_after_commit` gehen. Sie läuft auf der Loop der
    API selbst, halten Sie sie also kurz, und machen Sie alles, was geschehen
    muss, zu einem Job.

## Tests { #testing }

Führen Sie den Handler eines Jobs direkt in einem Unit-Test aus; er ist eine
gewöhnliche Coroutine. Einreihen und Abholen werden gegen die echte Datenbank in
`backend/tests/integration/test_background_job_queue.py` getestet, ein Worker,
der wirklich umgebracht wird, in
`backend/tests/integration/test_worker_runtime.py` - beginnen Sie dort, wenn eine
Änderung die Warteschlange selbst berührt.
