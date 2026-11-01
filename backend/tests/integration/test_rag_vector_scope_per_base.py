"""Two same-named bases of one vector tenant keep their chunks apart (#2537).

A collection name is not unique, so bases share one `rag_<name>` table, and its
rows used to be scoped by the vector tenant alone (#1684). Two pairs share a tenant:

1. An app-scoped base and a personal base outside any organization - both `None`.
   Every member of every organization reads the app base, so its search and
   `total_vectors` included the person's chunks.
2. An organization's base and a personal base in that organization - both the
   organization's id. Searching the organization's base returned the member's
   personal chunks.

Each chunk now records the base it was ingested for, and every row-level read and
write takes the base's `vector_scope`. These seed real bases, ingest through the
real `insert_document`, and drive the real SQL: the defect was a missing predicate,
which only a populated Postgres shows isolating real rows.
"""

import json
import uuid
from collections.abc import AsyncGenerator
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.vector_tables import VectorScope
from app.repositories import knowledge_base_repo
from app.services.rag.config import RAGSettings
from app.services.rag.filters import RetrievalQuery, scope_for
from app.services.rag.models import Document, DocumentMetadata, DocumentPage, DocumentPageChunk
from app.services.rag.vectorstore import PgVectorStore

pytestmark = [pytest.mark.anyio, pytest.mark.security]

COLLECTION = "handbook"
TABLE = f"rag_{COLLECTION}"
ORG = uuid.uuid4()
SOURCE_PATH = "/srv/handbook.pdf"


def _kb(scope: KBScope, organization_id: uuid.UUID | None) -> KnowledgeBase:
    """A base as the store sees it: only its id, scope and organization matter."""
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=COLLECTION,
        scope=scope.value,
        collection_name=COLLECTION,
        embedding_model="m",
        embedding_dim=3,
        organization_id=organization_id,
    )


async def _no_resolution(_name: str, _organization_id: object = None) -> None:
    return


def _store(engine: AsyncEngine) -> PgVectorStore:
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = async_sessionmaker(engine, expire_on_commit=False)
    store.dim = 3
    store.settings = RAGSettings()
    store._resolver = _no_resolution  # type: ignore[assignment]
    # Every chunk and every query embed to the same vector, so a search ranks
    # nothing out and what it returns is exactly what the scope lets through.
    embedder = MagicMock(
        embed_document=lambda document: [[0.1, 0.2, 0.3]] * len(document.chunked_pages),
        embed_query=MagicMock(return_value=[0.1, 0.2, 0.3]),
    )
    store._for_collection = AsyncMock(return_value=(embedder, 3))  # type: ignore[method-assign]
    return store


@pytest.fixture(autouse=True)
def _bases_are_not_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    """These bases never reach `knowledge_bases`, so the write's hold on the base
    (#2561) has no row to find; `test_deletion_reconciliation.py` covers it on real
    rows."""
    monkeypatch.setattr(knowledge_base_repo, "hold_key_share", AsyncMock(return_value=True))


def _document(content: str) -> Document:
    document = Document(
        pages=[DocumentPage(page_num=1, content=content)],
        metadata=DocumentMetadata(
            filename="handbook.pdf",
            filesize=1,
            filetype="pdf",
            source_path=SOURCE_PATH,
            content_hash="same-file",
        ),
    )
    document.chunked_pages = [
        DocumentPageChunk(
            chunk_content=content,
            chunk_num=0,
            page_num=1,
            content=content,
            parent_doc_id=document.id,
        )
    ]
    return document


async def _ingest(store: PgVectorStore, kb: KnowledgeBase, content: str) -> str:
    """Write one document through the real insert, as the base's ingester would."""
    document = _document(content)
    if kb.vector_tenant is not None:
        # What `IngestionService` mirrors from the scope before the insert.
        document.metadata.organization_id = str(kb.vector_tenant)
    await store.insert_document(COLLECTION, document, kb.vector_scope)
    return document.id


