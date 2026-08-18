"""The knowledge-search request path, and that it meters what it spends.

The search itself is delegated to retrieval; what this service adds is a ledger
scoped to the organization, opened around the search so the embedding and any
rerank book to it, and persisted afterwards. So the tests drive a retrieval
double that books spend the way an embedding or a rerank would, and assert it
reaches `ingestion_spend`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.budget import SpendEntry, book_ambient_spend
from app.schemas.rag import RAGSearchRequest
from app.services.knowledge_search import KnowledgeSearchService
from app.services.rag.models import SearchResult

pytestmark = pytest.mark.anyio

_MODULE = "app.services.knowledge_search"


def _kb(collection_name: str) -> MagicMock:
    return MagicMock(collection_name=collection_name)


def _ctx(organization_id: uuid.UUID | None = None) -> MagicMock:
    return MagicMock(organization_id=organization_id or uuid.uuid4())


def _service(*, readable: list[MagicMock], retrieve=None, retrieve_multi=None):
    access = MagicMock()
    access.readable_all = AsyncMock(return_value=readable)
    retrieval = MagicMock()
    retrieval.retrieve = AsyncMock(side_effect=retrieve or _no_spend_retrieve)
    retrieval.retrieve_multi = AsyncMock(side_effect=retrieve_multi or _no_spend_retrieve)
    return KnowledgeSearchService(MagicMock(), retrieval, access), retrieval


async def _no_spend_retrieve(*args, **kwargs) -> list[SearchResult]:
    return [SearchResult(content="hit", score=0.9)]


def _booking(cost: str, *, priced: bool = True, model: str = "rerank-v3.5"):
    async def _retrieve(*args, **kwargs) -> list[SearchResult]:
        book_ambient_spend(
            SpendEntry(
                model_name=model,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal(cost),
                priced=priced,
            )
        )
        return [SearchResult(content="hit", score=0.9)]

    return _retrieve


class TestRouting:
    async def test_one_collection_uses_the_single_collection_path(self):
        service, retrieval = _service(readable=[_kb("c1")])
        with patch(f"{_MODULE}.ingestion_spend_repo.record", new=AsyncMock()):
            await service.search(_ctx(), RAGSearchRequest(query="q", collection_name="c1"))
        retrieval.retrieve.assert_awaited_once()
        retrieval.retrieve_multi.assert_not_awaited()

    async def test_several_collections_use_the_multi_path(self):
        service, retrieval = _service(readable=[_kb("a"), _kb("b")])
        with patch(f"{_MODULE}.ingestion_spend_repo.record", new=AsyncMock()):
            await service.search(_ctx(), RAGSearchRequest(query="q", collection_names=["a", "b"]))
        retrieval.retrieve_multi.assert_awaited_once()
        retrieval.retrieve.assert_not_awaited()

    async def test_it_returns_what_retrieval_found(self):
        service, _ = _service(readable=[_kb("c1")])
        with patch(f"{_MODULE}.ingestion_spend_repo.record", new=AsyncMock()):
            results = await service.search(_ctx(), RAGSearchRequest(query="q"))
        assert [r.content for r in results] == ["hit"]


class TestMetering:
    async def test_spend_booked_during_the_search_is_persisted_to_the_organization(self):
        org = uuid.uuid4()
        service, _ = _service(readable=[_kb("c1")], retrieve=_booking("0.002"))
        with patch(f"{_MODULE}.ingestion_spend_repo.record", new=AsyncMock()) as record:
            await service.search(_ctx(org), RAGSearchRequest(query="q"))

        record.assert_awaited_once()
        kwargs = record.await_args.kwargs
        assert kwargs["organization_id"] == org
        assert kwargs["rag_document_id"] is None
        assert kwargs["cost_usd"] == Decimal("0.002")
        assert kwargs["cost_is_partial"] is False

    async def test_a_search_that_spends_nothing_writes_no_row(self):
        service, _ = _service(readable=[_kb("c1")])
        with patch(f"{_MODULE}.ingestion_spend_repo.record", new=AsyncMock()) as record:
            await service.search(_ctx(), RAGSearchRequest(query="q"))
        record.assert_not_awaited()

    async def test_an_unpriced_entry_makes_the_recorded_cost_partial(self):
        service, _ = _service(
            readable=[_kb("c1")], retrieve=_booking("0", priced=False, model="mystery")
        )
        with patch(f"{_MODULE}.ingestion_spend_repo.record", new=AsyncMock()) as record:
            await service.search(_ctx(), RAGSearchRequest(query="q"))
        assert record.await_args.kwargs["cost_is_partial"] is True

    async def test_spend_in_two_models_is_one_row_each(self):
        async def _retrieve(*args, **kwargs) -> list[SearchResult]:
            book_ambient_spend(SpendEntry("text-embedding-3-large", 100, 0, Decimal("0.001"), True))
            book_ambient_spend(SpendEntry("rerank-v3.5", 0, 0, Decimal("0.002"), True))
            return []

        service, _ = _service(readable=[_kb("c1")], retrieve=_retrieve)
        with patch(f"{_MODULE}.ingestion_spend_repo.record", new=AsyncMock()) as record:
            await service.search(_ctx(), RAGSearchRequest(query="q"))

        assert record.await_count == 2
        models = {call.kwargs["model"] for call in record.await_args_list}
        assert models == {"text-embedding-3-large", "rerank-v3.5"}
