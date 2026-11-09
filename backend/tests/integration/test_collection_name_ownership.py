"""A shared collection name never hands one owner's rows to another (#2747).

A collection name is not unique: two organizations, or two bases of one, can
hold it, and a name can hold rows and chunks no base owns at all - `rag-ingest`
writes both. Two paths acted on the name alone. A sync retired *every* failed
row at its path under the name, another tenant's included; and a claim adopted
a name holding only an operator's content, so deleting the claiming base
dropped the operator's table. Only a real `WHERE` answers whether a predicate
keeps owners apart, so these run against Postgres.
"""

import json
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.user import User
from app.repositories import rag_document_repo
from app.repositories.rag_document import CollectionScope
from app.services.collection_access import CollectionAccessService
from app.services.rag_document import RAGDocumentService

pytestmark = pytest.mark.anyio

PATH = "s3://bucket/handbook.pdf"


async def _org(db: AsyncSession, name: str) -> tuple[Organization, User]:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(founder)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization, founder


async def _kb(
    db: AsyncSession,
    collection_name: str,
    organization_id: uuid.UUID | None,
    *,
    scope: str = KBScope.ORG.value,
) -> KnowledgeBase:
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        name=f"{collection_name}-{uuid.uuid4().hex[:6]}",
        scope=scope,
        collection_name=collection_name,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_provider="openrouter",
        organization_id=organization_id,
        visibility="org" if scope == KBScope.ORG.value else None,
    )
    db.add(kb)
    await db.flush()
    return kb


async def _row(
    db: AsyncSession,
    collection_name: str,
    *,
    organization_id: uuid.UUID | None,
    knowledge_base_id: uuid.UUID | None,
    status: DocumentStatus = DocumentStatus.ERROR,
    vector_document_id: str | None = None,
) -> RAGDocument:
    doc = RAGDocument(
        id=uuid.uuid4(),
        collection_name=collection_name,
        filename="handbook.pdf",
        filesize=4,
        filetype="pdf",
        storage_path="",
        source_path=PATH,
        status=status,
        vector_document_id=vector_document_id,
        chunk_count=0,
        ingestion_config={},
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
    )
    db.add(doc)
    await db.flush()
    return doc


async def _open(
    db: AsyncSession,
    collection_name: str,
    *,
    organization_id: uuid.UUID | None,
    knowledge_base_id: uuid.UUID | None,
) -> RAGDocument:
    """What a sync does for a file it is about to ingest."""
    return await RAGDocumentService(db).create_document(
        collection_name=collection_name,
        filename="handbook.pdf",
        filesize=4,
        filetype="pdf",
        source_path=PATH,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
    )


async def _ids(db: AsyncSession, collection_name: str) -> set[uuid.UUID]:
    result = await db.execute(
        select(RAGDocument.id).where(RAGDocument.collection_name == collection_name)
    )
    return set(result.scalars().all())


def _ctx(organization_id: uuid.UUID, user_id: uuid.UUID, *, app_admin: bool = False):
    return AuthContext(
        user_id=user_id,
        organization_id=organization_id,
        role=OrgRoleName.OWNER.value,
        is_app_admin=app_admin,
    )


