---
source_sha: "957a4208f188"
---

# Dodaj zadanie w tle { #add-a-background-task }

Praca, która trwa dłużej niż żądanie, jest **zadaniem** w tabeli
`background_jobs`: serwis kolejkuje je we własnej transakcji, a worker
(`python -m app.worker`) je pobiera, wykonuje i zapisuje, jak się skończyło. Ta
sama tabela przechowuje cykliczne zadania wdrożenia. `app/core/background.py`
zostaje dla drobnej pracy bez gwarancji, którą żądanie przekazuje własnemu
procesowi.

Zadanie jest trwałe tam, gdzie task w pętli API nie jest. Przetrwa restart, jest
ponawiane z narastającą przerwą, a zadanie, które zabije swojego workera - także
przez brak pamięci - zużyło już swoją próbę, więc nie może się zapętlić. To, co
zrobiło, widać na stronie Background jobs.

## Krok po kroku { #step-by-step }

### 1. Zadeklaruj zadanie { #1-declare-the-job }

Rodzaj zadania deklaruje się w `app/worker/jobs.py`: jego payload, pulę, liczbę
prób, limit czasu i priorytet. Ten moduł importuje tylko Pydantic, więc serwis,
który kolejkuje zadanie, nigdy nie importuje kodu, który je wykona.

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

Payload niesie **identyfikatory i wartości proste**, nigdy wiersz ani sesję.
Zadanie czyta wiersz dopiero, gdy się wykonuje, i wtedy odtwarza uprawnienia,
których potrzebuje: zanim worker je pobierze, wiersz mógł się zmienić, a osoba,
która o nie poprosiła, mogła stracić dostęp.

Pulę wybierz według tego, co zadanie zużywa:

| Pula | Do czego | Jak się wykonuje |
|---|---|---|
| `agent` | Runy agentów i odpalenia triggerów: długie, czekają na modele | W pętli workera, `WORKER_AGENT_CONCURRENCY` naraz |
| `ingest` | Parsowanie i embeddingi: dużo CPU i pamięci | Jedno zadanie na proces potomny, w limicie `WORKER_INGEST_MEMORY_MB` |
| `system` | Sprzątanie, porządki, raporty: krótkie | W pętli workera, `WORKER_SYSTEM_CONCURRENCY` naraz |

### 2. Napisz handler i go podłącz { #2-write-the-handler-and-bind-it }

```python
# app/worker/tasks/notification_tasks.py
async def send_notification(job: SendNotification) -> None:
    async with get_worker_db_context() as db:
        notification = await notification_repo.get_by_id(db, job.notification_id)
        if notification is None:
            return  # deleted since it was queued: nothing left to send
        await NotificationDelivery(db).send(notification)
```

Podłącz go do jego rodzaju w `production()` w `app/worker/handlers.py`:

```python
Handler(jobs.SEND_NOTIFICATION, notification_tasks.send_notification),
```

Wyjątek kończy próbę niepowodzeniem, a zadanie jest ponawiane do `max_attempts`;
typ wyjątku, komunikat i ostatnie ramki trafiają do wiersza zadania. Payload,
który już się nie waliduje, albo rodzaj, którego żaden worker nie zna, kończy
się od razu, bez ponowień - za każdym razem skończyłby się tak samo. Handler może
zwrócić model Pydantic, który zostaje zapisany jako wynik zadania.

### 3. Zakolejkuj je z serwisu { #3-queue-it-from-a-service }

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

