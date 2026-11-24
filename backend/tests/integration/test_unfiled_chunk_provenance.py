"""A retained legacy table must not publish a former personal base's chunks (#2773)."""

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.background import drain, start_deferred
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.knowledge_base import KBScope
from app.services.collection_access import CollectionAccessService
from app.services.knowledge_base import KnowledgeBaseService
from app.services.rag.filters import RetrievalQuery, scope_for
from tests.integration.test_deletion_reconciliation import (
    _member,
    _org,
    _org_collection,
    _personal_kb,
    _store_embedding_in_3d,
    _user,
)
from tests.integration.test_deletion_reconciliation import (
    _run_queued_cleanups_after_the_commit as _run_queued_cleanups_after_the_commit,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("operator", [False, True], ids=["unknown-private", "confirmed-operator"])
async def test_claiming_a_deleted_personal_name_does_not_publish_its_rowless_legacy_chunk(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, operator: bool
) -> None:
    collection = f"provenance{uuid4().hex[:12]}"
    store = _store_embedding_in_3d(engine)
    table = store._table(collection)
    embedder, _ = await store._for_collection(collection)
    monkeypatch.setattr(embedder, "embed_query", MagicMock(return_value=[0.1, 0.2, 0.3]))
    await store._ensure_collection(collection)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        owner, admin, reader = _user(), _user(), _user()
        admin.is_app_admin = True
        session.add_all([owner, admin, reader])
        await session.flush()
        reader_org = await _org(session, admin)
        await _member(session, reader_org.id, reader.id, OrgRoleName.VIEWER.value)
        personal = _personal_kb(uuid4(), owner.id, collection)
        personal.organization_id = None
        personal.embedding_dim = 3
        session.add(personal)
        await session.flush()
        await session.execute(
            text(
                f"INSERT INTO {table} (id, parent_doc_id, content, embedding, metadata) "  # noqa: S608 - validated random collection
                "VALUES ('legacy-0', 'legacy-doc', :content, '[0.1,0.2,0.3]'::vector, CAST(:metadata AS jsonb))"
            ),
            {
                "content": "Former owner's private notes",
                "metadata": json.dumps(
                    {
                        "filename": "private.txt",
                        "filesize": 1,
                        "filetype": "txt",
                        **({"writer_kind": "operator"} if operator else {}),
                    }
                ),
            },
        )
        await session.commit()
        personal_id = personal.id
        owner_ctx = AuthContext(user_id=owner.id, organization_id=None, role=OrgRoleName.OWNER)
        admin_ctx = AuthContext(
            user_id=admin.id, organization_id=None, role=OrgRoleName.OWNER, is_app_admin=True
        )
        reader_ctx = AuthContext(
            user_id=reader.id, organization_id=reader_org.id, role=OrgRoleName.VIEWER
        )
    try:
        async with factory() as session:
            await KnowledgeBaseService(session).delete(personal_id, ctx=owner_ctx)
            await session.commit()
            start_deferred(session)
        await drain()
        async with factory() as session:
            # The private row-less chunk keeps the table. No owner may be guessed.
            assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 1  # noqa: S608 - store-validated name
            await CollectionAccessService(session).claim(admin_ctx, collection)
            app_base = _org_collection(uuid4(), collection)
            app_base.scope = KBScope.APP.value
            app_base.organization_id = None
            app_base.embedding_dim = 3
            session.add(app_base)
            await session.commit()
        async with factory() as session:
            assert reader_ctx.has(Perm.COLLECTIONS_VIEW)
            visible = await CollectionAccessService(session).readable(reader_ctx, collection)
            results = await store.search(
                collection, "private notes", RetrievalQuery(scope=scope_for(visible.vector_scope))
            )
            assert [result.content for result in results] == (
                ["Former owner's private notes"] if operator else []
            )
            app_id = visible.id
        async with factory() as session:
            await KnowledgeBaseService(session).delete(app_id, ctx=admin_ctx)
            await session.commit()
            start_deferred(session)
        await drain()
        assert await store._collection_exists(collection) is (not operator)
        if not operator:
            async with factory() as session:
                assert await session.scalar(text(f"SELECT count(*) FROM {table}")) == 1  # noqa: S608 - validated name
    finally:
        await drain()
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE IF EXISTS {table}"))


@pytest.mark.parametrize("origin", [None, "legacy_unknown", "document", "operator", "sql_null"])
async def test_operator_confirmation_never_promotes_a_known_document(
    engine: AsyncEngine, origin: str | None
) -> None:
    from sqlalchemy import select

    from app.db.models.rag_document import RAGDocument
    from app.db.vector_tables import VectorScope, VectorWriterKind
    from app.repositories.rag_document import CollectionScope, in_collection_scope
    from app.services.rag_document import RAGDocumentService

    collection = f"provenance{uuid4().hex[:12]}"
    store = _store_embedding_in_3d(engine)
    await store._ensure_collection(collection)
    table = store._table(collection)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            known = RAGDocument(
                collection_name=collection,
                filename="private.txt",
                filetype="txt",
                vector_document_id="known",
                writer_kind=VectorWriterKind.DOCUMENT,
            )
            unknown = RAGDocument(
                collection_name=collection,
                filename="import.txt",
                filetype="txt",
                vector_document_id="unknown",
                writer_kind=VectorWriterKind.LEGACY_UNKNOWN,
            )
            session.add_all([known, unknown])
            for parent in ("known", "unknown", "rowless"):
                metadata = {"filename": "test.txt", "filesize": 1, "filetype": "txt"}
                if origin is not None:
                    metadata["writer_kind"] = origin
                await session.execute(
                    text(
                        f"INSERT INTO {table} (id, parent_doc_id, content, embedding, metadata) "  # noqa: S608 - validated name
                        "VALUES (:parent, :parent, 'test', '[0.1,0.2,0.3]'::vector, CAST(:meta AS jsonb))"
                    ),
                    {
                        "parent": parent,
                        "meta": None if origin == "sql_null" else json.dumps(metadata),
                    },
                )
            await session.commit()
            known_id, unknown_id = known.id, unknown.id
        async with factory() as session:
            service = RAGDocumentService(session)
            before = await service.audit_unfiled_provenance(collection)
            assert before.tracked_document == 1
            assert before.tracked_legacy_unknown == 1
            assert before.tracked_confirmable == 1
            assert before.confirmable == (
                2 if origin in (None, "legacy_unknown", "sql_null") else 0
            )
            assert await service.confirm_operator_unfiled(collection) == before.confirmable
            await session.commit()
        async with factory() as session:
            assert (await session.get(RAGDocument, known_id)).writer_kind == "document"
            assert (await session.get(RAGDocument, unknown_id)).writer_kind == "operator"
            assert await RAGDocumentService(session).confirm_operator_unfiled(collection) == 0
            app_scope = CollectionScope(uuid4(), collection, None, True, True)
            visible_ids = set(
                await session.scalars(select(RAGDocument.id).where(in_collection_scope(app_scope)))
            )
            assert known_id not in visible_ids
            assert unknown_id in visible_ids
            await session.commit()
        public = VectorScope(tenant=None, knowledge_base_id=uuid4(), operator_unfiled_only=True)
        chunks = await store.get_documents(collection, public)
        visible = {chunk.document_id for chunk in chunks}
        if origin == "document":
            assert visible == set()
        elif origin == "operator":
            assert visible == {"known", "unknown", "rowless"}
        else:
            assert visible == {"unknown", "rowless"}
            assert await store.get_document_chunks(collection, "known", public) == []
        # A base clear only captures confirmed operator chunks, never quarantined data.
        async with factory() as session:
            from app.db.models.knowledge_base import KnowledgeBase
            from app.repositories import rag_document_repo

            kb = KnowledgeBase(id=public.knowledge_base_id, collection_name=collection, scope="app")
            ids = await rag_document_repo.stored_vector_ids_at_clear(
                session, kb, takes_unfiled=True
            )
            assert set(ids) == visible
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE IF EXISTS {table}"))


async def test_tracked_writer_origin_overrides_a_stale_or_forged_ingester_value(
    engine: AsyncEngine,
) -> None:
    from app.db.models.rag_document import DocumentStatus, RAGDocument
    from app.db.vector_tables import VectorScope, VectorWriterKind
    from tests.integration.test_deletion_reconciliation import _parsed

    collection = f"provenance{uuid4().hex[:12]}"
    store = _store_embedding_in_3d(engine)
    table = store._table(collection)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            row = RAGDocument(
                collection_name=collection,
                filename="test.txt",
                filetype="txt",
                status=DocumentStatus.PROCESSING,
                writer_kind=VectorWriterKind.DOCUMENT,
            )
            session.add(row)
            await session.commit()
            row_id = row.id
        document = _parsed("private")
        document.metadata.rag_document_id = row_id
        document.metadata.writer_kind = VectorWriterKind.OPERATOR
        await store.insert_document(collection, document, VectorScope(tenant=None))
        async with factory() as session:
            assert (
                await session.scalar(text(f"SELECT metadata->>'writer_kind' FROM {table}"))  # noqa: S608 - store-validated name
                == "document"
            )
            row = await session.get(RAGDocument, row_id)
            row.writer_kind = VectorWriterKind.OPERATOR
            await session.commit()
        document.metadata.writer_kind = VectorWriterKind.LEGACY_UNKNOWN
        await store.insert_document(collection, document, VectorScope(tenant=None))
        async with factory() as session:
            assert (
                await session.scalar(text(f"SELECT metadata->>'writer_kind' FROM {table}"))  # noqa: S608 - store-validated name
                == "operator"
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE IF EXISTS {table}"))


async def test_empty_and_reserved_provenance_destinations(engine: AsyncEngine) -> None:
    from app.core.exceptions import BadRequestError
    from app.services.rag_document import RAGDocumentService

    async with async_sessionmaker(engine)() as session:
        service = RAGDocumentService(session)
        counts = await service.audit_unfiled_provenance("missing_provenance")
        assert (counts.operator, counts.document, counts.legacy_unknown, counts.confirmable) == (
            0,
            0,
            0,
            0,
        )
        from app.db.models.rag_document import RAGDocument

        session.add(
            RAGDocument(
                collection_name="missing_provenance",
                filename="legacy.txt",
                filetype="txt",
                writer_kind="legacy_unknown",
            )
        )
        await session.flush()
        tracked = await service.audit_unfiled_provenance("missing_provenance")
        assert tracked.tracked_legacy_unknown == tracked.tracked_confirmable == 1
        assert await service.confirm_operator_unfiled("missing_provenance") == 0
        assert (await service.audit_unfiled_provenance("missing_provenance")).tracked_operator == 1
        with pytest.raises(BadRequestError):
            await service.audit_unfiled_provenance("documents")
        with pytest.raises(BadRequestError):
            await service.confirm_operator_unfiled("bad-name;DROP TABLE users")


async def test_migration_quarantines_old_tags_and_retains_certain_document_ownership(
    engine: AsyncEngine,
) -> None:
    import importlib.util
    from pathlib import Path

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy.engine import Connection
    from sqlalchemy.exc import IntegrityError

    from app.db.models.rag_document import RAGDocument

    path = (
        Path(__file__).resolve().parents[2] / "alembic/versions/0300_unfiled_writer_provenance.py"
    )
    spec = importlib.util.spec_from_file_location("writer_provenance_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def migrate(connection: Connection, upgrade: bool) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            if upgrade:
                migration.upgrade()
            else:
                migration.downgrade()

    collection = f"provenance{uuid4().hex[:12]}"
    store = _store_embedding_in_3d(engine)
    await store._ensure_collection(collection)
    table = store._table(collection)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            owner = _user()
            session.add(owner)
            await session.flush()
            base = _personal_kb(uuid4(), owner.id, collection)
            base.organization_id = None
            session.add(base)
            await session.flush()
            base_id = base.id
            for parent, kb_id, user_id in (
                ("private", base.id, None),
                ("null-private", base.id, None),
                ("upload", None, owner.id),
                ("unknown", None, None),
            ):
                session.add(
                    RAGDocument(
                        collection_name=collection,
                        filename="test.txt",
                        filetype="txt",
                        vector_document_id=parent,
                        knowledge_base_id=kb_id,
                        initiated_by_user_id=user_id,
                    )
                )
            for parent in (
                "private",
                "upload",
                "unknown",
                "rowless",
                "null-private",
                "null-rowless",
            ):
                await session.execute(
                    text(
                        f"INSERT INTO {table} (id, parent_doc_id, content, embedding, metadata) "  # noqa: S608 - validated name
                        "VALUES (:parent, :parent, 'test', '[0.1,0.2,0.3]'::vector, CAST(:metadata AS jsonb))"
                    ),
                    {
                        "parent": parent,
                        "metadata": None
                        if parent.startswith("null-")
                        else '{"writer_kind":"operator"}',
                    },
                )
            await session.commit()
        async with engine.begin() as connection:
            await connection.run_sync(migrate, False)
            await connection.run_sync(migrate, True)
        async with factory() as session:
            rows = (
                await session.execute(text(f"SELECT parent_doc_id, metadata FROM {table}"))  # noqa: S608 - store-validated name
            ).all()
            metadata = dict(rows)
            assert metadata["private"] == {
                "writer_kind": "document",
                "knowledge_base_id": str(base_id),
            }
            assert metadata["null-private"] == {
                "writer_kind": "document",
                "knowledge_base_id": str(base_id),
            }
            assert metadata["null-rowless"] == {"writer_kind": "legacy_unknown"}
            assert metadata["upload"] == {"writer_kind": "document"}
            assert metadata["unknown"] == {"writer_kind": "legacy_unknown"}
            assert metadata["rowless"] == {"writer_kind": "legacy_unknown"}
            kinds = dict(
                (
                    await session.execute(
                        text(
                            "SELECT vector_document_id, writer_kind FROM rag_documents WHERE collection_name = :name"
                        ),
                        {"name": collection},
                    )
                ).all()
            )
            assert kinds == {
                "private": "document",
                "null-private": "document",
                "upload": "document",
                "unknown": "legacy_unknown",
            }
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "UPDATE rag_documents SET writer_kind = 'guessed_owner' WHERE collection_name = :name"
                        ),
                        {"name": collection},
                    )
        async with engine.begin() as connection:
            await connection.run_sync(migrate, False)
            await connection.run_sync(migrate, True)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