class TestASyncRetiresOnlyItsOwnFailedRows:
    @pytest.mark.security
    async def test_another_organizations_failed_row_at_the_same_path_stays(
        self, db: AsyncSession
    ) -> None:
        """The issue's reproduction: A and B each sync `handbook.pdf` into a base
        named `docs`; B's failed row - its error and its retry - survives A's sync."""
        org_a, _ = await _org(db, "Alpha")
        org_b, _ = await _org(db, "Beta")
        kb_a = await _kb(db, "docs", org_a.id)
        kb_b = await _kb(db, "docs", org_b.id)
        theirs = await _row(db, "docs", organization_id=org_b.id, knowledge_base_id=kb_b.id)
        await _row(db, "docs", organization_id=org_a.id, knowledge_base_id=kb_a.id)

        opened = await _open(db, "docs", organization_id=org_a.id, knowledge_base_id=kb_a.id)

        assert await _ids(db, "docs") == {theirs.id, opened.id}

    @pytest.mark.security
    async def test_another_organizations_unfiled_failed_row_stays(self, db: AsyncSession) -> None:
        """A sync with no base, of either tenant, reaches only its own tenant's
        unfiled rows - the other's, and an untagged one, stay."""
        org_a, _ = await _org(db, "Alpha")
        org_b, _ = await _org(db, "Beta")
        theirs = await _row(db, "docs", organization_id=org_b.id, knowledge_base_id=None)
        untagged = await _row(db, "docs", organization_id=None, knowledge_base_id=None)
        await _row(db, "docs", organization_id=org_a.id, knowledge_base_id=None)

        opened = await _open(db, "docs", organization_id=org_a.id, knowledge_base_id=None)

        assert await _ids(db, "docs") == {theirs.id, untagged.id, opened.id}

    @pytest.mark.security
    async def test_an_untagged_unfiled_ingest_retires_only_untagged_rows(
        self, db: AsyncSession
    ) -> None:
        """`rag-ingest` has no organization: `None` matches rows with none, and an
        organization's unfiled row at the same path is not its to retire."""
        org_a, _ = await _org(db, "Alpha")
        theirs = await _row(db, "docs", organization_id=org_a.id, knowledge_base_id=None)
        await _row(db, "docs", organization_id=None, knowledge_base_id=None)

        opened = await _open(db, "docs", organization_id=None, knowledge_base_id=None)

        assert await _ids(db, "docs") == {theirs.id, opened.id}

    @pytest.mark.security
    async def test_another_base_of_the_same_organization_keeps_its_failed_row(
        self, db: AsyncSession
    ) -> None:
        """Two bases of one organization share the name but not their rows (#2537)."""
        org, _ = await _org(db, "Alpha")
        first = await _kb(db, "docs", org.id)
        second = await _kb(db, "docs", org.id)
        theirs = await _row(db, "docs", organization_id=org.id, knowledge_base_id=second.id)

        opened = await _open(db, "docs", organization_id=org.id, knowledge_base_id=first.id)

        assert await _ids(db, "docs") == {theirs.id, opened.id}

    @pytest.mark.security
    async def test_a_base_retires_its_tenants_unfiled_failure(self, db: AsyncSession) -> None:
        """The base lists its tenant's unfiled rows - a failure `mark_unindexed`
        left when the name's table was dropped - so its sync retires them too,
        rather than listing a stale failure beside the new attempt."""
        org, _ = await _org(db, "Alpha")
        kb = await _kb(db, "docs", org.id)
        await _row(db, "docs", organization_id=org.id, knowledge_base_id=None)

        opened = await _open(db, "docs", organization_id=org.id, knowledge_base_id=kb.id)

        assert await _ids(db, "docs") == {opened.id}


async def _vector_table(db: AsyncSession, collection_name: str, tenant: uuid.UUID | None) -> None:
    """A `rag_<name>` table holding one chunk tagged `tenant`, as the store writes it."""
    table = f"rag_{collection_name}"
    await db.execute(
        text(
            f"CREATE TABLE {table} (id VARCHAR(100) PRIMARY KEY, parent_doc_id VARCHAR(100), "
            "content TEXT, metadata JSONB DEFAULT '{}'::jsonb)"
        )
    )
    metadata = "{}" if tenant is None else f'{{"organization_id": "{tenant}"}}'
    await db.execute(
        text(
            f"INSERT INTO {table} (id, parent_doc_id, content, metadata) "  # noqa: S608
            "VALUES ('c1', 'd1', 'chunk', CAST(:metadata AS JSONB))"
        ),
        {"metadata": metadata},
    )