async def _unfiled(store: PgVectorStore, *, doc_id: str, tenant: uuid.UUID | None) -> None:
    """A chunk written before chunks recorded their base: only the tenant tag."""
    meta: dict[str, str] = {"source_path": f"/legacy/{doc_id}.pdf", "filename": f"{doc_id}.pdf"}
    if tenant is not None:
        meta["organization_id"] = str(tenant)
    async with store.async_session() as session:
        await session.execute(
            text(
                f"INSERT INTO {TABLE} (id, parent_doc_id, content, embedding, metadata) "  # noqa: S608
                "VALUES (:id, :pid, :content, CAST('[0.1,0.2,0.3]' AS vector), "
                "CAST(:meta AS jsonb))"
            ),
            {"id": f"{doc_id}-0", "pid": doc_id, "content": doc_id, "meta": json.dumps(meta)},
        )
        await session.commit()


async def _searched(store: PgVectorStore, kb: KnowledgeBase) -> set[str]:
    results = await store.search(
        COLLECTION, "anything", RetrievalQuery(scope=scope_for(kb.vector_scope)), limit=20
    )
    return {r.content for r in results}


async def _counted(store: PgVectorStore, kb: KnowledgeBase) -> int:
    return (await store.get_collection_info(COLLECTION, kb.vector_scope)).total_vectors


@pytest.fixture(autouse=True)
async def _clean_runtime_table(engine: AsyncEngine) -> AsyncGenerator[None]:
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
    yield
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))


PAIRS = {
    # Case 1: both have the vector tenant `None`.
    "app-and-orgless-personal": (
        lambda: _kb(KBScope.APP, None),
        lambda: _kb(KBScope.PERSONAL, None),
    ),
    # Case 2: both have the organization's id.
    "org-and-personal-in-org": (
        lambda: _kb(KBScope.ORG, ORG),
        lambda: _kb(KBScope.PERSONAL, ORG),
    ),
}


@pytest.fixture(params=sorted(PAIRS))
def pair(request: pytest.FixtureRequest) -> tuple[KnowledgeBase, KnowledgeBase]:
    shared, personal = PAIRS[request.param]
    return shared(), personal()


async def test_the_tenant_alone_cannot_tell_the_pair_apart(
    engine: AsyncEngine, pair: tuple[KnowledgeBase, KnowledgeBase]
) -> None:
    """The defect, kept as the premise: both bases resolve to one vector tenant, so
    a read scoped by the tenant alone - all the store had before - returns both
    bases' chunks. This is what confirms case 2 as well as case 1."""
    shared, personal = pair
    assert shared.vector_tenant == personal.vector_tenant
    store = _store(engine)
    await _ingest(store, shared, "shared chunk")
    await _ingest(store, personal, "personal chunk")

    tenant_only = VectorScope(tenant=shared.vector_tenant)
    listed = await store.get_documents(COLLECTION, tenant_only)

    assert len(listed) == 2


async def test_each_base_searches_only_its_own_chunks(
    engine: AsyncEngine, pair: tuple[KnowledgeBase, KnowledgeBase]
) -> None:
    shared, personal = pair
    store = _store(engine)
    await _ingest(store, shared, "shared chunk")
    await _ingest(store, personal, "personal chunk")

    assert await _searched(store, shared) == {"shared chunk"}
    assert await _searched(store, personal) == {"personal chunk"}


async def test_each_base_counts_only_its_own_vectors(
    engine: AsyncEngine, pair: tuple[KnowledgeBase, KnowledgeBase]
) -> None:
    shared, personal = pair
    store = _store(engine)
    await _ingest(store, shared, "shared chunk")
    await _ingest(store, personal, "personal chunk one")
    await _ingest(store, personal, "personal chunk two")

    assert await _counted(store, shared) == 1
    assert await _counted(store, personal) == 2


