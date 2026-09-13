---
source_sha: 1b7f3c282f31
---

# Dodaj zadanie w tle { #add-a-background-task }

Praca w tle dzieje się poza cyklem żądanie-odpowiedź. Ten projekt używa
**Prefect** do wszystkiego, co jest zaplanowane albo długo trwa, oraz
`app/core/background.py` do pracy, którą przekazuje żądanie.

## Krok po kroku { #step-by-step }

### 1. Utwórz zadanie { #1-create-the-task }
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

Ten flow przyjmuje **identyfikator i odczytuje wiersz**, co jest kształtem, jaki
ma niemal każdy prawdziwy flow, i powodem, dla którego opisane niżej przekazanie
ma znaczenie. Flow, który tylko wypisuje swoje argumenty, działałby tak czy
inaczej i niczego by nie nauczył.

### 2. Wywołaj go z serwisu { #2-call-it-from-a-service }

!!! danger "Praca, która czyta wiersz zapisany przez to żądanie, bierze `spawn_after_commit`"

    `spawn` tworzy zadanie natychmiast, a pętla startuje je przed commitem
    żądania, więc flow otwiera własną sesję i nie widzi wiersza, którego
    identyfikator dostał — upload, który odpowiedział `processing` i taki
    pozostał ([#417](https://github.com/vstorm-co/agenticos/issues/417)). Gołe
    `asyncio.create_task` ma ten problem *i dodatkowo* gubi wyjątek, bo nic nie
    trzyma referencji do zadania ani nie odczytuje jego wyniku.

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

Oba trzymają referencję do zadania, żeby nie zostało zebrane przez garbage
collector w locie, i oba logują błąd z nazwą `name`, którą im podałeś — a to
jedyny kontekst, jaki ten błąd kiedykolwiek poniesie, więc bądź konkretny.

### 3. Dodaj harmonogram (opcjonalnie) { #3-add-scheduling-optional }

Harmonogram odpala się ze **stałymi** parametrami, więc flow, który nazywa, musi
być takim, który ich nie potrzebuje — `send_notification_flow` powyżej przyjmuje
identyfikator wiersza, który ktoś zapisał, a o dziewiątej rano nie ma takiego
identyfikatora. Zarejestruj flow, który sam szuka swojej pracy:

```python
from prefect.client.schemas.schedules import CronSchedule

from app.worker.tasks.reports import nightly_digest_flow

deployments.append(await nightly_digest_flow.ato_deployment(
    name="daily-digest",
    schedules=[CronSchedule(cron="0 9 * * *")],  # Daily at 9 AM
))
```

### 4. Uruchom workera { #4-run-the-worker }

```bash
# The prefect-server + prefect-runner containers start with `make dev`.
# To run the runner directly (registers deployments + polls for work):
uv run --directory backend python -m app.worker.prefect_app
# Prefect UI: http://localhost:4200
```

!!! warning "Krótki harmonogram jest tani w dodaniu, ale nie darmowy"

    Naraz wykonuje się najwyżej `PREFECT_RUNNER_LIMIT` runów (domyślnie 5), a
    reszta czeka w kolejce. Każdy run to proces, który importuje całą aplikację,
    więc wybieraj najdłuższy interwał, który wciąż odpowiada na pytanie.

Interwał decyduje też o tym, ile pracy czeka po przestoju.
