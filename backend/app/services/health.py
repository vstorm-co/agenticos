"""What this deployment can actually verify about itself.

Two audiences read health, and they want different things. Kubernetes wants one
bit - should traffic come here - from an endpoint nobody authenticates to, and
it wants it while everything else is timing out. An operator on the admin page
wants to know which backing service is broken and what was tested to decide
that. The generated template served both from one payload, which is how
`/health/ready` came to carry a Stripe row, a vector-store check that never
checked anything, and a provider check reading environment variables that no run
has touched since credentials moved into the vault.

So the probes live here, each returning what it verified, and the two endpoints
compose only the checks they are entitled to:

* `GET /health/ready` - unauthenticated. The two dependencies that gate
  traffic, as status and latency and nothing else. It deliberately does not echo
  a driver error: "connection to server at 10.0.1.7 failed: password
  authentication failed for user postgres" is a useful line in a log and a map
  of the network to a stranger.
* `GET /admin/system` - authenticated, app admin. The same two, plus the
  deployment facts an operator asks about, each with the detail behind it.

Two rules hold for everything below.

**No probe reports a status it did not verify.** `healthy` means a query came
back. A check that cannot be performed says `unconfigured` or `not_checked`
and says why; nothing here guesses.

**No probe hangs.** Every await is bounded by :data:`PROBE_TIMEOUT_SECONDS`. A
health endpoint that blocks is an outage of its own - readiness is the one
request that has to answer when the database has stopped answering, and a probe
that times out at the kubelet is indistinguishable from a wedged pod.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy import distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.config import settings
from app.db.models.credential import ModelProfile
from app.schemas.health import SystemCheck, SystemHealthResponse

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 2.0
"""Ceiling for a single probe.

