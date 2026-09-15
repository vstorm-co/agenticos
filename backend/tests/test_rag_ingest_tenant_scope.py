"""One organization may not reach another's rows on a shared table (#1684).

`rag_<collection>` runtime tables are keyed by collection *name* only, and a
name is not unique across tenants - two organizations that pick the same name
share one physical table. The ingestion replace/dedup path looked a document up
and deleted it with no tenant predicate, so an ingest into a shared-named
collection could find, replace and DELETE a document belonging to a different
tenant.

These are the cheap, structural halves of the fix: that `IngestionService`
threads its bound tenant into every row-level store call, and that
`PgVectorStore` builds the tenant conjunct - `= :org` for a tenant, `IS NULL`
for the deployment-wide caller - with the value always bound. The real SQL
isolating real rows is exercised against a populated Postgres in
`tests/integration/test_rag_ingest_tenant_scope.py`; a mock here would only
restate the WHERE.

This module is template-inherited and outside the coverage gate, which is why
the behaviour is pinned by name rather than trusted to a percentage.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rag.ingestion import IngestionService
from app.services.rag.models import (
    Document,
    DocumentMetadata,
    DocumentPage,
    DocumentPageChunk,
)
from app.services.rag.vectorstore import PgVectorStore

# Every test here is a tenant-isolation refusal, so the whole module carries the
# security marker the refusal report collects.
pytestmark = [pytest.mark.anyio, pytest.mark.security]

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()


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


def _service(organization_id: uuid.UUID | None, *, existing: MagicMock | None = None):
    store = MagicMock()
    store.find_existing_document = AsyncMock(return_value=existing)
    store.insert_document = AsyncMock()
    store.delete_document = AsyncMock()
    processor = MagicMock(process_file=AsyncMock(return_value=_document()))
    service = IngestionService(
        processor=processor, vector_store=store, organization_id=organization_id
    )
    return service, store


class TestTheIngesterThreadsItsBoundTenant:
    """The org is bound once at construction and reaches every store call.

    Bound rather than passed per file so `ingest_file`'s many callers cannot each
    forget it - the trap #992 was, an argument some caller omits.
    """

    async def test_the_existence_lookup_is_scoped_to_the_bound_tenant(self):
        service, store = _service(ORG_A)

        await service.ingest_file(
            filepath=Path("handbook.pdf"),
            collection_name="kb",
            replace=True,
            source_path="/srv/sync/handbook.pdf",
        )

        assert store.find_existing_document.await_args.kwargs["organization_id"] == ORG_A

    async def test_the_replace_delete_is_scoped_to_the_bound_tenant(self):
        existing = MagicMock(document_id="doc-old", additional_info={"content_hash": "hash-old"})
        service, store = _service(ORG_A, existing=existing)

        result = await service.ingest_file(
            filepath=Path("handbook.pdf"),
            collection_name="kb",
            replace=True,
            source_path="/srv/sync/handbook.pdf",
        )

        assert result.replaced_document_id == "doc-old"
        store.delete_document.assert_awaited_once_with("kb", "doc-old", ORG_A)

    async def test_existing_document_passes_the_bound_tenant(self):
        service, store = _service(ORG_B)

        await service.existing_document("kb", "/srv/sync/handbook.pdf", content_hash="h")

        assert store.find_existing_document.await_args.kwargs["organization_id"] == ORG_B

    async def test_remove_document_uses_the_bound_tenant_by_default(self):
        service, store = _service(ORG_A)

        await service.remove_document("kb", "doc-1")

        assert store.delete_document.await_args.kwargs["organization_id"] == ORG_A

    async def test_remove_document_takes_an_explicit_tenant_over_the_bound_one(self):
        """The tracking service deletes by the document row's own organization -
        exactly the tenant the chunks were stamped with - which may be handed in
        rather than left to the request-bound default."""
        service, store = _service(ORG_A)

        await service.remove_document("kb", "doc-1", ORG_B)

        assert store.delete_document.await_args.kwargs["organization_id"] == ORG_B


class TestTheChunkMetadataCarriesTheTenant:
    def _store(self) -> PgVectorStore:
        store = PgVectorStore.__new__(PgVectorStore)
        return store

    def _chunk(self) -> DocumentPageChunk:
        return DocumentPageChunk(chunk_content="body", chunk_num=0, page_num=1, content="body")

    def test_a_tenant_is_stamped_as_text(self):
        meta = self._store()._build_chunk_metadata(self._chunk(), _document(), ORG_A)

        assert meta["organization_id"] == str(ORG_A)

    def test_no_tenant_leaves_no_tag(self):
        """The deployment-wide write (CLI, local sync) stamps nothing, so the
        `IS NULL` scope its own reads use matches it."""
        meta = self._store()._build_chunk_metadata(self._chunk(), _document(), None)

        assert "organization_id" not in meta


class TestTheOrgFilterClause:
    def test_a_tenant_is_an_equality_with_a_bound_value(self):
        clause, params = PgVectorStore._org_filter(ORG_A)

        assert clause == "(metadata->>'organization_id') = :org"
        assert params == {"org": str(ORG_A)}

    def test_the_deployment_wide_caller_is_is_null_and_binds_nothing(self):
        clause, params = PgVectorStore._org_filter(None)

        assert clause == "(metadata->>'organization_id') IS NULL"
        assert params == {}


class TestPgVectorStoreScopesEveryRowOp:
    """Each statement carries the tenant conjunct and binds the value (#1684)."""

    @staticmethod
    def _store_over(execute: AsyncMock, *, tenant: uuid.UUID | None = ORG_A) -> PgVectorStore:
        """A store whose collection resolves to `tenant`.

        The row ops resolve the collection's tenant before scoping, so the stub
        lives on `_tenant` and `_for_collection` rather than on the caller's
        organization argument - which is why passing an organization does not
        change what these assert.
        """
        session = MagicMock(execute=execute, commit=AsyncMock())
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)
        embedder = MagicMock(
            embed_query=MagicMock(return_value=[0.1, 0.2, 0.3]),
            embed_document=MagicMock(return_value=[[0.1, 0.2, 0.3]]),
        )
        store = PgVectorStore.__new__(PgVectorStore)
        store.async_session = MagicMock(return_value=session_ctx)
        store._collection_exists = AsyncMock(return_value=True)  # type: ignore[method-assign]
        store._table = MagicMock(return_value="rag_kb")  # type: ignore[method-assign]
        store._ensure_collection = AsyncMock()  # type: ignore[method-assign]
        store._tenant = AsyncMock(return_value=tenant)  # type: ignore[method-assign]
        store._for_collection = AsyncMock(return_value=(embedder, 3, tenant))  # type: ignore[method-assign]
        return store

    async def test_find_existing_document_binds_the_tenant_on_each_key(self):
        execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
        store = self._store_over(execute)

        await store.find_existing_document(
            "kb", source_path="/p/x.pdf", content_hash="h", organization_id=ORG_A
        )

        for call in execute.await_args_list:
            statement = str(call.args[0])
            assert "(metadata->>'organization_id') = :org" in statement
            assert call.args[1]["org"] == str(ORG_A)

    async def test_find_existing_document_uses_is_null_for_the_deployment_wide_collection(self):
        execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
        store = self._store_over(execute, tenant=None)

        await store.find_existing_document("kb", source_path="/p/x.pdf", content_hash="h")

        statement = str(execute.await_args_list[0].args[0])
        assert "(metadata->>'organization_id') IS NULL" in statement
        assert "org" not in execute.await_args_list[0].args[1]

    async def test_delete_document_scopes_by_tenant(self):
        execute = AsyncMock()
        store = self._store_over(execute)

        await store.delete_document("kb", "doc-1", ORG_A)

        statement = str(execute.await_args.args[0])
        assert "parent_doc_id = :doc_id AND (metadata->>'organization_id') = :org" in statement
        assert execute.await_args.args[1]["org"] == str(ORG_A)

    async def test_get_documents_scopes_by_tenant(self):
        execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
        store = self._store_over(execute)

        await store.get_documents("kb", ORG_A)

        statement = str(execute.await_args.args[0])
        assert "WHERE (metadata->>'organization_id') = :org" in statement
        assert "ORDER BY parent_doc_id, id" in statement

    async def test_get_document_chunks_scopes_by_tenant(self):
        execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
        store = self._store_over(execute)

        await store.get_document_chunks("kb", "doc-1", ORG_A)

        statement = str(execute.await_args.args[0])
        assert "parent_doc_id = :doc_id AND (metadata->>'organization_id') = :org" in statement

    async def test_search_scopes_reads_by_tenant(self):
        execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
        store = self._store_over(execute)

        await store.search("kb", "query", limit=4, organization_id=ORG_A)

        statement = str(execute.await_args.args[0])
        assert "(metadata->>'organization_id') = :org" in statement
        assert execute.await_args.args[1]["org"] == str(ORG_A)

    async def test_get_collection_info_counts_only_the_tenants_rows(self):
        execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=2)))
        store = self._store_over(execute)

        info = await store.get_collection_info("kb", ORG_A)

        statement = str(execute.await_args.args[0])
        assert "COUNT(*)" in statement
        assert "WHERE (metadata->>'organization_id') = :org" in statement
        assert info.total_vectors == 2


class TestInsertResolvesAndWritesTheTenant:
    """`insert_document` resolves the collection's tenant and renders it into the
    JSON metadata parameter it binds, which is what the scoped reads match on."""

    async def test_the_inserted_metadata_json_carries_the_resolved_tenant(self):
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
            return_value=(MagicMock(embed_document=lambda d: [[0.1]]), 3, ORG_A)
        )

        await store.insert_document("kb", _document())

        rows = execute.await_args.args[1]
        assert json.loads(rows[0]["metadata"])["organization_id"] == str(ORG_A)
