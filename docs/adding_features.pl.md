---
source_sha: abac9cb95a88
---

# Dodawanie funkcji { #adding-a-feature }

Cztery kształty zmiany, a każdy ma gdzie indziej opracowany przykład. Ta strona
jest mapą: czego musi dotknąć zmiana danego kształtu i gdzie znajdziesz jej
pełną wersję.

## Dodawanie nowego endpointu API { #adding-a-new-api-endpoint }

!!! abstract "Jeden przewodnik, w Guides"

    [Add an API endpoint](howto/add-api-endpoint.md) to opracowany przykład —
    schema, model, repozytorium, serwis, zależność, route, router, migracja,
    testy. Celowo nie ma tu jego drugiej kopii: dwie kopie napisane dla tego
    samego czytelnika to dwie kopie, które się ze sobą nie zgadzają.

Kształt, którego uczy, w jednym akapicie: **schema** na operację
(`*Create`/`*Update`/`*Read`/`*List`), **model** na `Base, TimestampMixin`
z `__repr__`, **repozytorium** bezstanowych funkcji używających
`flush()`/`refresh()` i nigdy `commit()`, **serwis** trzymający wyłącznie sesję
i podnoszący wyjątki domenowe, zależność `Annotated` w `api/deps.py` oraz
**route** zwracający `-> Any`, w którym serializacją zajmuje się
`response_model`.

## Dodawanie własnej komendy CLI { #adding-a-custom-cli-command }

Komendy są wykrywane automatycznie w `app/commands/`.

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

`success`, `error`, `warning` i `info` to helpery wypisujące wynik — komenda
mówi, co się stało, przez nie, a nie przez `print`, dzięki czemu każda komenda
w CLI czyta się tak samo. Uruchom ją tak:

```bash
uv run agenticos cmd my-command --name test
```

!!! note "Nowa komenda jest winna `docs/commands.md` wiersz"

    Ta strona jest materiałem referencyjnym, który czyta operator; komenda,
    której tam nie ma, to komenda, której nikt nie znajdzie.

## Dodawanie narzędzia, które agent może wywołać { #adding-a-tool-the-agent-can-call }

Nie ma pojedynczego modułu agenta, na którym można zawiesić `@agent.tool`.
Agenci są tutaj danymi, składanymi na każdy run z capability, które wymienia ich
spec, więc nowe narzędzie pojawia się jako część **capability**:

- Zupełnie nowa → [Add a capability](howto/add-capability.md).
- Jeszcze jedno narzędzie w już istniejącej capability →
  [Adding a tool to an existing capability](howto/add-capability.md#adding-a-tool-to-an-existing-capability).
- Zewnętrzne API, które publikuje już serwer MCP → żadnego kodu, zobacz
  [MCP](mcp.md).

!!! danger "Narzędzia, którego rejestr nie deklaruje, nie da się bramkować ani zmienić mu nazwy"

    Lista w `@register(tools=...)` jest tym, na czym opierają się zatwierdzanie
    per narzędzie i zmiana nazwy per agent. Niezadeklarowane narzędzie i tak
    działa — po prostu działa bez bramki, i to jest ta awaria, której warto
    uniknąć.

To, co jest dostępne dzisiaj, znajdziesz w
[katalogu capability](reference/capabilities.md).

## Dodawanie migracji bazy danych { #adding-a-database-migration }

!!! warning "`make db-check` pomija sam siebie, gdy żadna baza nie nasłuchuje"

    `alembic check` jej potrzebuje, więc bez bazy na `CHECK_DB_PORT` target
    wypisuje ostrzeżenie i **kończy się kodem 0** — zmiana modelu bez migracji
    przechodzi wtedy lokalne `make check`. Zadanie **`test`** w CI ma obok siebie
    Postgresa i dlatego niczego nie pomija, i to tam ten błąd faktycznie zostaje
    złapany. Uruchom najpierw `make docker-db`, jeśli chcesz lokalną odpowiedź.

!!! tip "Autogenerate to szkic, a nie odpowiedź"

    Przeczytaj rewizję, zanim ją zacommitujesz, i daj jej downgrade, który
    naprawdę ją odwraca — `make test-migrations` przepuszcza cały łańcuch w obie
    strony.

```bash
# Create migration
uv run alembic revision --autogenerate -m "Add notifications table"

# Apply migration
uv run alembic upgrade head

# Or use CLI
uv run agenticos db migrate -m "Add notifications table"
uv run agenticos db upgrade
```
