"""A website source, synced twice into a real collection and searched (#984).

The acceptance criteria of the web connector are claims about the whole path -
a configured source populates a collection that existing retrieval can search,
and a second sync skips what is unchanged, updates what changed and removes
what is gone. Each half is pinned in the unit suite against mocks
(`tests/test_web_connector.py`, `tests/test_sync_removal.py`); this runs the
real `_run_source_sync` against real Postgres and pgvector, so the rows the
removal reads are the rows the ingest wrote and the search is the store's own.

Two things are replaced, both at the edge: the network, below
`PinnedAsyncClient` so every request is still address-checked, and the
embedding provider, with a deterministic bag-of-words embedder - a search for a
word has to find the page that holds it, which is all retrieval is asked here.
"""

from __future__ import annotations

import hashlib
import re
import socket
import uuid
from collections.abc import AsyncGenerator, Iterator
from typing import Any
from unittest.mock import patch

import httpx2
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.locks import LockScope, try_hold_subject_on_connection
from app.db.models.organization import Organization
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.rag_document_claim import RAGDocumentClaim
from app.db.models.sync_log import SyncLog
from app.db.models.user import User
from app.repositories import sync_log as sync_log_repo
from app.repositories import sync_source as sync_source_repo
from app.services.rag.connectors.web import WebConnector
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.filters import RetrievalQuery, UnscopedScope
from app.services.rag.models import Document
from app.services.rag.vectorstore import PgVectorStore
from app.services.rag_document import RAGDocumentService
from app.worker.tasks import rag_tasks

pytestmark = pytest.mark.anyio

COLLECTION = "websync"


class _Words(EmbeddingService):
    """One dimension per hashed word: a query shares dimensions with the page holding its words."""

    def __init__(self, dim: int) -> None:
        # The real service with no key: nothing it builds is reached, because
        # both embedding methods are this class's own.
        super().__init__(settings.rag, expected_dim=dim)

    def _vector(self, content: str) -> list[float]:
        vector = [0.0] * self.expected_dim
        vector[0] = 0.01
        for word in re.findall(r"[a-z]+", content.lower()):
            vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % self.expected_dim] += 1.0
        return vector

    def embed_query(self, query: str) -> list[float]:
        return self._vector(query)

    def embed_document(self, document: Document) -> list[list[float]]:
        return [self._vector(page.chunk_content or "") for page in document.chunked_pages or []]


class _Site(httpx2.AsyncBaseTransport):
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        body = self.pages.get(request.url.raw_path.decode())
        if body is None:
            return httpx2.Response(404)
        return httpx2.Response(200, headers={"content-type": "text/html"}, content=body.encode())


class _Fast(WebConnector):
    MIN_REQUEST_INTERVAL = 0.0
    RETRY_BACKOFF = 0.0


