"""Diagnostic receipts retain fractional fees without borrowing the request pool."""

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models.ingestion_spend import IngestionSpend
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import get_independent_db_context
from app.repositories import ingestion_spend_repo
from app.services.spend import organization_monthly_spend

pytestmark = pytest.mark.anyio


async def test_fractional_receipt_survives_request_rollback_and_saturated_pool(engine):
    original = create_async_engine(
        settings.DATABASE_URL, pool_size=1, max_overflow=0, pool_timeout=0.2
    )
    sessions = async_sessionmaker(original, expire_on_commit=False)
    organization_id, user_id = uuid4(), uuid4()
    async with sessions() as seed:
        seed.add(
            User(id=user_id, email=f"{user_id}@example.test", hashed_password="x", is_active=True)
        )
        await seed.flush()
        seed.add(
            Organization(
                id=organization_id,
                name="Probe",
                slug=f"probe-{uuid4().hex}",
                created_by_user_id=user_id,
            )
        )
        await seed.commit()
    try:
        async with sessions() as caller:
            await caller.execute(text("SELECT 1"))
            # This transaction owns the only pooled connection. Its uncommitted
            # state must neither block settlement nor be committed by it.
            caller.add(User(id=uuid4(), email="rollback-probe@example.test", hashed_password="x"))
            await caller.flush()
            async with asyncio.timeout(2), get_independent_db_context() as receipt:
                await ingestion_spend_repo.record(
                    receipt,
                    organization_id=organization_id,
                    rag_document_id=None,
                    model="text-embedding-3-small",
                    input_tokens=8,
                    output_tokens=0,
                    cost_usd=Decimal("0.00000016"),
                    cost_is_partial=False,
                )
            assert caller.in_transaction()
            await caller.rollback()
        async with sessions() as verify:
            row = (
                await verify.execute(
                    select(IngestionSpend).where(IngestionSpend.organization_id == organization_id)
                )
            ).scalar_one()
            assert row.cost_usd == Decimal("0.000000160000")
            assert await organization_monthly_spend(verify, organization_id) == Decimal(
                "0.00000016"
            )
            assert (
                await verify.execute(
                    select(User).where(User.email == "rollback-probe@example.test")
                )
            ).scalar_one_or_none() is None
    finally:
        await original.dispose()


async def test_pgvector_rejects_finite_binary64_overflow(engine):
    from sqlalchemy.exc import DBAPIError

    async with engine.begin() as db:
        await db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    with pytest.raises(DBAPIError, match="out of range"):
        async with engine.begin() as db:
            await db.execute(text("SELECT '[1e308]'::vector"))
    async with engine.begin() as db:
        assert await db.scalar(text("SELECT vector_dims('[3.4028234663852886e38]'::vector)")) == 1


async def test_pgvector_wide_hnsw_cast_requires_half_precision(engine):
    from sqlalchemy.exc import DBAPIError

    async with engine.begin() as db:
        await db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        assert (
            await db.scalar(
                text("SELECT vector_dims(CAST(:vector AS vector(2001)))"),
                {"vector": "[" + ",".join(["70000"] * 2001) + "]"},
            )
            == 2001
        )
    with pytest.raises(DBAPIError, match="out of range"):
        async with engine.begin() as db:
            await db.execute(
                text("SELECT CAST(:vector AS vector(2001))::halfvec(2001)"),
                {"vector": "[" + ",".join(["70000"] * 2001) + "]"},
            )
    async with engine.begin() as db:
        assert (
            await db.scalar(
                text("SELECT vector_dims(CAST(:vector AS vector(2001))::halfvec(2001))"),
                {"vector": "[" + ",".join(["65504"] * 2001) + "]"},
            )
            == 2001
        )
