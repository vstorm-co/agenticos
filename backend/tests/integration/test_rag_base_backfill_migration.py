"""0179 files existing chunks under their knowledge base where that is certain (#2537).

The store now reads a base's chunks by `metadata->>'knowledge_base_id'`, and an
unfiled chunk falls back to its tenant - which is the very rule that mixed an
app-scoped base with a personal base outside any organization. The migration
files a chunk only when every `rag_documents` row for its vector document id is
filed under one existing base of that collection. Anything else stays unfiled:
an untracked residual row, a document tracked under no base, and an id whose
tracking rows disagree.

Driven against a real database because the migration is raw SQL over tables no
model declares, joined to `rag_documents` and `knowledge_bases`.
"""

import importlib.util
import json
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.user import User
from app.db.vector_tables import VectorScope
from app.services.rag.config import RAGSettings
from app.services.rag.vectorstore import PgVectorStore

pytestmark = [pytest.mark.anyio, pytest.mark.security]

COLLECTION = "handbook"
TABLE = f"rag_{COLLECTION}"


def _load_migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0180_stamp_rag_rows_by_base.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0179_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(schema_url: str, direction: str) -> None:
    migration = _load_migration()
    sync_engine = create_engine(schema_url.replace("+asyncpg", "+psycopg2"))
    try:
        with sync_engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                (migration.upgrade if direction == "up" else migration.downgrade)()
    finally:
        sync_engine.dispose()


def _kb(scope: KBScope, *, owner: uuid.UUID | None = None, name: str = COLLECTION) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=name,
        scope=scope.value,
        collection_name=name,
        embedding_model="text-embedding-3-small",
        embedding_dim=3,
        organization_id=None,
        owner_user_id=owner,
    )


def _doc(vector_document_id: str, kb_id: uuid.UUID | None) -> RAGDocument:
    return RAGDocument(
        id=uuid.uuid4(),
        collection_name=COLLECTION,
        filename="f.pdf",
        filetype="pdf",
        status=DocumentStatus.DONE.value,
        vector_document_id=vector_document_id,
        knowledge_base_id=kb_id,
    )


async def _chunk(engine: AsyncEngine, parent_doc_id: str, meta: dict[str, str]) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await session.execute(
            text(
                f"INSERT INTO {TABLE} (id, parent_doc_id, content, embedding, metadata) "  # noqa: S608
                "VALUES (:id, :pid, :content, CAST('[0.1,0.2,0.3]' AS vector), CAST(:meta AS jsonb))"
            ),
            {
                "id": f"{parent_doc_id}-0",
                "pid": parent_doc_id,
                "content": parent_doc_id,
                "meta": json.dumps(meta),
            },
        )
        await session.commit()


async def _filed_under(engine: AsyncEngine, parent_doc_id: str) -> str | None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        result = await session.execute(
            text(
                f"SELECT metadata->>'knowledge_base_id' FROM {TABLE} "  # noqa: S608
                "WHERE parent_doc_id = :pid"
            ),
            {"pid": parent_doc_id},
        )
        return result.scalar()


async def _has_kb_index(engine: AsyncEngine) -> bool:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        result = await session.execute(
            text("SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": f"{TABLE}_kb_idx"}
        )
        return result.scalar() is not None


async def _no_resolution(_name: str, _organization_id: object = None) -> None:
    return


def _store(engine: AsyncEngine) -> PgVectorStore:
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = async_sessionmaker(engine, expire_on_commit=False)
    store.dim = 3
    store.settings = RAGSettings()
    store.embedder = None  # type: ignore[assignment]  # unread for DDL and the scoped reads
    store._resolver = _no_resolution  # type: ignore[assignment]
    return store


