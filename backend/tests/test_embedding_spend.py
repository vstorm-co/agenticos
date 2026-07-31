"""Every model call ingestion and retrieval make is metered, and refused at the cap.

`app/services/rag/*` sits outside the coverage gate, which is exactly why its
metering is pinned explicitly: the usage on an embedding response was dropped
at the call site for months, the image describer's vision calls were billed to
nobody, and nothing failed while every knowledge search and every ingested
document spent for free.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.usage import RequestUsage, RunUsage

from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetScope,
    SpendLedger,
    metered_by,
)
from app.services.rag.embeddings import OpenAIEmbeddingProvider
from app.services.rag.image_describer import PydanticAIImageDescriber
from app.worker.tasks.rag_tasks import _record_embedding_spend, _run_ingestion


def _provider(*, usage: object) -> OpenAIEmbeddingProvider:
    provider = OpenAIEmbeddingProvider(model="text-embedding-3-large", api_key="key")
    response = MagicMock(data=[MagicMock(embedding=[0.1, 0.2])], usage=usage)
    provider._client = MagicMock(embeddings=MagicMock(create=MagicMock(return_value=response)))
    return provider


class TestProviderMetering:
    def test_what_a_query_embeds_is_booked_to_the_active_ledger(self):
        ledger = SpendLedger()

        with metered_by(ledger):
            _provider(usage=MagicMock(prompt_tokens=42)).embed_queries(
                ["what is the refund policy"]
            )

        assert [(entry.model_name, entry.input_tokens) for entry in ledger.entries] == [
            ("text-embedding-3-large", 42)
        ]
        # Priced, not merely counted - the provider hint is what resolves it.
        assert not ledger.has_unpriced_models

    def test_a_response_without_usage_still_embeds(self):
        """Some OpenAI-compatible endpoints omit usage; the search must not
        fail over the accounting, and the ledger must not invent a number."""
        ledger = SpendLedger()

        with metered_by(ledger):
            vectors = _provider(usage=None).embed_queries(["query"])

        assert vectors == [[0.1, 0.2]]
        assert ledger.entries == []


class TestDescriberMetering:
    """The vision model reads every image ingestion describes - that is spend.

    The describer's agent carries no BudgetGuard, because it is not a run; its
    usage is reported to the ambient ledger or it is reported nowhere.
    """

    @staticmethod
    def _describer() -> PydanticAIImageDescriber:
        return PydanticAIImageDescriber(
            MagicMock(model_name="gpt-4.1", system="openai"), prompt="Describe."
        )

    @pytest.mark.anyio
    async def test_what_an_image_costs_to_describe_is_booked(self):
        result = MagicMock(
            output="A bar chart.",
            usage=RunUsage(input_tokens=900, output_tokens=100),
        )
        ledger = SpendLedger()

        with (
            patch("pydantic_ai.Agent") as agent_cls,
            metered_by(ledger),
        ):
            agent_cls.return_value.run = AsyncMock(return_value=result)
            description = await self._describer().describe(b"png-bytes")

        assert description == "A bar chart."
        assert [
            (entry.model_name, entry.input_tokens, entry.output_tokens) for entry in ledger.entries
        ] == [("gpt-4.1", 900, 100)]
        assert not ledger.has_unpriced_models

    @pytest.mark.anyio
    async def test_an_unreadable_image_books_nothing_and_fails_nothing(self):
        """The existing contract - one bad image must not fail a document -
        now also means: no phantom spend for a call that never answered."""
        ledger = SpendLedger()

        with (
            patch("pydantic_ai.Agent") as agent_cls,
            metered_by(ledger),
        ):
            agent_cls.return_value.run = AsyncMock(side_effect=RuntimeError("boom"))
            description = await self._describer().describe(b"png-bytes")

        assert description == ""
        assert ledger.entries == []


class TestIngestionSpendPersistence:
    @staticmethod
    def _worker_db(db: MagicMock):
        @asynccontextmanager
        async def _context():
            yield db

        return _context

    @pytest.mark.anyio
    async def test_what_a_window_spent_is_written_per_model(self):
        """One window can spend in two models at once - the embedder and the
        image describer - and a bill is reconciled per model, not per blob."""
        organization_id, document_id = uuid.uuid4(), uuid.uuid4()
        ledger = SpendLedger()
        ledger.record("text-embedding-3-large", RequestUsage(input_tokens=1_000_000), "openai")
        ledger.record("gpt-4.1", RequestUsage(input_tokens=900, output_tokens=100), "openai")

        with (
            patch("app.worker.tasks.rag_tasks.get_worker_db_context", self._worker_db(MagicMock())),
            patch(
                "app.worker.tasks.rag_tasks.ingestion_spend_repo.record", new=AsyncMock()
            ) as record,
        ):
            await _record_embedding_spend(
                ledger, organization_id=organization_id, rag_document_id=document_id
            )

        rows = [call.kwargs for call in record.call_args_list]
        assert [(row["model"], row["input_tokens"], row["output_tokens"]) for row in rows] == [
            ("text-embedding-3-large", 1_000_000, 0),
            ("gpt-4.1", 900, 100),
        ]
        for row in rows:
            assert row["organization_id"] == organization_id
            assert row["rag_document_id"] == document_id
            assert row["cost_usd"] > Decimal(0)
            assert row["cost_is_partial"] is False

    @pytest.mark.anyio
    async def test_a_window_that_spent_nothing_writes_nothing(self):
        """A document that never reached the embedder - a parse failure, a
        refused format - must not leave a zero-dollar row for every attempt."""
        with patch("app.worker.tasks.rag_tasks.get_worker_db_context") as worker_db:
            await _record_embedding_spend(
                SpendLedger(), organization_id=uuid.uuid4(), rag_document_id=None
            )

        worker_db.assert_not_called()


class TestIngestionRefusedAtTheCap:
    @pytest.mark.anyio
    async def test_a_queued_document_is_refused_before_anything_is_parsed(self):
        """The budget can be reached by runs that finished while the file sat
        in the queue, so the worker checks again - and refuses before building
        the pipeline, not after embedding half the document."""
        refusal = BudgetExceeded(
            limit_usd=Decimal("40"), spent_usd=Decimal("40"), scope=BudgetScope.ORGANIZATION
        )
        record = MagicMock(organization_id=uuid.uuid4(), ingestion_config={})

        @asynccontextmanager
        async def _worker_db():
            yield MagicMock()

        with (
            patch("app.worker.tasks.rag_tasks.get_worker_db_context", _worker_db),
            patch("app.services.rag_document.RAGDocumentService") as documents,
            patch(
                "app.worker.tasks.rag_tasks.assert_organization_within_budget",
                new=AsyncMock(side_effect=refusal),
            ),
            patch("app.worker.tasks.rag_tasks._ingestion_service_for") as pipeline,
        ):
            documents.return_value.get_document = AsyncMock(return_value=record)
            with pytest.raises(BudgetExceeded):
                await _run_ingestion(str(uuid.uuid4()), "docs", "unreached/f.pdf", "f.pdf", False)

        pipeline.assert_not_called()
