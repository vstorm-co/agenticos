# Adding a feature

## Adding a new API endpoint

!!! abstract "One walkthrough, in the Guides"

    [How to: Add a New API Endpoint](howto/add-api-endpoint.md) is the worked
    example — schema, model, repository, service, dependency, route, router,
    migration, tests. There is deliberately no second copy of it here: two
    copies written for the same reader are two copies that disagree.

The shape it teaches, in one paragraph: a **schema** per operation
(`*Create`/`*Update`/`*Read`/`*List`), a **model** on `Base, TimestampMixin`
with a `__repr__`, a **repository** of stateless functions using
`flush()`/`refresh()` and never `commit()`, a **service** holding only the
session and raising domain exceptions, an `Annotated` **dependency** in
`api/deps.py`, and a **route** returning `-> Any` with `response_model` doing the
serialization.

## Adding a custom CLI command

Commands are auto-discovered from `app/commands/`.

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

`success`, `error`, `warning` and `info` are the output helpers — a command says
what happened through those rather than through `print`, so every command in the
CLI reads the same way. Run it with:

```bash
uv run agenticos cmd my-command --name test
```

!!! note "A new command owes `docs/commands.md` a row"

    That page is the reference an operator reads; a command absent from it is a
    command nobody finds.

## Adding a tool the agent can call

There is no single agent module to hang a `@agent.tool` on. Agents here are data,
assembled per run from the capabilities their spec names, so a new tool arrives as
part of a **capability**:

- A new one → [Add a capability](howto/add-capability.md).
- One more tool on a capability that already exists →
  [Adding a tool to an existing capability](howto/add-capability.md#adding-a-tool-to-an-existing-capability).
- A third-party API that already publishes an MCP server → no code at all, see
  [MCP](mcp.md).

!!! danger "A tool the registry does not declare cannot be gated or renamed"

    The list in `@register(tools=...)` is what per-tool approval and per-agent
    renaming key on. An undeclared tool still runs — it just runs ungated, which
    is the failure worth avoiding.

What ships today is in the [capability catalog](reference/capabilities.md).

## Adding a database migration

!!! warning "`make db-check` skips itself when no database is listening"

    `alembic check` needs one, so the target prints a warning and **exits 0**
    without a database on `CHECK_DB_PORT` — a model change with no migration then
    passes local `make check`. CI's **`test`** job has a Postgres beside it and so
    does not skip, which is where that mistake is actually caught. Run
    `make docker-db` first if you want the local answer.

!!! tip "Autogenerate is a draft, not an answer"

    Read the revision before committing it, and give it a downgrade that actually
    reverses it — `make test-migrations` cycles the whole chain both ways.

```bash
# Create migration
uv run alembic revision --autogenerate -m "Add notifications table"

# Apply migration
uv run alembic upgrade head

# Or use CLI
uv run agenticos db migrate -m "Add notifications table"
uv run agenticos db upgrade
```
