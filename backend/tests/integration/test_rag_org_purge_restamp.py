"""An org purge un-strands the personal bases its `SET NULL` orphans (#1684).

A personal base created while its owner was in an organization records that
organization, so its runtime rows are stamped with it. Deleting the organization
sets `knowledge_bases.organization_id` to `NULL` (the base is preserved), which
flips `KnowledgeBase.vector_tenant` to `None` while the rows stay stamped with the
now-deleted organization - so the read side's `IS NULL` scope no longer matches
them and the base's own chunks become unreachable. The purge re-stamps those rows
to untagged so they match again.

A mock could not show this: the whole mechanism is a `metadata->>'organization_id'`
value the read scope tests against, so only a real table carrying real rows proves
the re-stamp untags exactly the deleted organization's rows and leaves every other
tenant's alone. The purge wiring - which bases it re-stamps, which it excludes - is
pinned in the unit suite (`tests/test_org_purge_reservation.py`,
`tests/test_external_state_cleanup.py`).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import knowledge_base_repo
from app.services.organization import OrganizationService
from app.services.rag.vectorstore import PgVectorStore
from app.worker.tasks.teardown_tasks import cleanup_external_state

# Every test here defends a tenant boundary, so the module carries the security
# marker the refusal report collects.
pytestmark = [pytest.mark.anyio, pytest.mark.security]

COLLECTION = "handbook"
TABLE = f"rag_{COLLECTION}"
ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()


async def _no_resolution(_name: str, _organization_id: object = None) -> None:
    """The re-stamp and the reads take an explicit tenant, so resolution is unused;
    only `_ensure_collection` reads the store's own default width through it."""
    return


def _store(engine: AsyncEngine) -> PgVectorStore:
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = async_sessionmaker(engine, expire_on_commit=False)
    store.dim = 3
    store.embedder = None  # type: ignore[assignment]  # unread for DDL and the scoped ops
    store._resolver = _no_resolution  # type: ignore[assignment]
    return store


async def _insert(store: PgVectorStore, *, doc_id: str, tenant: uuid.UUID | None) -> None:
    meta: dict[str, str] = {"source_path": f"/srv/{doc_id}.pdf", "filename": f"{doc_id}.pdf"}
    if tenant is not None:
        meta["organization_id"] = str(tenant)
    insert = (
        f"INSERT INTO {TABLE} (id, parent_doc_id, content, embedding, metadata) "  # noqa: S608
        "VALUES (:id, :pid, :content, CAST(:emb AS vector), CAST(:meta AS jsonb))"
    )
    async with store.async_session() as session:
        await session.execute(
            text(insert),
            {
                "id": f"{doc_id}-0",
                "pid": doc_id,
                "content": f"content of {doc_id}",
                "emb": "[0.1,0.2,0.3]",
                "meta": json.dumps(meta),
            },
        )
        await session.commit()


async def _seed(store: PgVectorStore) -> None:
    await store._ensure_collection(COLLECTION)
    await _insert(store, doc_id="doc-a", tenant=ORG_A)
    await _insert(store, doc_id="doc-b", tenant=ORG_B)
    await _insert(store, doc_id="doc-none", tenant=None)


@pytest.fixture(autouse=True)
async def _clean_runtime_table(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
    yield
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))


