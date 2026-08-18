"""The knowledge-search request path, and the spend it books.

`POST /rag/search` used to be the one metered gap in RAG: it embedded the query
and, once configured, reranks - both of which cost money - inside no
`metered_by` block and against no ledger, so neither landed on the
organization's monthly bill (the #16 class of defect). This service closes that.

It opens a ledger scoped to the caller's organization, runs the search inside a
`metered_by` block so the ambient embedding and rerank calls book to it, and
persists what they spent to `ingestion_spend` - the same sink a worker's
ingestion spend lands in, with a null document id because a search indexed
nothing. Reranking is what made the gap worth closing; metering the embeddings
too is the beneficial side effect.

The search itself is unchanged: the same collection-access resolution and the
same single- vs multi-collection retrieval the route did inline, moved behind a
service so the route stays HTTP plumbing.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from app.agents.capabilities.budget import SpendLedger, metered_by
from app.db.session import get_db_context
from app.repositories import ingestion_spend_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.permissions import AuthContext
    from app.schemas.rag import RAGSearchRequest
    from app.services.collection_access import CollectionAccessService
    from app.services.rag.models import SearchResult
    from app.services.rag.retrieval import RetrievalService


class KnowledgeSearchService:
    """Resolves, meters and runs a knowledge search on the request path."""

    def __init__(
        self,
        db: AsyncSession,
        retrieval: RetrievalService,
        access: CollectionAccessService,
    ) -> None:
        self.db = db
        self.retrieval = retrieval
        self.access = access

    async def search(self, ctx: AuthContext, request: RAGSearchRequest) -> list[SearchResult]:
        """Run the search, metered against the caller's organization.

        A collection the caller cannot reach refuses the whole search rather
        than being dropped from it - `CollectionAccessService.readable_all`
        raises, and this never opens a ledger for a search that will not run.
        """
        names = request.collection_names or [request.collection_name]
        collections = [kb.collection_name for kb in await self.access.readable_all(ctx, names)]

        ledger = SpendLedger(organization_id=ctx.organization_id)
        try:
            with metered_by(ledger):
                if len(collections) > 1:
                    results = await self.retrieval.retrieve_multi(
                        query=request.query,
                        collection_names=collections,
                        limit=request.limit,
                        min_score=request.min_score,
                    )
                else:
                    results = await self.retrieval.retrieve(
                        query=request.query,
                        collection_name=collections[0],
                        limit=request.limit,
                        min_score=request.min_score,
                        filter=request.filter or "",
                    )
        except Exception:
            # The query embedding is booked before the vector query it pays for,
            # so a search that fails mid-flight has already spent. Recording that
            # on the request session would be undone with the failed request's
            # rollback, so the failure path books through a session of its own
            # that commits: the platform records spend even when the run fails.
            await self._book_failed_spend(ledger)
            raise

        await self._record_spend(self.db, ledger)
        return results

    async def _book_failed_spend(self, ledger: SpendLedger) -> None:
        """Persist a failed search's spend in a transaction of its own.

        The request that raised is about to roll back, taking `self.db` with it,
        so what was already spent is written through a fresh session that commits
        independently. Skips opening one when nothing was spent.
        """
        if not ledger.entries:
            return
        async with get_db_context() as db:
            await self._record_spend(db, ledger)

    @staticmethod
    async def _record_spend(db: AsyncSession, ledger: SpendLedger) -> None:
        """Persist what the search spent, one row per model, if it spent anything.

        A null `rag_document_id` because a search indexes no document; the
        organization is what a monthly budget reads this back against. Priced by
        the reranker and by embeddings independently, so a partial cost is one
        the embedding half could not price, exactly as ingestion records it.
        """
        if not ledger.entries:
            return
        for model in dict.fromkeys(entry.model_name for entry in ledger.entries):
            entries = [entry for entry in ledger.entries if entry.model_name == model]
            await ingestion_spend_repo.record(
                db,
                organization_id=ledger.organization_id,
                rag_document_id=None,
                model=model,
                input_tokens=sum(entry.input_tokens for entry in entries),
                output_tokens=sum(entry.output_tokens for entry in entries),
                cost_usd=sum((entry.cost_usd for entry in entries), Decimal(0)),
                cost_is_partial=any(not entry.priced for entry in entries),
            )