async def test_a_delete_through_one_base_leaves_the_others_chunks(
    engine: AsyncEngine, pair: tuple[KnowledgeBase, KnowledgeBase]
) -> None:
    """Even naming the other base's own vector document id."""
    shared, personal = pair
    store = _store(engine)
    shared_doc = await _ingest(store, shared, "shared chunk")
    personal_doc = await _ingest(store, personal, "personal chunk")

    await store.delete_document(COLLECTION, personal_doc, shared.vector_scope)
    await store.delete_document(COLLECTION, shared_doc, personal.vector_scope)

    assert await _searched(store, shared) == {"shared chunk"}
    assert await _searched(store, personal) == {"personal chunk"}

    await store.delete_document(COLLECTION, personal_doc, personal.vector_scope)

    assert await _searched(store, personal) == set()
    assert await _searched(store, shared) == {"shared chunk"}


async def test_the_replace_lookup_finds_only_the_bases_own_document(
    engine: AsyncEngine, pair: tuple[KnowledgeBase, KnowledgeBase]
) -> None:
    """Both documents share a source path and a hash. The ingest into one base
    looks up what it replaces - and then deletes it - so a match in the other base
    would delete that base's document."""
    shared, personal = pair
    store = _store(engine)
    await _ingest(store, shared, "shared chunk")

    assert (
        await store.find_existing_document(
            COLLECTION,
            source_path=SOURCE_PATH,
            content_hash="same-file",
            scope=personal.vector_scope,
        )
        is None
    )
    assert (
        await store.document_ids_at(
            COLLECTION, source_path=SOURCE_PATH, scope=personal.vector_scope
        )
        == []
    )


async def test_reading_chunks_and_neighbours_stays_in_the_base(
    engine: AsyncEngine, pair: tuple[KnowledgeBase, KnowledgeBase]
) -> None:
    shared, personal = pair
    store = _store(engine)
    personal_doc = await _ingest(store, personal, "personal chunk")

    assert await store.get_document_chunks(COLLECTION, personal_doc, shared.vector_scope) == []
    assert (
        await store.get_chunks_around(
            COLLECTION,
            personal_doc,
            shared.vector_scope,
            page_num=1,
            chunk_num=0,
            before=1,
            after=1,
        )
        == []
    )
    assert [
        c.content
        for c in await store.get_document_chunks(COLLECTION, personal_doc, personal.vector_scope)
    ] == ["personal chunk"]


async def test_the_facet_reads_only_the_bases_own_values(
    engine: AsyncEngine, pair: tuple[KnowledgeBase, KnowledgeBase]
) -> None:
    shared, personal = pair
    store = _store(engine)
    document = _document("personal chunk")
    document.metadata.organizational_unit = "Payroll"
    await store.insert_document(COLLECTION, document, personal.vector_scope)

    values = await store.distinct_metadata_values(
        COLLECTION, ["organizational_unit"], scope_for(shared.vector_scope)
    )

    assert values == {"organizational_unit": []}


class TestUnfiledChunks:
    """Chunks written before chunks recorded their base, and not backfilled - their
    document untracked, or its tracking ambiguous - match by the tenant rule
    `in_collection_scope` applies to unfiled document rows."""

    async def test_the_app_base_keeps_its_unfiled_deployment_wide_chunks(
        self, engine: AsyncEngine
    ) -> None:
        app = _kb(KBScope.APP, None)
        store = _store(engine)
        await store._ensure_collection(COLLECTION)
        await _unfiled(store, doc_id="legacy", tenant=None)

        assert await _searched(store, app) == {"legacy"}

    async def test_a_personal_base_outside_any_organization_takes_none_of_them(
        self, engine: AsyncEngine
    ) -> None:
        """An unfiled chunk with no tenant is the app scope's: the person's own
        chunks are always filed under their base."""
        personal = _kb(KBScope.PERSONAL, None)
        store = _store(engine)
        await store._ensure_collection(COLLECTION)
        await _unfiled(store, doc_id="legacy", tenant=None)

        assert await _searched(store, personal) == set()
        assert await _counted(store, personal) == 0

    async def test_an_organizations_bases_take_its_unfiled_chunks_and_no_others(
        self, engine: AsyncEngine
    ) -> None:
        org_base = _kb(KBScope.ORG, ORG)
        store = _store(engine)
        await store._ensure_collection(COLLECTION)
        await _unfiled(store, doc_id="ours", tenant=ORG)
        await _unfiled(store, doc_id="deployment-wide", tenant=None)
        await _unfiled(store, doc_id="theirs", tenant=uuid.uuid4())

        assert await _searched(store, org_base) == {"ours"}


