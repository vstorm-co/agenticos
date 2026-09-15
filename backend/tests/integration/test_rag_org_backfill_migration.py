"""0080 backfills the tenant tag from tracked documents, not from name references (#1684).

The runtime `rag_<collection>` tables predate the tenant tag. The migration
attributes an existing row to an organization only when a tracked `rag_documents`
row produced it and its knowledge base is org-scoped: an app-scoped base's rows
stay untagged (deployment-wide), and a residual row whose tracking document is
gone - an organization torn down out of a still-shared table - is left untagged
rather than reassigned to whoever still references the name.

Driven against a real database because the whole migration is raw SQL over
tables no model declares, joined to `rag_documents` and `knowledge_bases`.
"""

from __future__ import annotations

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
from app.db.models.organization import Organization
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.user import User

pytestmark = pytest.mark.anyio

ORG_COLLECTION = "org_docs"
APP_COLLECTION = "app_docs"


def _load_migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0080_scope_rag_rows_by_org.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0080_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sync_url(schema_url: str) -> str:
    return schema_url.replace("+asyncpg", "")


async def _org(session, name: str) -> uuid.UUID:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    session.add(founder)
    await session.flush()
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    session.add(org)
    await session.flush()
    return org.id


def _kb(collection_name: str, *, scope: str, organization_id: uuid.UUID | None) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=collection_name,
        scope=scope,
        collection_name=collection_name,
        embedding_model="text-embedding-3-small",
        embedding_dim=3,
        organization_id=organization_id,
    )


def _doc(kb: KnowledgeBase, *, org: uuid.UUID | None, vector_document_id: str) -> RAGDocument:
    return RAGDocument(
        id=uuid.uuid4(),
        collection_name=kb.collection_name,
        filename="f.pdf",
        filetype="pdf",
        status=DocumentStatus.DONE.value,
        vector_document_id=vector_document_id,
        organization_id=org,
        knowledge_base_id=kb.id,
    )


async def _make_runtime_table(
    engine: AsyncEngine, collection: str, parent_doc_ids: list[str]
) -> None:
    table = f"rag_{collection}"
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await session.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {table} ("
                "id VARCHAR(100) PRIMARY KEY, parent_doc_id VARCHAR(100), "
                "content TEXT, metadata JSONB DEFAULT '{}'::jsonb)"
            )
        )
        for pid in parent_doc_ids:
            await session.execute(
                text(
                    f"INSERT INTO {table} (id, parent_doc_id, content, metadata) "  # noqa: S608
                    "VALUES (:id, :pid, 'body', CAST(:meta AS jsonb))"
                ),
                {"id": f"{pid}-0", "pid": pid, "meta": json.dumps({"filename": "f.pdf"})},
            )
        await session.commit()


async def _tag(engine: AsyncEngine, collection: str, parent_doc_id: str) -> str | None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        result = await session.execute(
            text(
                f"SELECT metadata->>'organization_id' FROM rag_{collection} "  # noqa: S608
                "WHERE parent_doc_id = :pid"
            ),
            {"pid": parent_doc_id},
        )
        return result.scalar()


async def _has_org_index(engine: AsyncEngine, collection: str) -> bool:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        result = await session.execute(
            text("SELECT 1 FROM pg_indexes WHERE indexname = :n"),
            {"n": f"rag_{collection}_org_idx"},
        )
        return result.scalar() is not None


@pytest.fixture
async def seeded(engine: AsyncEngine) -> AsyncGenerator[uuid.UUID, None]:
    """An org-scoped collection and an app-scoped one, each with a tracked
    document, plus a residual row in the org table whose tracking document is
    gone (an organization torn down out of a still-shared table)."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        org_a = await _org(session, "orga")
        org_kb = _kb(ORG_COLLECTION, scope=KBScope.ORG.value, organization_id=org_a)
        app_kb = _kb(APP_COLLECTION, scope=KBScope.APP.value, organization_id=None)
        session.add_all([org_kb, app_kb])
        await session.flush()
        session.add_all(
            [
                _doc(org_kb, org=org_a, vector_document_id="vd-org"),
                _doc(app_kb, org=org_a, vector_document_id="vd-app"),
            ]
        )
        await session.commit()
    await _make_runtime_table(engine, ORG_COLLECTION, ["vd-org", "vd-residual"])
    await _make_runtime_table(engine, APP_COLLECTION, ["vd-app"])
    try:
        yield org_a
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            for collection in (ORG_COLLECTION, APP_COLLECTION):
                await session.execute(text(f"DROP TABLE IF EXISTS rag_{collection}"))
            await session.commit()


def _run(schema_url: str, direction: str) -> None:
    migration = _load_migration()
    sync_engine = create_engine(_sync_url(schema_url))
    try:
        with sync_engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                (migration.upgrade if direction == "up" else migration.downgrade)()
    finally:
        sync_engine.dispose()


async def test_a_tracked_org_document_is_backfilled(
    engine: AsyncEngine, schema_url: str, seeded: uuid.UUID
) -> None:
    _run(schema_url, "up")

    assert await _tag(engine, ORG_COLLECTION, "vd-org") == str(seeded)


async def test_a_residual_row_with_no_tracking_document_is_left_untagged(
    engine: AsyncEngine, schema_url: str, seeded: uuid.UUID
) -> None:
    """The round-2 case: a deleted organization's rows must not be reassigned to
    the organization that still shares the name."""
    _run(schema_url, "up")

    assert await _tag(engine, ORG_COLLECTION, "vd-residual") is None


async def test_an_app_scoped_documents_rows_are_left_untagged(
    engine: AsyncEngine, schema_url: str, seeded: uuid.UUID
) -> None:
    _run(schema_url, "up")

    assert await _tag(engine, APP_COLLECTION, "vd-app") is None


async def test_the_org_index_is_built_on_every_runtime_table(
    engine: AsyncEngine, schema_url: str, seeded: uuid.UUID
) -> None:
    _run(schema_url, "up")

    assert await _has_org_index(engine, ORG_COLLECTION)
    assert await _has_org_index(engine, APP_COLLECTION)


async def test_downgrade_removes_the_tag_and_the_index(
    engine: AsyncEngine, schema_url: str, seeded: uuid.UUID
) -> None:
    _run(schema_url, "up")
    _run(schema_url, "down")

    assert await _tag(engine, ORG_COLLECTION, "vd-org") is None
    assert not await _has_org_index(engine, ORG_COLLECTION)
