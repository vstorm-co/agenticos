"""A capped custom endpoint cannot turn omitted usage into another paid batch."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.capabilities.budget import (
    BudgetGuard,
    BudgetScope,
    SpendLedger,
    SpendLimit,
    guarded_by,
    metered_by,
)
from app.core.exceptions import EmbeddingBudgetError
from app.services import embedding_resolution as resolution
from app.services.embedding_resolution import EmbeddingKeySource, TargetIdentity
from app.services.rag import embeddings
from app.services.rag.embeddings import OpenAIEmbeddingProvider
from app.worker.child import ChildRequest, run_one
from app.worker.registry import Handler, by_kind
from tests import worker_handlers
from tests.embedding_responses import embedding_response

pytestmark = pytest.mark.anyio
MODEL = "text-embedding-3-small"


def _provider(
    *, require_usage: bool = False, keyless: bool = False, model: str = MODEL
) -> OpenAIEmbeddingProvider:
    provider = OpenAIEmbeddingProvider(
        model=model, api_key="fixture", keyless=keyless, require_usage=require_usage
    )
    provider._client = MagicMock(
        embeddings=MagicMock(
            with_raw_response=MagicMock(
                create=MagicMock(
                    side_effect=[
                        embedding_response([[1.0]], prompt_tokens=8),
                        embedding_response([[1.0]], prompt_tokens=None),
                        embedding_response([[1.0]], prompt_tokens=8),
                    ]
                )
            )
        )
    )
    return provider


@pytest.mark.parametrize("active_guard", [True, False])
async def test_missing_usage_stops_capped_worker_or_retrieval_before_next_batch(
    monkeypatch, active_guard
):
    monkeypatch.setattr(embeddings, "EMBED_BATCH_SIZE", 1)
    provider = _provider(require_usage=not active_guard)
    ledger = SpendLedger()
    guard = BudgetGuard(
        ledger=ledger,
        limits=[SpendLimit(scope=BudgetScope.RUN, limit_usd=Decimal(1))] if active_guard else [],
    )
    with metered_by(ledger), guarded_by(guard), pytest.raises(EmbeddingBudgetError):
        provider.embed_queries(["one", "two", "must not be sent"])
    assert provider._client.embeddings.with_raw_response.create.call_count == 2
    assert ledger.input_tokens == 8
    assert ledger.total_usd > 0
    assert ledger.has_unpriced_models


@pytest.mark.parametrize("keyless", [True, False])
async def test_uncapped_and_keyless_batches_continue_with_explicit_partial_cost(
    monkeypatch, keyless
):
    monkeypatch.setattr(embeddings, "EMBED_BATCH_SIZE", 1)
    provider = _provider(keyless=keyless)
    ledger = SpendLedger()
    guard = BudgetGuard(
        ledger=ledger,
        limits=[SpendLimit(scope=BudgetScope.RUN, limit_usd=Decimal(1))] if keyless else [],
    )
    with metered_by(ledger), guarded_by(guard):
        assert provider.embed_queries(["one", "two", "three"]) == [[1.0], [1.0], [1.0]]
    assert ledger.input_tokens == 16
    assert ledger.has_unpriced_models


async def test_unknown_model_is_refused_by_active_guard_before_provider_call():
    provider = _provider(model="unreviewed-custom-model")
    ledger = SpendLedger()
    guard = BudgetGuard(
        ledger=ledger, limits=[SpendLimit(scope=BudgetScope.RUN, limit_usd=Decimal(1))]
    )
    with metered_by(ledger), guarded_by(guard), pytest.raises(EmbeddingBudgetError):
        provider.embed_queries(["query"])
    provider._client.embeddings.with_raw_response.create.assert_not_called()


@pytest.mark.parametrize("required", [True, False])
async def test_unreadable_usage_is_partial_and_policy_refusal_under_cap(required):
    from app.core.exceptions import ExternalServiceError

    provider = _provider(require_usage=required)
    provider._client.embeddings.with_raw_response.create.side_effect = None
    provider._client.embeddings.with_raw_response.create.return_value = MagicMock(
        http_response=MagicMock(
            content=b'{"data":[{"embedding":[1]}],"usage":{"prompt_tokens":true}}'
        )
    )
    ledger = SpendLedger()
    with (
        metered_by(ledger),
        pytest.raises(EmbeddingBudgetError if required else ExternalServiceError),
    ):
        provider.embed_queries(["query"])
    assert ledger.has_unpriced_models
    assert ledger.input_tokens == 0


@pytest.mark.parametrize(
    "cap,source,required",
    [
        (None, EmbeddingKeySource.CONNECTION, False),
        (Decimal(1), EmbeddingKeySource.CONNECTION, True),
        (Decimal(1), EmbeddingKeySource.KEYLESS, False),
        (Decimal(1), EmbeddingKeySource.ORGANIZATION, False),
    ],
)
async def test_async_resolution_derives_usage_policy_from_actual_payer_cap(
    monkeypatch, cap, source, required
):
    payer = uuid4()
    identity = TargetIdentity(
        provider="openai_compatible",
        connection_id=uuid4(),
        base_url="https://gateway.test/v1",
        secret_id=uuid4(),
        key_generation=uuid4(),
        key_organization_id=payer,
        key_source=source,
    )
    get_org = AsyncMock(return_value=MagicMock(monthly_budget_usd=cap))
    monkeypatch.setattr(resolution.organization_repo, "get_by_id", get_org)
    assert await resolution._requires_reported_usage(MagicMock(), identity) is required
    if source is EmbeddingKeySource.CONNECTION:
        assert get_org.call_args.args[1] == payer
    else:
        get_org.assert_not_awaited()


async def test_nonretryable_policy_error_reaches_worker_outcome_without_replay():
    calls = 0

    async def policy(_note: worker_handlers.Note) -> None:
        nonlocal calls
        calls += 1
        raise EmbeddingBudgetError(message="endpoint omitted usage")

    task = worker_handlers.tasks()["fail"]
    handlers = by_kind([Handler(task, policy)])
    reply = await run_one(handlers, ChildRequest(kind=task.kind, payload={}))
    assert not reply.ok and reply.permanent
    assert reply.error is not None
    assert "endpoint omitted usage" in reply.error
    assert calls == 1


async def test_worker_requires_a_price_before_any_custom_embedding_call():
    provider = _provider(model="unreviewed-custom-model", require_usage=True)
    with pytest.raises(EmbeddingBudgetError):
        provider.embed_queries(["must not be sent"])
    provider._client.embeddings.with_raw_response.create.assert_not_called()


@pytest.mark.parametrize("model", [MODEL, "unreviewed-custom-model"])
async def test_enabling_org_cap_does_not_reuse_uncapped_cached_embedder(model):
    from dataclasses import replace

    from app.db.vector_tables import VectorScope
    from app.services.embedding_resolution import ResolvedEmbeddings
    from app.services.rag.vectorstore import PgVectorStore

    resolved = ResolvedEmbeddings(
        model=model,
        dim=1,
        api_key="fixture",
        key_source=EmbeddingKeySource.CONNECTION,
        base_url="https://gateway.test/v1",
        provider="openai_compatible",
        vector_scope=VectorScope(tenant=uuid4()),
    )
    store = PgVectorStore.__new__(PgVectorStore)
    store._resolver = AsyncMock(side_effect=[resolved, replace(resolved, require_usage=True)])
    store._services = {}
    uncapped, _ = await store._for_collection("docs")
    capped, _ = await store._for_collection("docs")
    assert capped is not uncapped
    capped.provider._client = MagicMock(
        embeddings=MagicMock(
            with_raw_response=MagicMock(create=MagicMock(return_value=embedding_response([[1.0]])))
        )
    )
    with pytest.raises(EmbeddingBudgetError):
        capped.embed_query("query")


@pytest.mark.parametrize("missing_payer", [True, False])
async def test_usage_policy_resolution_handles_unowned_or_removed_payer(monkeypatch, missing_payer):
    identity = TargetIdentity(
        provider="openai_compatible",
        connection_id=uuid4(),
        base_url="https://gateway.test/v1",
        secret_id=uuid4(),
        key_generation=uuid4(),
        key_organization_id=None if missing_payer else uuid4(),
        key_source=EmbeddingKeySource.CONNECTION,
    )
    organization = AsyncMock(return_value=None)
    monkeypatch.setattr(resolution.organization_repo, "get_by_id", organization)
    assert not await resolution._requires_reported_usage(MagicMock(), identity)
    assert organization.await_count == (0 if missing_payer else 1)
