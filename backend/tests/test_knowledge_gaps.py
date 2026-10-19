"""Grouping knowledge-base misses into topics, without a database.

What the database decides - which searches are misses, which are ungrouped,
which organization a knowledge base belongs to - is pinned against Postgres in
`tests/integration/test_knowledge_gaps.py`. Here: how misses join or start
topics, and that a pass with nothing to do costs no embedding call.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.db.models.knowledge_gap import KnowledgeGapMember, KnowledgeGapTopic, KnowledgeSearch
from app.repositories import knowledge_gap_repo
from app.repositories.knowledge_gap import DraftingRow
from app.services import change_feed
from app.services.knowledge_gaps import (
    TOPIC_SIMILARITY,
    KnowledgeGapService,
    _assign,
    _Cluster,
    _drafting_prompt,
)
from app.worker.tasks.knowledge_gap_tasks import group_knowledge_gaps_flow

pytestmark = pytest.mark.anyio

_SERVICE = "app.services.knowledge_gaps"
ORG = uuid.uuid4()
KB = uuid.uuid4()


def _vec(*values: float) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float64)
    return vector / np.linalg.norm(vector)


class TestAssign:
    def test_a_miss_close_to_a_topic_joins_it_and_moves_its_centroid(self):
        topic = _Cluster(centroid=_vec(1, 0), size=3, topic=MagicMock(), searches=[])
        search = uuid.uuid4()

        clusters = _assign([(search, _vec(1, 0.1))], [topic], threshold=TOPIC_SIMILARITY)

        assert clusters == [topic]
        assert topic.searches == [search]
        assert topic.size == 4
        assert topic.moved
        assert topic.centroid[1] > 0

    def test_a_miss_unlike_every_topic_starts_its_own(self):
        topic = _Cluster(centroid=_vec(1, 0), size=1, topic=MagicMock(), searches=[])

        clusters = _assign([(uuid.uuid4(), _vec(0, 1))], [topic], threshold=TOPIC_SIMILARITY)

        assert len(clusters) == 2
        assert not topic.moved
        assert clusters[1].topic is None
        assert clusters[1].size == 1
        assert clusters[1].moved

    def test_a_miss_can_join_a_topic_an_earlier_miss_of_the_same_pass_started(self):
        first, second = uuid.uuid4(), uuid.uuid4()

        clusters = _assign(
            [(first, _vec(0, 1)), (second, _vec(0.05, 1))], [], threshold=TOPIC_SIMILARITY
        )

        assert [c.searches for c in clusters] == [[first, second]]

    def test_the_nearest_topic_wins(self):
        far = _Cluster(centroid=_vec(1, 0.6), size=1, topic=MagicMock(), searches=[])
        near = _Cluster(centroid=_vec(1, 0.05), size=1, topic=MagicMock(), searches=[])

        _assign([(uuid.uuid4(), _vec(1, 0))], [far, near], threshold=0.5)

        assert near.moved and not far.moved


def _search(query: str) -> MagicMock:
    return MagicMock(id=uuid.uuid4(), query=query)


def _kb(*, organization_id: uuid.UUID = ORG) -> MagicMock:
    return MagicMock(
        id=KB,
        organization_id=organization_id,
        collection_name="handbook",
        embedding_model="text-embedding-3-small",
    )


class TestGroupPending:
    async def test_nothing_waiting_costs_no_embedding_call(self):
        with (
            patch(
                f"{_SERVICE}.knowledge_gap_repo.ungrouped_misses", new=AsyncMock(return_value=[])
            ),
            patch(f"{_SERVICE}.embeddings_for_collection", new=AsyncMock()) as resolve,
            patch(f"{_SERVICE}.embedder_for") as embedder,
        ):
            grouped = await KnowledgeGapService(MagicMock()).group_pending(
                organization_id=ORG, knowledge_base_id=KB
            )

        assert grouped == 0
        resolve.assert_not_awaited()
        embedder.assert_not_called()

    async def test_each_distinct_query_is_embedded_once_in_one_request(self):
        misses = [_search("parking"), _search("parking"), _search("visitor wifi")]
        embedder = MagicMock()
        embedder.embed_queries = MagicMock(return_value=[[1.0, 0.0], [0.0, 1.0]])
        created: list[dict[str, Any]] = []

        async def create_topic(_db: Any, **kwargs: Any) -> MagicMock:
            created.append(kwargs)
            return MagicMock(id=uuid.uuid4())

        with (
            patch(
                f"{_SERVICE}.knowledge_gap_repo.ungrouped_misses",
                new=AsyncMock(return_value=misses),
            ),
            patch(f"{_SERVICE}.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=_kb())),
            patch(f"{_SERVICE}.embeddings_for_collection", new=AsyncMock(return_value=MagicMock())),
            patch(f"{_SERVICE}.embedder_for", return_value=embedder),
            patch(f"{_SERVICE}.knowledge_gap_repo.topics_in_space", new=AsyncMock(return_value=[])),
            patch(f"{_SERVICE}.knowledge_gap_repo.create_topic", new=create_topic),
            patch(f"{_SERVICE}.knowledge_gap_repo.add_members", new=AsyncMock()) as add,
        ):
            grouped = await KnowledgeGapService(MagicMock()).group_pending(
                organization_id=ORG, knowledge_base_id=KB
            )

        embedder.embed_queries.assert_called_once_with(["parking", "visitor wifi"])
        assert grouped == 3
        assert len(created) == 2
        assert {c["embedding_model"] for c in created} == {"text-embedding-3-small"}
        assert len(add.await_args.args[1]) == 3

    async def test_a_stored_topic_that_takes_a_miss_has_its_centroid_written(self):
        topic = MagicMock(id=uuid.uuid4(), centroid=[1.0, 0.0])
        embedder = MagicMock(embed_queries=MagicMock(return_value=[[1.0, 0.05]]))

        with (
            patch(
                f"{_SERVICE}.knowledge_gap_repo.ungrouped_misses",
                new=AsyncMock(return_value=[_search("parking fines")]),
            ),
            patch(f"{_SERVICE}.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=_kb())),
            patch(f"{_SERVICE}.embeddings_for_collection", new=AsyncMock(return_value=MagicMock())),
            patch(f"{_SERVICE}.embedder_for", return_value=embedder),
            patch(
                f"{_SERVICE}.knowledge_gap_repo.topics_in_space",
                new=AsyncMock(return_value=[(topic, 2)]),
            ),
            patch(
                f"{_SERVICE}.knowledge_gap_repo.update_topic", new=AsyncMock(return_value=topic)
            ) as update,
            patch(f"{_SERVICE}.knowledge_gap_repo.create_topic", new=AsyncMock()) as create,
            patch(f"{_SERVICE}.knowledge_gap_repo.add_members", new=AsyncMock()) as add,
        ):
            await KnowledgeGapService(MagicMock()).group_pending(
                organization_id=ORG, knowledge_base_id=KB
            )

        create.assert_not_awaited()
        assert update.await_args.kwargs["update_data"]["centroid"][1] > 0
        assert [pair[0] for pair in add.await_args.args[1]] == [topic.id]

    async def test_a_stored_topic_no_miss_joins_is_left_as_it_was(self):
        topic = MagicMock(id=uuid.uuid4(), centroid=[1.0, 0.0])
        embedder = MagicMock(embed_queries=MagicMock(return_value=[[0.0, 1.0]]))
        fresh = MagicMock(id=uuid.uuid4())

        with (
            patch(
                f"{_SERVICE}.knowledge_gap_repo.ungrouped_misses",
                new=AsyncMock(return_value=[_search("guest wifi")]),
            ),
            patch(f"{_SERVICE}.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=_kb())),
            patch(f"{_SERVICE}.embeddings_for_collection", new=AsyncMock(return_value=MagicMock())),
            patch(f"{_SERVICE}.embedder_for", return_value=embedder),
            patch(
                f"{_SERVICE}.knowledge_gap_repo.topics_in_space",
                new=AsyncMock(return_value=[(topic, 4)]),
            ),
            patch(f"{_SERVICE}.knowledge_gap_repo.update_topic", new=AsyncMock()) as update,
            patch(f"{_SERVICE}.knowledge_gap_repo.create_topic", new=AsyncMock(return_value=fresh)),
            patch(f"{_SERVICE}.knowledge_gap_repo.add_members", new=AsyncMock()) as add,
        ):
            await KnowledgeGapService(MagicMock()).group_pending(
                organization_id=ORG, knowledge_base_id=KB
            )

        update.assert_not_awaited()
        assert [pair[0] for pair in add.await_args.args[1]] == [fresh.id]

    async def test_a_topic_of_another_width_is_another_space_and_does_not_break_the_pass(self):
        narrow = MagicMock(id=uuid.uuid4(), centroid=[1.0, 0.0])
        embedder = MagicMock(embed_queries=MagicMock(return_value=[[1.0, 0.0, 0.0]]))
        fresh = MagicMock(id=uuid.uuid4())

        with (
            patch(
                f"{_SERVICE}.knowledge_gap_repo.ungrouped_misses",
                new=AsyncMock(return_value=[_search("parking")]),
            ),
            patch(f"{_SERVICE}.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=_kb())),
            patch(f"{_SERVICE}.embeddings_for_collection", new=AsyncMock(return_value=MagicMock())),
            patch(f"{_SERVICE}.embedder_for", return_value=embedder),
            patch(
                f"{_SERVICE}.knowledge_gap_repo.topics_in_space",
                new=AsyncMock(return_value=[(narrow, 3)]),
            ),
            patch(f"{_SERVICE}.knowledge_gap_repo.update_topic", new=AsyncMock()) as update,
            patch(f"{_SERVICE}.knowledge_gap_repo.create_topic", new=AsyncMock(return_value=fresh)),
            patch(f"{_SERVICE}.knowledge_gap_repo.add_members", new=AsyncMock()) as add,
        ):
            await KnowledgeGapService(MagicMock()).group_pending(
                organization_id=ORG, knowledge_base_id=KB
            )

        update.assert_not_awaited()
        assert [pair[0] for pair in add.await_args.args[1]] == [fresh.id]

    @pytest.mark.parametrize(
        "kb", [None, _kb(organization_id=uuid.uuid4())], ids=["gone", "another organization"]
    )
    async def test_a_knowledge_base_that_is_not_this_organizations_is_not_embedded(self, kb):
        with (
            patch(
                f"{_SERVICE}.knowledge_gap_repo.ungrouped_misses",
                new=AsyncMock(return_value=[_search("q")]),
            ),
            patch(f"{_SERVICE}.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=kb)),
            patch(f"{_SERVICE}.embeddings_for_collection", new=AsyncMock()) as resolve,
        ):
            grouped = await KnowledgeGapService(MagicMock()).group_pending(
                organization_id=ORG, knowledge_base_id=KB
            )

        assert grouped == 0
        resolve.assert_not_awaited()

    async def test_no_embedding_configuration_leaves_the_misses_waiting(self, caplog):
        with (
            patch(
                f"{_SERVICE}.knowledge_gap_repo.ungrouped_misses",
                new=AsyncMock(return_value=[_search("q")]),
            ),
            patch(f"{_SERVICE}.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=_kb())),
            patch(f"{_SERVICE}.embeddings_for_collection", new=AsyncMock(return_value=None)),
            patch(f"{_SERVICE}.knowledge_gap_repo.add_members", new=AsyncMock()) as add,
        ):
            grouped = await KnowledgeGapService(MagicMock()).group_pending(
                organization_id=ORG, knowledge_base_id=KB
            )

        assert grouped == 0
        add.assert_not_awaited()
        assert "knowledge_gaps_not_grouped" in caplog.text


class _Context:
    async def __aenter__(self) -> MagicMock:
        return MagicMock()

    async def __aexit__(self, *_: object) -> None:
        return None


class TestTheFlow:
    async def test_every_waiting_knowledge_base_is_grouped_and_one_failure_spares_the_rest(
        self, caplog
    ):
        other_kb = uuid.uuid4()
        group = AsyncMock(side_effect=[RuntimeError("provider refused"), 4])

        with (
            patch("app.worker.tasks.knowledge_gap_tasks.get_db_context", new=_Context),
            patch.object(change_feed, "connect_in_worker", new=AsyncMock()),
            patch.object(change_feed, "publish_knowledge_gaps_grouped", new=AsyncMock()) as told,
            patch.object(KnowledgeGapService, "forget_empty_topics", new=AsyncMock()) as forget,
            patch.object(
                KnowledgeGapService,
                "waiting_to_be_grouped",
                new=AsyncMock(return_value=[(ORG, KB), (ORG, other_kb)]),
            ),
            patch.object(KnowledgeGapService, "group_pending", new=group),
        ):
            grouped = await group_knowledge_gaps_flow.fn()

        forget.assert_awaited_once()
        assert grouped == 4
        assert [c.kwargs["knowledge_base_id"] for c in group.await_args_list] == [KB, other_kb]
        assert "knowledge_gaps_grouping_failed" in caplog.text
        # Only the pass that placed something, after it committed.
        told.assert_awaited_once_with(ORG)

    async def test_a_pass_with_nothing_waiting_groups_nothing(self, caplog):
        with (
            patch("app.worker.tasks.knowledge_gap_tasks.get_db_context", new=_Context),
            patch.object(change_feed, "connect_in_worker", new=AsyncMock()),
            patch.object(change_feed, "publish_knowledge_gaps_grouped", new=AsyncMock()) as told,
            patch.object(KnowledgeGapService, "forget_empty_topics", new=AsyncMock()),
            patch.object(
                KnowledgeGapService, "waiting_to_be_grouped", new=AsyncMock(return_value=[])
            ),
        ):
            grouped = await group_knowledge_gaps_flow.fn()

        assert grouped == 0
        assert "grouped" not in caplog.text
        told.assert_not_awaited()

    async def test_a_named_knowledge_base_is_grouped_without_looking_for_others(self):
        with (
            patch("app.worker.tasks.knowledge_gap_tasks.get_db_context", new=_Context),
            patch.object(change_feed, "connect_in_worker", new=AsyncMock()),
            patch.object(change_feed, "publish_knowledge_gaps_grouped", new=AsyncMock()),
            patch.object(KnowledgeGapService, "forget_empty_topics", new=AsyncMock()),
            patch.object(KnowledgeGapService, "waiting_to_be_grouped", new=AsyncMock()) as waiting,
            patch.object(
                KnowledgeGapService, "group_pending", new=AsyncMock(return_value=1)
            ) as group,
        ):
            await group_knowledge_gaps_flow.fn(organization_id=str(ORG), knowledge_base_id=str(KB))

        waiting.assert_not_awaited()
        assert group.await_args.kwargs == {"organization_id": ORG, "knowledge_base_id": KB}


class TestTheRepository:
    async def test_writing_no_searches_sends_no_statement(self):
        db = MagicMock(execute=AsyncMock())

        await knowledge_gap_repo.record_searches(
            db, [], organization_id=ORG, run_id=uuid.uuid4(), conversation_id=None
        )
        await knowledge_gap_repo.add_members(db, [])

        db.execute.assert_not_awaited()

    def test_rows_name_themselves(self):
        search = KnowledgeSearch(id=uuid.uuid4(), run_id=uuid.uuid4(), top_similarity=0.2)
        topic = KnowledgeGapTopic(id=uuid.uuid4(), knowledge_base_id=KB, status="open")
        member = KnowledgeGapMember(topic_id=topic.id, search_id=search.id)

        assert "0.2" in repr(search)
        assert "open" in repr(topic)
        assert str(search.id) in repr(member)


class TestTheDraftingPrompt:
    def test_each_question_is_numbered_and_a_long_answer_is_cut(self):
        rows = [
            DraftingRow(
                search=MagicMock(query="parking"),
                question="Where do visitors park?",
                answer="x" * 5_000,
                found=None,
                down_rating_comment=None,
            )
        ]

        prompt = _drafting_prompt("Handbook", rows, [])

        assert '"Handbook"' in prompt
        assert "## Question 1" in prompt
        assert "Found: -" in prompt
        assert "x" * 1_500 + "..." in prompt
        assert "x" * 1_501 not in prompt
        assert "Documents the agent found" not in prompt
