---
source_sha: abac9cb95a88
---

# Añadir una funcionalidad { #adding-a-feature }

Cuatro formas de cambio, y cada una tiene un ejemplo desarrollado en otro sitio.
Esta página es el mapa: qué tiene que tocar un cambio de esa forma, y dónde está
la versión larga.

## Añadir un endpoint de API nuevo { #adding-a-new-api-endpoint }

!!! abstract "Un recorrido, en las guías"

    [Añadir un endpoint de API](howto/add-api-endpoint.md) es el ejemplo
    desarrollado — schema, modelo, repositorio, servicio, dependencia, ruta,
    router, migración, pruebas. Deliberadamente no hay aquí una segunda copia:
    dos copias escritas para el mismo lector son dos copias que se contradicen.

La forma que enseña, en un párrafo: un **schema** por operación
(`*Create`/`*Update`/`*Read`/`*List`), un **modelo** sobre `Base, TimestampMixin`
con un `__repr__`, un **repositorio** de funciones sin estado que usan
`flush()`/`refresh()` y nunca `commit()`, un **servicio** que solo guarda la
sesión y lanza excepciones de dominio, una **dependencia** `Annotated` en
`api/deps.py`, y una **ruta** que devuelve `-> Any` con `response_model`
encargándose de la serialización.

## Añadir un comando propio a la CLI { #adding-a-custom-cli-command }

Los comandos se descubren automáticamente desde `app/commands/`.

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

`success`, `error`, `warning` e `info` son los ayudantes de salida — un comando
dice lo que ha pasado a través de ellos y no de `print`, de modo que todos los
comandos de la CLI se lean igual. Ejecútalo con:

```bash
uv run agenticos cmd my-command --name test
```

!!! note "Un comando nuevo le debe una fila a `docs/commands.md`"

    Esa página es la referencia que lee quien opera el sistema; un comando que no
    está en ella es un comando que nadie encuentra.

## Añadir una herramienta que el agent pueda llamar { #adding-a-tool-the-agent-can-call }

No hay un módulo de agent único donde colgar un `@agent.tool`. Aquí los agents son
datos, ensamblados por run a partir de las capabilities que nombra su spec, así
que una herramienta nueva llega como parte de una **capability**:

- Una nueva → [Añadir una capability](howto/add-capability.md).
- Una herramienta más sobre una capability que ya existe →
  [Añadir una herramienta a una capability existente](howto/add-capability.md#adding-a-tool-to-an-existing-capability).
- Una API de terceros que ya publica un servidor MCP → nada de código, mira
  [MCP](mcp.md).

!!! danger "Una herramienta que el registro no declara no se puede controlar ni renombrar"

    La lista de `@register(tools=...)` es sobre lo que se apoyan la aprobación por
    herramienta y el renombrado por agent. Una herramienta no declarada se ejecuta
    igualmente — solo que se ejecuta sin control, que es el fallo que merece la
    pena evitar.

Lo que se entrega hoy está en el
[catálogo de capabilities](reference/capabilities.md).

## Añadir una migración de base de datos { #adding-a-database-migration }

!!! warning "`make db-check` se salta a sí mismo cuando no hay ninguna base de datos escuchando"

    `alembic check` necesita una, así que el target imprime un aviso y **sale con
    0** si no hay base de datos en `CHECK_DB_PORT` — un cambio de modelo sin
    migración pasa entonces el `make check` local. El job **`test`** de CI tiene un
    Postgres al lado y por eso no se salta, que es donde ese error se detecta de
    verdad. Ejecuta `make docker-db` primero si quieres la respuesta local.

!!! tip "Autogenerate es un borrador, no una respuesta"

    Lee la revisión antes de hacer commit, y dale un downgrade que realmente la
    revierta — `make test-migrations` recorre toda la cadena en ambos sentidos.

```bash
# Create migration
uv run alembic revision --autogenerate -m "Add notifications table"

# Apply migration
uv run alembic upgrade head

# Or use CLI
uv run agenticos db migrate -m "Add notifications table"
uv run agenticos db upgrade
```
