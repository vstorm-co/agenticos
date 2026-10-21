"""Recording an agent's knowledge searches, for knowledge gaps.

The search tool records into a log the runner injects, and the runner writes the
log once the run is over. These tests pin what a record holds, that only a
search that ran is recorded, and that a lost write never fails the run.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities._registry import CapabilityBuildContext
from app.agents.capabilities._registry import get as get_capability
from app.agents.capabilities.knowledge import (
    KNOWLEDGE_SEARCH_LOG_RESOURCE,
    Knowledge,
    KnowledgeConfig,
    KnowledgeSearchLog,
)
from app.agents.capabilities.knowledge._search import search_knowledge_base
from app.agents.capabilities.knowledge._toolset import build_knowledge_toolset
from app.agents.deps import AgentDeps
from app.agents.isolation import RunIsolation
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.permissions import AuthContext, OrgRoleName
from app.services.agent_runner import AgentRunnerService, PreparedRun
from app.services.rag.models import SearchResult
from app.services.rag.retrieval import RetrievalService

pytestmark = pytest.mark.anyio

_SEARCH = "app.agents.capabilities.knowledge._search"
AGENT = uuid.uuid4()
KB_A = uuid.uuid4()
KB_B = uuid.uuid4()


def _log() -> KnowledgeSearchLog:
    return KnowledgeSearchLog(agent_id=AGENT, collections={"kb_a": KB_A, "kb_b": KB_B})


def _hit(similarity: float | None, score: float = 0.02) -> SearchResult:
    return SearchResult(content="passage", score=score, similarity=similarity)


def _retrieval(results: list[SearchResult]) -> MagicMock:
    service = MagicMock()
    service.resolve_scope = AsyncMock(return_value=MagicMock())
    service.retrieve = AsyncMock(return_value=results)
    service.retrieve_multi = AsyncMock(return_value=results)
    return service


class TestTheLog:
    def test_a_search_keeps_the_best_similarity_not_the_ranking_score(self):
        log = _log()

        log.record("refund window", ["kb_a"], [_hit(0.41, score=0.03), _hit(0.58, score=0.01)])

        [record] = log.records
        assert record.agent_id == AGENT
        assert record.knowledge_base_ids == (KB_A,)
        assert record.query == "refund window"
        assert record.result_count == 2
        assert record.top_similarity == 0.58

    def test_fusion_keeps_the_closest_match_any_query_variant_found(self):
        """A passage one variant matched poorly and another matched well is not a miss."""
        first = SearchResult(content="passage", score=0.5, similarity=0.31)
        second = SearchResult(content="passage", score=0.9, similarity=0.82)
        unscored = SearchResult(content="passage", score=0.4)

        [fused] = RetrievalService._rrf_fuse([[first], [unscored], [second]])

        assert fused.similarity == 0.82

    def test_fusion_takes_a_similarity_a_later_list_has_when_the_first_had_none(self):
        bm25 = SearchResult(content="passage", score=3.1)
        vector = SearchResult(content="passage", score=0.9, similarity=0.64)

        [fused] = RetrievalService._rrf_fuse([[bm25], [vector]])

        assert fused.similarity == 0.64

    def test_a_runaway_query_is_kept_to_its_first_thousand_characters(self):
        log = _log()

        log.record("q" * 5_000, ["kb_a"], [])

        assert log.records[0].query == "q" * 1_000

    def test_a_search_that_found_nothing_has_no_similarity(self):
        log = _log()

        log.record("refund window", ["kb_a", "kb_b"], [])

        [record] = log.records
        assert record.knowledge_base_ids == (KB_A, KB_B)
        assert record.result_count == 0
        assert record.top_similarity is None

    def test_a_collection_the_agent_is_not_bound_to_is_not_recorded(self):
        log = _log()

        log.record("q", ["kb_a", "someone_elses"], [_hit(0.5)])
        log.record("q", ["someone_elses"], [_hit(0.5)])

        assert [r.knowledge_base_ids for r in log.records] == [(KB_A,)]

    def test_a_delegate_records_into_the_same_list_under_its_own_agent(self):
        log = _log()
        delegate = uuid.uuid4()
        delegate_kb = uuid.uuid4()

        log.for_agent(delegate, {"kb_d": delegate_kb}).record("q", ["kb_d"], [])
        log.for_agent(None, {"kb_a": KB_A}).record("q", ["kb_a"], [])

        assert [(r.agent_id, r.knowledge_base_ids) for r in log.records] == [
            (delegate, (delegate_kb,)),
            (AGENT, (KB_A,)),
        ]


class TestTheSearchReportsWhatItFound:
    async def test_a_search_that_ran_reports_its_collections_and_results(self):
        seen: list[tuple[list[str], list[SearchResult]]] = []
        results = [_hit(0.6)]

        with patch(f"{_SEARCH}.get_retrieval_service", return_value=_retrieval(results)):
            await search_knowledge_base(
                query="q",
                kb_collection_names=["kb_a", "kb_b"],
                organization_id=uuid.uuid4(),
                on_results=lambda names, found: seen.append((names, found)),
            )

        assert seen == [(["kb_a", "kb_b"], results)]

    async def test_a_refused_search_reports_nothing(self):
        seen: list[Any] = []

        await search_knowledge_base(
            query="q",
            kb_collection_names=["kb_a"],
            organization_id=None,
            on_results=lambda *args: seen.append(args),
        )

        assert seen == []


def _tool_ctx() -> RunContext[AgentDeps]:
    return RunContext(
        deps=AgentDeps(kb_collection_names=["kb_a"], organization_id=uuid.uuid4()),
        model=TestModel(),
        usage=RunUsage(),
    )


class TestTheToolRecords:
    async def test_each_search_the_model_makes_is_recorded(self):
        log = _log()
        search = build_knowledge_toolset(default_top_k=5, search_log=log).tools["search_documents"]

        with patch(f"{_SEARCH}.get_retrieval_service", return_value=_retrieval([_hit(0.22)])):
            await search.function(_tool_ctx(), query="parking policy")
            await search.function(_tool_ctx(), query="parking fines")

        assert [(r.query, r.top_similarity) for r in log.records] == [
            ("parking policy", 0.22),
            ("parking fines", 0.22),
        ]

    async def test_a_search_that_failed_records_nothing(self):
        log = _log()
        search = build_knowledge_toolset(default_top_k=5, search_log=log).tools["search_documents"]
        broken = _retrieval([])
        broken.retrieve = AsyncMock(side_effect=RuntimeError("store down"))

        with patch(f"{_SEARCH}.get_retrieval_service", return_value=broken):
            await search.function(_tool_ctx(), query="parking policy")

        assert log.records == []

    def test_the_capability_records_into_the_log_the_runner_injected(self):
        log = _log()

        built = get_capability("knowledge").builder(
            CapabilityBuildContext(
                binding=CapabilityBindingSpec(id="knowledge"),
                config=KnowledgeConfig(),
                resources={"kb_collection_names": ["kb_a"], KNOWLEDGE_SEARCH_LOG_RESOURCE: log},
            )
        )

        assert isinstance(built, Knowledge)
        assert built.search_log is log


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


def _prepared(
    log: KnowledgeSearchLog | None, *, surface: str = "web", is_test: bool = False
) -> PreparedRun:
    run = MagicMock(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        surface=surface,
        is_test=is_test,
    )
    return PreparedRun(
        run=run,
        agent=MagicMock(),
        spec=AgentSpec(name="Support"),
        built=MagicMock(),
        approvals=MagicMock(),
        knowledge_searches=log,
    )


def _savepoint_db() -> MagicMock:
    db = MagicMock()
    savepoint = MagicMock()
    savepoint.__aenter__ = AsyncMock(return_value=None)
    savepoint.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=savepoint)
    return db


class TestTheRunnerWritesTheLog:
    async def test_the_runs_searches_are_written_once_under_its_run(self):
        log = _log()
        log.record("q", ["kb_a"], [_hit(0.3)])
        prepared = _prepared(log)
        service = AgentRunnerService(_savepoint_db())

        with patch(
            "app.services.agent_runner.knowledge_gap_repo.record_searches", new=AsyncMock()
        ) as write:
            await service._write_knowledge_searches(prepared)
            await service._write_knowledge_searches(prepared)

        write.assert_awaited_once()
        assert write.await_args.kwargs["run_id"] == prepared.run.id
        assert write.await_args.kwargs["organization_id"] == prepared.run.organization_id
        assert write.await_args.kwargs["conversation_id"] == prepared.run.conversation_id
        assert [r.query for r in write.await_args.args[1]] == ["q"]

    async def test_a_run_that_searched_nothing_writes_nothing(self):
        service = AgentRunnerService(_savepoint_db())

        with patch(
            "app.services.agent_runner.knowledge_gap_repo.record_searches", new=AsyncMock()
        ) as write:
            await service._write_knowledge_searches(_prepared(None))
            await service._write_knowledge_searches(_prepared(_log()))

        write.assert_not_awaited()

    async def test_an_eval_run_records_no_searches(self):
        log = _log()
        log.record("q", ["kb_a"], [])
        service = AgentRunnerService(_savepoint_db())

        with patch(
            "app.services.agent_runner.knowledge_gap_repo.record_searches", new=AsyncMock()
        ) as write:
            await service._write_knowledge_searches(_prepared(log, surface="eval"))

        write.assert_not_awaited()
        assert log.records == []

    async def test_a_builder_testing_a_draft_records_no_searches(self):
        log = _log()
        log.record("q", ["kb_a"], [])
        service = AgentRunnerService(_savepoint_db())

        with patch(
            "app.services.agent_runner.knowledge_gap_repo.record_searches", new=AsyncMock()
        ) as write:
            await service._write_knowledge_searches(_prepared(log, is_test=True))

        write.assert_not_awaited()
        assert log.records == []

    async def test_an_isolated_run_records_no_searches_whatever_its_surface(self):
        log = _log()
        log.record("q", ["kb_a"], [])
        prepared = _prepared(log)
        prepared.isolation = RunIsolation()
        service = AgentRunnerService(_savepoint_db())

        with patch(
            "app.services.agent_runner.knowledge_gap_repo.record_searches", new=AsyncMock()
        ) as write:
            await service._write_knowledge_searches(prepared)

        write.assert_not_awaited()

    async def test_a_lost_write_does_not_fail_the_run(self, caplog):
        log = _log()
        log.record("q", ["kb_a"], [])
        service = AgentRunnerService(_savepoint_db())

        with patch(
            "app.services.agent_runner.knowledge_gap_repo.record_searches",
            new=AsyncMock(side_effect=RuntimeError("insert failed")),
        ):
            await service._write_knowledge_searches(_prepared(log))

        assert "knowledge_searches_not_written" in caplog.text


class TestADelegateSearchesUnderItsOwnName:
    async def _resources(self, parent: dict[str, Any], agent_id: uuid.UUID | None) -> Any:
        ctx = _ctx()
        kb = MagicMock(organization_id=ctx.organization_id, collection_name="kb_d")
        kb_id = uuid.uuid4()
        service = AgentRunnerService(MagicMock())
        service.skills = MagicMock(resolve_for_agent=AsyncMock(return_value=[]))
        service.context = MagicMock(resolve_for_agent=AsyncMock(return_value=[]))
        with patch(
            "app.services.agent_runner.knowledge_base_repo.get_by_ids",
            new=AsyncMock(return_value={kb_id: kb}),
        ):
            resources = await service._delegate_resources(
                ctx,
                AgentSpec(name="Delegate", collection_ids=[kb_id]),
                agent_id=agent_id,
                shared=[],
                parent_resources=parent,
            )
        return resources, kb_id

    async def test_a_delegate_records_into_the_parents_log(self):
        log = _log()
        delegate = uuid.uuid4()

        resources, kb_id = await self._resources(
            {KNOWLEDGE_SEARCH_LOG_RESOURCE: log}, agent_id=delegate
        )
        resources[KNOWLEDGE_SEARCH_LOG_RESOURCE].record("q", ["kb_d"], [])

        assert resources["kb_collection_names"] == ["kb_d"]
        assert [(r.agent_id, r.knowledge_base_ids) for r in log.records] == [(delegate, (kb_id,))]

    async def test_a_parent_with_no_log_gives_its_delegate_none(self):
        resources, _ = await self._resources({}, agent_id=uuid.uuid4())

        assert KNOWLEDGE_SEARCH_LOG_RESOURCE not in resources
