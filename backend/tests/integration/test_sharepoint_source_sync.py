"""A SharePoint library, synced into a real collection, searched, changed and synced again (#985).

The acceptance criteria are claims about the whole path: a configured source
populates a collection existing retrieval can search; a second sync skips what
is unchanged, updates what changed and removes what was deleted; a library
nothing has touched is not listed again; and a listing that could not see
everything removes nothing. This runs the real `_run_source_sync` against real
Postgres and pgvector, with the fake tenant from `tests/test_sharepoint_connector.py`
below the HTTP client and a bag-of-words embedder from the website test - so the
rows removal reads are the rows the ingest wrote, and the search is the store's own.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.organization import Organization
from app.db.models.rag_document import RAGDocument
from app.db.models.sync_log import SyncLog
from app.db.models.sync_source import SyncSource
from app.db.models.user import User
from app.repositories import sync_log as sync_log_repo
from app.repositories import sync_source as sync_source_repo
from app.services.rag.filters import RetrievalQuery, UnscopedScope
from app.services.rag.vectorstore import PgVectorStore
from app.worker.tasks import rag_tasks
from tests.integration.test_web_source_sync import _store
from tests.test_sharepoint_connector import CREDENTIAL, DRIVE, SITE, _Fast, _Tenant

pytestmark = pytest.mark.anyio

COLLECTION = "sharepointsync"


@pytest.fixture(autouse=True)
async def _clean_runtime_table(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """The runtime table is not a model, so the suite's reset does not reach it."""
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS rag_{COLLECTION}"))
    yield
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS rag_{COLLECTION}"))


@pytest.fixture
def tenant() -> Iterator[_Tenant]:
    library = _Tenant()
    library.add("f-hr", "HR")
    library.add("f-it", "IT")
    library.add("i-welcome", "Welcome.md", content=b"Welcome to the company handbook.")
    library.add(
        "i-leave", "leave.md", parent="f-hr", content=b"Annual leave is twenty days a year."
    )
    library.add(
        "i-laptops",
        "laptops.txt",
        parent="f-it",
        content=b"Laptops are replaced every three years.",
    )
    library.add("i-photo", "team.png", content=b"\x89PNG")

    def store_on(**kwargs: Any) -> PgVectorStore:
        return _store(kwargs["engine"])

    with (
        patch.object(rag_tasks, "VectorStore", side_effect=store_on),
        patch.object(rag_tasks, "_connector_credential", new=AsyncMock(return_value=CREDENTIAL)),
        patch.dict(
            rag_tasks.CONNECTOR_REGISTRY,
            {"sharepoint": lambda: _Fast(transport=httpx.MockTransport(library.handler))},
        ),
    ):
        yield library


async def _source(engine: AsyncEngine) -> str:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
        db.add(user)
        await db.flush()
        organization = Organization(
            name="Contoso", slug=f"contoso-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id
        )
        db.add(organization)
        await db.flush()
        source = await sync_source_repo.create(
            db,
            name="Handbook",
            connector_type="sharepoint",
            config={"site_url": SITE},
            organization_id=organization.id,
            collection_name=COLLECTION,
        )
        await db.commit()
        return str(source.id)


async def _sync(engine: AsyncEngine, source_id: str) -> SyncLog:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        log = await sync_log_repo.create(
            db,
            source="sharepoint",
            collection_name=COLLECTION,
            mode="new_only",
            sync_source_id=uuid.UUID(source_id),
        )
        await db.commit()
        log_id = log.id
    await rag_tasks._run_source_sync(source_id, sync_log_id=str(log_id))
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        finished = await db.get(SyncLog, log_id)
        assert finished is not None
        return finished


async def _tracked(db: AsyncSession) -> set[str]:
    rows = await db.execute(
        select(RAGDocument.source_path).where(RAGDocument.collection_name == COLLECTION)
    )
    return {path for (path,) in rows.all() if path}


