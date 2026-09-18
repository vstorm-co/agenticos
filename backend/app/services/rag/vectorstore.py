import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from uuid import UUID

# Registers every model table on `Base.metadata`, which `list_collections` judges a
# `rag_` table against and `_table` refuses a collection name against. Another import
# already reaches the models today; this one says the store depends on it, rather than
# leaving that to a chain belonging to a different concern. On an empty metadata both
# answers invert silently: the listing reports the tracking table as a collection, and
# a caller may drop it.
import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.vector_tables import (
    RAG_SAFE_TO_DATE_FN,
    VECTOR_CONTENT_HASH_INDEX_SUFFIX,
    VECTOR_DOCDATE_INDEX_SUFFIX,
    VECTOR_DOCTYPE_INDEX_SUFFIX,
    VECTOR_FILENAME_INDEX_SUFFIX,
    VECTOR_INDEX_SUFFIX,
    VECTOR_ORG_INDEX_SUFFIX,
    VECTOR_ORGUNIT_INDEX_SUFFIX,
    VECTOR_SOURCE_INDEX_SUFFIX,
    VECTOR_SOURCE_PATH_INDEX_SUFFIX,
    VECTOR_TABLE_PREFIX,
    is_runtime_vector_table,
    validate_collection_name,
)
from app.schemas.rag import RAGDocumentItem, RAGDocumentList
from app.services.rag.filters import AppScope, RetrievalQuery, RetrievalScope, TenantScope
from app.services.rag.models import (
    CollectionInfo,
    Document,
    DocumentChunk,
    DocumentInfo,
    DocumentPageChunk,
    SearchResult,
    VectorDocumentId,
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
    async def _ensure_collection(self, name: str) -> None:
        """Create the collection's backing objects if they do not already exist.

        `create_collection` below is the one concrete method every subclass
        shares, and it calls this; declaring it abstract here is what makes a
        subclass that forgets to implement it fail at class definition rather
        than at the first `create_collection` call.
        """

    @abstractmethod
    async def insert_document(
        self, collection_name: str, document: Document, tenant: UUID | None = None
    ) -> None:
        """Write a document's chunks, stamped with the collection's tenant.

        `tenant` is the collection's own - its organization for an org base,
        `None` for an app-scoped one every organization reads or a collection no
        knowledge base claims - passed in by the ingester that resolved the base.
        It is recorded on every chunk, so the shared runtime table (a collection
        name is not unique across tenants) can be scoped per tenant afterwards
        (#1684).
        """

    @abstractmethod
    async def search(
        self,
        collection_name: str,
        query: str,
        query_filter: RetrievalQuery,
        limit: int = 4,
    ) -> list[SearchResult]:
        """Nearest chunks, restricted by the composed scope AND business filters.

        `query_filter` carries the server-trusted `RetrievalScope` (the mandatory
        tenant conjunct, or the explicit unscoped maintenance marker) and the
        caller-supplied `RetrievalFilters`. The store ANDs every restriction into
        the backend query before top-k, so a selective filter cannot leak an
        out-of-scope row and top-k is computed over already-restricted rows.
        """

    @abstractmethod
    async def resolve_tenant(self, name: str, organization_id: UUID | None) -> UUID | None:
        """The tenant a search of this collection scopes its rows by (#1684).

        The retrieval service resolves it from the collection for the searching
        organization and hands it to `search` and `get_documents`; see the
        `PgVectorStore` implementation for the semantics.
        """

    @abstractmethod
    async def delete_collection(self, collection_name: str) -> None:
        pass

    @abstractmethod
    async def delete_document(
        self, collection_name: str, document_id: str, tenant: UUID | None = None
    ) -> None:
        """Remove one document's chunks, only within the collection's tenant.

        `tenant` scopes the delete to the rows that tenant wrote, so a collection
        name shared across tenants cannot have one org delete another's document
        (#1684). `None` matches only the untagged, deployment-wide rows.
        """

    @abstractmethod
    async def restamp_documents_to_untagged(
        self, collection_name: str, tenant: UUID, knowledge_base_id: UUID
    ) -> None:
        """Strip an organization's tag off a base's own rows, making them untagged.

        Used by an organization purge for a personal base the `SET NULL` orphans:
        its `vector_tenant` flips to `None` while its rows stay stamped with the
        deleted organization, so they must be re-stamped to untagged to match the
        `None` read scope again (#1684). Scoped to the base's *surviving* documents,
        resolved from `rag_documents` inside the one update statement, *and* to
        `tenant`'s tag - so a shared runtime table's other tenants, the deleted
        org's own torn-down residual rows, and a document deleted before this runs
        are all left alone. Resolving the survivor set in the same statement rather
        than from a list read earlier closes the window in which a document deleted
        between the read and the update would be un-deleted here (#1684). A base with
        no surviving documents or a missing table is a no-op, so the durable
        cleanup's retry is safe.
        """

    @abstractmethod
    async def get_collection_info(
        self,
        collection_name: str,
        organization_id: UUID | None = None,
        tenant: UUID | None = None,
    ) -> CollectionInfo:
        pass

    @abstractmethod
    async def list_collections(self) -> list[str]:
        pass

    @abstractmethod
    async def get_documents(
        self, collection_name: str, tenant: UUID | None = None
    ) -> list[DocumentInfo]:
        """Every document the tenant holds in a collection.

        `tenant` scopes the listing to that tenant's own rows on a shared runtime
        table (#1684); `None` lists only the untagged, deployment-wide rows.
        """

    @abstractmethod
    async def get_document_chunks(
        self, collection_name: str, document_id: str, tenant: UUID | None = None
    ) -> list[DocumentChunk]:
        """Every stored chunk of one document, in document order.

        Document order means (page_num, chunk_num) ascending - the order the
        splitter produced them - so callers can reconstruct what the parse
        looked like. An unknown document or collection is an empty list.

        `tenant` scopes the read to that tenant's own rows, so a shared collection
        name does not expose another tenant's chunks (#1684).
        """

    @abstractmethod
    async def distinct_metadata_values(
        self, collection_name: str, keys: list[str], scope: RetrievalScope
    ) -> dict[str, list[str]]:
        """Distinct in-scope values for whitelisted free-form metadata keys.

        Backs the filter-value facet so a caller can discover the corpus's
        author-supplied values (e.g. `organizational_unit`) rather than guessing.
        Tenant-scoped by the same `RetrievalScope` search carries, so it never
        reveals another organization's values, and empty for an absent collection.
        """

    async def get_document_list(
        self, collection_name: str, tenant: UUID | None = None
    ) -> RAGDocumentList:
        docs = await self.get_documents(collection_name, tenant)
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
        self,
        collection_name: str,
        *,
        source_path: str,
        content_hash: str,
        tenant: UUID | None = None,
    ) -> DocumentInfo | None:
        """The stored document this file refers to, found by one precedence.

        `tenant` is the collection's own, passed in by the ingester that resolved
        the knowledge base: the search is confined to the rows that tenant wrote,
        so a collection name shared across tenants cannot have one org match,
        replace or delete another's document (#1684). This reference
        implementation gets that confinement for free, because `get_documents`
        already scopes to the tenant.

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
        docs = await self.get_documents(collection_name, tenant)
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
        self,
        chunk: "DocumentPageChunk",
        document: Document,
        tenant: UUID | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "page_num": chunk.page_num,
            "chunk_num": chunk.chunk_num,
            "has_images": bool(getattr(chunk, "images", None)),
            "image_count": len(getattr(chunk, "images", [])),
            **document.metadata.model_dump(),
        }
        # The tenant tag. `document.metadata.organization_id` already carries it in
        # the spread above for a caller that set it directly (a store caller with
        # no separate tenant argument to give, like a test seeding rows) - never
        # from parsed file content or an uploaded field, since `DocumentProcessor`
        # leaves it unset and only a trusted caller writes it (#1684). `tenant` is
        # an explicit override for a caller that resolved the collection's own
        # knowledge base separately from the `Document` it is inserting -
        # `IngestionService`, which mirrors it onto `document.metadata.organization_id`
        # itself before this is ever reached, so the two cannot disagree in
        # practice. Stored as text so `metadata->>'organization_id'` - what every
        # scoped query reads and what the hash index is built on - compares
        # against it directly. `None` on both leaves the key out of the spread
        # entirely, so the `IS NULL` scope matches it.
        if tenant is not None:
            metadata["organization_id"] = str(tenant)
        return metadata

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
from app.services.embedding_resolution import (
    EmbeddingKeySource,
    ResolvedEmbeddings,
    embeddings_for_collection,
)
from app.services.rag.config import EmbeddingsConfig, RAGSettings
from app.services.rag.embeddings import EmbeddingService

# How a store learns which model a collection embeds with. Async because the
# answer lives in the database, injected so the template's store never imports
# platform policy. The organization scopes resolution to the right tenant when a
# collection name is shared, and is None where the caller has none in hand (#913).
EmbeddingResolver = Callable[[str, UUID | None], Awaitable[ResolvedEmbeddings | None]]

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


# The free-form metadata keys the facet read may return distinct values for.
# Whitelisted because the key name is interpolated into SQL (the values are not).
_FACET_KEYS: frozenset[str] = frozenset({"organizational_unit", "source", "document_type"})


def _scope_conjuncts(scope: RetrievalScope) -> tuple[list[str], dict[str, Any]]:
    """The mandatory server-trusted conjuncts for a scope (tenant + FA-037 slot).

    A `TenantScope` contributes the mandatory tenant conjunct as an equality; an
    `AppScope` contributes it as `IS NULL`, since an app-scoped ingest stamps no
    tenant onto its rows (#1688) - the two are mutually exclusive, so a row
    matches at most one. Either way, when the authorization slot is populated, the
    per-document restriction is added too. The unscoped maintenance marker
    contributes nothing. Every value is bound.
    """
    conjuncts: list[str] = []
    params: dict[str, Any] = {}
    authz: frozenset[VectorDocumentId] | None = None
    if isinstance(scope, TenantScope):
        conjuncts.append("metadata->>'organization_id' = :scope_org")
        params["scope_org"] = str(scope.organization_id)
        authz = scope.authorized_document_ids
    elif isinstance(scope, AppScope):
        conjuncts.append("(metadata->>'organization_id') IS NULL")
        authz = scope.authorized_document_ids
    if authz is not None:
        if authz:
            # Intersected with any business parent_doc_id (both are AND
            # conjuncts), so an id outside the authorized set matches nothing.
            conjuncts.append("parent_doc_id = ANY(:scope_authz)")
            params["scope_authz"] = list(authz)
        else:
            # Populated-but-empty => match nothing (empty-denies-all). Never
            # conflated with None, which leaves the slot unapplied.
            conjuncts.append("FALSE")
    return conjuncts, params


def _retrieval_conjuncts(query_filter: RetrievalQuery) -> tuple[list[str], dict[str, Any]]:
    """Translate a composed scope+filters object into bound SQL conjuncts.

    Every value is a bound parameter; the only literals are the fixed metadata
    key names and the `rag_safe_to_date` helper name, so nothing caller-supplied
    is interpolated. Semantics: OR within a multi-value field (`= ANY(:list)`),
    AND across fields and against the scope. This is the pgvector mapping of the
    backend-neutral contract; another store owns its own translation.
    """
    conjuncts, params = _scope_conjuncts(query_filter.scope)

    filters = query_filter.filters
    if filters.source is not None:
        conjuncts.append("metadata->>'source' = ANY(:f_source)")
        params["f_source"] = list(filters.source)
    if filters.document_type is not None:
        conjuncts.append("metadata->>'document_type' = ANY(:f_doctype)")
        params["f_doctype"] = list(filters.document_type)
    if filters.organizational_unit is not None:
        conjuncts.append("metadata->>'organizational_unit' = ANY(:f_orgunit)")
        params["f_orgunit"] = list(filters.organizational_unit)
    if filters.date_from is not None:
        # A row whose doc_date is missing or malformed yields NULL here, so the
        # comparison is NULL and the row fails closed - excluded from a date
        # filter rather than raising on a bad `::date` cast (FA-039 R7).
        conjuncts.append(f"{RAG_SAFE_TO_DATE_FN}(metadata->>'doc_date') >= :f_date_from")
        params["f_date_from"] = filters.date_from
    if filters.date_to is not None:
        conjuncts.append(f"{RAG_SAFE_TO_DATE_FN}(metadata->>'doc_date') <= :f_date_to")
        params["f_date_to"] = filters.date_to
    if filters.parent_doc_id is not None:
        conjuncts.append("parent_doc_id = :f_parent_doc_id")
        params["f_parent_doc_id"] = filters.parent_doc_id

    return conjuncts, params


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
        # outside the KB table gets this store's own keyless embedder, which
        # refuses on first use - the resolver answering None rather than nobody
        # asking.
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

    async def _for_collection(
        self, name: str, organization_id: UUID | None = None
    ) -> tuple[EmbeddingService, int]:
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
                # So a resolution that ended on an empty key says which key it
                # tried, for which collection, instead of advising an operator
                # to set a variable they may already have set.
                key_origin=resolved.describe(name),
                # The collection's provider. In the cache key beside the model and
                # the key, because moving a collection to another provider must
                # not be answered by a client already built for the old one.
                base_url=resolved.base_url,
                keyless=resolved.key_source is EmbeddingKeySource.KEYLESS,
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

    @staticmethod
    def _org_filter(tenant: UUID | None) -> tuple[str, dict[str, Any]]:
        """The tenant conjunct for the shared runtime table, and its bound param.

        Every row carries the organization that ingested it in
        `metadata->>'organization_id'` (stamped by `_build_chunk_metadata`), and
        a caller may only find, replace, delete or read the rows of the tenant it
        resolved to - the whole of the #1684 fix, since a collection name is not
        unique across tenants and they share one physical table.

        `tenant` is the resolved vector tenant, not a caller's raw organization:
        `None` is a deployment-wide collection - an app-scoped base every
        organization reads, the CLI, a local-path sync - and matches only rows
        with no tenant tag. It is `IS NULL` deliberately, not a dropped
        predicate: without a conjunct the deployment-wide caller would read and
        delete across every tenant, which is the defect inverted rather than
        fixed. The clause is built from these two literals alone; the value is
        always bound.
        """
        if tenant is None:
            return "(metadata->>'organization_id') IS NULL", {}
        return "(metadata->>'organization_id') = :org", {"org": str(tenant)}

    async def resolve_tenant(self, name: str, organization_id: UUID | None) -> UUID | None:
        """The tenant a search of this collection scopes its rows by (#1684).

        Only the search path uses this, and only when the caller carries an
        organization - a route request, an agent run - which has one that is never
        None. It maps that organization to the one knowledge base the caller may
        read for this name (its own where a name is shared, an app-scoped base as
        the deployment-wide fallback, #913) and returns that base's vector tenant:
        its organization for an org base, `None` for an app-scoped one every
        organization reads or a collection no base claims.

        `None` in short-circuits to `None`: a caller with no organization - the
        CLI's `rag-search` - is deployment-wide, and must not be handed whichever
        organization's base a name-only lookup happened to match first. Every
        other path is handed the exact tenant of the knowledge base it already
        resolved, rather than resolving one from a name.
        """
        if organization_id is None:
            return None
        resolved = await self._resolver(name, organization_id)
        return resolved.vector_tenant if resolved is not None else None

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
                # The tenant key every row-level op scopes by (#1684), plus the
                # FA-039 equality filter dimensions. Same hash-index shape and
                # reasoning as the lookup keys above: equality only, a value may
                # be unbounded in length, and `0086_scope_rag_rows_by_org`
                # backfills the collections created before `organization_id`
                # existed.
                (VECTOR_ORG_INDEX_SUFFIX, "organization_id"),
                (VECTOR_SOURCE_INDEX_SUFFIX, "source"),
                (VECTOR_DOCTYPE_INDEX_SUFFIX, "document_type"),
                (VECTOR_ORGUNIT_INDEX_SUFFIX, "organizational_unit"),
            ):
                await session.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {table}{suffix} "
                        f"ON {table} USING hash ((metadata->>'{key}'))"
                    )
                )
            # The date dimension is a range, so a partial btree on the identical
            # safe expression the WHERE predicate uses, `WHERE` the result is
            # non-NULL - so the index build cannot raise on a bad legacy row
            # (FA-039 R7). `rag_safe_to_date` is created by the prerequisite
            # migration, which must have run before any collection is ensured.
            await session.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {table}{VECTOR_DOCDATE_INDEX_SUFFIX} "
                    f"ON {table} (({RAG_SAFE_TO_DATE_FN}(metadata->>'doc_date'))) "
                    f"WHERE {RAG_SAFE_TO_DATE_FN}(metadata->>'doc_date') IS NOT NULL"
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

    async def insert_document(
        self, collection_name: str, document: Document, tenant: UUID | None = None
    ) -> None:
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
        # `tenant` is the collection's own, passed in by the ingester that
        # resolved the knowledge base; it is stamped on every chunk so the shared
        # runtime table can be scoped per tenant afterwards (#1684).
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
                            "metadata": json.dumps(
                                self._build_chunk_metadata(chunk, document, tenant)
                            ),
                        }
                        for i, chunk in batch
                    ],
                )
            await session.commit()

    async def search(
        self,
        collection_name: str,
        query: str,
        query_filter: RetrievalQuery,
        limit: int = 4,
    ) -> list[SearchResult]:
        """Nearest chunks, restricted by scope AND business filters, absent = empty.

        A collection's table is created by its first ingest, so "no table" and
        "nothing indexed yet" are one state here - the same reasoning
        `get_collection_info` documents below. Without the check, searching a
        knowledge base nobody has uploaded to yet turned asyncpg's
        `UndefinedTableError` into a 500, and it is checked before embedding so
        an empty collection costs no embedding call either.

        `query_filter` carries the server-trusted `RetrievalScope` and the
        caller-supplied `RetrievalFilters`. Every restriction is applied in the
        SQL `WHERE` (not a Python post-filter), so top-k is computed over already
        restricted rows. The tenant conjunct is mandatory for a `TenantScope`
        (`metadata->>'organization_id' = :scope_org`) or an `AppScope`
        (`... IS NULL`), and absent only for the explicit unscoped maintenance
        marker. `query_filter.organization_id` also scopes which tenant's
        knowledge base the query embeds through, so a name shared across
        organizations does not embed on another tenant's key (#913).
        """
        table = self._table(collection_name)
        if not await self._collection_exists(collection_name):
            return []
        embedder, dim = await self._for_collection(collection_name, query_filter.organization_id)
        query_vector = embedder.embed_query(query)

        conjuncts, filter_params = _retrieval_conjuncts(query_filter)
        where_clause = f"WHERE {' AND '.join(conjuncts)}" if conjuncts else ""
        # The query vector has to be cast the same way the column is, or Postgres
        # compares a halfvec against a vector and refuses the operator outright.
        query_expr = f"(:query_vec)::halfvec({dim})" if dim > _HNSW_MAX_VECTOR_DIM else ":query_vec"
        params: dict[str, Any] = {"query_vec": str(query_vector), "limit": limit, **filter_params}

        distance = self._distance_expr(dim)
        async with self.async_session() as session:
            await self._apply_search_tuning(session)
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
        results = [
            SearchResult(
                content=row[0],
                score=float(row[3]),
                metadata=row[2] if isinstance(row[2], dict) else json.loads(row[2]),
                parent_doc_id=row[1],
            )
            for row in rows
        ]
        # Re-sort by score: `hnsw.iterative_scan = 'relaxed_order'` does not
        # guarantee exact distance order, so the store orders the fetched rows
        # rather than trusting the scan's order (FA-039 H1).
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    async def _apply_search_tuning(self, session: AsyncSession) -> None:
        """Tune HNSW recall for this search's transaction (FA-039 H1).

        `set_config(name, value, is_local=true)` is `SET LOCAL`, so the knobs
        apply to this search's transaction only and never leak to another
        statement or an unfiltered path on the same connection. Iterative index
        scan (pgvector >= 0.8) keeps the scan expanding past `ef_search` until it
        has `k` rows that pass the mandatory, selective tenant conjunct, bounded
        by `max_scan_tuples`; the raised `ef_search` is the fallback.

        The whole block runs inside a savepoint: on a pgvector older than 0.8
        `hnsw.iterative_scan` is an unknown GUC and setting it aborts the
        (sub)transaction, so the savepoint is rolled back and the search proceeds
        on defaults rather than failing. Set `hnsw_iterative_scan = false` to skip
        the unknown knobs entirely on such an image.
        """
        knobs: list[tuple[str, str]] = []
        if self.settings.hnsw_iterative_scan:
            knobs.append(("hnsw.iterative_scan", "relaxed_order"))
            knobs.append(("hnsw.max_scan_tuples", str(self.settings.hnsw_max_scan_tuples)))
        knobs.append(("hnsw.ef_search", str(self.settings.hnsw_ef_search)))
        try:
            async with session.begin_nested():
                for name, value in knobs:
                    await session.execute(
                        text("SELECT set_config(:name, :value, true)"),
                        {"name": name, "value": value},
                    )
        except Exception:
            logger.warning(
                "HNSW search tuning unavailable (iterative scan needs pgvector >= 0.8); "
                "searching on defaults",
                exc_info=True,
            )

    async def get_collection_info(
        self,
        collection_name: str,
        organization_id: UUID | None = None,
        tenant: UUID | None = None,
    ) -> CollectionInfo:
        """Vector count for a collection, reporting an absent one as empty.

        A collection's table is created lazily by the first ingest, so "no table"
        and "nothing indexed yet" are the same state in this design - which is
        why this reports zero rather than raising. It used to run the COUNT
        unconditionally and let asyncpg's `UndefinedTableError` become a 500,
        so asking about a knowledge base nobody had uploaded to yet looked like
        the server breaking. `get_documents` has always answered the same
        question with an empty list; its comment claimed this method already did
        the same, and now it does.

        `organization_id` scopes the width lookup to the caller's own knowledge
        base, so a collection name shared across tenants does not resolve - and
        unseal the vault key of - another organization's row (#913). `tenant`
        scopes the count, so a shared name reports the caller's own vector total
        rather than every tenant's summed together (#1684).
        """
        _, dim = await self._for_collection(collection_name, organization_id)
        if not await self._collection_exists(collection_name):
            return CollectionInfo(name=collection_name, total_vectors=0, dim=dim)
        table = self._table(collection_name)
        org_clause, org_params = self._org_filter(tenant)
        async with self.async_session() as session:
            result = await session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {org_clause}"),
                org_params,
            )
            count = result.scalar() or 0
        return CollectionInfo(name=collection_name, total_vectors=count, dim=dim)

    async def delete_collection(self, collection_name: str) -> None:
        table = self._table(collection_name)
        async with self.async_session() as session:
            await session.execute(text(f"DROP TABLE IF EXISTS {table}"))
            await session.commit()

    async def delete_document(
        self, collection_name: str, document_id: str, tenant: UUID | None = None
    ) -> None:
        table = self._table(collection_name)
        sanitized = self._sanitize_id(document_id)
        # The tenant conjunct is what stops one org deleting another's document
        # from the shared table (#1684): matching a `parent_doc_id` alone reaches
        # every tenant's rows under that id, which is how the replace path could
        # delete across tenants. `tenant` is the collection's own, passed in by
        # the caller that resolved the knowledge base, so it agrees with the tag
        # the ingest wrote.
        org_clause, org_params = self._org_filter(tenant)
        async with self.async_session() as session:
            await session.execute(
                text(f"DELETE FROM {table} WHERE parent_doc_id = :doc_id AND {org_clause}"),
                {"doc_id": sanitized, **org_params},
            )
            await session.commit()

    async def restamp_documents_to_untagged(
        self, collection_name: str, tenant: UUID, knowledge_base_id: UUID
    ) -> None:
        """Drop the `organization_id` tag from a base's own rows stamped by a tenant.

        `metadata - 'organization_id'` makes `metadata->>'organization_id'` read
        `NULL`, which is exactly what the `None` branch of `_org_filter` tests -
        so the orphaned personal base's rows match its new `vector_tenant=None`,
        the same as a personal base that never carried an organization (#1684).

        Two conjuncts, both load-bearing on a runtime table a collection name shares
        across tenants (#913). The `parent_doc_id IN (SELECT ...)` subquery confines
        the update to the base's *surviving* documents - the `vector_document_id`s
        `rag_documents` still holds for this knowledge base - so the deleted org's
        own torn-down residual rows, another tenant's rows, and a document deleted
        before this runs (its `rag_documents` row is gone, so it is not in the
        subquery) are never touched. Resolving that set in the *same* statement,
        rather than from a list read in a separate earlier query, is what closes the
        window: a document the owner deletes concurrently is either still tracked
        when this statement's snapshot is taken (untagged here, then removed by its
        own `tenant=None` cleanup) or already gone (left stamped and never
        un-deleted), never un-deleted-and-orphaned as a stale id list allowed
        (#1684). The `_org_filter(tenant)` conjunct then untags only rows still
        stamped with the deleted org. Every value is bound; `_table` validates the
        only interpolated token. A base with no surviving documents or a missing
        table is a no-op, so a retry is safe.
        """
        if not await self._collection_exists(collection_name):
            return
        table = self._table(collection_name)
        org_clause, org_params = self._org_filter(tenant)
        # The only interpolated token is `table`, validated by `_table`; the tenant
        # and the knowledge-base id are bound. `rag_documents` is a fixed model
        # table name, not caller input. S608 is ignored file-wide for that reason.
        async with self.async_session() as session:
            await session.execute(
                text(
                    f"UPDATE {table} SET metadata = metadata - 'organization_id' "
                    f"WHERE {org_clause} AND parent_doc_id IN ("
                    "SELECT vector_document_id FROM rag_documents "
                    "WHERE knowledge_base_id = :kb_id AND vector_document_id IS NOT NULL)"
                ),
                {"kb_id": knowledge_base_id, **org_params},
            )
            await session.commit()

    async def get_documents(
        self, collection_name: str, tenant: UUID | None = None
    ) -> list[DocumentInfo]:
        # Return an empty list for non-existent collections instead of silently
        # creating them via _ensure_collection. `get_collection_info` answers the
        # same question the same way.
        if not await self._collection_exists(collection_name):
            return []
        table = self._table(collection_name)
        # Scoped to the caller's own tenant on the shared table (#1684); the
        # reference `find_existing_document` reads this, so the scope reaches the
        # lookup too.
        org_clause, org_params = self._org_filter(tenant)
        async with self.async_session() as session:
            # Ordered so a lookup that falls back to a filename match does not
            # depend on heap order (#548).
            result = await session.execute(
                text(
                    f"SELECT parent_doc_id, metadata FROM {table} "
                    f"WHERE {org_clause} ORDER BY parent_doc_id, id"
                ),
                org_params,
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

    async def distinct_metadata_values(
        self, collection_name: str, keys: list[str], scope: RetrievalScope
    ) -> dict[str, list[str]]:
        """Distinct in-scope values for whitelisted free-form metadata keys.

        Backs the filter-value facet: it makes the corpus-dependent
        `organizational_unit` values discoverable so a caller narrows on values
        that exist rather than guessing one that returns silently empty. The read
        is tenant-scoped by the same `RetrievalScope` every search carries, so it
        never reveals another organization's values. Keys are whitelisted because
        the key name is interpolated into SQL (the values never are).
        """
        unknown = [key for key in keys if key not in _FACET_KEYS]
        if unknown:
            raise ValueError(f"not a facetable metadata key: {', '.join(sorted(unknown))}")
        result: dict[str, list[str]] = {key: [] for key in keys}
        if not await self._collection_exists(collection_name):
            return result
        table = self._table(collection_name)
        scope_conjuncts, params = _scope_conjuncts(scope)
        async with self.async_session() as session:
            for key in keys:
                conjuncts = [f"metadata->>'{key}' IS NOT NULL", *scope_conjuncts]
                rows = await session.execute(
                    text(
                        f"SELECT DISTINCT metadata->>'{key}' AS value FROM {table} "
                        f"WHERE {' AND '.join(conjuncts)} ORDER BY value"
                    ),
                    params,
                )
                result[key] = [row[0] for row in rows.fetchall() if row[0] is not None]
        return result

    async def find_existing_document(
        self,
        collection_name: str,
        *,
        source_path: str,
        content_hash: str,
        tenant: UUID | None = None,
    ) -> DocumentInfo | None:
        """Look the document up by its indexed metadata keys, not a full scan (#1102).

        One indexed statement per key, in the precedence the base class
        documents - `source_path`, then a `filename` the stored document has not
        addressed under another path, then `content_hash` - stopping at the
        first hit. Each statement returns one document, so the id and hash a
        caller reads name one document, which is the #548 invariant.

        Every statement carries the tenant conjunct, so the match is confined to
        the rows the ingesting organization wrote (#1684): a collection name
        shared across tenants cannot let one org find - and then replace or
        delete - another's document. `tenant` is the collection's own, passed in
        by the ingester that resolved the knowledge base, the same source the
        ingest stamped from.

        The expression indexes these lean on are built by `_ensure_collection`;
        a collection predating them still answers correctly, at a scan, until
        its next ingest rebuilds them through that same path.
        """
        if not await self._collection_exists(collection_name):
            return None
        table = self._table(collection_name)
        filename = Path(source_path).name if source_path else ""
        org_clause, org_params = self._org_filter(tenant)
        async with self.async_session() as session:
            if source_path:
                hit = await self._first_document(
                    session,
                    table,
                    f"metadata->>'source_path' = :v AND {org_clause}",
                    {"v": source_path, **org_params},
                )
                if hit is not None:
                    return hit
            if filename:
                hit = await self._first_document(
                    session,
                    table,
                    "metadata->>'filename' = :v AND ("
                    "coalesce(metadata->>'source_path', '') = '' "
                    f"OR metadata->>'source_path' = :v) AND {org_clause}",
                    {"v": filename, **org_params},
                )
                if hit is not None:
                    return hit
            if content_hash:
                hit = await self._first_document(
                    session,
                    table,
                    f"metadata->>'content_hash' = :v AND {org_clause}",
                    {"v": content_hash, **org_params},
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
        self, collection_name: str, document_id: str, tenant: UUID | None = None
    ) -> list[DocumentChunk]:
        # Same answer for "no such collection" as get_documents: empty, not an
        # UndefinedTableError dressed up as a 500.
        if not await self._collection_exists(collection_name):
            return []
        table = self._table(collection_name)
        # Scoped to the caller's own tenant, so a shared collection name cannot
        # read back another organization's chunk content (#1684).
        org_clause, org_params = self._org_filter(tenant)
        async with self.async_session() as session:
            result = await session.execute(
                text(
                    f"SELECT content, metadata FROM {table} "
                    f"WHERE parent_doc_id = :doc_id AND {org_clause}"
                ),
                {"doc_id": self._sanitize_id(document_id), **org_params},
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
