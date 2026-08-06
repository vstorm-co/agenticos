import logging
import re
from abc import ABC, abstractmethod
from typing import Any

import app.db.models  # noqa: F401  - registers every model table on `Base.metadata`
from app.db.base import Base
from app.db.vector_tables import VECTOR_TABLE_PREFIX, is_runtime_vector_table
from app.schemas.rag import RAGDocumentItem, RAGDocumentList
from app.services.rag.models import (
    CollectionInfo,
    Document,
    DocumentChunk,
    DocumentInfo,
    DocumentPageChunk,
    SearchResult,
)

logger = logging.getLogger(__name__)

_COLLECTION_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
_RESERVED_COLLECTION_NAMES = frozenset({"all"})


class BaseVectorStore(ABC):
    @abstractmethod
    async def insert_document(self, collection_name: str, document: Document) -> None:
        pass

    @abstractmethod
    async def search(
        self, collection_name: str, query: str, limit: int = 4, filter_expr: str = ""
    ) -> list[SearchResult]:
        pass

    @abstractmethod
    async def delete_collection(self, collection_name: str) -> None:
        pass

    @abstractmethod
    async def delete_document(self, collection_name: str, document_id: str) -> None:
        pass

    @abstractmethod
    async def get_collection_info(self, collection_name: str) -> CollectionInfo:
        pass

    @abstractmethod
    async def list_collections(self) -> list[str]:
        pass

    @abstractmethod
    async def get_documents(self, collection_name: str) -> list[DocumentInfo]:
        pass

    @abstractmethod
    async def get_document_chunks(
        self, collection_name: str, document_id: str
    ) -> list[DocumentChunk]:
        """Every stored chunk of one document, in document order.

        Document order means (page_num, chunk_num) ascending - the order the
        splitter produced them - so callers can reconstruct what the parse
        looked like. An unknown document or collection is an empty list.
        """

    async def get_document_list(self, collection_name: str) -> RAGDocumentList:
        docs = await self.get_documents(collection_name)
        return RAGDocumentList(
            items=[
                RAGDocumentItem(
                    document_id=doc.document_id,
                    filename=doc.filename,
                    filesize=doc.filesize,
                    filetype=doc.filetype,
                    chunk_count=doc.chunk_count,
                    additional_info=doc.additional_info,
                )
                for doc in docs
            ],
            total=len(docs),
        )

    async def create_collection(self, name: str) -> None:
        if not _COLLECTION_NAME_RE.match(name):
            raise ValueError(
                "Collection name must start with a letter and contain only "
                "letters, numbers, and underscores (max 64 chars)"
            )
        if name.lower() in _RESERVED_COLLECTION_NAMES:
            raise ValueError(f"'{name}' is a reserved collection name")
        await self._ensure_collection(name)

    def _build_chunk_metadata(
        self, chunk: "DocumentPageChunk", document: Document
    ) -> dict[str, Any]:
        # `document.metadata.model_dump()` is spread last so it can override per-chunk
        # defaults. `getattr` with defaults is used for optional image fields that may
        # not be present on all chunk types.
        return {
            "page_num": chunk.page_num,
            "chunk_num": chunk.chunk_num,
            "has_images": bool(getattr(chunk, "images", None)),
            "image_count": len(getattr(chunk, "images", [])),
            **document.metadata.model_dump(),
        }

    def _sanitize_id(self, document_id: str) -> str:
        """Sanitize document_id to prevent filter injection."""
        return document_id.replace('"', "").replace("\\", "")

    def _group_documents(self, results: list[dict[str, Any]]) -> list[DocumentInfo]:
        # Iterates results twice: first to record the initial occurrence of each
        # parent_doc_id (capturing filename/filesize/filetype and merging source_path,
        # content_hash, and any extra dict into additional_info), then to increment
        # chunk_count for every row belonging to that document.
        doc_map: dict[str, dict[str, Any]] = {}
        for item in results:
            doc_id = item.get("parent_doc_id")
            metadata = item.get("metadata", {})
            if doc_id and doc_id not in doc_map:
                doc_map[doc_id] = {
                    "document_id": doc_id,
                    "filename": metadata.get("filename"),
                    "filesize": metadata.get("filesize"),
                    "filetype": metadata.get("filetype"),
                    "additional_info": {
                        "source_path": metadata.get("source_path", ""),
                        "content_hash": metadata.get("content_hash", ""),
                        **(metadata.get("additional_info") or {}),
                    },
                    "chunk_count": 0,
                }
            if doc_id:
                doc_map[doc_id]["chunk_count"] += 1
        return [
            DocumentInfo(
                document_id=d["document_id"],
                filename=d.get("filename"),
                filesize=d.get("filesize"),
                filetype=d.get("filetype"),
                chunk_count=d["chunk_count"],
                additional_info=d.get("additional_info"),
            )
            for d in doc_map.values()
        ]


