"""Qdrant-backed RAG vector store (single physical collection, logical names in payload)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from itertools import batched
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.rag.qdrant_client import create_qdrant_client
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    PointStruct,
    VectorParams,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.exceptions import BadRequestError
from app.db.base import Base
from app.db.vector_tables import is_runtime_vector_table, validate_collection_name
from app.services.embedding_resolution import (
    EmbeddingKeySource,
    ResolvedEmbeddings,
)
from app.services.rag.config import EmbeddingsConfig, RAGSettings
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.filters import RetrievalQuery, RetrievalScope
from app.services.rag.models import (
    CollectionInfo,
    Document,
    DocumentChunk,
    DocumentInfo,
    SearchResult,
)
from app.services.rag.qdrant_filters import (
    LOGICAL_COLLECTION_KEY,
    logical_collection_filter,
    retrieval_query_to_qdrant_filter,
    tenant_payload_conditions,
    tenant_scoped_filter,
)
from app.services.rag.vectorstore import BaseVectorStore, _document_is_unaddressed

logger = logging.getLogger(__name__)

_FACET_KEYS: frozenset[str] = frozenset({"organizational_unit", "source", "document_type"})
_CHUNK_UPSERT_BATCH = 200
_SCROLL_PAGE = 256

EmbeddingResolver = Callable[[str, UUID | None], Awaitable[ResolvedEmbeddings | None]]

_PAYLOAD_CONTENT = "content"
_EXCLUDED_METADATA_KEYS = frozenset(
    {_PAYLOAD_CONTENT, LOGICAL_COLLECTION_KEY, "parent_doc_id"},
)


class QdrantVectorStore(BaseVectorStore):
    """Qdrant implementation of :class:`BaseVectorStore` (Shop AI / Agentra cutover)."""

    def __init__(
        self,
        settings: RAGSettings,
        embedding_service: EmbeddingService,
        resolver: EmbeddingResolver,
        *,
        qdrant_url: str,
        qdrant_api_key: str | None,
        physical_collection: str,
        engine: AsyncEngine,
    ) -> None:
        self.settings = settings
        self.embedder = embedding_service
        self.dim = settings.embeddings_config.dim
        self._resolver = resolver
        self._services: dict[tuple[str, str, str, str], EmbeddingService] = {}
        self.physical_collection = physical_collection
        self._client = create_qdrant_client(
            url=qdrant_url,
            api_key=qdrant_api_key,
        )
        self.async_session = async_sessionmaker(engine, expire_on_commit=False)

    def _vector_size(self) -> int:
        return self.settings.embeddings_config.dim

    def _ensure_physical_collection_sync(self) -> None:
        if self._client.collection_exists(self.physical_collection):
            info = self._client.get_collection(self.physical_collection)
            existing_dim = info.config.params.vectors.size  # type: ignore[union-attr]
            if existing_dim != self._vector_size():
                raise BadRequestError(
                    message="Qdrant collection dimension mismatch",
                    details={
                        "collection": self.physical_collection,
                        "expected": self._vector_size(),
                        "actual": existing_dim,
                    },
                )
            return
        self._client.create_collection(
            collection_name=self.physical_collection,
            vectors_config=VectorParams(size=self._vector_size(), distance=Distance.COSINE),
        )

    async def _ensure_physical_collection(self) -> None:
        await asyncio.to_thread(self._ensure_physical_collection_sync)

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        try:
            uuid.UUID(chunk_id)
        except ValueError:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
        else:
            return chunk_id

    async def _for_collection(
        self, name: str, organization_id: UUID | None = None
    ) -> tuple[EmbeddingService, int]:
        resolved = await self._resolver(name, organization_id)
        if resolved is None:
            return self.embedder, self.dim
        cache_key = (name, resolved.model, resolved.api_key, resolved.base_url)
        service = self._services.get(cache_key)
        if service is None:
            service = EmbeddingService(
                settings=RAGSettings(embeddings_config=EmbeddingsConfig(model=resolved.model)),
                api_key=resolved.api_key,
                expected_dim=resolved.dim,
                key_origin=resolved.describe(name),
                base_url=resolved.base_url,
                keyless=resolved.key_source is EmbeddingKeySource.KEYLESS,
            )
            self._services[cache_key] = service
        return service, resolved.dim

    async def resolve_tenant(self, name: str, organization_id: UUID | None) -> UUID | None:
        if organization_id is None:
            return None
        resolved = await self._resolver(name, organization_id)
        return resolved.vector_tenant if resolved is not None else None

    async def _ensure_collection(self, name: str) -> None:
        validate_collection_name(name, metadata=Base.metadata)
        await self._ensure_physical_collection()

    async def _collection_has_points(self, collection_name: str) -> bool:
        def _check() -> bool:
            if not self._client.collection_exists(self.physical_collection):
                return False
            records, _ = self._client.scroll(
                collection_name=self.physical_collection,
                scroll_filter=Filter(must=[logical_collection_filter(collection_name)]),
                limit=1,
                with_payload=False,
                with_vectors=False,
            )
            return bool(records)

        return await asyncio.to_thread(_check)

    async def insert_document(
        self, collection_name: str, document: Document, tenant: UUID | None = None
    ) -> None:
        await self._ensure_collection(collection_name)
        if not document.chunked_pages:
            raise ValueError("Document has no chunked pages.")
        embedder, _ = await self._for_collection(collection_name)
        vectors = embedder.embed_document(document)

        def _upsert_batch(batch_points: list[PointStruct]) -> None:
            self._client.upsert(collection_name=self.physical_collection, points=batch_points)

        points: list[PointStruct] = []
        for chunk, vector in zip(document.chunked_pages, vectors, strict=True):
            payload: dict[str, Any] = {
                **self._build_chunk_metadata(chunk, document, tenant),
                _PAYLOAD_CONTENT: chunk.chunk_content,
                LOGICAL_COLLECTION_KEY: collection_name,
                "parent_doc_id": chunk.parent_doc_id,
            }
            points.append(
                PointStruct(id=self._point_id(chunk.chunk_id), vector=vector, payload=payload),
            )

        for batch in batched(points, _CHUNK_UPSERT_BATCH):
            await asyncio.to_thread(_upsert_batch, list(batch))

    async def search(
        self,
        collection_name: str,
        query: str,
        query_filter: RetrievalQuery,
        limit: int = 4,
    ) -> list[SearchResult]:
        if not await self._collection_has_points(collection_name):
            return []
        qdrant_filter = retrieval_query_to_qdrant_filter(collection_name, query_filter)
        if qdrant_filter == "empty":
            return []
        embedder, _ = await self._for_collection(collection_name, query_filter.organization_id)
        query_vector = embedder.embed_query(query)

        def _query() -> list[SearchResult]:
            response = self._client.query_points(
                collection_name=self.physical_collection,
                query=query_vector,
                query_filter=qdrant_filter,
                limit=limit,
                with_payload=True,
            )
            results: list[SearchResult] = []
            for point in response.points:
                payload = dict(point.payload or {})
                score = float(point.score or 0.0)
                parent = payload.get("parent_doc_id")
                metadata = {k: v for k, v in payload.items() if k not in _EXCLUDED_METADATA_KEYS}
                results.append(
                    SearchResult(
                        content=str(payload.get(_PAYLOAD_CONTENT) or ""),
                        score=score,
                        metadata=metadata,
                        parent_doc_id=str(parent) if parent else None,
                    ),
                )
            results.sort(key=lambda r: r.score, reverse=True)
            return results

        return await asyncio.to_thread(_query)

    async def get_collection_info(
        self,
        collection_name: str,
        organization_id: UUID | None = None,
        tenant: UUID | None = None,
    ) -> CollectionInfo:
        _, dim = await self._for_collection(collection_name, organization_id)
        if not await self._collection_has_points(collection_name):
            return CollectionInfo(name=collection_name, total_vectors=0, dim=dim)
        must = [
            logical_collection_filter(collection_name),
            *tenant_payload_conditions(tenant),
        ]

        def _count() -> int:
            result = self._client.count(
                collection_name=self.physical_collection,
                count_filter=Filter(must=must),
                exact=True,
            )
            return int(result.count)

        count = await asyncio.to_thread(_count)
        return CollectionInfo(name=collection_name, total_vectors=count, dim=dim)

    async def delete_collection(self, collection_name: str) -> None:
        await self._ensure_physical_collection()

        def _delete() -> None:
            self._client.delete(
                collection_name=self.physical_collection,
                points_selector=Filter(must=[logical_collection_filter(collection_name)]),
            )

        await asyncio.to_thread(_delete)

    async def delete_document(
        self, collection_name: str, document_id: str, tenant: UUID | None = None
    ) -> None:
        sanitized = self._sanitize_id(document_id)
        filt = tenant_scoped_filter(collection_name, tenant, parent_doc_id=sanitized)

        def _delete() -> None:
            self._client.delete(
                collection_name=self.physical_collection,
                points_selector=filt,
            )

        await asyncio.to_thread(_delete)

    async def restamp_documents_to_untagged(
        self, collection_name: str, tenant: UUID, knowledge_base_id: UUID
    ) -> None:
        if not await self._collection_has_points(collection_name):
            return
        async with self.async_session() as session:
            result = await session.execute(
                text(
                    "SELECT vector_document_id FROM rag_documents "
                    "WHERE knowledge_base_id = :kb_id AND vector_document_id IS NOT NULL"
                ),
                {"kb_id": knowledge_base_id},
            )
            doc_ids = [str(row[0]) for row in result.fetchall()]
            await session.commit()
        if not doc_ids:
            return
        selector = Filter(
            must=[
                logical_collection_filter(collection_name),
                *tenant_payload_conditions(tenant),
                FieldCondition(key="parent_doc_id", match=MatchAny(any=doc_ids)),
            ]
        )

        def _strip_org() -> None:
            self._client.delete_payload(
                collection_name=self.physical_collection,
                keys=["organization_id"],
                points=selector,
            )

        await asyncio.to_thread(_strip_org)

    async def get_documents(
        self, collection_name: str, tenant: UUID | None = None
    ) -> list[DocumentInfo]:
        if not await self._collection_has_points(collection_name):
            return []
        filt = tenant_scoped_filter(collection_name, tenant)

        def _scroll() -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            offset = None
            while True:
                records, offset = self._client.scroll(
                    collection_name=self.physical_collection,
                    scroll_filter=filt,
                    limit=_SCROLL_PAGE,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for record in records:
                    payload = dict(record.payload or {})
                    rows.append(
                        {
                            "parent_doc_id": payload.get("parent_doc_id"),
                            "metadata": {
                                k: v for k, v in payload.items() if k not in _EXCLUDED_METADATA_KEYS
                            },
                        }
                    )
                if offset is None:
                    break
            return rows

        raw = await asyncio.to_thread(_scroll)
        return self._group_documents(raw)

    async def distinct_metadata_values(
        self, collection_name: str, keys: list[str], scope: RetrievalScope
    ) -> dict[str, list[str]]:
        unknown = [key for key in keys if key not in _FACET_KEYS]
        if unknown:
            raise ValueError(f"not a facetable metadata key: {', '.join(sorted(unknown))}")
        result: dict[str, list[str]] = {key: [] for key in keys}
        if not await self._collection_has_points(collection_name):
            return result
        from app.services.rag.filters import RetrievalFilters, RetrievalQuery

        # Reuse scope translation via a dummy query (filters empty).
        dummy = RetrievalQuery(scope=scope, filters=RetrievalFilters())
        qfilter = retrieval_query_to_qdrant_filter(collection_name, dummy)
        if qfilter == "empty":
            return result

        def _scroll_values() -> dict[str, set[str]]:
            seen: dict[str, set[str]] = {key: set() for key in keys}
            offset = None
            while True:
                records, offset = self._client.scroll(
                    collection_name=self.physical_collection,
                    scroll_filter=qfilter,
                    limit=_SCROLL_PAGE,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for record in records:
                    payload = record.payload or {}
                    for key in keys:
                        val = payload.get(key)
                        if val is not None and val != "":
                            seen[key].add(str(val))
                if offset is None:
                    break
            return seen

        seen = await asyncio.to_thread(_scroll_values)
        for key in keys:
            result[key] = sorted(seen[key])
        return result

    async def find_existing_document(
        self,
        collection_name: str,
        *,
        source_path: str,
        content_hash: str,
        tenant: UUID | None = None,
    ) -> DocumentInfo | None:
        if not await self._collection_has_points(collection_name):
            return None
        filename = Path(source_path).name if source_path else ""

        async def _first_hit(**kwargs: Any) -> DocumentInfo | None:
            filt = tenant_scoped_filter(collection_name, tenant, **kwargs)

            def _scroll_one() -> DocumentInfo | None:
                records, _ = self._client.scroll(
                    collection_name=self.physical_collection,
                    scroll_filter=filt,
                    limit=1,
                    with_payload=True,
                    with_vectors=False,
                )
                if not records:
                    return None
                payload = dict(records[0].payload or {})
                grouped = self._group_documents(
                    [
                        {
                            "parent_doc_id": payload.get("parent_doc_id"),
                            "metadata": {
                                k: v for k, v in payload.items() if k not in _EXCLUDED_METADATA_KEYS
                            },
                        }
                    ]
                )
                return grouped[0] if grouped else None

            return await asyncio.to_thread(_scroll_one)

        if source_path:
            hit = await _first_hit(source_path=source_path)
            if hit is not None:
                return hit
        if filename:
            hit = await _first_hit(filename=filename)
            if hit is not None and _document_is_unaddressed(hit):
                return hit
        if content_hash:
            return await _first_hit(content_hash=content_hash)
        return None

    async def document_ids_at(
        self, collection_name: str, *, source_path: str, tenant: UUID | None = None
    ) -> list[str]:
        if not await self._collection_has_points(collection_name):
            return []
        filt = tenant_scoped_filter(collection_name, tenant, source_path=source_path)

        def _ids() -> list[str]:
            ids: set[str] = set()
            offset = None
            while True:
                records, offset = self._client.scroll(
                    collection_name=self.physical_collection,
                    scroll_filter=filt,
                    limit=_SCROLL_PAGE,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for record in records:
                    parent = (record.payload or {}).get("parent_doc_id")
                    if parent:
                        ids.add(str(parent))
                if offset is None:
                    break
            return sorted(ids)

        return await asyncio.to_thread(_ids)

    async def get_document_chunks(
        self, collection_name: str, document_id: str, tenant: UUID | None = None
    ) -> list[DocumentChunk]:
        if not await self._collection_has_points(collection_name):
            return []
        filt = tenant_scoped_filter(
            collection_name, tenant, parent_doc_id=self._sanitize_id(document_id)
        )

        def _scroll_chunks() -> list[DocumentChunk]:
            chunks: list[DocumentChunk] = []
            offset = None
            while True:
                records, offset = self._client.scroll(
                    collection_name=self.physical_collection,
                    scroll_filter=filt,
                    limit=_SCROLL_PAGE,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for record in records:
                    payload = record.payload or {}
                    chunks.append(
                        DocumentChunk(
                            content=str(payload.get(_PAYLOAD_CONTENT) or ""),
                            page_num=int(payload.get("page_num", 0)),
                            chunk_num=int(payload.get("chunk_num", 0)),
                        )
                    )
                if offset is None:
                    break
            return sorted(chunks, key=lambda c: (c.page_num, c.chunk_num))

        return await asyncio.to_thread(_scroll_chunks)

    async def get_chunks_around(
        self,
        collection_name: str,
        document_id: str,
        tenant: UUID | None,
        *,
        page_num: int,
        chunk_num: int,
        before: int,
        after: int,
    ) -> list[DocumentChunk]:
        chunks = await self.get_document_chunks(collection_name, document_id, tenant)
        if not chunks:
            return []
        pos = (page_num, chunk_num)
        indexed = [(c.page_num, c.chunk_num) for c in chunks]
        try:
            center = indexed.index(pos)
        except ValueError:
            center = None
        selected: list[DocumentChunk] = []
        if center is not None:
            start = max(0, center - before)
            end = min(len(chunks), center + after + 1)
            selected = chunks[start:end]
        else:
            before_chunks = [c for c in chunks if (c.page_num, c.chunk_num) < pos]
            after_chunks = [c for c in chunks if (c.page_num, c.chunk_num) > pos]
            selected = before_chunks[-before:] + after_chunks[:after]
        return sorted(selected, key=lambda c: (c.page_num, c.chunk_num))

    async def list_collections(self) -> list[str]:
        def _list() -> list[str]:
            if not self._client.collection_exists(self.physical_collection):
                return []
            names: set[str] = set()
            offset = None
            while True:
                records, offset = self._client.scroll(
                    collection_name=self.physical_collection,
                    limit=_SCROLL_PAGE,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for record in records:
                    logical = (record.payload or {}).get(LOGICAL_COLLECTION_KEY)
                    if (
                        isinstance(logical, str)
                        and logical
                        and is_runtime_vector_table(f"rag_{logical}", metadata=Base.metadata)
                    ):
                        names.add(logical)
                if offset is None:
                    break
            return sorted(names)

        return await asyncio.to_thread(_list)
