import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

# Registers every model table on `Base.metadata`, which `list_collections` judges a
# `rag_` table against and `_table` refuses a collection name against. Another import
# already reaches the models today; this one says the store depends on it, rather than
# leaving that to a chain belonging to a different concern. On an empty metadata both
# answers invert silently: the listing reports the tracking table as a collection, and
# a caller may drop it.
import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.vector_tables import (
    VECTOR_CONTENT_HASH_INDEX_SUFFIX,
    VECTOR_FILENAME_INDEX_SUFFIX,
    VECTOR_INDEX_SUFFIX,
    VECTOR_SOURCE_PATH_INDEX_SUFFIX,
    VECTOR_TABLE_PREFIX,
    is_runtime_vector_table,
    validate_collection_name,
)
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


def _document_is_unaddressed(doc: DocumentInfo) -> bool:
    """Whether this document may be matched by its *name* alone.

    Only one that does not already claim an address of its own. A file uploaded
    through the browser stores its filename as its `source_path`, so the two
    agree and it stays reachable by name - which is what the filename fallback is
    for: a document uploaded once and later synced from the folder it came from
    should be replaced rather than duplicated.

    A document that names a *different* address is a different document, and
    matching it by basename loses one of them. An S3 bucket holding
    `a/readme.md` and `b/readme.md` is the case: the second key found the first's
    document by name, so equal contents skipped it and unequal contents replaced
    the first - either way a first sync could not keep both, silently (#990). The
    same collision existed for two local files of the same name in different
    directories.
    """
    stored_path = str((doc.additional_info or {}).get("source_path") or "")
    return not stored_path or stored_path == doc.filename


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

    async def find_existing_document(
        self, collection_name: str, *, source_path: str, content_hash: str
    ) -> DocumentInfo | None:
        """The stored document this file refers to, found by one precedence.

        **One precedence, both answers about one document.** A `source_path`
        match anywhere in the collection beats a `filename` match anywhere in it,
        and a `content_hash` match is the last resort - the order the ingest
        applies to decide whether a file is already held.

        The id and the hash returned are the *same* document's, which is the
        invariant this exists to keep. Computed by two lookups with different
        rules they disagreed: one checked every document for a `source_path`
        match before falling back to `filename` while the other interleaved the
        two, so a caller compared a live file's hash against a different
        document's `content_hash` than the one it was about to replace - an
        unchanged file re-embedded on every sync, or a changed one skipped as
        current (#548). Returning one document forecloses that.

        This reference implementation reads the whole collection; `PgVectorStore`
        overrides it with an indexed lookup per key (#1102). Both answer `None`
        for no match - never an empty document, a stored hash of `""` included.
        """
        docs = await self.get_documents(collection_name)
        filename = Path(source_path).name if source_path else ""
        by_filename: DocumentInfo | None = None
        by_hash: DocumentInfo | None = None
        for doc in docs:
            meta = doc.additional_info or {}
            if source_path and meta.get("source_path") == source_path:
                return doc
            if (
                by_filename is None
                and filename
                and doc.filename == filename
                and _document_is_unaddressed(doc)
            ):
                by_filename = doc
            if by_hash is None and content_hash and meta.get("content_hash") == content_hash:
                by_hash = doc
        return by_filename or by_hash

    async def create_collection(self, name: str) -> None:
        """Make the collection's backing objects, refusing a name that cannot have any.

        The check is here as well as in `_table` because a subclass is free to
        implement `_ensure_collection` without building a table name, and this
        is the method a caller creating a collection reaches.

        Raises:
            BadRequestError: The name is malformed, too long, reserved, or one
                a model table already answers to - see
                :func:`app.db.vector_tables.validate_collection_name`.
        """
        validate_collection_name(name, metadata=Base.metadata)
        await self._ensure_collection(name)

    def _build_chunk_metadata(
        self, chunk: "DocumentPageChunk", document: Document
    ) -> dict[str, Any]:
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
from itertools import batched

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.session import agent_vector_engine, vector_engine
from app.services.embedding_resolution import ResolvedEmbeddings, embeddings_for_collection
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

# How many chunks go into one `INSERT`. The statement used to run once per chunk,
# so a 200-page PDF at the default `chunk_size` was one to three thousand
# sequential round trips inside one open transaction - a second or two on a local
# socket, five to fifteen against a managed Postgres at 3-5ms (#950).
#
# Batched rather than one statement for the whole document, because the parameter
# list is held in memory and each row carries an embedding rendered as text: at
# 3072 dimensions that is tens of kilobytes a row, so three thousand of them in
# one statement is a parameter list measured in hundreds of megabytes.
_CHUNK_INSERT_BATCH = 200


