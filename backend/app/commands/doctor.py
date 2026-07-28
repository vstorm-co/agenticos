"""Is this deployment actually able to run an agent?

The failures this catches all look the same from a browser - a 500, or a page
that loads and does nothing - and each has a different cause several layers
down. The one that has cost this project the most is stock Postgres: RAG issues
`CREATE EXTENSION vector` the first time a collection is written to, and an
image without pgvector answers "extension not available" *after* the upload was
accepted, the row committed and the task dispatched. The document then sits in
the listing with no explanation.

So this asks, in the order the answers depend on each other: can I reach the
database, is its schema current, can it hold embeddings, is Redis there, is the
vault able to unseal, and is there a model an agent could actually run on.

It reuses the same probes the health endpoint publishes rather than asking the
same questions differently - two implementations of "is this healthy" is how a
dashboard says green while a terminal says red.
"""

import asyncio
from typing import Any

from sqlalchemy import text

from app.commands import command, error, info, success, warning
from app.core.config import settings
from app.db.session import get_db_context
from app.services.health import probe_database, probe_model_access, probe_vector_store

# What each outcome prints. `unconfigured` is deliberately not a failure: a
# deployment that never ingests a document and never runs an agent is installed
# correctly, it is just not finished - and exiting non-zero on that would make
# this useless in a provisioning script.
_MARK = {
    "healthy": ("ok", success),
    "unconfigured": ("--", warning),
    "not_checked": ("--", warning),
    "unhealthy": ("!!", error),
}


def _report(key: str, status: str, detail: str) -> bool:
    """Print one line. Returns whether it counts as a failure."""
    mark, printer = _MARK.get(status, ("!!", error))
    printer(f"[{mark}] {key}: {detail}")
    return status == "unhealthy"


async def _migrations_current(db: Any) -> tuple[str, str]:
    """Whether the database is at the newest revision on disk.

    Read from `alembic_version` rather than by running Alembic: the point is to
    answer without mutating anything, and `upgrade head` in a doctor command is
    exactly the surprise nobody wants from a command that says it only looks.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    try:
        current = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    except Exception:
        return "unhealthy", "no alembic_version table - run `alembic upgrade head`"

    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    if current == head:
        return "healthy", f"at {current}"
    return "unhealthy", f"at {current}, newest on disk is {head} - run `alembic upgrade head`"


async def _redis_reachable() -> tuple[str, str]:
    """A connection of its own: the app's lives in the request lifespan, and
    this runs from a terminal where there is no request."""
    from app.clients.redis import RedisClient

    redis = RedisClient()
    try:
        await redis.connect()
        answered = await redis.ping()
    except Exception as exc:
        return "unhealthy", f"PING failed: {exc}"
    finally:
        await redis.close()
    return ("healthy", "PING answered") if answered else ("unhealthy", "PING failed")


def _vault_configured() -> tuple[str, str]:
    """A vault with no key cannot unseal a provider credential, so no agent runs."""
    if not settings.VAULT_MASTER_KEY:
        return "unhealthy", "VAULT_MASTER_KEY is unset - no stored credential can be unsealed"
    return "healthy", "a key is configured"


async def _run() -> int:
    failures = 0
    async with get_db_context() as db:
        database = await probe_database(db)
        failures += _report("database", database.status, database.detail)

        if database.status != "healthy":
            error("Nothing else can be checked without a database. Is it running?")
            return 1

        status, detail = await _migrations_current(db)
        failures += _report("migrations", status, detail)

        vector = await probe_vector_store(db)
        failures += _report("vector store", vector.status, vector.detail)

        model = await probe_model_access(db)
        failures += _report("model access", model.status, model.detail)

    status, detail = await _redis_reachable()
    failures += _report("redis", status, detail)

    status, detail = _vault_configured()
    failures += _report("vault", status, detail)

    return failures


@command("doctor", help="Check that this deployment can actually run an agent")
def doctor() -> None:
    """Diagnose a deployment, in dependency order.

    Exits non-zero when something is broken, so it can gate a provisioning
    script. A subsystem that is merely unconfigured - pgvector not installed on
    a deployment that has never ingested anything - is a warning, not a failure.

    Example:
        agenticos cmd doctor
    """
    info(f"Checking {settings.PROJECT_NAME} at {settings.POSTGRES_HOST}...")
    failures = asyncio.run(_run())
    if failures:
        error(f"{failures} check(s) failed.")
        raise SystemExit(1)
    success("Everything this can check is working.")