class TestAClaimDoesNotAdoptUnownedContent:
    @pytest.mark.security
    async def test_a_member_cannot_take_an_operators_ingested_name(self, db: AsyncSession) -> None:
        """The issue's reproduction: `rag-ingest ./manuals --collection manuals`
        leaves rows filed under no base and no organization, and a table. A member
        creating a base on `manuals` is refused - deleting that base would drop the
        operator's chunks."""
        org, member = await _org(db, "Alpha")
        await _row(
            db,
            "manuals",
            organization_id=None,
            knowledge_base_id=None,
            status=DocumentStatus.DONE,
            vector_document_id="vec-1",
        )
        await _vector_table(db, "manuals", None)

        with pytest.raises(AlreadyExistsError):
            await CollectionAccessService(db).claim(_ctx(org.id, member.id), "manuals")

    @pytest.mark.security
    async def test_a_table_no_base_holds_is_refused_without_any_row(self, db: AsyncSession) -> None:
        """Chunks written before tracking rows existed are as unowned."""
        org, member = await _org(db, "Alpha")
        other, _ = await _org(db, "Beta")
        await _vector_table(db, "manuals", other.id)

        with pytest.raises(AlreadyExistsError):
            await CollectionAccessService(db).claim(_ctx(org.id, member.id), "manuals")

    @pytest.mark.security
    async def test_an_ingest_still_running_is_unowned_content_too(self, db: AsyncSession) -> None:
        """A `PROCESSING` row has no vector id yet, but its chunks are on the way."""
        org, member = await _org(db, "Alpha")
        await _row(
            db,
            "manuals",
            organization_id=None,
            knowledge_base_id=None,
            status=DocumentStatus.PROCESSING,
        )

        with pytest.raises(AlreadyExistsError):
            await CollectionAccessService(db).claim(_ctx(org.id, member.id), "manuals")

    async def test_the_callers_own_unfiled_content_may_be_claimed(self, db: AsyncSession) -> None:
        """A sync with no base, or a deleted base, left the organization's own
        rows and chunks: its next base on the name takes them, as it always did."""
        org, member = await _org(db, "Alpha")
        await _row(
            db,
            "manuals",
            organization_id=org.id,
            knowledge_base_id=None,
            status=DocumentStatus.DONE,
            vector_document_id="vec-1",
        )
        await _vector_table(db, "manuals", org.id)

        await CollectionAccessService(db).claim(_ctx(org.id, member.id), "manuals")

    async def test_failures_left_by_a_dropped_table_do_not_hold_the_name(
        self, db: AsyncSession
    ) -> None:
        """`mark_unindexed` leaves another tenant's rows failed with no vector id
        when the table goes. They describe no chunk, so nothing of theirs is lost
        if the name's table goes again, and the name is free."""
        org, member = await _org(db, "Alpha")
        await _row(db, "manuals", organization_id=None, knowledge_base_id=None)

        await CollectionAccessService(db).claim(_ctx(org.id, member.id), "manuals")

    async def test_an_app_admin_may_adopt_it(self, db: AsyncSession) -> None:
        """The operator's own path to give `rag-ingest` content a base."""
        org, admin = await _org(db, "Alpha")
        await _row(
            db,
            "manuals",
            organization_id=None,
            knowledge_base_id=None,
            status=DocumentStatus.DONE,
            vector_document_id="vec-1",
        )
        await _vector_table(db, "manuals", None)

        await CollectionAccessService(db).claim(_ctx(org.id, admin.id, app_admin=True), "manuals")

    async def test_a_name_the_caller_holds_stays_claimable(self, db: AsyncSession) -> None:
        """A base the caller writes holds the name, so it may delete that base and
        drop the table anyway: a repeat claim on it is not refused for an
        operator's rows and chunks under the name."""
        org, member = await _org(db, "Alpha")
        await _kb(db, "manuals", org.id)
        await _row(
            db,
            "manuals",
            organization_id=None,
            knowledge_base_id=None,
            status=DocumentStatus.DONE,
            vector_document_id="vec-1",
        )
        await _vector_table(db, "manuals", None)

        await CollectionAccessService(db).claim(_ctx(org.id, member.id), "manuals")

    async def test_no_table_holds_no_chunks(self, db: AsyncSession) -> None:
        assert not await rag_document_repo.table_holds_chunks_outside(
            db, collection_name="manuals", tenant=uuid.uuid4()
        )