def _page(text_: str, *links: str) -> str:
    nav = "".join(f'<a href="{link}">{link}</a>' for link in links)
    return f"<html><body><nav>{nav}</nav><main><p>{text_}</p></main></body></html>"


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """The site's name resolves to a public address; every other name - the
    database's own, which shares the `socket` module - resolves for real."""
    real = socket.getaddrinfo

    def fake_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        if host == "docs.example.com":
            return [(2, 1, 6, "", ("93.184.216.34", port))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", fake_getaddrinfo)


@pytest.fixture(autouse=True)
async def _clean_runtime_table(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """The runtime table is not a model, so the suite's reset does not reach it."""
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS rag_{COLLECTION}"))
    yield
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS rag_{COLLECTION}"))


def _store(engine: AsyncEngine) -> PgVectorStore:
    async def no_collection_model(_name: str, _organization_id: object = None) -> None:
        return None

    return PgVectorStore(
        settings=settings.rag,
        embedding_service=_Words(settings.rag.embeddings_config.dim),
        resolver=no_collection_model,
        engine=engine,
    )


@pytest.fixture
def _site() -> Iterator[_Site]:
    site = _Site({})

    def store_on(**kwargs: Any) -> PgVectorStore:
        return _store(kwargs["engine"])

    with (
        patch.object(rag_tasks, "VectorStore", side_effect=store_on),
        patch.dict(rag_tasks.CONNECTOR_REGISTRY, {"web": lambda: _Fast(transport=site)}),
    ):
        yield site


async def _source(
    engine: AsyncEngine, *, beside: str | None = None, sync_mode: str = "new_only"
) -> str:
    """A web source on the collection, in a new organization or in `beside`'s."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        if beside is None:
            user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
            db.add(user)
            await db.flush()
            organization = Organization(
                name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id
            )
            db.add(organization)
            await db.flush()
            organization_id = organization.id
        else:
            neighbour = await sync_source_repo.get_by_id(db, uuid.UUID(beside))
            assert neighbour is not None
            organization_id = neighbour.organization_id
        source = await sync_source_repo.create(
            db,
            name="Docs site",
            connector_type="web",
            config={"root_url": "https://docs.example.com/"},
            organization_id=organization_id,
            collection_name=COLLECTION,
            sync_mode=sync_mode,
        )
        await db.commit()
        return str(source.id)


async def _narrow_to_start_page(engine: AsyncEngine, source_id: str) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        await sync_source_repo.update(
            db,
            uuid.UUID(source_id),
            config={"root_url": "https://docs.example.com/", "max_depth": 0},
        )
        await db.commit()


async def _sync(engine: AsyncEngine, source_id: str) -> SyncLog:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        log = await sync_log_repo.create(
            db,
            source="web",
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


async def test_a_site_is_searchable_and_a_second_sync_follows_its_changes(
    engine: AsyncEngine, db: AsyncSession, _site: _Site
) -> None:
    _site.pages.update(
        {
            "/": _page("Welcome to the product documentation.", "install", "billing"),
            "/install": _page("Run the installer and choose a workspace."),
            "/billing": _page("Invoices are issued monthly in arrears."),
        }
    )
    source_id = await _source(engine)

    first = await _sync(engine, source_id)

    assert (first.status, first.ingested, first.failed, first.removed) == ("done", 3, 0, 0)
    assert await _tracked(db) == {
        "web://docs.example.com/",
        "web://docs.example.com/install",
        "web://docs.example.com/billing",
    }
    assert await _found(engine, "invoices arrears") == ["web://docs.example.com/billing"]

    # The billing page is taken down, the install page is rewritten, and the
    # front page's text is unchanged although its navigation lost a link.
    del _site.pages["/billing"]
    _site.pages["/"] = _page("Welcome to the product documentation.", "install")
    _site.pages["/install"] = _page("Download the installer, then sign in.")

    second = await _sync(engine, source_id)

    assert (second.status, second.skipped, second.updated, second.removed) == ("done", 1, 1, 1)
    assert await _tracked(db) == {"web://docs.example.com/", "web://docs.example.com/install"}
    assert "web://docs.example.com/billing" not in await _found(
        engine, "invoices arrears", limit=10
    )
    assert await _found(engine, "download sign") == ["web://docs.example.com/install"]


async def test_a_crawl_that_stops_short_removes_nothing(
    engine: AsyncEngine, db: AsyncSession, _site: _Site
) -> None:
    _site.pages.update({"/": _page("Front page.", "a"), "/a": _page("Page a.")})
    source_id = await _source(engine)
    await _sync(engine, source_id)

    del _site.pages["/"]  # the start URL now answers 404: the crawl saw nothing
    partial = await _sync(engine, source_id)

    assert partial.status == "error"
    assert partial.removed == 0
    assert partial.error_message is not None
    assert "did not lead to an HTML page" in partial.error_message
    assert await _tracked(db) == {"web://docs.example.com/", "web://docs.example.com/a"}


async def test_a_sync_overlapping_a_running_one_does_nothing_and_says_so(
    engine: AsyncEngine, db: AsyncSession, _site: _Site
) -> None:
    """The run lock is Postgres's, so only a real one shows the second run of
    a source refused - before it lists anything it could remove by."""
    _site.pages.update({"/": _page("Front page.")})
    source_id = await _source(engine)

    async with engine.connect() as running:
        assert await try_hold_subject_on_connection(
            running, LockScope.SYNC_SOURCE_RUN, uuid.UUID(source_id)
        )
        refused = await _sync(engine, source_id)
        # Closed, not handed back to the suite's pool with the lock still on it.
        await running.invalidate()

    assert (refused.status, refused.error_message) == ("error", rag_tasks.OVERLAPPING_RUN)
    assert await _tracked(db) == set()
    # And released with the connection that held it: the next run goes ahead.
    after = await _sync(engine, source_id)
    assert (after.status, after.error_message) == ("done", None)
    assert await _tracked(db) == {"web://docs.example.com/"}


def _row(path: str, status: DocumentStatus) -> RAGDocument:
    return RAGDocument(
        id=uuid.uuid4(),
        collection_name=COLLECTION,
        filename="page.md",
        filetype="md",
        source_path=path,
        status=status,
    )


async def _add_claimed(
    session: AsyncSession, source_id: uuid.UUID | None, path: str, status: DocumentStatus
) -> None:
    """A row, and the claim `source_id` holds on it when there is one."""
    row = _row(path, status)
    session.add(row)
    # The claim's foreign key needs its row written first.
    await session.flush()
    if source_id is not None:
        session.add(RAGDocumentClaim(rag_document_id=row.id, sync_source_id=source_id))
        await session.flush()


async def test_only_this_sources_settled_documents_are_candidates_for_removal(
    engine: AsyncEngine, db: AsyncSession
) -> None:
    """Two sources may feed one collection, and one may be mid-run: neither the
    other's documents nor a row still being ingested is this sync's to remove."""
    mine = uuid.UUID(await _source(engine))
    theirs = uuid.UUID(await _source(engine))
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        for claimant, path, status in [
            (mine, "web://docs.example.com/gone", DocumentStatus.DONE),
            (mine, "web://docs.example.com/failed", DocumentStatus.ERROR),
            (mine, "web://docs.example.com/running", DocumentStatus.PROCESSING),
            (mine, "web://docs.example.com/kept", DocumentStatus.DONE),
            (theirs, "web://docs.example.com/theirs", DocumentStatus.DONE),
            (None, "upload.pdf", DocumentStatus.DONE),
        ]:
            await _add_claimed(session, claimant, path, status)
        await session.commit()

    unlisted = await RAGDocumentService(db).unlisted_by_source(
        sync_source_id=mine, collection_name=COLLECTION, listed={"web://docs.example.com/kept"}
    )

    assert {row.source_path for row in unlisted} == {
        "web://docs.example.com/gone",
        "web://docs.example.com/failed",
    }


async def test_deleting_a_source_leaves_its_documents_nobodys(
    engine: AsyncEngine, db: AsyncSession
) -> None:
    source_id = uuid.UUID(await _source(engine))
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await _add_claimed(session, source_id, "web://docs.example.com/", DocumentStatus.DONE)
        await session.commit()
        await session.execute(text("DELETE FROM sync_sources WHERE id = :id"), {"id": source_id})
        await session.commit()

    assert await _tracked(db) == {"web://docs.example.com/"}
    assert (await db.execute(select(RAGDocumentClaim))).scalars().all() == []


# The second source either skips the page the first ingested and claims it as
# unchanged (`new_only`), or re-ingests it and takes the first source's claim
# over with the row (`full`). Either may then be the first to stop listing it.
@pytest.mark.parametrize("second_mode", ["new_only", "full"])
@pytest.mark.parametrize("drops_first", ["first", "second"])
async def test_a_page_two_sources_list_stays_until_both_stop_listing_it(
    engine: AsyncEngine, db: AsyncSession, _site: _Site, second_mode: str, drops_first: str
) -> None:
    """The page belonged to whichever source ingested it last, and that one
    dropping it removed it, although the other still listed it (#1879)."""
    _site.pages.update(
        {"/": _page("Welcome to the documentation.", "billing"), "/billing": _page("Invoices.")}
    )
    first = await _source(engine)
    second = await _source(engine, beside=first, sync_mode=second_mode)
    await _sync(engine, first)
    await _sync(engine, second)
    dropping, remaining = (first, second) if drops_first == "first" else (second, first)

    await _narrow_to_start_page(engine, dropping)
    narrowed = await _sync(engine, dropping)

    assert (narrowed.status, narrowed.removed) == ("done", 0)
    assert await _tracked(db) == {"web://docs.example.com/", "web://docs.example.com/billing"}
    assert await _found(engine, "invoices") == ["web://docs.example.com/billing"]

    await _narrow_to_start_page(engine, remaining)
    last = await _sync(engine, remaining)

    assert (last.status, last.removed) == ("done", 1)
    assert await _tracked(db) == {"web://docs.example.com/"}
    assert "web://docs.example.com/billing" not in await _found(engine, "invoices", limit=10)
