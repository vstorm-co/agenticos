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
    if not settings.VAULT_MASTER_KEY and not settings.VAULT_MASTER_KEYS:
        return "unhealthy", "VAULT_MASTER_KEY is unset - no stored credential can be unsealed"
    return "healthy", "a key is configured"


async def _sandbox_connections(db: Any) -> tuple[str, str]:
    """Whether every registered sandbox host can actually be reached.

    Unconfigured is not a failure: the `state` backend needs no service and is
    what a default install runs on. What *is* a failure is a connection that is
    registered and does not answer - an agent bound to it then fails on its
    first tool call, inside somebody's conversation, with a connection error
    nobody was watching for.

    Every active `docker` connection in the deployment is probed, not one
    address: an organization may run two hosts, and a deployment hosts many
    organizations. Daytona is skipped because there is nothing local to reach -
    the credential is validated by their API on first use.

    The token is checked as well as the address. `/healthz` is deliberately
    unauthenticated, so a probe that stopped there would report a healthy
    service to a deployment holding the wrong secret while every session was
    still refused. The credential is unsealed here for that one request and
    never printed - a doctor line that leaked a token would be worse than the
    outage it diagnoses.
    """
    from sqlalchemy import select

    from app.db.models.organization_secret import OrganizationSecret
    from app.db.models.sandbox_connection import SandboxConnection

    rows = (
        (
            await db.execute(
                select(SandboxConnection, OrganizationSecret)
                .outerjoin(OrganizationSecret, OrganizationSecret.id == SandboxConnection.secret_id)
                .where(SandboxConnection.is_active.is_(True))
                .where(SandboxConnection.kind == "docker")
            )
        )
        .tuples()
        .all()
    )
    if not rows:
        return "unconfigured", "no sandbox connection registered - only 'state' workspaces run"

    problems: list[str] = []
    healthy = 0
    for connection, secret in rows:
        detail = await _probe_connection(connection, secret)
        if detail is None:
            healthy += 1
        else:
            problems.append(f"{connection.name}: {detail}")

    if problems:
        return "unhealthy", "; ".join(problems)
    return "healthy", f"{healthy} connection(s) answered /policy with a runtime"


async def _probe_connection(connection: Any, secret: Any) -> str | None:
    """What is wrong with one connection, or `None` if nothing is."""
    from app.core.secret_kinds import ApiKeySecret, SecretKind, unseal_secret
    from app.core.vault import VaultScope

    if secret is None:
        return "no credential in the vault - re-attach one"
    try:
        unsealed = unseal_secret(
            secret.sealed_secret,
            kind=SecretKind(secret.kind),
            scope=VaultScope.organization(connection.organization_id),
            key_version=secret.key_version,
        )
    except Exception as exc:
        return f"its credential could not be unsealed: {exc}"
    if not isinstance(unsealed, ApiKeySecret):
        return f"its credential is a {secret.kind}, which cannot authenticate a sandbox service"

    import httpx

    base = (connection.base_url or "").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            (await client.get(f"{base}/healthz")).raise_for_status()
            policy = await client.get(
                f"{base}/policy",
                headers={"X-Sandbox-Token": unsealed.api_key.get_secret_value()},
            )
    except Exception as exc:
        return f"{base} did not answer: {exc}"

    if policy.status_code == 401:
        return "the service answered but refused its credential"
    if policy.status_code != 200:
        return f"/policy answered {policy.status_code}"
    if not policy.json().get("runtimes"):
        return "the service allows no runtime, so no sandbox can start"
    return None


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

    # A session of its own, after the vault check rather than beside the database
    # ones above: unsealing a connection's credential is meaningless while the
    # vault has no key, and reporting "did not answer" for that would name the
    # wrong cause.
    async with get_db_context() as db:
        status, detail = await _sandbox_connections(db)
    failures += _report("sandbox connections", status, detail)

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
