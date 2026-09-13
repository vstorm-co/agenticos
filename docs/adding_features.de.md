---
source_sha: abac9cb95a88
---

# Ein Feature hinzufügen { #adding-a-feature }

Vier Arten von Änderungen, und für jede gibt es an anderer Stelle ein
ausgearbeitetes Beispiel. Diese Seite ist die Landkarte: was eine Änderung dieser
Art berühren muss, und wo die ausführliche Fassung steht.

## Einen neuen API-Endpunkt hinzufügen { #adding-a-new-api-endpoint }

!!! abstract "Eine Anleitung, in den Guides"

    [Einen API-Endpunkt hinzufügen](howto/add-api-endpoint.md) ist das
    ausgearbeitete Beispiel — Schema, Modell, Repository, Service, Dependency,
    Route, Router, Migration, Tests. Hier steht bewusst keine zweite Fassung
    davon: zwei Fassungen für denselben Leser sind zwei Fassungen, die einander
    widersprechen.

Die Form, die sie lehrt, in einem Absatz: ein **Schema** je Operation
(`*Create`/`*Update`/`*Read`/`*List`), ein **Modell** auf `Base, TimestampMixin`
mit einem `__repr__`, ein **Repository** aus zustandslosen Funktionen, die
`flush()`/`refresh()` nutzen und niemals `commit()`, ein **Service**, der nur die
Session hält und Domain-Exceptions auslöst, eine `Annotated`-**Dependency** in
`api/deps.py`, und eine **Route**, die `-> Any` zurückgibt, während
`response_model` die Serialisierung übernimmt.

## Einen eigenen CLI-Befehl hinzufügen { #adding-a-custom-cli-command }

Befehle werden aus `app/commands/` automatisch gefunden.

```python
# app/commands/my_command.py
import click

from app.commands import command, success


@command("my-command", help="What this does")
@click.option("--name", "-n", required=True, help="Whose name")
def my_command(name: str) -> None:
    """One line, because `--help` prints it."""
    success(f"Done: {name}")
```

`success`, `error`, `warning` und `info` sind die Ausgabehelfer — ein Befehl sagt
über sie, was geschehen ist, und nicht über `print`, damit sich jeder Befehl im
CLI gleich liest. So führen Sie ihn aus:

```bash
uv run agenticos cmd my-command --name test
```

!!! note "Ein neuer Befehl schuldet `docs/commands.md` eine Zeile"

    Diese Seite ist die Referenz, die eine Betreiberin liest; ein Befehl, der dort
    fehlt, ist ein Befehl, den niemand findet.

## Ein Tool hinzufügen, das der Agent aufrufen kann { #adding-a-tool-the-agent-can-call }

Es gibt kein einzelnes Agent-Modul, an das sich ein `@agent.tool` hängen ließe.
Agents sind hier Daten, je Run aus den Capabilities zusammengesetzt, die ihr Spec
nennt — ein neues Tool kommt also als Teil einer **Capability**:

- Eine neue → [Eine Capability hinzufügen](howto/add-capability.md).
- Ein weiteres Tool auf einer bereits bestehenden Capability →
  [Ein Tool zu einer bestehenden Capability hinzufügen](howto/add-capability.md#adding-a-tool-to-an-existing-capability).
- Eine fremde API, die bereits einen MCP-Server veröffentlicht → gar kein Code,
  siehe [MCP](mcp.md).

!!! danger "Ein Tool, das die Registry nicht deklariert, lässt sich weder gaten noch umbenennen"

    Die Liste in `@register(tools=...)` ist das, worauf die Freigabe je Tool und
    die Umbenennung je Agent aufsetzen. Ein nicht deklariertes Tool läuft
    trotzdem — es läuft nur ohne Gate, und genau das ist das Versagen, das es zu
    vermeiden lohnt.

Was heute ausgeliefert wird, steht im
[Capability-Katalog](reference/capabilities.md).

## Eine Datenbankmigration hinzufügen { #adding-a-database-migration }

!!! warning "`make db-check` überspringt sich selbst, wenn keine Datenbank lauscht"

    `alembic check` braucht eine, also gibt das Target eine Warnung aus und
    **beendet sich mit 0**, wenn auf `CHECK_DB_PORT` keine Datenbank läuft — eine
    Modelländerung ohne Migration besteht dann das lokale `make check`. Der Job
    **`test`** in CI hat ein Postgres neben sich und überspringt deshalb nicht;
    dort wird dieser Fehler tatsächlich gefangen. Führen Sie zuerst
    `make docker-db` aus, wenn Sie die lokale Antwort wollen.

!!! tip "Autogenerate ist ein Entwurf, keine Antwort"

    Lesen Sie die Revision, bevor Sie sie committen, und geben Sie ihr ein
    Downgrade, das sie auch wirklich rückgängig macht — `make test-migrations`
    durchläuft die ganze Kette in beide Richtungen.

```bash
# Create migration
uv run alembic revision --autogenerate -m "Add notifications table"

# Apply migration
uv run alembic upgrade head

# Or use CLI
uv run agenticos db migrate -m "Add notifications table"
uv run agenticos db upgrade
```