import json
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings as app_settings
from app.services.embedding_resolution import ResolvedEmbeddings
from app.services.rag.config import EmbeddingsConfig, RAGSettings
from app.services.rag.embeddings import EmbeddingService

# How a store learns which model a collection embeds with. Async because the
# answer lives in the database, injected so the template's store never imports
# platform policy.
EmbeddingResolver = Callable[[str], Awaitable[ResolvedEmbeddings | None]]

# pgvector's HNSW builds over a `vector` column only up to this width; past it,
# `CREATE INDEX` fails with "column cannot have more than 2000 dimensions for
# hnsw index". `halfvec` raises the ceiling to 4000, which is how the wider
# models are supported here.
#
# This was reachable for the first time today. The dev and CI databases ran
# stock `postgres:16-alpine`, so `CREATE EXTENSION vector` failed first and hid
# it - and the shipped default, `text-embedding-3-large`, is 3072 wide. Every
# collection created with the default configuration would have failed on its
# first upload, in a worker, with a 500 and no explanation on screen.
_HNSW_MAX_VECTOR_DIM = 2000


def _validate_collection_name(name: str) -> str:
    """Validate collection name to prevent SQL injection."""
    if not re.match(r"^[a-zA-Z0-9_]+$", name):
        raise ValueError(
            f"Invalid collection name: {name}. Only alphanumeric and underscores allowed."
        )
    return name


