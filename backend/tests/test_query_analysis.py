"""Optional query analysis and expansion before retrieval (#1649).

The security-bearing property is tested where the scope lives - see
`tests/integration/test_rag_filter_scope.py` for the proof that an expanded query
cannot reach another tenant's chunk. This file pins the per-mode behaviour, the
bounded fan-out and the fusion, none of which need a database.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.services.rag.models import SearchResult
from app.services.rag.query_analysis import (
    QueryAnalysisMode,
    QueryExpansionFailed,
    hypothetical_document,
    multi_query_variants,
    plan_queries,
)
from app.services.rag.retrieval import RetrievalService, fuse_over_queries

pytestmark = pytest.mark.anyio


def _fixed(text: str) -> Callable[[str], object]:
    async def generate(_: str) -> str:
        return text

    return generate


class TestPlanQueries:
    async def test_off_returns_the_query_alone(self):
        assert await plan_queries("hello", mode="off", max_variants=3, generate=None) == ["hello"]

    async def test_multi_query_keeps_the_original_and_adds_bounded_variants(self):
        generate = _fixed("reset password\nchange my password\nrecover my account\nunlock login")
        planned = await plan_queries(
            "reset password", mode="multi_query", max_variants=2, generate=generate
        )
        # The original, then at most `max_variants` distinct variants; the line
        # equal to the original is dropped rather than searched twice.
        assert planned == ["reset password", "change my password", "recover my account"]

    async def test_multi_query_strips_list_markers_and_quotes(self):
        generate = _fixed('1. "change my password"\n- recover my account')
        planned = await plan_queries("x", mode="multi_query", max_variants=5, generate=generate)
        assert planned == ["x", "change my password", "recover my account"]

    async def test_hyde_searches_the_hypothetical_passage(self):
        generate = _fixed("  A refund is issued within 30 days of purchase.  ")
        planned = await plan_queries(
            "refund window", mode="hyde", max_variants=3, generate=generate
        )
        assert planned == ["A refund is issued within 30 days of purchase."]

    async def test_hyde_falls_back_to_the_query_when_the_model_writes_nothing(self):
        planned = await plan_queries(
            "refund window", mode="hyde", max_variants=3, generate=_fixed("")
        )
        assert planned == ["refund window"]

    async def test_off_never_calls_the_generator(self):
        async def never(_: str) -> str:
            raise AssertionError("off must not run the model")

        assert await plan_queries("q", mode="off", max_variants=3, generate=never) == ["q"]

    async def test_a_mode_without_a_generator_degrades_to_the_plain_query(self):
        """A run model that cannot make a request-response call still searches -
        it just does not expand."""
        assert await plan_queries("q", mode="multi_query", max_variants=3, generate=None) == ["q"]

    @pytest.mark.parametrize("mode", ["multi_query", "hyde"])
    async def test_an_expected_generation_failure_degrades_rather_than_failing(
        self, mode: QueryAnalysisMode
    ):
        async def refused(_: str) -> str:
            raise QueryExpansionFailed("ModelHTTPError")

        assert await plan_queries("q", mode=mode, max_variants=3, generate=refused) == ["q"]

    async def test_a_programming_error_in_the_generator_propagates(self):
        """Only the failures the callback declares expected fall back; a bug is
        not laundered into a plain search that hides it."""

        async def broken(_: str) -> str:
            raise TypeError("a bug, not an outage")

        with pytest.raises(TypeError):
            await plan_queries("q", mode="hyde", max_variants=3, generate=broken)


class TestMultiQueryBounds:
    async def test_never_returns_more_than_max_variants(self):
        generate = _fixed("\n".join(f"variant {i}" for i in range(20)))
        variants = await multi_query_variants("q", generate=generate, max_variants=3)
        assert len(variants) == 3

    async def test_caps_the_length_of_a_runaway_variant(self):
        generate = _fixed("x" * 5000)
        [variant] = await multi_query_variants("q", generate=generate, max_variants=1)
        assert len(variant) <= 400

    async def test_hypothetical_document_is_length_bounded(self):
        passage = await hypothetical_document("q", generate=_fixed("y" * 5000))
        assert len(passage) <= 2000


def _hit(content: str, doc: str) -> SearchResult:
    return SearchResult(content=content, score=0.5, parent_doc_id=doc, metadata={"chunk_num": 1})


class TestFuseOverQueries:
    async def test_a_single_query_is_returned_untouched(self):
        """Analysis off must retrieve exactly as before: no fusion pass."""
        sentinel = [_hit("only", "d1")]

        async def retrieve_one(_: str) -> list[SearchResult]:
            return sentinel

        assert await fuse_over_queries(["q"], retrieve_one, limit=5) is sentinel

    async def test_a_chunk_found_by_several_variants_ranks_above_one_found_by_one(self):
        async def retrieve_one(query: str) -> list[SearchResult]:
            if query == "q1":
                return [_hit("shared", "d1"), _hit("only-1", "d2")]
            return [_hit("shared", "d1"), _hit("only-2", "d3")]

        fused = await fuse_over_queries(["q1", "q2"], retrieve_one, limit=5)
        assert next(r.content for r in fused) == "shared"
        assert {r.content for r in fused} == {"shared", "only-1", "only-2"}

    async def test_the_fused_set_is_cut_to_the_limit(self):
        async def retrieve_one(query: str) -> list[SearchResult]:
            return [_hit(f"{query}-a", f"{query}1"), _hit(f"{query}-b", f"{query}2")]

        fused = await fuse_over_queries(["q1", "q2"], retrieve_one, limit=2)
        assert len(fused) == 2


class TestRrfFusesAnyNumberOfLists:
    def test_two_lists_prefer_the_earlier_list_representative(self):
        first = [_hit("a", "d1")]
        second = [_hit("a-other-content", "d1")]
        fused = RetrievalService._rrf_fuse([first, second])
        # Same fusion key (parent doc + chunk), so one row, represented by the
        # first list it appeared in - the vector leg, in the hybrid case.
        assert len(fused) == 1
        assert fused[0].content == "a"

    def test_three_lists_sum_reciprocal_ranks(self):
        lists = [[_hit("shared", "d1")], [_hit("shared", "d1")], [_hit("other", "d2")]]
        fused = RetrievalService._rrf_fuse(lists)
        assert [r.content for r in fused] == ["shared", "other"]

    def test_fusion_keeps_every_field_of_the_representative(self):
        """Only the score is replaced. A field a store or a later stage adds to a
        result - an expanded parent passage, say - must come out of fusion intact
        rather than being dropped by a rebuild that names only the fields it knew."""
        first = [_Expanded(content="a", score=0.9, parent_doc_id="d1", expanded_content="ctx")]
        second = [_hit("b", "d2")]

        fused = RetrievalService._rrf_fuse([first, second])

        assert isinstance(fused[0], _Expanded)
        assert fused[0].expanded_content == "ctx"
        assert fused[0].score == pytest.approx(1.0 / 61)
        # A copy, so the store's own result keeps the score it was ranked by.
        assert first[0].score == 0.9


class _Expanded(SearchResult):
    expanded_content: str | None = None