class TestTheStoreReStamp:
    async def test_it_untags_only_the_named_organizations_rows(self, engine: AsyncEngine) -> None:
        """Org A's rows lose the tag and join the untagged, deployment-wide rows;
        Org B's are untouched, and Org A no longer has any tagged rows of its own."""
        store = _store(engine)
        await _seed(store)

        await store.restamp_documents_to_untagged(COLLECTION, ORG_A, ["doc-a"])

        untagged = {d.document_id for d in await store.get_documents(COLLECTION, None)}
        assert untagged == {"doc-a", "doc-none"}
        assert [d.document_id for d in await store.get_documents(COLLECTION, ORG_B)] == ["doc-b"]
        assert await store.get_documents(COLLECTION, ORG_A) == []

    async def test_it_untags_only_the_named_documents_leaving_other_org_rows(
        self, engine: AsyncEngine
    ) -> None:
        """The document-id scope is what keeps the deleted org's own torn-down
        residual rows - and any row the survivor list omits - stamped, so untagging
        one document does not resurrect another (#1684)."""
        store = _store(engine)
        await store._ensure_collection(COLLECTION)
        await _insert(store, doc_id="doc-a", tenant=ORG_A)
        await _insert(store, doc_id="residual", tenant=ORG_A)  # a row not in the survivor list

        await store.restamp_documents_to_untagged(COLLECTION, ORG_A, ["doc-a"])

        assert [d.document_id for d in await store.get_documents(COLLECTION, None)] == ["doc-a"]
        assert [d.document_id for d in await store.get_documents(COLLECTION, ORG_A)] == ["residual"]

    async def test_the_untagged_rows_are_reachable_by_the_read_paths(
        self, engine: AsyncEngine
    ) -> None:
        """`find`, the count and the chunk read all see Org A's rows once they are
        untagged and queried at `vector_tenant=None` - the base's new scope."""
        from unittest.mock import AsyncMock

        store = _store(engine)
        await _seed(store)

        await store.restamp_documents_to_untagged(COLLECTION, ORG_A, ["doc-a"])

        found = await store.find_existing_document(
            COLLECTION, source_path="/srv/doc-a.pdf", content_hash="", tenant=None
        )
        info = await store.get_collection_info(COLLECTION, tenant=None)
        chunks = await store.get_document_chunks(COLLECTION, "doc-a", tenant=None)
        store._for_collection = AsyncMock(  # type: ignore[method-assign]
            return_value=(MagicMock(embed_query=MagicMock(return_value=[0.1, 0.2, 0.3])), 3)
        )
        results = await store.search(COLLECTION, "anything", limit=10, tenant=None)

        assert found is not None and found.document_id == "doc-a"
        assert info.total_vectors == 2  # doc-a and doc-none, both untagged now
        assert len(chunks) == 1
        assert "content of doc-a" in {r.content for r in results}

    async def test_empty_ids_or_a_missing_table_is_a_noop(self, engine: AsyncEngine) -> None:
        """The durable cleanup retries, and a base with no documents or a collection
        whose table was already dropped must not raise - there is nothing to untag."""
        store = _store(engine)
        await _seed(store)

        await store.restamp_documents_to_untagged(COLLECTION, ORG_A, [])  # no ids
        assert [d.document_id for d in await store.get_documents(COLLECTION, ORG_A)] == ["doc-a"]

        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        await store.restamp_documents_to_untagged(COLLECTION, ORG_A, ["doc-a"])  # no table
        assert not await store._collection_exists(COLLECTION)


class TestTheDeferredCleanup:
    async def test_it_untags_the_orphaned_rows_through_the_real_cleanup(
        self, engine: AsyncEngine
    ) -> None:
        """The production path: `cleanup_external_state` resolves the base's own
        document ids and, on its own store, untags exactly those rows. Only the id
        resolution is stubbed; the store UPDATE runs against the real table."""
        from unittest.mock import AsyncMock, patch

        store = _store(engine)
        await _seed(store)

        kb_id = str(uuid.uuid4())
        with patch(
            "app.repositories.rag_document_repo.list_vector_document_ids",
            AsyncMock(return_value=["doc-a"]),
        ):
            result = await cleanup_external_state([], [], [[COLLECTION, str(ORG_A), kb_id]])

        assert result["restamped"] == 1
        reader = _store(engine)
        assert {d.document_id for d in await reader.get_documents(COLLECTION, None)} == {
            "doc-a",
            "doc-none",
        }
        assert [d.document_id for d in await reader.get_documents(COLLECTION, ORG_B)] == ["doc-b"]


async def _org(db: AsyncSession, org_id: uuid.UUID) -> tuple[Organization, User]:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(founder)
    await db.flush()
    org = Organization(
        id=org_id,
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(org)
    await db.flush()
    return org, founder


def _kb(
    *, collection_name: str, scope: str, organization_id: uuid.UUID | None, owner: uuid.UUID | None
) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=collection_name,
        scope=scope,
        collection_name=collection_name,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_provider="openrouter",
        organization_id=organization_id,
        owner_user_id=owner,
    )


class TestThePurgeEndToEnd:
    async def test_it_deletes_org_bases_and_hands_the_personal_ones_to_the_restamp(
        self, db: AsyncSession
    ) -> None:
        """An org-scoped base is torn down; a personal base carrying the org's id
        survives with a null org, and its collection is the one handed to the
        deferred re-stamp - the org's own collection is not (#1684)."""
        org, founder = await _org(db, ORG_A)
        org_kb = _kb(
            collection_name="orgbook", scope=KBScope.ORG.value, organization_id=ORG_A, owner=None
        )
        personal_kb = _kb(
            collection_name="mybook",
            scope=KBScope.PERSONAL.value,
            organization_id=ORG_A,
            owner=founder.id,
        )
        db.add_all([org_kb, personal_kb])
        await db.flush()

        dispatch = MagicMock(return_value=None)
        with (
            patch("app.worker.tasks.teardown_tasks.dispatch_external_state_cleanup", dispatch),
            patch("app.core.background.spawn_after_commit"),
        ):
            await OrganizationService(db, vector_store=MagicMock()).purge(org)

        assert await knowledge_base_repo.get_by_id(db, org_kb.id) is None
        survivor = await knowledge_base_repo.get_by_id(db, personal_kb.id)
        assert survivor is not None
        await db.refresh(survivor)
        assert survivor.organization_id is None  # the `SET NULL` that would strand it

        _paths, to_drop, restamps = dispatch.call_args.args
        assert to_drop == ["orgbook"]
        assert restamps == [["mybook", str(ORG_A), str(personal_kb.id)]]