class PgVectorStore(BaseVectorStore):
    """PostgreSQL + pgvector implementation.

    Uses the existing PostgreSQL database with pgvector extension.
    No additional Docker services needed.

    **The store borrows its engine; it never builds or disposes one.** It used
    to call `create_async_engine` in `__init__`, which gave every instance a
    private pool of `DB_POOL_SIZE + DB_MAX_OVERFLOW` connections: the API
    process ran three of them beside the application's own - the lifespan's,
    the knowledge capability's, and one per request when the lifespan's was
    absent - and a worker flow that forgot to dispose its own walked into
    Postgres `max_connections` at around two hundred uploads (#948, #12).
    Injection puts each of those decisions where it can be seen: the API and
    the CLI pass the process engine and dispose nothing, and a worker flow
    builds an engine for the flow and disposes it with the flow's own work.

    A pool is still worth having *within* a flow: `insert_document` writes a
    document's chunks over one connection each, and a flow runs in one event
    loop. Across flows an engine is not shared, for the reason
    `get_worker_db_context` gives about cross-loop connections.
    """

    def __init__(
        self,
        settings: RAGSettings,
        embedding_service: EmbeddingService,
        resolver: "EmbeddingResolver",
        *,
        engine: AsyncEngine,
    ):
        self.settings = settings
        self.embedder = embedding_service
        self.dim = settings.embeddings_config.dim
        # Which model - and whose key - one collection embeds with. Required,
        # and deliberately not defaulted: it used to default to None, and the
        # one construction that forgot it - the worker that ingests every
        # uploaded document - silently ignored every collection's chosen key
        # and model for as long as nobody read the bill (#306). A collection
        # outside the KB table still gets the deployment defaults, but that is
        # now the resolver answering None rather than nobody asking.
        self._resolver = resolver
        self._services: dict[tuple[str, str, str, str], EmbeddingService] = {}
        self.async_session = async_sessionmaker(engine, expire_on_commit=False)

    def _table(self, name: str) -> str:
        """Get validated table name for a collection.

        The prefix comes from `app/db/vector_tables.py` because `alembic/env.py` has
        to recognise these names to keep them out of `alembic check` - a table created
        here exists in no model and no migration, and read as a table to drop (#288).

        The name is judged here rather than only in `create_collection`, because
        every method funnels through this one and two of them are destructive.
        `rag-drop documents --yes` reaches `delete_collection` with no knowledge
        base, no route and no permission between the operator and
        `DROP TABLE IF EXISTS` on the tracking table (#345), so a guard on the
        create path would not have been on that path. This one used to hold a
        laxer rule than `create_collection`'s - no length bound and no leading
        letter - which is how a name refused at creation reached SQL anyway
        (#368).

        Raises:
            BadRequestError: The name is malformed, too long, reserved, or one a
                model table already answers to.
        """
        validate_collection_name(name, metadata=Base.metadata)
        return f"{VECTOR_TABLE_PREFIX}{name}"

    async def _for_collection(self, name: str) -> tuple[EmbeddingService, int]:
        """The embedder and vector width this one collection uses.

        Cached per (collection, model, key): an `EmbeddingService` holds an
        HTTP client, and rebuilding one per chunk would open a connection pool
        per page of a PDF. The collection is in the key because the service
        carries a `key_origin` naming it - two collections on the same key
        would otherwise share a client whose refusal names whichever of them
        embedded first. That bounds a long-lived store's cache by the number
        of collections it has embedded for rather than by the number of
        distinct credentials; each entry builds its `OpenAI` client lazily, so
        a collection only ever read costs an object and no socket.

        The recorded width wins over the catalog's: the table was created at
        that number.
        """
        resolved = await self._resolver(name)
        if resolved is None:
            return self.embedder, self.dim
        cache_key = (name, resolved.model, resolved.api_key, resolved.base_url)
        service = self._services.get(cache_key)
        if service is None:
            service = EmbeddingService(
                settings=RAGSettings(embeddings_config=EmbeddingsConfig(model=resolved.model)),
                api_key=resolved.api_key,
                expected_dim=resolved.dim,
                # So a resolution that ended on an empty key says which key it
                # tried, for which collection, instead of advising an operator
                # to set a variable they may already have set.
                key_origin=resolved.describe(name),
                # The collection's provider. In the cache key beside the model and
                # the key, because moving a collection to another provider must
                # not be answered by a client already built for the old one.
                base_url=resolved.base_url,
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
                CREATE INDEX IF NOT EXISTS {table}{VECTOR_INDEX_SUFFIX}
                ON {table} USING hnsw ({self._distance_expr(dim)} {operator_class})
            """)
            )
            # The keys `find_existing_document` looks a document up by; without
            # them that check is a full read of the runtime table (#1102).
            #
            # `hash`, not btree: the lookups are equality only, and a btree entry
            # is capped near 2700 bytes - so a btree on `source_path` fails the
            # index-row-size limit the moment a document carries a path longer
            # than that (they are unbounded - `s3://`, `gdrive://`, a deep key -
            # and `RAGDocument.source_path` is a hash index for the same reason),
            # which would fail every ingest into the collection. Hashing the
            # value has no such ceiling. `IF NOT EXISTS` so this is idempotent;
            # `0058_backfill_rag_lookup_indexes` backfills the collections that
            # predate it.
            for suffix, key in (
                (VECTOR_SOURCE_PATH_INDEX_SUFFIX, "source_path"),
                (VECTOR_FILENAME_INDEX_SUFFIX, "filename"),
                (VECTOR_CONTENT_HASH_INDEX_SUFFIX, "content_hash"),
            ):
                await session.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {table}{suffix} "
                        f"ON {table} USING hash ((metadata->>'{key}'))"
                    )
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
        """Write a document's chunks, a batch of rows per statement.

        One statement per `_CHUNK_INSERT_BATCH` chunks rather than one per chunk:
        SQLAlchemy takes a list of parameter dictionaries and issues an
        `executemany`, which asyncpg pipelines. What that replaces is a Python
        loop of sequential round trips inside one open transaction, holding a
        connection while it waited - and the number of them scaled with the
        document, so the worst case was a long PDF against the slowest database
        (#950).

        **Each batch's rows are built inside the loop, not before it.** The
        embedding is rendered as text here, and at 3072 dimensions that is tens
        of kilobytes a row - so materialising every row first would hold a
        three-thousand-chunk document's parameters, better than 100MB of live
        strings, on top of the float vectors already in hand. Batching the
        statements and not the rows would have bounded what asyncpg receives
        while leaving the worker's memory exactly where it was.
        """
        table = self._table(collection_name)
        await self._ensure_collection(collection_name)
        if not document.chunked_pages:
            raise ValueError("Document has no chunked pages.")
        embedder, _ = await self._for_collection(collection_name)
        vectors = embedder.embed_document(document)
        statement = text(f"""
            INSERT INTO {table} (id, parent_doc_id, content, embedding, metadata)
            VALUES (:id, :parent_doc_id, :content, :embedding, :metadata)
            ON CONFLICT (id) DO UPDATE SET content = :content, embedding = :embedding, metadata = :metadata
        """)
        async with self.async_session() as session:
            for batch in batched(enumerate(document.chunked_pages), _CHUNK_INSERT_BATCH):
                await session.execute(
                    statement,
                    [
                        {
                            "id": chunk.chunk_id,
                            "parent_doc_id": chunk.parent_doc_id,
                            "content": chunk.chunk_content,
                            "embedding": str(vectors[i]),
                            "metadata": json.dumps(self._build_chunk_metadata(chunk, document)),
                        }
                        for i, chunk in batch
                    ],
                )
            await session.commit()

    async def search(
        self, collection_name: str, query: str, limit: int = 4, filter_expr: str = ""
    ) -> list[SearchResult]:
        """Nearest chunks in a collection, reporting an absent one as empty.

        A collection's table is created by its first ingest, so "no table" and
        "nothing indexed yet" are one state here - the same reasoning
        `get_collection_info` documents below. Without the check, searching a
        knowledge base nobody has uploaded to yet turned asyncpg's
        `UndefinedTableError` into a 500, and it is checked before embedding so
        an empty collection costs no embedding call either.
        """
        table = self._table(collection_name)
        if not await self._collection_exists(collection_name):
            return []
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
            # Ordered so a lookup that falls back to a filename match does not
            # depend on heap order (#548).
            result = await session.execute(
                text(f"SELECT parent_doc_id, metadata FROM {table} ORDER BY parent_doc_id, id")
            )
            rows = result.fetchall()
        results = [
            {
                "parent_doc_id": row[0],
                "metadata": row[1] if isinstance(row[1], dict) else json.loads(row[1]),
            }
            for row in rows
        ]
        return self._group_documents(results)

    async def find_existing_document(
        self, collection_name: str, *, source_path: str, content_hash: str
    ) -> DocumentInfo | None:
        """Look the document up by its indexed metadata keys, not a full scan (#1102).

        One indexed statement per key, in the precedence the base class
        documents - `source_path`, then a `filename` the stored document has not
        addressed under another path, then `content_hash` - stopping at the
        first hit. Each statement returns one document, so the id and hash a
        caller reads name one document, which is the #548 invariant.

        The expression indexes these lean on are built by `_ensure_collection`;
        a collection predating them still answers correctly, at a scan, until
        its next ingest rebuilds them through that same path.
        """
        if not await self._collection_exists(collection_name):
            return None
        table = self._table(collection_name)
        filename = Path(source_path).name if source_path else ""
        async with self.async_session() as session:
            if source_path:
                hit = await self._first_document(
                    session, table, "metadata->>'source_path' = :v", {"v": source_path}
                )
                if hit is not None:
                    return hit
            if filename:
                hit = await self._first_document(
                    session,
                    table,
                    "metadata->>'filename' = :v AND ("
                    "coalesce(metadata->>'source_path', '') = '' "
                    "OR metadata->>'source_path' = :v)",
                    {"v": filename},
                )
                if hit is not None:
                    return hit
            if content_hash:
                hit = await self._first_document(
                    session, table, "metadata->>'content_hash' = :v", {"v": content_hash}
                )
                if hit is not None:
                    return hit
        return None

    async def _first_document(
        self, session: AsyncSession, table: str, where: str, params: dict[str, Any]
    ) -> DocumentInfo | None:
        """The first document by `(parent_doc_id, id)` matching `where`, or None.

        The order makes a fallback that matches several rows pick the one the
        reference scan would, rather than whichever the heap returns (#548).
        `where` is built from literals here and every value it reads is bound,
        so the only interpolation is the already-validated `table`.
        """
        result = await session.execute(
            text(
                f"SELECT parent_doc_id, metadata FROM {table} "
                f"WHERE {where} ORDER BY parent_doc_id, id LIMIT 1"
            ),
            params,
        )
        row = result.fetchone()
        if row is None:
            return None
        grouped = self._group_documents(
            [
                {
                    "parent_doc_id": row[0],
                    "metadata": row[1] if isinstance(row[1], dict) else json.loads(row[1]),
                }
            ]
        )
        return grouped[0] if grouped else None

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


def process_vector_store(
    settings: RAGSettings, embedding_service: EmbeddingService
) -> PgVectorStore:
    """A store on the process's vector engine, resolving embeddings per collection.

    The one construction the API's lifespan, its per-request fallback, the
    knowledge capability and the CLI all mean. Spelled once because it carries
    two invariants a call site can silently drop: the engine has to be the
    process's shared vector pool - not a private pool per store (#948), and
    not the request pool either, whose connections a handler already holds
    while the store asks for a second (`app.db.session.vector_engine` says why
    that is a circular wait) - and the resolver has to be the platform's, which
    one of five sites once forgot, billing every collection's embeddings to the
    deployment key (#306).

    Two callers are deliberately *not* this, both because a pooled connection
    made on one event loop breaks whoever checks it out on the next: the
    worker's flows, which build an engine per flow
    (`app.worker.tasks.rag_tasks._ingestion_service`), and the knowledge
    capability, which cannot know which loop it is on and takes
    `unpooled_vector_store` instead (#1079).
    """
    return PgVectorStore(
        settings=settings,
        embedding_service=embedding_service,
        resolver=embeddings_for_collection,
        engine=vector_engine,
    )


def unpooled_vector_store(
    settings: RAGSettings, embedding_service: EmbeddingService
) -> PgVectorStore:
    """A store safe to use from any event loop, at one connect per query.

    The same construction as `process_vector_store` and the same resolver, on
    `agent_vector_engine` rather than the process's vector pool. For a caller
    that does not own its event loop and cannot be given one: an agent's
    knowledge search runs on the API's loop in one process and on a Prefect
    flow's loop in another, and a pooled store shared between two loops in one
    worker process hands the second a connection the first opened (#1079).
    `NullPool` keeps no connection to hand over, so one store serves every loop.
    """
    return PgVectorStore(
        settings=settings,
        embedding_service=embedding_service,
        resolver=embeddings_for_collection,
        engine=agent_vector_engine,
    )