async def _chunks(db: AsyncSession, collection_name: str, *metadata: dict[str, str]) -> None:
    """A `rag_<name>` table holding one chunk per `metadata`."""
    table = f"rag_{collection_name}"
    await db.execute(
        text(f"CREATE TABLE {table} (id VARCHAR(100) PRIMARY KEY, metadata JSONB DEFAULT '{{}}')")
    )
    for index, meta in enumerate(metadata):
        await db.execute(
            text(f"INSERT INTO {table} (id, metadata) VALUES (:id, CAST(:meta AS JSONB))"),  # noqa: S608
            {"id": f"c{index}", "meta": json.dumps(meta)},
        )


class TestALastHolderAsksTheTableWhatIsNotItsOwn:
    """What keeps a last holder's table: an unfiled chunk its tenant does not hold.

    A filed chunk is never what keeps it. With the last base gone none is read by
    any scope, and one filed under a base deleted a moment ago is waiting for its
    purge (#2537)."""

    @pytest.mark.security
    async def test_an_organizations_base_is_kept_from_any_other_tenants_chunk(
        self, db: AsyncSession
    ) -> None:
        org, _ = await _org(db, "Alpha")
        other, _ = await _org(db, "Beta")
        for name, metadata in (
            ("untagged", {}),
            ("other", {"organization_id": str(other.id)}),
        ):
            base = await _kb(db, name, org.id)
            await _chunks(db, name, metadata)
            assert await rag_document_repo.table_holds_unfiled_outside(db, CollectionScope.of(base))

    @pytest.mark.security
    async def test_its_own_and_filed_chunks_keep_no_table(self, db: AsyncSession) -> None:
        org, _ = await _org(db, "Alpha")
        other, _ = await _org(db, "Beta")
        base = await _kb(db, "docs", org.id)
        await _chunks(
            db,
            "docs",
            {"organization_id": str(org.id)},
            {"organization_id": str(org.id), "knowledge_base_id": str(base.id)},
            {"organization_id": str(other.id), "knowledge_base_id": str(uuid.uuid4())},
            {"knowledge_base_id": str(uuid.uuid4())},
        )
        assert not await rag_document_repo.table_holds_unfiled_outside(db, CollectionScope.of(base))

    @pytest.mark.security
    async def test_an_app_scoped_base_takes_only_operator_global_chunks(
        self, db: AsyncSession
    ) -> None:
        org, _ = await _org(db, "Alpha")
        takes = await _kb(db, "takes", None, scope=KBScope.APP.value)
        await _chunks(db, "takes", {"writer_kind": "operator"})
        assert not await rag_document_repo.table_holds_unfiled_outside(
            db, CollectionScope.of(takes)
        )

        unknown = await _kb(db, "unknown", None, scope=KBScope.APP.value)
        await _chunks(db, "unknown", {})
        assert await rag_document_repo.table_holds_unfiled_outside(db, CollectionScope.of(unknown))

        kept = await _kb(db, "kept", None, scope=KBScope.APP.value)
        await _chunks(db, "kept", {"organization_id": str(org.id)})
        assert await rag_document_repo.table_holds_unfiled_outside(db, CollectionScope.of(kept))

    @pytest.mark.security
    async def test_a_personal_base_outside_an_organization_takes_no_unfiled_chunk(
        self, db: AsyncSession
    ) -> None:
        """Its tenant `None` is the app scope's, so the operator's untagged chunks
        are as foreign to it as to an organization's base."""
        base = await _kb(db, "mine", None, scope=KBScope.PERSONAL.value)
        await _chunks(db, "mine", {})
        assert await rag_document_repo.table_holds_unfiled_outside(db, CollectionScope.of(base))

    async def test_no_table_keeps_nothing(self, db: AsyncSession) -> None:
        org, _ = await _org(db, "Alpha")
        base = await _kb(db, "docs", org.id)
        assert not await rag_document_repo.table_holds_unfiled_outside(db, CollectionScope.of(base))