Zadanie jest zapisywane w transakcji żądania, więc istnieje dokładnie wtedy, gdy
istnieje wiersz, który wskazuje: wycofane żądanie niczego nie kolejkuje, a
zatwierdzone budzi workery puli przez `NOTIFY` dopiero wtedy, gdy wiersz da się
odczytać. To był wyścig z
[#417](https://github.com/vstorm-co/agenticos/issues/417), zamknięty przez samą
konstrukcję, a nie przez `spawn_after_commit`.

Trzy opcje decydują o tym, jak zachowują się kopie zadania:

- `dedupe_key` trzyma najwyżej jedną zakolejkowaną kopię. Z `dedupe_active=True`
  także trwająca kopia odrzuca nową - synchronizacja, która już trwa, sprawia, że
  druga prośba o nią jest zbędna.
- `concurrency_key` pozwala kopiom czekać w kolejce, ale wykonuje je po jednej,
  na przykład dwie synchronizacje jednego źródła.
- `run_after` opóźnia pierwszą próbę.

### 4. Zaplanuj je (opcjonalnie) { #4-schedule-it-optional }

Zadanie cykliczne deklaruje się w `SCHEDULES` w `app/worker/schedules.py`. Jego
payload to `Tick`, który wskazuje wystąpienie, dla którego zadanie odpalono, więc
zadanie obejmujące okres - raport tygodniowy - wie, którego okresu dotyczy:

```python
Schedule("send-digest", jobs.SEND_DIGEST, timedelta(days=1)),
```

Każdy harmonogram to interwał na stałej siatce, trzymanej w
`background_schedules`, więc po restarcie praca rusza tam, gdzie skończył
poprzedni worker. Dwa ustawienia decydują o tym, co robi niewygodne wystąpienie:

- **`misfire`** - dla wystąpienia spóźnionego o więcej niż `grace` (minuta):
  `latest` odpala raz za całą zaległość, `skip` czeka na następne. Nic nigdy nie
  odpala się raz za każde przegapione wystąpienie.
- **`overlap`** - dla wystąpienia, które przychodzi, gdy poprzednie zadanie
  czeka w kolejce albo trwa: `skip` je pomija, `queue` pozwala jednemu poczekać
  za nim, `allow` wykonuje je równolegle.

Sprzątanie bieżącego stanu zostaw z domyślnymi `latest` i `skip`. Zadanie, którego
run obejmuje własny okres, jak raporty użycia, dostaje `overlap=QUEUE`, żeby
wolny tydzień nie był tygodniem, którego raportu nikt nie dostanie.

### 5. Uruchom workera { #5-run-the-worker }

```bash
make dev                                   # API, worker, frontend, Postgres, Redis
uv run --directory backend python -m app.worker   # the worker on its own
```

`WORKER_POOLS` ogranicza pule, które obsługuje worker, więc wdrożenie może
wykonywać ingestion na większym hoście. Każdy worker wykonuje harmonogramy; ich
pobranie bierze każdy należny harmonogram raz, niezależnie od tego, ile workerów
tyka w tej samej chwili.

## Gdy coś pójdzie nie tak { #when-something-goes-wrong }

Zadanie, które pięć razy z rzędu zabiło swojego workera, wstrzymuje swój
**rodzaj**: żaden worker go nie pobiera, dopóki właściciel wdrożenia nie wznowi
go na stronie Background jobs, a każdy właściciel dostaje powiadomienie w
aplikacji i e-mailem. Martwe zadanie można z tej strony ponowić, a zakolejkowane
anulować. Każda z tych akcji trafia do dziennika audytu.

!!! note "Kiedy `spawn_after_commit` wciąż jest dobrym wyborem"

    Pracę, której utrata przy restarcie nikomu nie szkodzi - rozgrzanie cache,
    powiadomienie o czymś, co widać też gdzie indziej - nadal można przekazać do
    `spawn_after_commit`. Wykonuje się w pętli samego API, więc niech będzie
    krótka, a wszystko, co musi się wydarzyć, niech będzie zadaniem.

## Testy { #testing }

Handler zadania uruchom bezpośrednio w teście jednostkowym; to zwykła
korutyna. Kolejkowanie i pobieranie są testowane na prawdziwej bazie w
`backend/tests/integration/test_background_job_queue.py`, a worker naprawdę
zabijany - w `backend/tests/integration/test_worker_runtime.py`. Zacznij od nich,
gdy zmiana dotyka samej kolejki.