async def _filed(
    store: PgVectorStore, *, doc_id: str, kb: KnowledgeBase, tenant: uuid.UUID | None
) -> None:
    """A chunk filed under `kb`, carrying `tenant` - which need not be the base's."""
    meta = {"knowledge_base_id": str(kb.id), "filename": f"{doc_id}.pdf"}
    if tenant is not None:
        meta["organization_id"] = str(tenant)
    async with store.async_session() as session:
        await session.execute(
            text(
                f"INSERT INTO {TABLE} (id, parent_doc_id, content, embedding, metadata) "  # noqa: S608
                "VALUES (:id, :pid, :content, CAST('[0.1,0.2,0.3]' AS vector), "
                "CAST(:meta AS jsonb))"
            ),
            {"id": f"{doc_id}-0", "pid": doc_id, "content": doc_id, "meta": json.dumps(meta)},
        )
        await session.commit()


async def test_deleting_a_personal_document_also_removes_its_unfiled_chunks(
    engine: AsyncEngine,
) -> None:
    """A personal base outside any organization reads no unfiled chunks, but a
    document it tracks may still have some - written before chunks recorded their
    base, or left unfiled by the upgrade. Its delete names the document by id, so
    those go too; left behind, a same-named app base would serve them to every
    organization with nothing tracking them."""
    app = _kb(KBScope.APP, None)
    personal = _kb(KBScope.PERSONAL, None)
    store = _store(engine)
    await store._ensure_collection(COLLECTION)
    await _unfiled(store, doc_id="mine", tenant=None)
    assert await _searched(store, app) == {"mine"}

    await store.delete_document(COLLECTION, "mine", personal.vector_scope)

    assert await _searched(store, app) == set()


async def test_a_chunk_filed_under_the_base_with_another_tenant_stays_out(
    engine: AsyncEngine,
) -> None:
    """After an organization purge a personal base has no tenant, and the purge
    re-stamps only its surviving documents. A chunk of a document deleted before
    that - its cleanup lost - is still filed under the base but carries the purged
    organization, and must not come back into the person's search."""
    personal = _kb(KBScope.PERSONAL, None)
    store = _store(engine)
    await store._ensure_collection(COLLECTION)
    await _filed(store, doc_id="restamped", kb=personal, tenant=None)
    await _filed(store, doc_id="deleted-before-purge", kb=personal, tenant=uuid.uuid4())

    assert await _searched(store, personal) == {"restamped"}
    assert await _counted(store, personal) == 1


@pytest.mark.parametrize("tenant", [None, ORG], ids=["orgless", "org"])
async def test_a_bound_union_reads_both_bases_and_no_unbound_sibling(
    engine: AsyncEngine, tenant: uuid.UUID | None
) -> None:
    scope = KBScope.PERSONAL if tenant is None else KBScope.ORG
    first, second, unbound = [_kb(scope, tenant) for _ in range(3)]
    foreign = _kb(KBScope.ORG, uuid.uuid4())
    store = _store(engine)
    await _ingest(store, first, "first")
    await _ingest(store, second, "second")
    unbound_doc = await _ingest(store, unbound, "unbound")
    await _ingest(store, foreign, "foreign")
    union = replace(first.vector_scope, additional_knowledge_base_ids=(second.id,))
    retrieval = scope_for(union)
    assert retrieval.vectors() == union
    results = await store.search(COLLECTION, "anything", RetrievalQuery(scope=retrieval), limit=20)
    assert {result.content for result in results} == {"first", "second"}
    assert (await store.get_collection_info(COLLECTION, union)).total_vectors == 2
    assert len(await store.get_documents(COLLECTION, union)) == 2
    assert await store.get_document_chunks(COLLECTION, unbound_doc, union) == []
