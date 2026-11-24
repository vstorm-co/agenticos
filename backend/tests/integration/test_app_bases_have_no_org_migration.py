"""0363 clears an app-scoped base's organization id and forbids one from then on.

The suite's schema is built from the models, so it already holds the check. Each
test drops it through the migration's own downgrade to stand where a deployment
stands before the upgrade, and puts it back however the test ends, because the
schema is shared by every test after it.
"""

import importlib.util
import uuid
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path
from types import ModuleType

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization
from app.db.models.user import User

pytestmark = pytest.mark.anyio


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0363_app_bases_have_no_org.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0363_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _has_check(schema_url: str) -> bool:
    sync_engine = create_engine(schema_url.replace("+asyncpg", "+psycopg2"))
    try:
        with sync_engine.connect() as conn:
            found = conn.execute(
                text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
                {"name": _migration().CHECK},
            )
            return found.scalar() is not None
    finally:
        sync_engine.dispose()


def _run(schema_url: str, direction: str) -> None:
    migration = _migration()
    sync_engine = create_engine(schema_url.replace("+asyncpg", "+psycopg2"))
    try:
        with sync_engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            (migration.upgrade if direction == "up" else migration.downgrade)()
    finally:
        sync_engine.dispose()


@pytest.fixture
def before_upgrade(schema_url: str, engine: AsyncEngine) -> Iterator[None]:
    """The schema without the check, restored to it afterwards."""
    _run(schema_url, "down")
    try:
        yield
    finally:
        if not _has_check(schema_url):
            _run(schema_url, "up")


def _base(name: str, *, scope: str, organization_id: uuid.UUID | None) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=name,
        scope=scope,
        collection_name=name,
        embedding_model="text-embedding-3-small",
        embedding_dim=3,
        organization_id=organization_id,
    )


@pytest.fixture
async def org_id(engine: AsyncEngine) -> AsyncGenerator[uuid.UUID]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        founder = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
        session.add(founder)
        await session.flush()
        org = Organization(
            name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=founder.id
        )
        session.add(org)
        await session.commit()
        yield org.id


async def _add(engine: AsyncEngine, *bases: KnowledgeBase) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all(bases)
        await session.commit()


async def _organization_of(engine: AsyncEngine, base_id: uuid.UUID) -> uuid.UUID | None:
    async with async_sessionmaker(engine)() as session:
        return await session.scalar(
            select(KnowledgeBase.organization_id).where(KnowledgeBase.id == base_id)
        )


@pytest.mark.usefixtures("before_upgrade")
async def test_an_app_base_loses_its_organization_and_the_others_keep_theirs(
    engine: AsyncEngine, schema_url: str, org_id: uuid.UUID
) -> None:
    app = _base("handbook", scope=KBScope.APP.value, organization_id=org_id)
    org = _base("policies", scope=KBScope.ORG.value, organization_id=org_id)
    personal = _base("notes", scope=KBScope.PERSONAL.value, organization_id=org_id)
    await _add(engine, app, org, personal)

    _run(schema_url, "up")

    assert await _organization_of(engine, app.id) is None
    assert await _organization_of(engine, org.id) == org_id
    assert await _organization_of(engine, personal.id) == org_id


async def test_after_the_upgrade_an_app_base_cannot_carry_an_organization(
    engine: AsyncEngine, org_id: uuid.UUID
) -> None:
    with pytest.raises(IntegrityError, match="app_scope_has_no_org"):
        await _add(engine, _base("handbook", scope=KBScope.APP.value, organization_id=org_id))


async def test_an_app_base_cannot_be_moved_into_an_organization(
    engine: AsyncEngine, org_id: uuid.UUID
) -> None:
    app = _base("handbook", scope=KBScope.APP.value, organization_id=None)
    await _add(engine, app)

    async with async_sessionmaker(engine)() as session:
        with pytest.raises(IntegrityError, match="app_scope_has_no_org"):
            await session.execute(
                text("UPDATE knowledge_bases SET organization_id = :org WHERE id = :id"),
                {"org": org_id, "id": app.id},
            )


@pytest.mark.usefixtures("before_upgrade")
async def test_the_downgrade_drops_the_check_only(engine: AsyncEngine, org_id: uuid.UUID) -> None:
    app = _base("handbook", scope=KBScope.APP.value, organization_id=org_id)

    await _add(engine, app)

    assert await _organization_of(engine, app.id) == org_id
