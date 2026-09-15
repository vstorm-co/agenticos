"""0080 backfills the tenant tag only where it can be attributed (#1684).

The runtime `rag_<collection>` tables predate the tenant tag, so the migration
stamps existing rows with their organization - but only for a collection whose
name maps to exactly one. A name shared by several organizations carries no
per-row evidence of which wrote which chunk, so its rows cannot be attributed
and are left untagged; a name with no organization (personal/app/local) is left
untagged deliberately. The forward fix still holds: every new ingest stamps its
tenant and matches only tenant-tagged rows.

Driven against a real database because the whole migration is raw SQL over
tables no model declares, joined to `knowledge_bases` - a mock proves none of it.
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
from app.db.models.user import User

pytestmark = pytest.mark.anyio

SHARED = "shared_kb"
SOLO = "solo_kb"
ORPHAN = "orphan_kb"


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


def _kb(collection_name: str, organization_id: uuid.UUID | None) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=collection_name,
        scope=KBScope.ORG.value if organization_id else KBScope.APP.value,
        collection_name=collection_name,
        embedding_model="text-embedding-3-small",
        embedding_dim=3,
        organization_id=organization_id,
    )


async def _make_runtime_table(engine: AsyncEngine, collection: str, doc_id: str) -> None:
    table = f"rag_{collection}"
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await session.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {table} ("
                "id VARCHAR(100) PRIMARY KEY, parent_doc_id VARCHAR(100), "
                "content TEXT, metadata JSONB DEFAULT '{}'::jsonb)"
            )
        )
        await session.execute(
            text(
                f"INSERT INTO {table} (id, parent_doc_id, content, metadata) "  # noqa: S608
                "VALUES (:id, :pid, 'body', CAST(:meta AS jsonb))"
            ),
            {"id": f"{doc_id}-0", "pid": doc_id, "meta": json.dumps({"filename": "f.pdf"})},
        )
        await session.commit()


async def _org_tag(engine: AsyncEngine, collection: str) -> str | None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        result = await session.execute(
            text(f"SELECT metadata->>'organization_id' FROM rag_{collection}")  # noqa: S608
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
    """One name shared by two orgs, one owned by exactly one, one owned by none."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        org_a = await _org(session, "orga")
        org_b = await _org(session, "orgb")
        session.add_all(
            [
                _kb(SHARED, org_a),
                _kb(SHARED, org_b),
                _kb(SOLO, org_a),
                _kb(ORPHAN, None),
            ]
        )
        await session.commit()
    await _make_runtime_table(engine, SHARED, "doc-shared")
    await _make_runtime_table(engine, SOLO, "doc-solo")
    await _make_runtime_table(engine, ORPHAN, "doc-orphan")
    try:
        yield org_a
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            for collection in (SHARED, SOLO, ORPHAN):
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


async def test_a_single_org_collection_is_backfilled(
    engine: AsyncEngine, schema_url: str, seeded: uuid.UUID
) -> None:
    _run(schema_url, "up")

    assert await _org_tag(engine, SOLO) == str(seeded)


async def test_a_shared_name_is_left_untagged(
    engine: AsyncEngine, schema_url: str, seeded: uuid.UUID
) -> None:
    """The vulnerable case: rows cannot be attributed to one of the two orgs, so
    the migration leaves them untagged rather than guess."""
    _run(schema_url, "up")

    assert await _org_tag(engine, SHARED) is None


async def test_a_collection_owned_by_no_org_is_left_untagged(
    engine: AsyncEngine, schema_url: str, seeded: uuid.UUID
) -> None:
    _run(schema_url, "up")

    assert await _org_tag(engine, ORPHAN) is None


async def test_the_org_index_is_built_on_every_runtime_table(
    engine: AsyncEngine, schema_url: str, seeded: uuid.UUID
) -> None:
    _run(schema_url, "up")

    assert await _has_org_index(engine, SHARED)
    assert await _has_org_index(engine, SOLO)


async def test_downgrade_removes_the_tag_and_the_index(
    engine: AsyncEngine, schema_url: str, seeded: uuid.UUID
) -> None:
    _run(schema_url, "up")
    _run(schema_url, "down")

    assert await _org_tag(engine, SOLO) is None
    assert not await _has_org_index(engine, SOLO)
