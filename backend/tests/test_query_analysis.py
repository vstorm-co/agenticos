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
    extract_keywords,
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


class TestKeywordExtraction:
    def test_drops_stopwords_and_keeps_content_terms_in_order(self):
        assert extract_keywords("How do I reset my password quickly?") == [
            "reset",
            "password",
            "quickly",
        ]

    def test_collapses_duplicates_and_one_character_tokens(self):
        assert extract_keywords("budget budget a x plan") == ["budget", "plan"]

    def test_an_all_stopword_query_yields_nothing(self):
        assert extract_keywords("what is the of a") == []

    def test_keeps_accented_words_whole(self):
        # An ASCII-only tokenizer truncates "contraseña" to "contrase"; the
        # Unicode-aware one keeps the whole term so BM25 sees the real word.
        assert extract_keywords("olvidé mi contraseña") == ["olvidé", "mi", "contraseña"]

    def test_extracts_terms_from_non_latin_scripts(self):
        # A non-Latin query must not silently reduce `keywords` mode to `off`.
        assert extract_keywords("パスワード リセット") == ["パスワード", "リセット"]


class TestPlanQueries:
    async def test_off_returns_the_query_alone(self):
        assert await plan_queries("hello", mode="off", max_variants=3, generate=None) == ["hello"]

    async def test_keywords_appends_the_content_terms(self):
        planned = await plan_queries(
            "reset my password", mode="keywords", max_variants=3, generate=None
        )
        assert planned == ["reset my password reset password"]

    async def test_keywords_leaves_an_all_stopword_query_unchanged(self):
        """Appending nothing must not produce a trailing-space variant of the query."""
        assert await plan_queries("of the a", mode="keywords", max_variants=3, generate=None) == [
            "of the a"
        ]

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

    async def test_an_llm_mode_without_a_generator_degrades_to_the_plain_query(self):
        """A surface with no model to run (a channel searching directly) still
        searches - it just does not expand."""
        assert await plan_queries("q", mode="multi_query", max_variants=3, generate=None) == ["q"]

    async def test_a_generation_that_raises_degrades_rather_than_failing(self):
        async def boom(_: str) -> str:
            raise RuntimeError("provider down")

        assert await plan_queries("q", mode="hyde", max_variants=3, generate=boom) == ["q"]


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