class PgVectorStore(BaseVectorStore):
    """PostgreSQL + pgvector implementation.

    Uses the existing PostgreSQL database with pgvector extension.
    No additional Docker services needed.

    NOTE: This class creates its own SQLAlchemy engine per instance. In
    production, prefer injecting a shared engine from app.db.session to
    avoid multiple connection pools. Call `await self.aclose()` on shutdown
    to release pool connections.
    """

    def __init__(
        self,
        settings: RAGSettings,
        embedding_service: EmbeddingService,
        resolver: "EmbeddingResolver | None" = None,
    ):
        self.settings = settings
        self.embedder = embedding_service
        self.dim = settings.embeddings_config.dim
        # Which model - and whose key - one collection embeds with. None keeps
        # the deployment defaults for everything, which is the pre-resolver
        # behaviour and still what a collection outside the KB table gets.
        self._resolver = resolver
        self._services: dict[tuple[str, str], EmbeddingService] = {}
        self.engine = create_async_engine(app_settings.DATABASE_URL, echo=False)
        self.async_session = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def aclose(self) -> None:
        """Dispose the connection pool. Call during application shutdown."""
        await self.engine.dispose()

    def _table(self, name: str) -> str:
        """Get validated table name for a collection.

        The prefix comes from `app/db/vector_tables.py` because `alembic/env.py` has
        to recognise these names to keep them out of `alembic check` - a table created
        here exists in no model and no migration, and read as a table to drop (#288).
        """
        return f"{VECTOR_TABLE_PREFIX}{_validate_collection_name(name)}"

    async def _for_collection(self, name: str) -> tuple[EmbeddingService, int]:
        """The embedder and vector width this one collection uses.

        Cached per (model, key): an `EmbeddingService` holds an HTTP client,
        and rebuilding one per chunk would open a connection pool per page of a
        PDF. The recorded width wins over the catalog's - the table was created
        at that number.
        """
        if self._resolver is None:
            return self.embedder, self.dim
        resolved = await self._resolver(name)
        if resolved is None:
            return self.embedder, self.dim
        cache_key = (resolved.model, resolved.api_key)
        service = self._services.get(cache_key)
        if service is None:
            service = EmbeddingService(
                settings=RAGSettings(embeddings_config=EmbeddingsConfig(model=resolved.model)),
                api_key=resolved.api_key,
                expected_dim=resolved.dim,
            )
            self._services[cache_key] = service
        return service, resolved.dim

    @staticmethod
    def _distance_expr(dim: int) -> str:
        """The expression the index is built on, and searches must match.

        pgvector's HNSW takes at most 2000 dimensions on a `vector` column but
        4000 on `halfvec`, so anything wider is indexed and compared at half
        precision. That is pgvector's own answer for wide embeddings, and the
        alternative is not full precision - it is no index at all.

        Building the index on one expression and ordering by another silently
        costs the index, so both come from here.
        """
        if dim > _HNSW_MAX_VECTOR_DIM:
            return f"(embedding::halfvec({dim}))"
        return "embedding"

    async def _ensure_collection(self, name: str) -> None:
        """Create table for collection if not exists."""
        table = self._table(name)
        _, dim = await self._for_collection(name)
        operator_class = "halfvec_cosine_ops" if dim > _HNSW_MAX_VECTOR_DIM else "vector_cosine_ops"
        async with self.async_session() as session:
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await session.execute(
                text(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id VARCHAR(100) PRIMARY KEY,
                    parent_doc_id VARCHAR(100),
                    content TEXT,
                    embedding vector({dim}),
                    metadata JSONB DEFAULT '{{}}'::jsonb
                )
            """)
            )
            await session.execute(
                text(f"""
                CREATE INDEX IF NOT EXISTS {table}_embedding_idx
                ON {table} USING hnsw ({self._distance_expr(dim)} {operator_class})
            """)
            )
            await session.commit()

    async def _collection_exists(self, name: str) -> bool:
        """Return True if the backing table for a collection exists."""
        table = self._table(name)
        async with self.async_session() as session:
            result = await session.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = :table AND table_schema = 'public'"
                ),
                {"table": table},
            )
            return result.scalar() is not None

    async def insert_document(self, collection_name: str, document: Document) -> None:
        table = self._table(collection_name)
        await self._ensure_collection(collection_name)
        if not document.chunked_pages:
            raise ValueError("Document has no chunked pages.")
        embedder, _ = await self._for_collection(collection_name)
        vectors = embedder.embed_document(document)
        async with self.async_session() as session:
            for i, chunk in enumerate(document.chunked_pages):
                meta = self._build_chunk_metadata(chunk, document)
                await session.execute(
                    text(f"""
                        INSERT INTO {table} (id, parent_doc_id, content, embedding, metadata)
                        VALUES (:id, :parent_doc_id, :content, :embedding, :metadata)
                        ON CONFLICT (id) DO UPDATE SET content = :content, embedding = :embedding, metadata = :metadata
                    """),
                    {
                        "id": chunk.chunk_id,
                        "parent_doc_id": chunk.parent_doc_id,
                        "content": chunk.chunk_content,
                        "embedding": str(vectors[i]),
                        "metadata": json.dumps(meta),
                    },
                )
            await session.commit()

    async def search(
        self, collection_name: str, query: str, limit: int = 4, filter_expr: str = ""
    ) -> list[SearchResult]:
        table = self._table(collection_name)
        embedder, dim = await self._for_collection(collection_name)
        query_vector = embedder.embed_query(query)

        # Parse the shared `parent_doc_id == "<value>"` filter format and apply
        # it as a parameterised WHERE clause to avoid returning results from
        # unrelated documents (same behaviour as Qdrant/Chroma implementations).
        doc_id_filter: str | None = None
        if filter_expr and "parent_doc_id" in filter_expr:
            m = re.search(r'parent_doc_id\s*==\s*"([^"]+)"', filter_expr)
            if m:
                doc_id_filter = m.group(1)

        where_clause = "WHERE parent_doc_id = :doc_id" if doc_id_filter else ""
        # The query vector has to be cast the same way the column is, or Postgres
        # compares a halfvec against a vector and refuses the operator outright.
        query_expr = f"(:query_vec)::halfvec({dim})" if dim > _HNSW_MAX_VECTOR_DIM else ":query_vec"
        params: dict[str, Any] = {"query_vec": str(query_vector), "limit": limit}
        if doc_id_filter:
            params["doc_id"] = doc_id_filter

        distance = self._distance_expr(dim)
        async with self.async_session() as session:
            result = await session.execute(
                text(f"""
                    SELECT content, parent_doc_id, metadata,
                           1 - ({distance} <=> {query_expr}) AS score
                    FROM {table}
                    {where_clause}
                    ORDER BY {distance} <=> {query_expr}
                    LIMIT :limit
                """),
                params,
            )
            rows = result.fetchall()
        return [
            SearchResult(
                content=row[0],
                score=float(row[3]),
                metadata=row[2] if isinstance(row[2], dict) else json.loads(row[2]),
                parent_doc_id=row[1],
            )
            for row in rows
        ]

    async def get_collection_info(self, collection_name: str) -> CollectionInfo:
        """Vector count for a collection, reporting an absent one as empty.

        A collection's table is created lazily by the first ingest, so "no table"
        and "nothing indexed yet" are the same state in this design - which is
        why this reports zero rather than raising. It used to run the COUNT
        unconditionally and let asyncpg's `UndefinedTableError` become a 500,
        so asking about a knowledge base nobody had uploaded to yet looked like
        the server breaking. `get_documents` has always answered the same
        question with an empty list; its comment claimed this method already did
        the same, and now it does.
        """
        _, dim = await self._for_collection(collection_name)
        if not await self._collection_exists(collection_name):
            return CollectionInfo(name=collection_name, total_vectors=0, dim=dim)
        table = self._table(collection_name)
        async with self.async_session() as session:
            result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar() or 0
        return CollectionInfo(name=collection_name, total_vectors=count, dim=dim)

    async def delete_collection(self, collection_name: str) -> None:
        table = self._table(collection_name)
        async with self.async_session() as session:
            await session.execute(text(f"DROP TABLE IF EXISTS {table}"))
            await session.commit()

    async def delete_document(self, collection_name: str, document_id: str) -> None:
        table = self._table(collection_name)
        sanitized = self._sanitize_id(document_id)
        async with self.async_session() as session:
            await session.execute(
                text(f"DELETE FROM {table} WHERE parent_doc_id = :doc_id"),
                {"doc_id": sanitized},
            )
            await session.commit()

    async def get_documents(self, collection_name: str) -> list[DocumentInfo]:
        # Return an empty list for non-existent collections instead of silently
        # creating them via _ensure_collection. `get_collection_info` answers the
        # same question the same way.
        if not await self._collection_exists(collection_name):
            return []
        table = self._table(collection_name)
        async with self.async_session() as session:
            result = await session.execute(text(f"SELECT parent_doc_id, metadata FROM {table}"))
            rows = result.fetchall()
        results = [
            {
                "parent_doc_id": row[0],
                "metadata": row[1] if isinstance(row[1], dict) else json.loads(row[1]),
            }
            for row in rows
        ]
        return self._group_documents(results)

    async def get_document_chunks(
        self, collection_name: str, document_id: str
    ) -> list[DocumentChunk]:
        # Same answer for "no such collection" as get_documents: empty, not an
        # UndefinedTableError dressed up as a 500.
        if not await self._collection_exists(collection_name):
            return []
        table = self._table(collection_name)
        async with self.async_session() as session:
            result = await session.execute(
                text(f"SELECT content, metadata FROM {table} WHERE parent_doc_id = :doc_id"),
                {"doc_id": self._sanitize_id(document_id)},
            )
            rows = result.fetchall()
        chunks = []
        for row in rows:
            meta = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            chunks.append(
                DocumentChunk(
                    content=row[0] or "",
                    page_num=int(meta.get("page_num", 0)),
                    chunk_num=int(meta.get("chunk_num", 0)),
                )
            )
        # Sorted here rather than in SQL: page_num and chunk_num live inside the
        # metadata JSONB, and a `(metadata->>'page_num')::int` ORDER BY fails on
        # any row where the key is absent instead of sorting it first.
        return sorted(chunks, key=lambda chunk: (chunk.page_num, chunk.chunk_num))

    async def list_collections(self) -> list[str]:
        """Every collection this store holds, and nothing that only looks like one.

        Carrying the prefix is not enough to be a collection: `rag_documents`
        is a model table, so the prefix alone reported a collection called
        `documents` on every deployment since that table existed, and a caller
        that believed it would read chunks out of a schema with none of the
        columns it expects (#339).

        The question is the same one `alembic/env.py` asks from the other side,
        so it is the same predicate rather than a second one - a `rag_` table
        the models have never heard of. `app/db/vector_tables.py` says why both
        halves are load-bearing.
        """
        async with self.async_session() as session:
            result = await session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_name LIKE :prefix AND table_schema = 'public'"
                ),
                {"prefix": f"{VECTOR_TABLE_PREFIX}%"},
            )
            # removeprefix strips the leading occurrence only, unlike str.replace,
            # which would also hit the prefix inside a collection's own name.
            return [
                row[0].removeprefix(VECTOR_TABLE_PREFIX)
                for row in result.fetchall()
                if is_runtime_vector_table(row[0], metadata=Base.metadata)
            ]
