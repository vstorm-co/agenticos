"""Durable probe execution; personal observations never become admin job results."""

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.exceptions import BadRequestError, ConflictError
from app.core.permissions import AuthContext
from app.db.models.coding_account import CodingAccount
from app.db.session import get_worker_db_context
from app.repositories import background_job as job_repo
from app.repositories import coding_account as account_repo
from app.schemas.coding_account import ProviderModelCatalog, ProviderUsageSnapshot, UsageReasonCode
from app.services.api_key import job_context
from app.services.coding_account_lease import account_lease
from app.services.personal_codex import PersonalCodexCredentials
from app.services.sandbox_workspace import SandboxWorkspaceService
from app.worker.attempt import current_attempt_number
from app.worker.jobs import RefreshCodingAccountUsage

from ._runtime import Observation, ProbeUnavailable, read_usage
from ._service import (
    CachedObservation,
    CodingAccountUsageService,
    account_key,
    request_key,
    supported,
)


async def current(
    db: AsyncSession,
    payload: RefreshCodingAccountUsage,
    fence: int,
) -> tuple[AuthContext, CodingAccount] | None:
    job = await job_repo.get_by_idempotency_key(
        db,
        organization_id=payload.organization_id,
        idempotency_key=request_key(payload.request_id),
    )
    if job is None or await job_repo.get_for_attempt(db, job.id, fence=fence) is None:
        return None
    ctx = await job_context(
        db,
        organization_id=payload.organization_id,
        user_id=payload.user_id,
        api_key_id=None,
    )
    if ctx is None:
        return None
    row = await account_repo.get(
        db,
        organization_id=payload.organization_id,
        user_id=payload.user_id,
        account_id=payload.account_id,
        locked=True,
    )
    if row is None or not row.enabled or row.generation != payload.generation or not supported(row):
        return None
    return ctx, row


async def probe(
    payload: RefreshCodingAccountUsage,
    ctx: AuthContext,
    redis: RedisClient,
) -> Observation:
    key = f"personal-coding:{payload.organization_id}:{payload.user_id}:{payload.account_id}"
    async with account_lease(key, 110, redis=redis), get_worker_db_context() as db:
        service = SandboxWorkspaceService(db)
        opened = await service.open_account_usage(ctx, request_id=payload.request_id)
        try:
            return await read_usage(
                opened.workspace,
                PersonalCodexCredentials(
                    payload.organization_id, payload.user_id, payload.account_id, payload.generation
                ),
            )
        finally:
            with anyio.move_on_after(10, shield=True):
                await service.close(opened)


async def publish(
    payload: RefreshCodingAccountUsage,
    fence: int,
    redis: RedisClient,
    observation: Observation | None,
    failure: UsageReasonCode | None,
) -> None:
    async with get_worker_db_context() as db:
        held = await current(db, payload, fence)
        if held is None:
            return
        _ctx, row = held
        if observation is None:
            previous = await CodingAccountUsageService(db, redis).cached(row)
            if (
                failure != "provider_identity_mismatch"
                and previous is not None
                and (
                    previous.usage.source != "unavailable"
                    or previous.model_catalog.status == "advertised"
                )
            ):
                return
            observation = Observation(
                usage=ProviderUsageSnapshot(reason_code=failure or "telemetry_unavailable"),
                model_catalog=ProviderModelCatalog(),
            )
        envelope = CachedObservation(
            organization_id=row.organization_id,
            user_id=row.user_id,
            account_id=row.id,
            generation=row.generation,
            observation=observation,
        )
        # The queue attempt and account generation remain locked until this
        # write completes. Later generations use a different key immediately.
        await redis.set(account_key(row), envelope.model_dump_json(), ttl=300)


async def refresh_usage(payload: RefreshCodingAccountUsage) -> None:
    """Recheck current authority at admission and fenced publication; return no private result."""
    fence = current_attempt_number()
    async with get_worker_db_context() as db:
        held = await current(db, payload, fence)
        if held is None:
            return
        ctx, _row = held
    # No database lock crosses native startup or a provider request.
    redis = RedisClient()
    observation: Observation | None = None
    failure: UsageReasonCode | None = None
    try:
        await redis.connect()
        try:
            with anyio.fail_after(100):
                observation = await probe(payload, ctx, redis)
        except ProbeUnavailable as unavailable:
            failure = unavailable.reason
        except ConflictError:
            failure = "provider_busy"
        except BadRequestError:
            failure = "telemetry_unsupported"
        except TimeoutError:
            failure = "probe_timeout"
        await publish(payload, fence, redis, observation, failure)
    finally:
        with anyio.move_on_after(5, shield=True):
            await redis.close()