async def _found(engine: AsyncEngine, query: str, *, limit: int = 1) -> list[str]:
    results = await _store(engine).search(
        COLLECTION, query, RetrievalQuery(scope=UnscopedScope()), limit=limit
    )
    return [r.metadata.get("source_path", "") for r in results]


def _address(item_id: str) -> str:
    return f"sharepoint://{DRIVE}/{item_id}"


def _listings(tenant: _Tenant) -> int:
    return sum(1 for r in tenant.requests if r.url.path.endswith("/children"))


async def test_a_library_is_searchable_and_a_second_sync_follows_its_changes(
    engine: AsyncEngine, db: AsyncSession, tenant: _Tenant
) -> None:
    source_id = await _source(engine)

    first = await _sync(engine, source_id)

    assert (first.status, first.ingested, first.failed, first.removed) == ("done", 3, 0, 0)
    assert await _tracked(db) == {_address("i-welcome"), _address("i-leave"), _address("i-laptops")}
    assert await _found(engine, "annual leave days") == [_address("i-leave")]

    # The leave policy is rewritten, the laptop page is deleted, and the welcome
    # page is left alone.
    tenant.nodes["i-leave"].content = b"Annual leave is now thirty days, carried over once."
    tenant.touch("i-leave")
    tenant.delete("i-laptops")

    second = await _sync(engine, source_id)

    assert (second.status, second.skipped, second.updated, second.removed) == ("done", 1, 1, 1)
    assert await _tracked(db) == {_address("i-welcome"), _address("i-leave")}
    assert await _found(engine, "thirty carried") == [_address("i-leave")]
    assert _address("i-laptops") not in await _found(engine, "laptops replaced years", limit=10)


async def test_an_untouched_library_is_not_listed_again(
    engine: AsyncEngine, db: AsyncSession, tenant: _Tenant
) -> None:
    source_id = await _source(engine)
    await _sync(engine, source_id)
    listed = _listings(tenant)

    again = await _sync(engine, source_id)

    assert (again.status, again.total_files, again.ingested, again.removed) == ("done", 0, 0, 0)
    assert _listings(tenant) == listed, "the change feed answered for the library"
    assert len(await _tracked(db)) == 3
    source = await db.get(SyncSource, uuid.UUID(source_id))
    assert source is not None
    assert source.sync_state is not None
    assert source.sync_state["version"].startswith(f"{DRIVE} https://graph.microsoft.com/")


async def test_a_folder_the_app_cannot_read_removes_nothing_and_says_which(
    engine: AsyncEngine, db: AsyncSession, tenant: _Tenant
) -> None:
    source_id = await _source(engine)
    await _sync(engine, source_id)

    tenant.delete("i-laptops")
    tenant.queue(
        f"/v1.0/drives/{DRIVE}/items/f-hr/children",
        httpx.Response(403, json={"error": {"code": "accessDenied"}}),
    )
    partial = await _sync(engine, source_id)

    assert (partial.status, partial.removed, partial.failed) == ("error", 0, 1)
    assert partial.error_message is not None
    assert "The folder HR could not be listed" in partial.error_message
    assert "accessDenied" in partial.error_message
    # The deleted laptop page waits for a listing that can vouch for the library.
    assert await _tracked(db) == {_address("i-welcome"), _address("i-leave"), _address("i-laptops")}
    source = await db.get(SyncSource, uuid.UUID(source_id))
    assert source is not None
    assert source.last_error is not None


@pytest.mark.security
async def test_an_app_the_tenant_refuses_fails_the_sync_on_its_log(
    engine: AsyncEngine, tenant: _Tenant
) -> None:
    tenant.queue(
        "/contoso.onmicrosoft.com/oauth2/v2.0/token",
        httpx.Response(401, json={"error": "invalid_client"}),
    )
    source_id = await _source(engine)

    refused = await _sync(engine, source_id)

    assert refused.status == "error"
    assert refused.error_message is not None
    assert "invalid_client" in refused.error_message
    assert CREDENTIAL.client_secret.get_secret_value() not in refused.error_message
