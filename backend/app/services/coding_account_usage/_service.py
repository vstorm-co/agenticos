"""Owner-scoped observation reads and transactional refresh admission."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.coding_account import CodingAccount
from app.repositories import background_job as job_repo
from app.repositories import coding_account as account_repo
from app.repositories import member as member_repo
from app.schemas.base import BaseSchema
from app.schemas.coding_account import (
    CodingAccountRead,
    CodingAccountUsageRead,
    ProviderUsageSnapshot,
)
from app.services.background_jobs import enqueue
from app.services.coding_accounts import CodingAccountService, account_owner
from app.worker.jobs import REFRESH_CODING_ACCOUNT_USAGE, RefreshCodingAccountUsage

from ._runtime import Observation


class CachedObservation(BaseSchema):
    organization_id: UUID
    user_id: UUID
    account_id: UUID
    generation: UUID
    observation: Observation


def account_key(row: CodingAccount) -> str:
    return f"coding-account-usage:{row.organization_id}:{row.user_id}:{row.id}:{row.generation}"


def request_key(request_id: UUID) -> str:
    return f"coding-account-usage-request:{request_id}"


def supported(row: CodingAccount) -> bool:
    return row.harness == "codex" and row.secret_kind == "openai_codex"


class CodingAccountUsageService:
    def __init__(self, db: AsyncSession, redis: RedisClient) -> None:
        self.db, self.redis = db, redis

    async def _account(
        self, ctx: AuthContext, account_id: UUID, *, locked: bool = False
    ) -> CodingAccount:
        owner = account_owner(ctx)
        member = await member_repo.get_active(
            self.db, organization_id=ctx.organization_id, user_id=owner
        )
        if member is None:
            raise AuthorizationError(
                message="The coding account owner is no longer an active member"
            )
        row = await account_repo.get(
            self.db,
            organization_id=ctx.organization_id,
            user_id=owner,
            account_id=account_id,
            locked=locked,
        )
        if row is None:
            raise NotFoundError(message="Coding account not found")
        return row

    async def cached(self, row: CodingAccount) -> Observation | None:
        try:
            raw = await self.redis.get(account_key(row))
        except RedisError:
            return None
        if raw is None or len(raw) > 65536:
            return None
        try:
            cached = CachedObservation.model_validate_json(raw)
        except ValidationError:
            return None
        if (
            cached.organization_id != row.organization_id
            or cached.user_id != row.user_id
            or cached.account_id != row.id
            or cached.generation != row.generation
        ):
            return None
        now = datetime.now(UTC)
        usage = cached.observation.usage
        return Observation(
            usage=ProviderUsageSnapshot.normalize(
                status=usage.status,
                source=usage.source,
                observed_at=usage.observed_at,
                valid_until=usage.valid_until,
                windows=usage.windows,
                reason_code=usage.reason_code,
                now=now,
            ),
            model_catalog=cached.observation.model_catalog.fresh(now),
        )

    async def read(self, ctx: AuthContext, account_id: UUID) -> CodingAccountUsageRead:
        """Read current evidence without a provider call, scoped to this owner and generation."""
        return await self._read(await self._account(ctx, account_id))

    async def _read(self, row: CodingAccount) -> CodingAccountUsageRead:
        result = CodingAccountUsageRead(
            account_id=row.id,
            generation=row.generation,
            usage=ProviderUsageSnapshot(reason_code="telemetry_unavailable"),
        )
        if not row.enabled:
            result.usage = ProviderUsageSnapshot(status="disabled")
            return result
        if not supported(row):
            result.usage = ProviderUsageSnapshot(reason_code="telemetry_unsupported")
            return result
        observed = await self.cached(row)
        if observed is not None:
            result.usage, result.model_catalog = observed.usage, observed.model_catalog
        job = await job_repo.latest_with_dedupe_key(self.db, account_key(row))
        result.refresh_pending = job is not None and job.status in ("queued", "running")
        return result

    async def mine(self, ctx: AuthContext) -> list[CodingAccountRead]:
        """Enrich only metadata already visible through the personal account service."""
        result: list[CodingAccountRead] = []
        for row in await CodingAccountService(self.db).mine(ctx):
            data = CodingAccountRead.model_validate(row)
            observed = await self._read(row)
            data.usage, data.model_catalog = observed.usage, observed.model_catalog
            data.usage_refresh_pending = observed.refresh_pending
            result.append(data)
        return result

    async def refresh(
        self, ctx: AuthContext, account_id: UUID, generation: UUID
    ) -> CodingAccountUsageRead:
        """Queue one bounded native read; never start a task or silently change an account.

        Admission and the durable job commit with the request. A repeated active
        request shares that job; completed requests have a thirty-second cooldown.
        """
        row = await self._account(ctx, account_id, locked=True)
        if row.generation != generation:
            raise ConflictError(
                message="The coding account changed. Reload it before refreshing usage."
            )
        if not row.enabled:
            raise BadRequestError(message="Enable this coding account before refreshing usage")
        if not supported(row):
            raise BadRequestError(
                message="Usage refresh currently supports Codex ChatGPT sign-ins only"
            )
        key = account_key(row)
        latest = await job_repo.latest_with_dedupe_key(self.db, key)
        if latest is not None:
            if latest.status in ("queued", "running"):
                return await self._read(row)
            if latest.created_at > datetime.now(UTC) - timedelta(seconds=30):
                raise ConflictError(
                    message="Usage was just refreshed. Try again in thirty seconds."
                )
        request_id = uuid4()
        await enqueue(
            self.db,
            REFRESH_CODING_ACCOUNT_USAGE,
            RefreshCodingAccountUsage(
                organization_id=row.organization_id,
                user_id=row.user_id,
                account_id=row.id,
                generation=row.generation,
                request_id=request_id,
            ),
            organization_id=row.organization_id,
            dedupe_key=key,
            dedupe_active=True,
            concurrency_key=f"coding-account-usage:{row.organization_id}:{row.user_id}:{row.id}",
            idempotency_key=request_key(request_id),
        )
        result = await self._read(row)
        result.refresh_pending = True
        return result
