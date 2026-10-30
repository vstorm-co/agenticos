"""One organization may not reach another's rows on a shared table (#1684).

`rag_<collection>` runtime tables are keyed by collection *name* only, and a
name is not unique across tenants - two organizations that pick the same name
share one physical table. The ingestion replace/dedup path looked a document up
and deleted it with no tenant predicate, so an ingest into a shared-named
collection could find, replace and DELETE a document belonging to a different
tenant.

These are the cheap, structural halves of the fix: that `IngestionService`
threads its bound tenant into every row-level store call, that a search resolves
its tenant from the collection, and that `PgVectorStore` builds the tenant
conjunct - `= :org` for a tenant, `IS NULL` for a deployment-wide collection -
with the value always bound. The real SQL isolating real rows is exercised
against a populated Postgres in `tests/integration/test_rag_ingest_tenant_scope.py`.

This module is template-inherited and outside the coverage gate, which is why
the behaviour is pinned by name rather than trusted to a percentage.
"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.vector_tables import VectorScope
from app.services.embedding_resolution import EmbeddingKeySource, ResolvedEmbeddings
from app.services.rag.filters import AppScope, RetrievalQuery, TenantScope, scope_for
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import (
    Document,
    DocumentMetadata,
    DocumentPage,
    DocumentPageChunk,
)
from app.services.rag.vectorstore import PgVectorStore, _vector_scope_clause

# Every test here is a tenant-isolation refusal, so the whole module carries the
# security marker the refusal report collects.
pytestmark = [pytest.mark.anyio, pytest.mark.security]

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
KB_A = uuid.uuid4()
SCOPE_A = VectorScope(tenant=ORG_A, knowledge_base_id=KB_A)
SCOPE_B = VectorScope(tenant=ORG_B)
DEPLOYMENT_WIDE = VectorScope(tenant=None)


def _document(*, content_hash: str = "hash-new") -> Document:
    document = Document(
        pages=[DocumentPage(page_num=1, content="body")],
        metadata=DocumentMetadata(filename="handbook.pdf", filesize=4, filetype="pdf"),
    )
    document.chunked_pages = [
        DocumentPageChunk(chunk_content="body", chunk_num=0, page_num=1, content="body")
    ]
    document.metadata.content_hash = content_hash
    return document


def _service(scope: VectorScope | None, *, existing: MagicMock | None = None):
    store = MagicMock()
    store.find_existing_document = AsyncMock(return_value=existing)
    store.insert_document = AsyncMock()
    store.delete_document = AsyncMock()
    processor = MagicMock(process_file=AsyncMock(return_value=_document()))
    service = IngestionService(processor=processor, vector_store=store, scope=scope)
    return service, store


class TestTheIngesterThreadsItsBoundTenant:
    """The scope (tenant and base) is bound once at construction and reaches every store call.

    Bound rather than passed per file so `ingest_file`'s many callers cannot each
    forget it - the trap #992 was, an argument some caller omits.
    """

    async def test_insert_carries_the_bound_tenant(self):
        service, store = _service(SCOPE_A)

        await service.ingest_file(
            filepath=Path("handbook.pdf"),
            collection_name="kb",
            replace=True,
            source_path="/srv/sync/handbook.pdf",
        )

        assert store.insert_document.await_args.kwargs["scope"] == SCOPE_A

    async def test_the_existence_lookup_is_scoped_to_the_bound_tenant(self):
        service, store = _service(SCOPE_A)

        await service.ingest_file(
            filepath=Path("handbook.pdf"),
            collection_name="kb",
            replace=True,
            source_path="/srv/sync/handbook.pdf",
        )

        assert store.find_existing_document.await_args.kwargs["scope"] == SCOPE_A

    async def test_the_replace_delete_is_scoped_to_the_bound_tenant(self):
        existing = MagicMock(document_id="doc-old", additional_info={"content_hash": "hash-old"})
        service, store = _service(SCOPE_A, existing=existing)

        result = await service.ingest_file(
            filepath=Path("handbook.pdf"),
            collection_name="kb",
            replace=True,
            source_path="/srv/sync/handbook.pdf",
        )

        assert result.replaced_document_id == "doc-old"
        store.delete_document.assert_awaited_once_with("kb", "doc-old", SCOPE_A)

    async def test_existing_document_passes_the_bound_tenant(self):
        service, store = _service(SCOPE_B)

        await service.existing_document("kb", "/srv/sync/handbook.pdf", content_hash="h")

        assert store.find_existing_document.await_args.kwargs["scope"] == SCOPE_B

    async def test_document_metadata_mirrors_the_bound_tenant_not_a_caller_value(self):
        """`document.metadata.organization_id` is set from the bound scope alone.

        It used to be set from a caller-supplied `organization_id` naming the
        *paying* organization, which disagreed with the bound tenant for an
        app-scoped base (the scope's tenant is `None` even though a real organization
        uploaded and paid) - mistagging the row with the payer and leaving it
        unreachable by every scope (#1684, FA-039). There is no `organization_id`
        parameter on `ingest_file` to pass a conflicting value through any more.
        """
        service, store = _service(SCOPE_A)

        await service.ingest_file(
            filepath=Path("handbook.pdf"),
            collection_name="kb",
            replace=True,
            source_path="/srv/sync/handbook.pdf",
        )

        document = store.insert_document.await_args.kwargs["document"]
        assert document.metadata.organization_id == str(ORG_A)

    async def test_an_app_scoped_ingester_stamps_no_organization_on_the_document(self):
        service, store = _service(DEPLOYMENT_WIDE)

        await service.ingest_file(
            filepath=Path("handbook.pdf"),
            collection_name="kb",
            replace=True,
            source_path="/srv/sync/handbook.pdf",
        )

        document = store.insert_document.await_args.kwargs["document"]
        assert document.metadata.organization_id is None

    async def test_remove_document_uses_the_bound_scope_by_default(self):
        service, store = _service(SCOPE_A)

        await service.remove_document("kb", "doc-1")

        assert store.delete_document.await_args.kwargs["scope"] == SCOPE_A

    async def test_remove_document_takes_an_explicit_scope_over_the_bound_one(self):
        """The tracking service deletes by the document's own base's scope -
        exactly the tags the chunks were stamped with - handed in rather than left
        to the request-bound default."""
        service, store = _service(SCOPE_A)

        await service.remove_document("kb", "doc-1", SCOPE_B)

        assert store.delete_document.await_args.kwargs["scope"] == SCOPE_B

    async def test_remove_document_honours_an_explicit_deployment_wide_scope(self):
        """The deployment-wide tenant is a real scope - the rows an app-scoped
        document writes - so it must not be replaced by the ingester's bound one."""
        service, store = _service(SCOPE_A)

        await service.remove_document("kb", "doc-1", DEPLOYMENT_WIDE)

        assert store.delete_document.await_args.kwargs["scope"] == DEPLOYMENT_WIDE

    async def test_an_ingester_bound_to_nothing_is_deployment_wide(self):
        service, store = _service(None)

        await service.remove_document("kb", "doc-1")

        assert store.delete_document.await_args.kwargs["scope"] == DEPLOYMENT_WIDE


class TestTheChunkMetadataCarriesTheTenant:
    def _store(self) -> PgVectorStore:
        return PgVectorStore.__new__(PgVectorStore)

    def _chunk(self) -> DocumentPageChunk:
        return DocumentPageChunk(chunk_content="body", chunk_num=0, page_num=1, content="body")

    def test_a_tenant_is_stamped_as_text(self):
        meta = self._store()._build_chunk_metadata(self._chunk(), _document(), SCOPE_A)

        assert meta["organization_id"] == str(ORG_A)

    def test_the_base_is_stamped_as_text(self):
        """The base a chunk was ingested for, so two same-named bases of one
        tenant - or an app base and a personal base outside any organization -
        can tell their chunks apart (#2537)."""
        meta = self._store()._build_chunk_metadata(self._chunk(), _document(), SCOPE_A)

        assert meta["knowledge_base_id"] == str(KB_A)

    def test_no_base_leaves_the_chunk_unfiled(self):
        meta = self._store()._build_chunk_metadata(self._chunk(), _document(), SCOPE_B)

        assert "knowledge_base_id" not in meta

    def test_no_tenant_leaves_no_tag(self):
        """A deployment-wide write (app-scoped, CLI, local sync) stamps nothing,
        so the `IS NULL` scope its own reads use matches it. `DocumentMetadata`
        always carries the key (pydantic dumps every field), so this is a null
        value rather than an absent key - `metadata->>'organization_id'` reads
        both as SQL NULL, which is what the scope actually tests against."""
        meta = self._store()._build_chunk_metadata(self._chunk(), _document(), DEPLOYMENT_WIDE)

        assert meta["organization_id"] is None

    def test_a_tenant_set_directly_on_document_metadata_is_stamped(self):
        """A caller with no separate tenant argument - a direct store caller
        seeding rows, not through `IngestionService` - sets
        `document.metadata.organization_id` itself and gets it stamped as-is."""
        doc = _document()
        doc.metadata.organization_id = str(ORG_A)

        meta = self._store()._build_chunk_metadata(self._chunk(), doc, DEPLOYMENT_WIDE)

        assert meta["organization_id"] == str(ORG_A)


class TestKnowledgeBaseVectorTenant:
    """The tenant a collection's rows are stamped and scoped by, off its base."""

    @staticmethod
    def _kb(scope: str, organization_id: uuid.UUID | None):
        from app.db.models.knowledge_base import KnowledgeBase

        return KnowledgeBase(
            id=KB_A,
            name="handbook",
            scope=scope,
            collection_name="handbook",
            embedding_model="m",
            embedding_dim=3,
            organization_id=organization_id,
        )

    def test_an_org_base_carries_its_organization(self):
        from app.db.models.knowledge_base import KBScope

        assert self._kb(KBScope.ORG.value, ORG_A).vector_tenant == ORG_A

    def test_an_app_base_is_deployment_wide_and_carries_no_tenant(self):
        """Readable by every organization, so its rows carry no tenant even if a
        stray organization id were set on the row."""
        from app.db.models.knowledge_base import KBScope

        assert self._kb(KBScope.APP.value, ORG_A).vector_tenant is None

    def test_a_personal_base_carries_no_tenant(self):
        from app.db.models.knowledge_base import KBScope

        assert self._kb(KBScope.PERSONAL.value, None).vector_tenant is None

    def test_an_org_base_reads_its_own_and_its_organizations_unfiled_chunks(self):
        from app.db.models.knowledge_base import KBScope

        assert self._kb(KBScope.ORG.value, ORG_A).vector_scope == VectorScope(
            tenant=ORG_A, knowledge_base_id=KB_A, takes_unfiled=True
        )

    def test_a_personal_base_in_an_organization_names_itself(self):
        """Same tenant as the organization's base, so only the base id keeps an
        organization's search from returning a member's personal chunks (#2537)."""
        from app.db.models.knowledge_base import KBScope

        assert self._kb(KBScope.PERSONAL.value, ORG_A).vector_scope == VectorScope(
            tenant=ORG_A, knowledge_base_id=KB_A, takes_unfiled=True
        )

    def test_an_app_base_takes_the_unfiled_deployment_wide_chunks(self):
        from app.db.models.knowledge_base import KBScope

        assert self._kb(KBScope.APP.value, None).vector_scope == VectorScope(
            tenant=None, knowledge_base_id=KB_A, takes_unfiled=True
        )

    def test_a_personal_base_outside_any_organization_takes_no_unfiled_chunks(self):
        """Its tenant is `None`, as the app scope's is: an unfiled chunk with no
        tenant belongs to a same-named app base, never to the person (#2537)."""
        from app.db.models.knowledge_base import KBScope

        assert self._kb(KBScope.PERSONAL.value, None).vector_scope == VectorScope(
            tenant=None, knowledge_base_id=KB_A, takes_unfiled=False
        )


class TestTheScopeClause:
    @pytest.mark.parametrize("tenant", [None, ORG_A], ids=["orgless", "org"])
    @pytest.mark.parametrize("takes_unfiled", [False, True])
    def test_a_bound_union_preserves_the_tenant_and_round_trips(self, tenant, takes_unfiled):
        second = uuid.uuid4()
        scope = VectorScope(
            tenant=tenant,
            knowledge_base_id=KB_A,
            takes_unfiled=takes_unfiled,
            additional_knowledge_base_ids=(second,),
        )
        assert scope_for(scope).vectors() == scope
        clause, params = _vector_scope_clause(scope, prefix="search_")
        assert "(metadata->>'knowledge_base_id') = ANY(:search_kbs)" in clause
        assert params["search_kbs"] == [str(KB_A), str(second)]
        if tenant is None:
            assert "(metadata->>'organization_id') IS NULL" in clause
        else:
            assert params["search_org"] == str(tenant)
        assert ("OR (metadata->>'knowledge_base_id') IS NULL" in clause) is takes_unfiled

    def test_a_tenant_is_an_equality_with_a_bound_value(self):
        clause, params = _vector_scope_clause(VectorScope(tenant=ORG_A))

        assert clause == "(metadata->>'organization_id') = :org"
        assert params == {"org": str(ORG_A)}

    def test_the_deployment_wide_caller_is_is_null_and_binds_nothing(self):
        clause, params = _vector_scope_clause(DEPLOYMENT_WIDE)

        assert clause == "(metadata->>'organization_id') IS NULL"
        assert params == {}

    def test_a_base_takes_its_own_chunks_and_its_tenants_unfiled_ones(self):
        """The rule `in_collection_scope` applies to document rows (#2537)."""
        clause, params = _vector_scope_clause(SCOPE_A)

        assert clause == (
            "(metadata->>'organization_id') = :org AND "
            "((metadata->>'knowledge_base_id') = :kb OR "
            "(metadata->>'knowledge_base_id') IS NULL)"
        )
        assert params == {"org": str(ORG_A), "kb": str(KB_A)}

    def test_a_base_that_takes_no_unfiled_chunks_reads_only_its_own(self):
        """A personal base outside any organization: an unfiled chunk with no
        tenant is the app scope's, never the person's (#2537). The tenant rule
        still applies, so a filed chunk still carrying a purged organization's
        tag - a document deleted before the re-stamp - stays out."""
        scope = VectorScope(tenant=None, knowledge_base_id=KB_A, takes_unfiled=False)

        clause, params = _vector_scope_clause(scope)

        assert clause == (
            "(metadata->>'organization_id') IS NULL AND (metadata->>'knowledge_base_id') = :kb"
        )
        assert params == {"kb": str(KB_A)}

    async def test_a_delete_by_id_also_removes_the_documents_unfiled_chunks(self):
        """Even from a base that reads no unfiled chunks: the document is named
        by its own id, and its unfiled chunks left behind would be read through a
        same-named app-scoped base with nothing tracking them (#2537)."""
        execute = AsyncMock()
        store = TestPgVectorStoreScopesEveryRowOp._store_over(execute)
        scope = VectorScope(tenant=None, knowledge_base_id=KB_A, takes_unfiled=False)

        await store.delete_document("kb", "doc-1", scope)

        statement = str(execute.await_args.args[0])
        assert "(metadata->>'knowledge_base_id') IS NULL" in statement

    def test_a_prefix_keeps_the_bound_names_apart(self):
        clause, params = _vector_scope_clause(SCOPE_A, prefix="scope_")

        assert ":scope_kb" in clause and ":scope_org" in clause
        assert set(params) == {"scope_org", "scope_kb"}


class TestResolveScopeForASearch:
    """The one place a scope is resolved rather than passed: a search, whose
    caller carries an organization but not the knowledge base (#1684, #2537)."""

    @staticmethod
    def _store(resolved: ResolvedEmbeddings | None) -> PgVectorStore:
        store = PgVectorStore.__new__(PgVectorStore)
        store._resolver = AsyncMock(return_value=resolved)  # type: ignore[method-assign]
        return store

    async def test_no_organization_short_circuits_to_the_deployment_wide_tenant(self):
        """A caller with no organization - the CLI - is deployment-wide and must
        not be handed whichever base a name-only lookup matched first."""
        store = self._store(ResolvedEmbeddings.__new__(ResolvedEmbeddings))
        store._resolver = AsyncMock(side_effect=AssertionError("must not resolve"))  # type: ignore[method-assign]

        assert await store.resolve_scope("kb", None) == DEPLOYMENT_WIDE

    async def test_an_org_collection_resolves_to_its_base(self):
        resolved = ResolvedEmbeddings(
            model="m",
            dim=3,
            api_key="",
            key_source=EmbeddingKeySource.KEYLESS,
            base_url="",
            provider="p",
            vector_scope=SCOPE_A,
        )
        store = self._store(resolved)

        assert await store.resolve_scope("kb", ORG_B) == SCOPE_A

    async def test_a_collection_no_base_claims_resolves_to_the_deployment_wide_tenant(self):
        store = self._store(None)

        assert await store.resolve_scope("kb", ORG_B) == DEPLOYMENT_WIDE


@asynccontextmanager
async def _noop_savepoint() -> AsyncIterator[None]:
    yield


class TestPgVectorStoreScopesEveryRowOp:
    """Each statement carries the tenant conjunct and binds the value (#1684)."""

    @staticmethod
    def _store_over(execute: AsyncMock) -> PgVectorStore:
        session = MagicMock(execute=execute, commit=AsyncMock())
        # `search` tunes HNSW recall inside a savepoint (FA-039 H1); a mocked
        # session has to satisfy that context manager too.
        session.begin_nested = MagicMock(side_effect=_noop_savepoint)
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)
        embedder = MagicMock(embed_query=MagicMock(return_value=[0.1, 0.2, 0.3]))
        store = PgVectorStore.__new__(PgVectorStore)
        store.async_session = MagicMock(return_value=session_ctx)
        store.settings = MagicMock(hnsw_iterative_scan=False, hnsw_ef_search=100)
        store._collection_exists = AsyncMock(return_value=True)  # type: ignore[method-assign]
        store._table = MagicMock(return_value="rag_kb")  # type: ignore[method-assign]
        store._for_collection = AsyncMock(return_value=(embedder, 3))  # type: ignore[method-assign]
        return store

    async def test_find_existing_document_binds_the_tenant_on_each_key(self):
        execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
        store = self._store_over(execute)

        await store.find_existing_document(
            "kb", source_path="/p/x.pdf", content_hash="h", scope=VectorScope(tenant=ORG_A)
        )

        for call in execute.await_args_list:
            statement = str(call.args[0])
            assert "(metadata->>'organization_id') = :org" in statement
            assert call.args[1]["org"] == str(ORG_A)

    async def test_find_existing_document_uses_is_null_for_a_deployment_wide_collection(self):
        execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
        store = self._store_over(execute)

        await store.find_existing_document(
            "kb", source_path="/p/x.pdf", content_hash="h", scope=DEPLOYMENT_WIDE
        )

        statement = str(execute.await_args_list[0].args[0])
        assert "(metadata->>'organization_id') IS NULL" in statement
        assert "org" not in execute.await_args_list[0].args[1]

    async def test_delete_document_scopes_by_tenant(self):
        execute = AsyncMock()
        store = self._store_over(execute)

        await store.delete_document("kb", "doc-1", VectorScope(tenant=ORG_A))

        statement = str(execute.await_args.args[0])
        assert "parent_doc_id = :doc_id AND (metadata->>'organization_id') = :org" in statement
        assert execute.await_args.args[1]["org"] == str(ORG_A)

    async def test_get_documents_scopes_by_tenant(self):
        execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
        store = self._store_over(execute)

        await store.get_documents("kb", VectorScope(tenant=ORG_A))

        statement = str(execute.await_args.args[0])
        assert "WHERE (metadata->>'organization_id') = :org" in statement
        assert "ORDER BY parent_doc_id, id" in statement

    async def test_get_document_chunks_scopes_by_tenant(self):
        execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
        store = self._store_over(execute)

        await store.get_document_chunks("kb", "doc-1", VectorScope(tenant=ORG_A))

        statement = str(execute.await_args.args[0])
        assert "parent_doc_id = :doc_id AND (metadata->>'organization_id') = :org" in statement

    async def test_search_scopes_reads_by_tenant(self):
        execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
        store = self._store_over(execute)

        await store.search(
            "kb", "query", RetrievalQuery(scope=TenantScope(organization_id=ORG_A)), limit=4
        )

        statement = str(execute.await_args.args[0])
        assert "(metadata->>'organization_id') = :scope_org" in statement
        assert execute.await_args.args[1]["scope_org"] == str(ORG_A)

    async def test_search_scopes_an_app_base_by_is_null(self):
        """The FA-039 `AppScope` compiles to the same `IS NULL` conjunct the
        deployment-wide row-level scope uses, so an app-scoped base's search
        reads its own untagged rows rather than matching nothing (#1684)."""
        execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
        store = self._store_over(execute)

        await store.search("kb", "query", RetrievalQuery(scope=AppScope()), limit=4)

        statement = str(execute.await_args.args[0])
        assert "(metadata->>'organization_id') IS NULL" in statement
        assert "scope_org" not in execute.await_args.args[1]

    async def test_get_collection_info_counts_only_the_tenants_rows(self):
        execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=2)))
        store = self._store_over(execute)

        info = await store.get_collection_info("kb", VectorScope(tenant=ORG_A), ORG_A)

        statement = str(execute.await_args.args[0])
        assert "COUNT(*)" in statement
        assert "WHERE (metadata->>'organization_id') = :org" in statement
        assert info.total_vectors == 2


class TestInsertStampsTheTenantIntoTheStatementParams:
    """`insert_document` renders the tenant into the JSON metadata parameter it
    binds, which is what the scoped reads later match on."""

    async def test_the_inserted_metadata_json_carries_the_tenant(self):
        execute = AsyncMock()
        session = MagicMock(execute=execute, commit=AsyncMock())
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)
        store = PgVectorStore.__new__(PgVectorStore)
        store.async_session = MagicMock(return_value=session_ctx)
        store._table = MagicMock(return_value="rag_kb")  # type: ignore[method-assign]
        store._ensure_collection = AsyncMock()  # type: ignore[method-assign]
        store._for_collection = AsyncMock(  # type: ignore[method-assign]
            return_value=(MagicMock(embed_document=lambda d: [[0.1]]), 3)
        )

        await store.insert_document("kb", _document(), SCOPE_A)

        rows = execute.await_args.args[1]
        assert json.loads(rows[0]["metadata"])["organization_id"] == str(ORG_A)
        assert json.loads(rows[0]["metadata"])["knowledge_base_id"] == str(KB_A)
