"""`knowledge.search` in a real run: typed sources, empty results, access (#1789).

The collections are real `knowledge_bases` rows, so who may search them is
decided by the same access rules the RAG routes use. The vector search itself
is replaced by a recording stand-in for `RetrievalService` - what is under test
is what the node asks it for and what it makes of the answer, not pgvector's
ranking, which the RAG suites cover.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.exceptions import ExternalServiceError
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRunStatus
from app.services.rag.models import SearchResult
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from app.workflows.nodes.knowledge_search import _handler as search_handler
from tests.integration.workflow_run_support import drive, seed_member, seed_run

pytestmark = pytest.mark.anyio


class _Retrieval:
    """Stands in for `RetrievalService`: records the calls, answers as told."""

    def __init__(self, results: list[SearchResult] | Exception) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def resolve_scope(self, name: str, organization_id: uuid.UUID) -> str:
        return f"scope:{name}:{organization_id}"

    async def _answer(self, method: str, **kwargs: Any) -> list[SearchResult]:
        self.calls.append((method, kwargs))
        if isinstance(self.results, Exception):
            raise self.results
        return self.results

    async def retrieve(self, **kwargs: Any) -> list[SearchResult]:
        return await self._answer("retrieve", **kwargs)

    async def retrieve_multi(self, **kwargs: Any) -> list[SearchResult]:
        return await self._answer("retrieve_multi", **kwargs)


@pytest.fixture
def retrieval(monkeypatch: pytest.MonkeyPatch):
    def install(results: list[SearchResult] | Exception) -> _Retrieval:
        service = _Retrieval(results)
        monkeypatch.setattr(search_handler, "get_retrieval_service", lambda: service)
        return service

    return install


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
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


def _graph(collection_ids: list[uuid.UUID]) -> tuple[WorkflowGraph, NodeInstance]:
    entry = _node("core.input")
    search = _node(
        "knowledge.search", {"collection_ids": [str(c) for c in collection_ids], "top_k": 3}
    )
    output = _node("core.output")
    graph = WorkflowGraph(
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
    return graph, search


async def _collection(
    engine: AsyncEngine, org: Organization, owner: User, *, scope: str = KBScope.ORG.value
) -> uuid.UUID:
    name = f"kb_{uuid.uuid4().hex[:10]}"
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        name=name,
        scope=scope,
        collection_name=name,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_provider="openrouter",
        organization_id=org.id,
        owner_user_id=owner.id,
        visibility="org" if scope == KBScope.ORG.value else None,
    )
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        db.add(kb)
        await db.commit()
    return kb.id


async def _member(engine: AsyncEngine, role: str = "owner") -> tuple[User, Organization]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        member = await seed_member(db, role=role)
        await db.commit()
    return member


def _hit(filename: str, score: float) -> SearchResult:
    return SearchResult(
        content=f"about {filename}",
        score=score,
        metadata={"filename": filename, "page_num": 2, "chunk_num": 5, "document_id": "doc-1"},
    )


async def test_passages_come_back_as_typed_sources_the_output_carries(
    engine: AsyncEngine, retrieval
):
    member = await _member(engine)
    kb_id = await _collection(engine, member[1], member[0])
    service = retrieval([_hit("handbook.pdf", 0.91), _hit("faq.md", 0.72)])
    graph, _search = _graph([kb_id])
    seeded = await seed_run(engine, graph, run_input={"q": "leave policy"}, member=member)
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    ((method, call),) = service.calls
    assert method == "retrieve" and call["query"] == "leave policy" and call["limit"] == 3
    assert call["scope"] == f"scope:{call['collection_name']}:{member[1].id}"
    assert run.output is not None
    first, second = run.output["sources"]
    assert first == {
        "document_id": "doc-1",
        "filename": "handbook.pdf",
        "collection": call["collection_name"],
        "page": 2,
        "chunk": 5,
        "score": 0.91,
        "content": "about handbook.pdf",
    }
    assert second["filename"] == "faq.md"


async def test_no_results_is_an_answer_not_a_failure(engine: AsyncEngine, retrieval):
    member = await _member(engine)
    kb_id = await _collection(engine, member[1], member[0])
    retrieval([])
    graph, _search = _graph([kb_id])

    run = await drive(await seed_run(engine, graph, run_input={"q": "x"}, member=member))

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None and run.output["sources"] == []


async def test_several_collections_are_searched_together(engine: AsyncEngine, retrieval):
    member = await _member(engine)
    first = await _collection(engine, member[1], member[0])
    second = await _collection(engine, member[1], member[0])
    service = retrieval([_hit("a.pdf", 0.5)])
    graph, _search = _graph([first, second])

    run = await drive(await seed_run(engine, graph, run_input={"q": "x"}, member=member))

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    ((method, call),) = service.calls
    assert method == "retrieve_multi" and len(call["collection_names"]) == 2


@pytest.mark.security
async def test_a_collection_the_author_cannot_read_cannot_be_published(
    engine: AsyncEngine, retrieval
):
    member = await _member(engine)
    someone_else = await _member(engine)
    foreign = await _collection(engine, someone_else[1], someone_else[0])
    graph, search = _graph([foreign])
    seeded = await seed_run(engine, graph, member=member)

    with pytest.raises(GraphValidationError) as refused:
        async with async_sessionmaker(engine)() as db:
            await validate_graph(db, seeded.ctx, graph)

    fields = {problem["field"] for problem in refused.value.details["fields"]}
    assert f"nodes.{search.id}.config.collection_ids.0" in fields


@pytest.mark.security
async def test_a_run_whose_principal_cannot_read_a_collection_searches_nothing(
    engine: AsyncEngine, retrieval
):
    """Another member's personal collection: named in the graph, out of reach at run time."""
    member = await _member(engine)
    colleague, _their_org = await _member(engine)
    personal = await _collection(engine, member[1], colleague, scope=KBScope.PERSONAL.value)
    service = retrieval([_hit("secret.pdf", 0.9)])
    graph, _search = _graph([personal])

    run = await drive(await seed_run(engine, graph, run_input={"q": "x"}, member=member))

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "COLLECTION_NOT_ACCESSIBLE"
    assert service.calls == []


