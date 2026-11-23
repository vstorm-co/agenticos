"""A search bound to a checked knowledge base reads that base, not one sharing its name.

A collection name is not unique (#2537): an organization holds bases that share
one, and bases of other organizations do too. Looked up by name alone, the store
answers with the base it prefers for the organization. These seed three bases
called `handbook` - the one being searched, a private sibling in the same
organization and one in another organization - and point the name lookup at the
sibling, then drive the knowledge-gap draft search and the workflow knowledge
search through the real store and its SQL.
"""

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.capabilities.knowledge import _search
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.knowledge_gap import KnowledgeSearch
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRunStatus
from app.repositories import knowledge_base_repo
from app.repositories.knowledge_gap import DraftingRow
from app.services.knowledge_gaps import KnowledgeGapService
from app.services.rag.config import RAGSettings
from app.services.rag.models import Document, DocumentMetadata, DocumentPage, DocumentPageChunk
from app.services.rag.retrieval import RetrievalService
from app.services.rag.vectorstore import PgVectorStore
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.nodes.knowledge_search import _handler as search_handler
from tests.integration.workflow_run_support import drive, seed_member, seed_run

pytestmark = [pytest.mark.anyio, pytest.mark.security]

COLLECTION = "handbook"
TABLE = f"rag_{COLLECTION}"


def _kb(
    org: Organization, owner: User, *, scope: KBScope, visibility: str | None = None
) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=f"{COLLECTION} {uuid.uuid4().hex[:6]}",
        scope=scope.value,
        collection_name=COLLECTION,
        embedding_model="m",
        embedding_dim=3,
        embedding_provider="openrouter",
        organization_id=org.id,
        owner_user_id=owner.id,
        visibility=visibility,
    )


def _document(content: str) -> Document:
    document = Document(
        pages=[DocumentPage(page_num=1, content=content)],
        metadata=DocumentMetadata(
            filename=f"{content}.pdf",
            filesize=1,
            filetype="pdf",
            source_path=f"/srv/{content}.pdf",
            content_hash=content,
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


class World:
    """Three bases called `handbook`, a chunk in each, and a store that prefers the sibling."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.store = PgVectorStore.__new__(PgVectorStore)
        self.store.async_session = async_sessionmaker(engine, expire_on_commit=False)
        self.store.dim = 3
        self.store.settings = RAGSettings()
        # Every chunk and every query embed alike, so what a search returns is
        # exactly what its scope lets through.
        embedder = MagicMock(
            embed_document=lambda document: [[0.1, 0.2, 0.3]] * len(document.chunked_pages),
            embed_query=MagicMock(return_value=[0.1, 0.2, 0.3]),
        )
        self.store._for_collection = AsyncMock(return_value=(embedder, 3))  # type: ignore[method-assign]
        self.service = RetrievalService(self.store, RAGSettings())

    async def seed(self) -> None:
        async with async_sessionmaker(self.engine, expire_on_commit=False)() as db:
            self.member, self.org = await seed_member(db, role="member")
            self.colleague = await self._colleague(db)
            self.foreign_owner, self.foreign_org = await seed_member(db)
            self.own = _kb(self.org, self.member, scope=KBScope.PERSONAL)
            self.sibling = _kb(self.org, self.colleague, scope=KBScope.ORG, visibility="private")
            self.foreign = _kb(self.foreign_org, self.foreign_owner, scope=KBScope.ORG)
            db.add_all([self.own, self.sibling, self.foreign])
            await db.commit()
        for kb, content in (
            (self.own, "own chunk"),
            (self.sibling, "sibling chunk"),
            (self.foreign, "foreign chunk"),
        ):
            document = _document(content)
            document.metadata.organization_id = str(kb.vector_tenant)
            await self.store.insert_document(COLLECTION, document, kb.vector_scope)

        async def prefers_the_sibling(_name: str, _organization_id: object = None):
            return self.sibling

        self.store._resolver = prefers_the_sibling  # type: ignore[assignment]

    async def _colleague(self, db: AsyncSession) -> User:
        colleague = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        db.add(colleague)
        await db.flush()
        db.add(
            OrganizationMember(
                id=uuid.uuid4(),
                organization_id=self.org.id,
                user_id=colleague.id,
                role=OrgRoleName.OWNER.value,
            )
        )
        await db.flush()
        return colleague


@pytest.fixture
async def world(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[World]:
    monkeypatch.setattr(knowledge_base_repo, "hold_key_share", AsyncMock(return_value=True))
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
    built = World(engine)
    monkeypatch.setattr(_search, "get_retrieval_service", lambda: built.service)
    monkeypatch.setattr(search_handler, "get_retrieval_service", lambda: built.service)
    await built.seed()
    yield built
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))


async def test_the_name_alone_resolves_to_the_sibling(world: World) -> None:
    """The premise: a search holding only the name reads the base the store prefers."""
    found = await _search.search_knowledge_base(
        "policy", kb_collection_names=[COLLECTION], organization_id=world.org.id
    )

    assert "sibling chunk" in found
    assert "own chunk" not in found


async def test_a_gap_draft_searches_only_its_topic_s_base(
    world: World, engine: AsyncEngine
) -> None:
    ctx = AuthContext(
        user_id=world.member.id, organization_id=world.org.id, role=OrgRoleName.MEMBER
    )
    material = [
        DraftingRow(
            search=KnowledgeSearch(query="leave policy"),
            question=None,
            answer=None,
            found=None,
            down_rating_comment=None,
        )
    ]

    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        ((query, found),) = await KnowledgeGapService(db)._search_now(ctx, world.own, material)

    assert query == "leave policy"
    assert "own chunk" in found
    assert "sibling chunk" not in found
    assert "foreign chunk" not in found


def _node(definition_id: str, config: dict[str, object] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance) -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port="out",
        target_node_id=target.id,
        target_port="in",
    )


def _graph(collection_id: uuid.UUID) -> WorkflowGraph:
    entry = _node("core.input")
    search = _node("knowledge.search", {"collection_ids": [str(collection_id)], "top_k": 10})
    output = _node("core.output")
    return WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, search, output),
        edges=(_edge(entry, search), _edge(search, output)),
        bindings=(
            Binding(
                target_node_id=search.id,
                target_field="query",
                source=NodeOutputRef(node_id=entry.id, port="out", field_path=("payload", "q")),
            ),
            Binding(
                target_node_id=output.id,
                target_field="sources",
                source=NodeOutputRef(node_id=search.id, port="out", field_path=("sources",)),
            ),
        ),
    )


async def test_a_workflow_search_reads_only_the_base_it_checked(
    world: World, engine: AsyncEngine
) -> None:
    seeded = await seed_run(
        engine,
        _graph(world.own.id),
        run_input={"q": "leave policy"},
        member=(world.member, world.org),
    )

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None
    assert [source["content"] for source in run.output["sources"]] == ["own chunk"]


async def test_another_organization_s_base_is_never_searched(
    world: World, engine: AsyncEngine
) -> None:
    """Even when it shares the name: the run's principal cannot name it at all."""
    seeded = await seed_run(
        engine,
        _graph(world.foreign.id),
        run_input={"q": "leave policy"},
        member=(world.member, world.org),
    )

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "COLLECTION_NOT_ACCESSIBLE"
