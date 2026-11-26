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


async def test_custom_endpoint_passes_test_then_omits_usage_settles_partial_and_stops_job(
    engine, monkeypatch
):
    import httpx
    from openai import AsyncOpenAI, OpenAI

    from app.agents.capabilities.budget import SpendLedger, metered_by
    from app.core.permissions import AuthContext
    from app.db.models.organization import OrganizationMember
    from app.services.embedding_probe_call import run_probe_call
    from app.services.embedding_resolution import (
        EmbeddingKeySource,
        TargetIdentity,
        _requires_reported_usage,
    )
    from app.services.rag import embeddings
    from app.worker.child import ChildRequest, run_one
    from app.worker.registry import Handler, by_kind
    from app.worker.tasks.rag_tasks import _record_embedding_spend
    from tests import worker_handlers

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    organization_id, user_id = uuid4(), uuid4()
    async with sessions() as seed:
        seed.add(
            User(id=user_id, email=f"{user_id}@example.test", hashed_password="x", is_active=True)
        )
        await seed.flush()
        seed.add(
            Organization(
                id=organization_id,
                name="Paid custom endpoint",
                slug=f"probe-{uuid4().hex}",
                created_by_user_id=user_id,
                monthly_budget_usd=Decimal(1),
            )
        )
        await seed.flush()
        seed.add(
            OrganizationMember(
                id=uuid4(), user_id=user_id, organization_id=organization_id, role="owner"
            )
        )
        await seed.commit()

    calls = 0

    def answer(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body: dict[str, object] = {"data": [{"embedding": [1.0]}]}
        if calls == 1:
            body["usage"] = {"prompt_tokens": 8}
        return httpx.Response(200, json=body)

    model = "text-embedding-3-small"
    identity = TargetIdentity(
        provider="openai_compatible",
        connection_id=uuid4(),
        base_url="https://gateway.test/v1",
        secret_id=uuid4(),
        key_generation=uuid4(),
        key_organization_id=organization_id,
        key_source=EmbeddingKeySource.CONNECTION,
    )

    async def authorize(db, _actor):
        assert await _requires_reported_usage(db, identity)

    client = AsyncOpenAI(
        api_key="fixture",
        base_url=identity.base_url,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(answer)),
        max_retries=0,
    )
    monkeypatch.setattr(embeddings, "AsyncOpenAI", lambda **_: client)

    async def test_call():
        return await embeddings.embed_for_probe(
            base_url=identity.base_url,
            api_key="fixture",
            keyless=False,
            model=model,
            text="width probe",
        )

    assert await run_probe_call(
        actor=AuthContext(user_id=user_id, organization_id=organization_id, role="owner"),
        identity=identity,
        model=model,
        authorize=authorize,
        request=test_call,
    ) == [1.0]
    assert client.is_closed()

    monkeypatch.setattr(embeddings, "EMBED_BATCH_SIZE", 1)
    ledger = SpendLedger(organization_id=organization_id)
    with OpenAI(
        api_key="fixture",
        base_url=identity.base_url,
        http_client=httpx.Client(transport=httpx.MockTransport(answer)),
        max_retries=0,
    ) as sync_client:
        provider = embeddings.OpenAIEmbeddingProvider(
            model=model, api_key="fixture", require_usage=True
        )
        provider._client = sync_client

        async def ingest(_note: worker_handlers.Note) -> None:
            with metered_by(ledger):
                try:
                    provider.embed_queries(["first batch", "must not be sent"])
                finally:
                    await _record_embedding_spend(
                        ledger, organization_id=organization_id, rag_document_id=None
                    )

        task = worker_handlers.tasks()["fail"]
        result = await run_one(
            by_kind([Handler(task, ingest)]), ChildRequest(kind=task.kind, payload={})
        )
    assert not result.ok and result.permanent
    assert calls == 2  # One successful Test, one refused batch, no paid replay.
    async with sessions() as verify:
        rows = list(
            (
                await verify.execute(
                    select(IngestionSpend).where(IngestionSpend.organization_id == organization_id)
                )
            ).scalars()
        )
        assert len(rows) == 2
        assert sum(row.cost_usd for row in rows) == Decimal("0.00000016")
        assert sum(row.cost_is_partial for row in rows) == 1