Short on purpose: each of these is a local round trip, and what a readiness
probe needs when Postgres is unreachable is "not ready" now rather than the
truth in thirty seconds.
"""

_PGVECTOR_VERSION = text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")

# What the *image* ships and what this *role* may do with it - both different
# questions from whether the extension has been created here, and between them
# the ones that decide what the first ingestion does. `pg_extension` alone
# cannot tell a fresh deployment apart from a stock-postgres one, and reporting
# the second's consequence for the first is how a working deployment read as
# broken (#1504).
#
# `CREATE EXTENSION` is a superuser action unless the extension is trusted, in
# which case CREATE on the database is enough. Asked rather than assumed: an
# application connecting as a restricted role sees `vector` listed here and
# still cannot create it, so availability alone is one more consequence claimed
# without evidence.
_PGVECTOR_CAPABILITY = text(
    "SELECT "
    "(SELECT default_version FROM pg_available_extensions WHERE name = 'vector'), "
    "(SELECT bool_or(trusted) FROM pg_available_extension_versions WHERE name = 'vector'), "
    "current_setting('is_superuser') = 'on', "
    "has_database_privilege(current_database(), 'CREATE')"
)

# Tables carrying an embedding column, which is what the RAG store creates per
# collection. Counted, never named: the count answers "is anything ingested
# here", the names are the organizations' business.
_EMBEDDING_TABLE_COUNT = text(
    "SELECT count(DISTINCT table_name) FROM information_schema.columns "
    "WHERE table_schema = 'public' AND udt_name = 'vector'"
)


def build_health_response(
    status: str,
    checks: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "service": settings.PROJECT_NAME,
    }
    if checks is not None:
        response["checks"] = checks
    if details is not None:
        response["details"] = details
    return response


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)


def _timed_out(key: str, what: str) -> SystemCheck:
    logger.warning("%s health probe timed out after %ss", key, PROBE_TIMEOUT_SECONDS)
    return SystemCheck(
        key=key,
        status="unhealthy",
        detail=f"{what} did not answer within {PROBE_TIMEOUT_SECONDS:g}s",
    )


def _not_checked(key: str, because: str) -> SystemCheck:
    return SystemCheck(key=key, status="not_checked", detail=f"not checked: {because}")


async def _abandon_the_transaction(db: AsyncSession) -> None:
    """Leave the session usable after a probe's query has failed on it.

    A statement that raises leaves its transaction in a failed state, and every
    later use of that session - including the commit the request's session
    dependency performs on the way out - raises too. That commit now runs
    *before* the response is written (#353), so without this the endpoint an
    operator reads because something is wrong answers 500 instead of the 503 it
    diagnosed. Before #353 the same commit failed after the 503 had been sent,
    which merely logged a traceback per readiness probe and told Starlette its
    response had already started.

    A rollback here does no I/O: the session either never acquired a connection
    or holds one already invalidated. It is still guarded, because a session
    that cannot be reset is not a reason for a health endpoint to raise.
    """
    try:
        await db.rollback()
    except Exception:
        logger.warning("could not reset the session after a failed health probe", exc_info=True)


async def probe_database(db: AsyncSession) -> SystemCheck:
    """Round-trip a trivial query.

    The broad `except` is deliberate: this runs on the endpoint an operator
    reads *because* something is wrong, and a probe that propagates turns a
    diagnosis into a 500.
    """
    start = perf_counter()
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            await db.execute(text("SELECT 1"))
    except TimeoutError:
        await _abandon_the_transaction(db)
        return _timed_out("database", "SELECT 1")
    except Exception as exc:
        logger.warning("database health probe failed", exc_info=True)
        await _abandon_the_transaction(db)
        return SystemCheck(key="database", status="unhealthy", detail=f"SELECT 1 failed: {exc}")
    return SystemCheck(
        key="database",
        status="healthy",
        detail="SELECT 1 answered",
        latency_ms=_elapsed_ms(start),
    )


async def probe_redis(redis: RedisClient) -> SystemCheck:
    """PING the cache and queue broker.

    `RedisClient.ping` answers False rather than raising when it has no
    connection, so False is the ordinary failure; the `except` covers a client
    breaking in a way it did not anticipate.
    """
    start = perf_counter()
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            answered = await redis.ping()
    except TimeoutError:
        return _timed_out("redis", "PING")
    except Exception as exc:
        logger.warning("redis health probe failed", exc_info=True)
        return SystemCheck(key="redis", status="unhealthy", detail=f"PING failed: {exc}")
    if not answered:
        return SystemCheck(key="redis", status="unhealthy", detail="PING was not answered")
    return SystemCheck(
        key="redis",
        status="healthy",
        detail="PING answered",
        latency_ms=_elapsed_ms(start),
    )


async def probe_vector_store(db: AsyncSession) -> SystemCheck:
    """Ask Postgres whether it can hold embeddings at all.

    The vector store is pgvector in this same database, so there is no second
    service to reach and the honest question is whether the extension is
    installed and how many collection tables exist. Both are catalog reads,
    which is what makes this cheap enough for a page that refreshes itself.

    A missing extension is usually `unconfigured`, not `unhealthy`: the RAG store
    runs `CREATE EXTENSION IF NOT EXISTS vector` the first time a collection is
    written to, so a deployment that never ingests a document is working exactly
    as installed - and it will keep working when somebody uploads one.

    Usually, because "absent" covers four situations with two different outcomes,
    and the row in `pg_extension` distinguishes none of them. What decides is
    whether the image ships pgvector and whether this role may create it, so both
    are asked before any consequence is claimed - the whole defect here was
    claiming one (#1504):

    | Ships it | Created | This role may create it | |
    |---|---|---|---|
    | yes | yes | - | `healthy` |
    | yes | no | yes | `unconfigured`, and the first ingestion creates it |
    | yes | no | no | `unhealthy` - a restricted role, and it fails at the upload |
    | no | no | - | `unhealthy` - stock Postgres, the gotcha CLAUDE.md opens with |
    | no | yes | - | `unhealthy` - a volume that outlived its image |

    That last row is why availability is read whether or not the extension exists.
    A data directory carrying the `pg_extension` row, started on an image without
    the library, keeps the row and loses `$libdir/vector`: the catalog says
    installed, the collection tables are still countable, and every vector
    operation fails.
    """
    start = perf_counter()
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            available, trusted, superuser, may_create = (
                await db.execute(_PGVECTOR_CAPABILITY)
            ).one()
            version = (await db.execute(_PGVECTOR_VERSION)).scalar_one_or_none()
            if available is None:
                return SystemCheck(
                    key="vector_store",
                    status="unhealthy",
                    detail=(
                        "this Postgres image does not ship pgvector, so vector "
                        "operations fail loading $libdir/vector; the database must be "
                        "pgvector/pgvector:pg16"
                        if version is not None
                        else "this Postgres image does not ship pgvector, so the first "
                        "document ingestion will fail after accepting the upload; "
                        "the database must be pgvector/pgvector:pg16"
                    ),
                    latency_ms=_elapsed_ms(start),
                )
            if version is None:
                if not (superuser or (trusted and may_create)):
                    return SystemCheck(
                        key="vector_store",
                        status="unhealthy",
                        detail=(
                            f"pgvector {available} is available but this database role "
                            "cannot create it, so the first document ingestion will fail "
                            "after accepting the upload; create the extension as a "
                            "superuser, once"
                        ),
                        latency_ms=_elapsed_ms(start),
                    )
                return SystemCheck(
                    key="vector_store",
                    status="unconfigured",
                    detail=(
                        f"pgvector {available} is available and this role may create it; "
                        "the first document ingestion does"
                    ),
                    latency_ms=_elapsed_ms(start),
                )
            tables = (await db.execute(_EMBEDDING_TABLE_COUNT)).scalar_one()
    except TimeoutError:
        await _abandon_the_transaction(db)
        return _timed_out("vector_store", "the pgvector catalog query")
    except Exception as exc:
        logger.warning("vector store health probe failed", exc_info=True)
        await _abandon_the_transaction(db)
        return SystemCheck(
            key="vector_store",
            status="unhealthy",
            detail=f"reading the pgvector catalog failed: {exc}",
        )
    return SystemCheck(
        key="vector_store",
        status="healthy",
        detail=f"pgvector {version} installed, {tables} collection table(s) with embeddings",
        latency_ms=_elapsed_ms(start),
    )


async def probe_model_access(db: AsyncSession) -> SystemCheck:
    """Whether anything in this deployment is configured to run a model.

    What this does not do is call a provider. That would spend money on a page
    that refreshes itself, and a key's validity is not something a
    deployment-wide endpoint can speak for anyway: credentials are sealed per
    organization and chosen through model profiles, so "is the LLM up" has no
    single answer here.

    What is answerable - and what an operator is actually asking when they look
    at this row - is whether any organization could run anything. The join
    mirrors what `ModelProfileService.resolve` requires, a profile pointing at
    a credential that is still active, so a profile counted here is a profile a
    run can use up to the key having been revoked upstream. The count says that
    much and claims nothing more.
    """
    start = perf_counter()
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            usable = select(
                func.count(ModelProfile.id),
                func.count(distinct(ModelProfile.organization_id)),
            ).where(ModelProfile.secret_id.is_not(None))
            profiles, organizations = (await db.execute(usable)).one()
    except TimeoutError:
        await _abandon_the_transaction(db)
        return _timed_out("model_access", "the model profile query")
    except Exception as exc:
        logger.warning("model access health probe failed", exc_info=True)
        await _abandon_the_transaction(db)
        return SystemCheck(
            key="model_access",
            status="unhealthy",
            detail=f"counting usable model profiles failed: {exc}",
        )
    if not profiles:
        return SystemCheck(
            key="model_access",
            status="unconfigured",
            detail=(
                "no organization has a model profile with an active key, so an agent run "
                "will fail when it resolves a model"
            ),
            latency_ms=_elapsed_ms(start),
        )
    return SystemCheck(
        key="model_access",
        status="healthy",
        detail=(
            f"{profiles} model profile(s) with an active key across "
            f"{organizations} organization(s); no provider was called"
        ),
        latency_ms=_elapsed_ms(start),
    )


_HEARTBEAT_DEPLOYMENT = "agent-triggers-check"
"""The trigger heartbeat's deployment, as `app/worker/prefect_app.py` registers it.

The heartbeat stands for every interval deployment there: one scheduler service
creates all their runs and one runner executes them, so when this one stops
completing, the others have stopped with it.
"""

_HEARTBEAT_SECONDS = 60
"""The heartbeat's declared interval in `app/worker/prefect_app.py`."""

_MISSED_HEARTBEATS = 5
"""How many intervals may pass without a completed heartbeat before it is a failure.

One missed tick is a slow run or a runner restart; five is a stopped scheduler.
"""


async def _last_heartbeat() -> datetime | None:
    """When the trigger heartbeat last completed, according to Prefect - or never.

    Imported here rather than at the top: the API process otherwise loads Prefect
    only when it dispatches a run, and this module is imported at start-up.
    """
    from prefect.client.orchestration import get_client
    from prefect.client.schemas.filters import (
        DeploymentFilter,
        DeploymentFilterName,
        FlowRunFilter,
        FlowRunFilterState,
        FlowRunFilterStateType,
    )
    from prefect.client.schemas.objects import StateType
    from prefect.client.schemas.sorting import FlowRunSort

    async with get_client() as client:
        runs = await client.read_flow_runs(
            deployment_filter=DeploymentFilter(
                name=DeploymentFilterName(any_=[_HEARTBEAT_DEPLOYMENT])
            ),
            flow_run_filter=FlowRunFilter(
                state=FlowRunFilterState(type=FlowRunFilterStateType(any_=[StateType.COMPLETED]))
            ),
            sort=FlowRunSort.END_TIME_DESC,
            limit=1,
        )
    return runs[0].end_time if runs else None


async def probe_scheduler() -> SystemCheck:
    """Whether scheduled work is actually running, judged by the trigger heartbeat.

    The Prefect server's own health says nothing about this. From 2026-09-28 to
    2026-10-09 its scheduler failed on every tick (PrefectHQ/prefect#23199) and
    created no runs, while `/api/health` answered and every deployment read
    `READY`; scheduled triggers, notification emails and the sweeps all stopped,
    and nothing reported it. A completed heartbeat is the one fact that needs the
    scheduler, the runner and the database all working, so its age is the check.

    The threshold honours `WORKER_MIN_INTERVAL_SECONDS` the way the deployment
    does, or a development machine that slows its ticks would always read failed.
    """
    interval = max(_HEARTBEAT_SECONDS, settings.WORKER_MIN_INTERVAL_SECONDS)
    start = perf_counter()
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            completed_at = await _last_heartbeat()
    except TimeoutError:
        return _timed_out("scheduler", "the Prefect API")
    except Exception as exc:
        logger.warning("scheduler health probe failed", exc_info=True)
        return SystemCheck(
            key="scheduler",
            status="unhealthy",
            detail=f"reading flow runs from the Prefect API failed: {exc}",
        )
    latency = _elapsed_ms(start)
    if completed_at is None:
        return SystemCheck(
            key="scheduler",
            status="unhealthy",
            detail=(
                f"no {_HEARTBEAT_DEPLOYMENT} run has ever completed, so scheduled triggers, "
                "notification emails and sweeps are not running; check the Prefect server "
                "log for scheduler errors and that the worker is up"
            ),
            latency_ms=latency,
        )
    age = (datetime.now(UTC) - completed_at).total_seconds()
    if age > interval * _MISSED_HEARTBEATS:
        return SystemCheck(
            key="scheduler",
            status="unhealthy",
            detail=(
                f"the {_HEARTBEAT_DEPLOYMENT} heartbeat last completed {age / 60:.0f} min ago "
                f"(expected every {interval}s), so scheduled triggers, notification emails "
                "and sweeps are not running; check the Prefect server log for scheduler "
                "errors and that the worker is up"
            ),
            latency_ms=latency,
        )
    return SystemCheck(
        key="scheduler",
        status="healthy",
        detail=f"the {_HEARTBEAT_DEPLOYMENT} heartbeat completed {age:.0f}s ago",
        latency_ms=latency,
    )


async def readiness(*, db: AsyncSession, redis: RedisClient) -> tuple[bool, dict[str, Any]]:
    """The Kubernetes answer: is this instance fit to serve traffic.

    Only the dependencies a request cannot proceed without are consulted - the
    rest is deployment configuration, worth showing an operator and never a
    reason to pull a pod out of the load balancer. The payload carries status and
    latency only; why a check failed goes to the log, which is already scoped to
    whoever is allowed to read it.

    Returns:
        Whether traffic should be accepted, and the per-check payload to publish.
    """
    checks = await asyncio.gather(probe_database(db), probe_redis(redis))
    ready = all(check.status == "healthy" for check in checks)
    published: dict[str, Any] = {
        check.key: {"status": check.status, "latency_ms": check.latency_ms} for check in checks
    }
    return ready, published


async def system_health(*, db: AsyncSession, redis: RedisClient) -> SystemHealthResponse:
    """Every check this deployment can perform, for an operator who is signed in.

    The database probe gates the two that read through it. Not for speed - a
    timed-out query leaves the session unusable, and the cascade of driver errors
    that follows reports three broken things when one is. `not_checked` names
    the reason instead.
    """
    database, redis_check, scheduler = await asyncio.gather(
        probe_database(db), probe_redis(redis), probe_scheduler()
    )
    if database.status == "healthy":
        vector_store = await probe_vector_store(db)
        model_access = await probe_model_access(db)
    else:
        vector_store = _not_checked("vector_store", "the database probe failed")
        model_access = _not_checked("model_access", "the database probe failed")

    return SystemHealthResponse(
        checked_at=datetime.now(UTC),
        checks=[database, redis_check, vector_store, model_access, scheduler],
    )