async def test_a_store_failure_is_retryable_and_says_nothing_of_the_provider(
    engine: AsyncEngine, retrieval
):
    member = await _member(engine)
    kb_id = await _collection(engine, member[1], member[0])
    retrieval(RuntimeError("POST https://embed.example/v1?key=sk-live-123 failed"))
    graph, _search = _graph([kb_id])

    run = await drive(await seed_run(engine, graph, run_input={"q": "x"}, member=member))

    assert run.status == WorkflowRunStatus.WAITING_RETRY.value


async def test_an_account_of_what_is_wrong_is_passed_through(engine: AsyncEngine, retrieval):
    member = await _member(engine)
    kb_id = await _collection(engine, member[1], member[0])
    retrieval(ExternalServiceError(message="No embedding key is configured for this collection"))
    graph, _search = _graph([kb_id])

    run = await drive(await seed_run(engine, graph, run_input={"q": "x"}, member=member))

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None
    assert run.error["message"] == "No embedding key is configured for this collection"


@pytest.mark.parametrize("fails", [False, True])
async def test_search_books_embedding_spend_even_when_retrieval_then_fails(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    from decimal import Decimal

    from app.agents.capabilities.budget import record_ambient_cost

    member = await _member(engine)
    kb_id = await _collection(engine, member[1], member[0])

    class PaidRetrieval(_Retrieval):
        async def _answer(self, method: str, **kwargs: Any) -> list[SearchResult]:
            record_ambient_cost("embedding-test", Decimal("0.002"))
            return await super()._answer(method, **kwargs)

    service = PaidRetrieval(ExternalServiceError(message="Search unavailable") if fails else [])
    monkeypatch.setattr(search_handler, "get_retrieval_service", lambda: service)
    graph, _search = _graph([kb_id])
    seeded = await seed_run(engine, graph, run_input={"q": "policy"}, member=member)
    final = await drive(seeded)
    assert final.status == ("failed" if fails else "succeeded")
    assert final.spent_cost == Decimal("0.002")
    assert not final.cost_is_partial
    from sqlalchemy import delete, select

    from app.agents.capabilities.budget import BudgetExceeded
    from app.db.models.workflow_run import WorkflowNodeSpend, WorkflowRun
    from app.repositories import workflow_run as run_repo
    from app.services.spend import assert_organization_within_budget, organization_monthly_spend

    async with seeded.factory() as db:
        assert await organization_monthly_spend(db, seeded.org.id) == Decimal("0.002")
        attempts = await db.execute(
            select(WorkflowNodeSpend.attempt_id).where(WorkflowNodeSpend.cost_usd > 0)
        )
        attempt_id = attempts.scalar_one()
        await run_repo.record_node_spend(
            db,
            organization_id=seeded.org.id,
            attempt_id=attempt_id,
            cost_usd=Decimal("0.002"),
            cost_is_partial=False,
        )
        assert await organization_monthly_spend(db, seeded.org.id) == Decimal("0.002")
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        assert await run_repo.node_spend_since(
            db,
            organization_id=seeded.org.id,
            since=now - timedelta(days=1),
            until=now + timedelta(days=1),
        ) == Decimal("0.002")
        assert (
            await run_repo.node_spend_since(
                db,
                organization_id=seeded.org.id,
                since=now - timedelta(days=1),
                until=now - timedelta(hours=1),
            )
            == 0
        )
        assert (
            await run_repo.node_spend_since(
                db, organization_id=uuid.uuid4(), since=now - timedelta(days=1)
            )
            == 0
        )
        org = await db.get(Organization, seeded.org.id)
        assert org is not None
        org.monthly_budget_usd = Decimal("0.001")
        await db.flush()
        with pytest.raises(BudgetExceeded):
            await assert_organization_within_budget(db, seeded.org.id)
        await db.execute(delete(WorkflowRun).where(WorkflowRun.id == seeded.run.id))
        assert await organization_monthly_spend(db, seeded.org.id) == Decimal("0.002")


@pytest.mark.security
async def test_an_exhausted_organization_budget_prevents_search_embedding(
    engine: AsyncEngine, retrieval
) -> None:
    from decimal import Decimal

    member = await _member(engine)
    kb_id = await _collection(engine, member[1], member[0])
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        org = await db.get(Organization, member[1].id)
        assert org is not None
        org.monthly_budget_usd = Decimal("0.001")
        from app.repositories import workflow_run as run_repo

        await run_repo.record_node_spend(
            db,
            organization_id=org.id,
            attempt_id=uuid.uuid4(),
            cost_usd=Decimal("0.001"),
            cost_is_partial=False,
        )
        await db.commit()
    service = retrieval([])
    graph, _search = _graph([kb_id])
    seeded = await seed_run(engine, graph, run_input={"q": "policy"}, member=member)
    final = await drive(seeded)
    assert final.status == "failed"
    assert final.error is not None and final.error["code"] == "BUDGET_EXCEEDED"
    assert not service.calls


@pytest.mark.security
async def test_search_stops_between_collections_at_the_organization_budget(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decimal import Decimal
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.capabilities.budget import record_ambient_cost
    from app.services.rag.retrieval import RetrievalService

    member = await _member(engine)
    first = await _collection(engine, member[1], member[0])
    second = await _collection(engine, member[1], member[0])
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        org = await db.get(Organization, member[1].id)
        assert org is not None
        org.monthly_budget_usd = Decimal("0.001")
        await db.commit()

    async def paid_search(**_kwargs: Any) -> list[SearchResult]:
        record_ambient_cost("embedding", Decimal("0.002"))
        return []

    store = MagicMock()
    store.resolve_tenant = AsyncMock(return_value=member[1].id)
    store.search = AsyncMock(side_effect=paid_search)
    service = RetrievalService(store, MagicMock(enable_hybrid_search=False))
    monkeypatch.setattr(search_handler, "get_retrieval_service", lambda: service)
    graph, _search = _graph([first, second])
    seeded = await seed_run(engine, graph, run_input={"q": "policy"}, member=member)
    final = await drive(seeded)
    assert final.status == "failed"
    assert final.error is not None and final.error["code"] == "BUDGET_EXCEEDED"
    assert store.search.await_count == 1
    assert final.spent_cost == Decimal("0.002")