@pytest.fixture
async def seeded(engine: AsyncEngine) -> AsyncGenerator[dict[str, KnowledgeBase]]:
    """Case 1 on an existing table: an app base and a personal base outside any
    organization share the name and the tenant `None`, and none of their chunks
    records its base yet - plus the chunks the backfill must leave alone."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        owner = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        session.add(owner)
        await session.flush()
        app = _kb(KBScope.APP)
        personal = _kb(KBScope.PERSONAL, owner=owner.id)
        other_name = _kb(KBScope.APP, name="elsewhere")
        session.add_all([app, personal, other_name])
        await session.flush()
        session.add_all(
            [
                _doc("vd-app", app.id),
                _doc("vd-personal", personal.id),
                _doc("vd-unfiled", None),
                # Two tracking rows that disagree about the base.
                _doc("vd-ambiguous", app.id),
                _doc("vd-ambiguous", personal.id),
                # Filed under a base of another collection name.
                _doc("vd-misfiled", other_name.id),
            ]
        )
        await session.commit()
    await _store(engine)._ensure_collection(COLLECTION)
    # `_ensure_collection` builds today's indexes; drop the new one so the table
    # looks like one created before this revision.
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP INDEX IF EXISTS {TABLE}_kb_idx"))
    for pid in (
        "vd-app",
        "vd-personal",
        "vd-unfiled",
        "vd-ambiguous",
        "vd-misfiled",
        "vd-residual",
    ):
        await _chunk(engine, pid, {"filename": f"{pid}.pdf"})
    try:
        yield {"app": app, "personal": personal}
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))


async def test_each_tracked_document_is_filed_under_its_own_base(
    engine: AsyncEngine, schema_url: str, seeded: dict[str, KnowledgeBase]
) -> None:
    _run(schema_url, "up")

    assert await _filed_under(engine, "vd-app") == str(seeded["app"].id)
    assert await _filed_under(engine, "vd-personal") == str(seeded["personal"].id)


async def test_what_is_not_certain_stays_unfiled(
    engine: AsyncEngine, schema_url: str, seeded: dict[str, KnowledgeBase]
) -> None:
    """Filing a chunk under the wrong base would hand it to that base's readers;
    an unfiled one keeps the tenant rule it had before the upgrade."""
    _run(schema_url, "up")

    for pid in ("vd-unfiled", "vd-ambiguous", "vd-misfiled", "vd-residual"):
        assert await _filed_under(engine, pid) is None, pid


async def test_a_chunk_already_filed_is_not_refiled(
    engine: AsyncEngine, schema_url: str, seeded: dict[str, KnowledgeBase]
) -> None:
    """Idempotent: a chunk the new code filed, or an earlier run did, is kept."""
    elsewhere = str(uuid.uuid4())
    await _chunk(engine, "vd-app-new", {"knowledge_base_id": elsewhere})
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(_doc("vd-app-new", seeded["app"].id))
        await session.commit()

    _run(schema_url, "up")
    _run(schema_url, "up")

    assert await _filed_under(engine, "vd-app-new") == elsewhere
    assert await _filed_under(engine, "vd-app") == str(seeded["app"].id)


async def test_after_the_backfill_the_app_base_no_longer_reads_the_persons_chunks(
    engine: AsyncEngine, schema_url: str, seeded: dict[str, KnowledgeBase]
) -> None:
    """The point of the backfill: before it, both bases' chunks were unfiled with
    no tenant, and the app base - read by every organization - listed the
    person's document."""
    store = _store(engine)
    app_scope = seeded["app"].vector_scope
    before = {d.document_id for d in await store.get_documents(COLLECTION, app_scope)}
    assert "vd-personal" in before

    _run(schema_url, "up")

    after = {d.document_id for d in await store.get_documents(COLLECTION, app_scope)}
    personal = await store.get_documents(COLLECTION, seeded["personal"].vector_scope)
    assert "vd-personal" not in after
    assert "vd-app" in after
    assert [d.document_id for d in personal] == ["vd-personal"]


async def test_the_base_index_is_built(
    engine: AsyncEngine, schema_url: str, seeded: dict[str, KnowledgeBase]
) -> None:
    _run(schema_url, "up")

    assert await _has_kb_index(engine)


async def test_downgrade_removes_the_key_and_the_index(
    engine: AsyncEngine, schema_url: str, seeded: dict[str, KnowledgeBase]
) -> None:
    _run(schema_url, "up")
    _run(schema_url, "down")

    assert await _filed_under(engine, "vd-app") is None
    assert not await _has_kb_index(engine)
    # A tenant-only scope still reads every row, as the older code did.
    assert len(await _store(engine).get_documents(COLLECTION, VectorScope(tenant=None))) == 6
