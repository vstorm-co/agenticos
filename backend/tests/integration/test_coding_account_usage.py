"""Refresh ownership, queue deduplication and generation revocation against PostgreSQL."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.clients.redis import RedisClient
from app.core.exceptions import ConflictError, NotFoundError
from app.core.secret_kinds import OpenAICodexSecret
from app.db.models.background_job import BackgroundJob
from app.db.models.organization import OrganizationMember
from app.schemas.coding_account import CodingAccountUpdate
from app.services.coding_account_usage import CodingAccountUsageService
from app.services.coding_account_usage import _refresh as worker
from app.services.coding_accounts import CodingAccountService
from app.worker.jobs import REFRESH_CODING_ACCOUNT_USAGE, RefreshCodingAccountUsage
from tests.integration.test_personal_coding_accounts import context, organization, person

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_only_owner_can_queue_refresh_and_changed_generation_cannot_execute(
    engine: AsyncEngine,
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        owner, other = await person(db), await person(db)
        org = await organization(db, owner)
        elsewhere = await organization(db, owner)
        db.add(OrganizationMember(organization_id=org.id, user_id=other.id, role="admin"))
        await db.flush()
        accounts = CodingAccountService(db)
        row = await accounts.save(
            context(owner, org),
            harness="codex",
            label="Owned Codex",
            enabled=True,
            secret=OpenAICodexSecret(
                access_token="fixture-private-access",
                refresh_token="fixture-private-refresh",
                account_id="fixture-provider-account",
            ),
        )
        redis = AsyncMock(spec=RedisClient)
        redis.get.return_value = None
        service = CodingAccountUsageService(db, redis)
        for foreign in (context(other, org), context(owner, elsewhere)):
            with pytest.raises(NotFoundError):
                await service.read(foreign, row.id)
            with pytest.raises(NotFoundError):
                await service.refresh(foreign, row.id, row.generation)
        first = await service.refresh(context(owner, org), row.id, row.generation)
        repeated = await service.refresh(context(owner, org), row.id, row.generation)
        assert first.refresh_pending and repeated.refresh_pending
        jobs = (
            await db.scalars(
                select(BackgroundJob).where(
                    BackgroundJob.organization_id == org.id,
                    BackgroundJob.kind == REFRESH_CODING_ACCOUNT_USAGE.kind,
                )
            )
        ).all()
        assert len(jobs) == 1
        job = jobs[0]
        assert "fixture-private" not in str(job.payload)
        request = RefreshCodingAccountUsage.model_validate(job.payload)
        assert request.user_id == owner.id and request.account_id == row.id
        job.status, job.attempts = "running", 1
        await db.flush()
        assert await worker.current(db, request, 1) is not None
        old_generation = row.generation
        await accounts.update(
            context(owner, org),
            row.id,
            CodingAccountUpdate(generation=old_generation, enabled=False),
        )
        assert await worker.current(db, request, 1) is None
        with pytest.raises(ConflictError):
            await service.refresh(context(owner, org), row.id, old_generation)
        disabled = await service.read(context(owner, org), row.id)
        assert disabled.usage.status == "disabled" and not disabled.refresh_pending
        redis.set.assert_not_awaited()
