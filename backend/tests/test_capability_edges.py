"""Tests for the paths that only run when something is unusual.

Refusals, fallbacks and guard clauses are where a platform earns its keep, and
they are exactly the branches that never run during a demo. Each test here
pins one of them.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities import CapabilityBinding, build, load_builtins
from app.agents.capabilities.budget import BudgetGuard, SpendLedger
from app.agents.capabilities.charts._spec import (
    MAX_DATA_POINTS,
    MAX_SERIES,
    ChartSpec,
)
from app.agents.capabilities.code_execution._sandbox import _clip, _format_result
from app.agents.capabilities.knowledge._search import search_knowledge_base
from app.agents.capabilities.skills import Skills
from app.agents.capabilities.web_research import WebResearch
from app.agents.factory import _as_decimal
from app.agents.model_resolver import ResolvedCredential, build_with_fallbacks
from app.core.config import settings as app_settings
from app.core.exceptions import ConfigurationError, ExternalServiceError
from app.core.secret_kinds import ApiKeySecret
from app.services.mcp_catalog import CatalogAuth, get_entry
from app.services.rag.embeddings import EmbeddingService, OpenAIEmbeddingProvider
from app.services.rag.models import SearchResult
from app.services.rag.retrieval import RetrievalService
from app.services.rag.vectorstore import PgVectorStore


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


def _retrieval_over(store: MagicMock) -> RetrievalService:
    settings = MagicMock()
    settings.enable_hybrid_search = False
    return RetrievalService(vector_store=store, settings=settings)


class TestSearchingSeveralCollections:
    """What a multi-collection search may and may not quietly leave out."""

    @pytest.mark.anyio
    async def test_a_collection_that_fails_fails_the_whole_search(self):
        """A partial answer presented as a complete one is the worse failure.

        The caller is asking whether something is in the organization's
        knowledge; a shortfall reads as "no". This used to log the exception and
        carry on, so a broken collection answered 200 with whatever the others
        held and nothing on any screen said so.
        """
        store = MagicMock()
        store.search = AsyncMock(
            side_effect=[
                [SearchResult(content="from the healthy one", score=0.9)],
                RuntimeError("pgvector is having a day"),
            ]
        )

        with pytest.raises(RuntimeError):
            await _retrieval_over(store).retrieve_multi(
                query="anything", collection_names=["healthy", "broken"], organization_id=None
            )

    @pytest.mark.anyio
    async def test_an_empty_collection_is_not_a_failure(self):
        """The store reports an absent table as no results, so it merges as none."""
        store = MagicMock()
        store.search = AsyncMock(
            side_effect=[[SearchResult(content="found", score=0.9)], []],
        )

        results = await _retrieval_over(store).retrieve_multi(
            query="anything", collection_names=["populated", "never_ingested"], organization_id=None
        )

        assert [r.content for r in results] == ["found"]

    @pytest.mark.anyio
    async def test_every_result_names_the_collection_it_came_from(self):
        """Provenance on one collection too, not only when several are searched.

        The UI offers to say which knowledge base answered, and the tagging used
        to live in `retrieve_multi` alone - so narrowing the scope to one base
        silently dropped the attribution from every result.
        """
        store = MagicMock()
        store.search = AsyncMock(return_value=[SearchResult(content="chunk", score=0.5)])

        results = await _retrieval_over(store).retrieve(
            query="anything", collection_name="handbook", organization_id=None
        )

        assert [r.metadata["collection"] for r in results] == ["handbook"]


class TestKnowledgeSearchGuards:
    @pytest.mark.anyio
    async def test_no_collections_says_so_rather_than_searching_everything(self):
        """The dangerous failure mode would be an unscoped search."""
        result = await search_knowledge_base(
            query="x", kb_collection_names=[], organization_id=None
        )
        assert "No active knowledge bases" in result

    @pytest.mark.anyio
    async def test_one_collection_uses_the_single_collection_path(self):
        service = MagicMock()
        service.retrieve = AsyncMock(return_value=[])
        with patch(
            "app.agents.capabilities.knowledge._search.get_retrieval_service",
            return_value=service,
        ):
            await search_knowledge_base(
                query="x", kb_collection_names=["kb_a"], organization_id=None
            )
        service.retrieve.assert_awaited_once()

    @pytest.mark.anyio
    async def test_several_collections_use_the_multi_path(self):
        service = MagicMock()
        service.retrieve_multi = AsyncMock(return_value=[])
        with patch(
            "app.agents.capabilities.knowledge._search.get_retrieval_service",
            return_value=service,
        ):
            await search_knowledge_base(
                query="x", kb_collection_names=["kb_a", "kb_b"], organization_id=None
            )
        service.retrieve_multi.assert_awaited_once()

    @pytest.mark.anyio
    async def test_a_retrieval_failure_surfaces_as_an_external_service_error(self):
        """Not a silent empty result: an agent must not answer as if it searched."""
        service = MagicMock()
        service.retrieve = AsyncMock(side_effect=RuntimeError("pgvector down"))
        with (
            patch(
                "app.agents.capabilities.knowledge._search.get_retrieval_service",
                return_value=service,
            ),
            pytest.raises(ExternalServiceError),
        ):
            await search_knowledge_base(
                query="x", kb_collection_names=["kb_a"], organization_id=None
            )

    @pytest.mark.anyio
    async def test_an_unconfigured_deployment_keeps_saying_what_to_configure(self):
        """The generic rewrap used to eat the one message that named the fix.

        A missing embedding credential reaches this tool as a ConfigurationError
        carrying the setting to set; turning that into "Knowledge base search
        failed" leaves an operator with a symptom and no next step.
        """
        service = MagicMock()
        service.retrieve = AsyncMock(
            side_effect=ConfigurationError(
                message="No embedding credential is configured",
                details={"setting": "OPENROUTER_API_KEY"},
            )
        )
        with (
            patch(
                "app.agents.capabilities.knowledge._search.get_retrieval_service",
                return_value=service,
            ),
            pytest.raises(ConfigurationError) as refusal,
        ):
            await search_knowledge_base(
                query="x", kb_collection_names=["kb_a"], organization_id=None
            )

        assert refusal.value.details == {"setting": "OPENROUTER_API_KEY"}


class TestEmbeddingCredential:
    """An unconfigured embedding key is a configuration state, not a crash."""

    def test_building_the_provider_does_not_require_a_key(self):
        """Half of RAG never embeds anything.

        Reading a collection's stats is one COUNT(*), but the client used to be
        built while FastAPI resolved the dependency, so an unconfigured
        deployment answered /rag/collections/{name}/info with a 500 out of the
        OpenAI SDK.
        """
        assert OpenAIEmbeddingProvider(model="text-embedding-3-small").model

    def test_embedding_without_a_key_names_the_setting_to_set(self):
        provider = OpenAIEmbeddingProvider(model="text-embedding-3-small")

        with pytest.raises(ConfigurationError) as refusal:
            provider.embed_queries(["hello"])

        assert refusal.value.status_code == 503
        assert "OPENROUTER_API_KEY" in refusal.value.message
        assert refusal.value.details == {
            "setting": "OPENROUTER_API_KEY",
            "model": "text-embedding-3-small",
        }

    def test_the_client_is_built_once_and_reused(self):
        provider = OpenAIEmbeddingProvider(model="m", api_key="sk-test", base_url="https://x/v1")
        assert provider.client is provider.client

    def test_a_collection_nobody_has_uploaded_to_reports_as_empty(self):
        """The second half of the reported 500 on `/rag/collections/{name}/info`.

        Fixing the credential got the request as far as the COUNT, which then
        failed with `UndefinedTableError`: a collection's table is created by
        its first ingest, so a knowledge base nobody has uploaded to has no
        table. "Nothing indexed yet" is the answer, not a server fault - and
        `get_documents` had been answering the same question that way all
        along.
        """
        store = PgVectorStore.__new__(PgVectorStore)
        store.dim = 1536
        # No knowledge base claims this name, which is the resolver's `None`
        # and the store's deployment defaults.
        store._resolver = AsyncMock(return_value=None)
        store.embedder = MagicMock()
        store._collection_exists = AsyncMock(return_value=False)
        # A session that would raise if it were opened at all: reporting the
        # empty collection must not depend on the query succeeding.
        store.async_session = MagicMock(side_effect=AssertionError("should not query"))

        info = asyncio.run(store.get_collection_info("never_ingested", organization_id=None))

        assert (info.name, info.total_vectors, info.dim) == ("never_ingested", 0, 1536)

    def test_searching_a_collection_nobody_has_uploaded_to_finds_nothing(self):
        """Same absent table, reached from the search path rather than the count.

        `get_collection_info` learned this and `search` did not, so the knowledge
        page's own search - the first surface that lets somebody query a base
        with no documents in it - answered 500 on a base created a minute
        earlier. The embedder must not be reached either: an empty collection is
        not worth an embedding call, and paying for one would be metered.
        """
        store = PgVectorStore.__new__(PgVectorStore)
        store.dim = 1536
        store._resolver = None
        store.embedder = MagicMock()
        store._collection_exists = AsyncMock(return_value=False)
        store._for_collection = AsyncMock(side_effect=AssertionError("should not embed"))
        store.async_session = MagicMock(side_effect=AssertionError("should not query"))

        assert asyncio.run(store.search("never_ingested", "anything", organization_id=None)) == []

    def test_the_service_builds_on_a_deployment_with_no_key(self, monkeypatch):
        """`get_embedding_service` is a FastAPI dependency of every RAG route.

        Raising here failed the request before any handler ran, which is why
        `GET /rag/collections/{name}/info` - a COUNT(*) that embeds nothing -
        answered 500 with an OpenAI SDK traceback instead of its row count.
        """
        monkeypatch.setattr(app_settings, "OPENROUTER_API_KEY", "")

        service = EmbeddingService(settings=app_settings.rag)

        with pytest.raises(ConfigurationError):
            service.embed_query("only searching needs the key")


class TestChartValidation:
    def test_empty_data_is_refused(self):
        with pytest.raises(ValueError, match="at least one row"):
            ChartSpec(chart_type="bar", title="t", data=[])

    def test_too_many_rows_are_refused(self):
        """A chart nobody can read is a rendering failure, not a big chart."""
        with pytest.raises(ValueError, match="too many rows"):
            ChartSpec(
                chart_type="bar",
                title="t",
                data=[{"x": i, "y": i} for i in range(MAX_DATA_POINTS + 1)],
            )

    def test_too_many_series_are_refused(self):
        with pytest.raises(ValueError, match="too many series"):
            ChartSpec(
                chart_type="bar",
                title="t",
                data=[{"x": 1}],
                series=[{"key": f"s{i}"} for i in range(MAX_SERIES + 1)],
            )

    def test_rows_that_do_not_carry_the_x_axis_field_are_refused(self):
        """The shape that drew an empty frame, guarded at the format itself.

        The tool can no longer send it - the axis is its own argument - but
        `parse_chart_spec` builds a spec straight from a persisted result, and
        the ones written before the tool changed are still in the table.
        """
        with pytest.raises(ValueError, match="x-axis field 'miesiac'"):
            ChartSpec(
                chart_type="line",
                title="t",
                data=[{}],
                series=[{"key": "sprzedaz"}],
                x_key="miesiac",
            )

    def test_booleans_do_not_count_as_something_to_plot(self):
        """`True` is an int in Python, and a flag is not a value on an axis.

        Asserted on the format rather than through the tool: `values` is typed
        `list[float]`, so this can only reach a spec that was assembled from a
        persisted result rather than from a tool call.
        """
        with pytest.raises(ValueError, match="number to plot"):
            ChartSpec(chart_type="bar", title="t", data=[{"x": "Jan", "active": True}])


class TestSandboxFormatting:
    def test_output_and_value_together(self):
        assert "printed" in _format_result("printed", 1)

    def test_value_alone(self):
        assert "42" in _format_result("", 42)

    def test_output_alone(self):
        assert "printed" in _format_result("printed", None)

    def test_clipping_marks_what_it_removed(self):
        clipped = _clip("y" * 50_000)
        assert len(clipped) < 50_000


class TestFactoryHelpers:
    """Approval resolution moved to tests/test_approval_gate.py with the rule."""

    def test_a_float_budget_becomes_an_exact_decimal(self):
        """0.1 as a float drifts when accumulated; this is where that ends."""
        assert _as_decimal(0.1) == Decimal("0.1")
        # Via the string, not the float: `Decimal(0.1)` carries the binary
        # approximation across and the budget stops being reconcilable.
        assert str(_as_decimal(0.1)) == "0.1"


class TestModelFallbacks:
    def test_no_fallbacks_builds_a_plain_model(self):
        credential = ResolvedCredential(provider="openai", secret=ApiKeySecret(api_key="sk-test"))
        model = build_with_fallbacks((credential, "gpt-4.1"), [])
        assert type(model).__name__ != "FallbackModel"

    def test_fallbacks_wrap_the_primary(self):
        """A single provider outage should not take an organization's agents down."""
        credential = ResolvedCredential(provider="openai", secret=ApiKeySecret(api_key="sk-test"))
        model = build_with_fallbacks(
            (credential, "gpt-4.1"),
            [
                (
                    ResolvedCredential(provider="anthropic", secret=ApiKeySecret(api_key="sk-b")),
                    "claude-sonnet-4-6",
                )
            ],
        )
        assert type(model).__name__ == "FallbackModel"


class TestBudgetEdges:
    @pytest.mark.anyio
    async def test_a_response_without_usage_is_not_charged(self):
        """Some providers omit usage on cached or filtered responses."""
        guard = BudgetGuard(ledger=SpendLedger())
        response = MagicMock(model_name="gpt-4.1")
        response.usage = None
        await guard.wrap_model_request(
            MagicMock(), request_context=MagicMock(), handler=AsyncMock(return_value=response)
        )
        assert guard.ledger.total_usd == Decimal(0)

    @pytest.mark.anyio
    async def test_a_response_without_a_model_name_is_still_recorded(self):
        guard = BudgetGuard(ledger=SpendLedger())
        response = MagicMock(spec=["usage"])
        response.usage = RequestUsage(input_tokens=10, output_tokens=10)
        await guard.wrap_model_request(
            MagicMock(), request_context=MagicMock(), handler=AsyncMock(return_value=response)
        )
        assert guard.ledger.entries[0].model_name == "unknown"


class TestCapabilityBuilderBranches:
    def test_web_research_uses_its_default_when_unconfigured(self):
        built = build([CapabilityBinding(capability_id="web_research")])
        capability = built[0]
        assert isinstance(capability, WebResearch)
        assert capability.max_results == 5

    def test_skills_is_not_attached_without_any(self):
        assert build([CapabilityBinding(capability_id="skills")]) == []

    def test_skills_is_attached_when_resolved(self):
        skill = MagicMock(name="refunds", description="d", content="c", resources=[])
        built = build([CapabilityBinding(capability_id="skills")], resources={"skills": [skill]})
        assert isinstance(built[0], Skills)

    def test_an_empty_skill_set_yields_no_toolset(self):
        assert Skills(skills=[]).get_toolset() is None


class TestChartFailureModes:
    """A tool that raises kills the turn; a ModelRetry lets the model correct itself."""

    def test_invalid_arguments_come_back_as_a_retry(self):
        from app.agents.capabilities.charts import ChartsToolset

        with pytest.raises(ModelRetry, match="`x_values` was empty"):
            ChartsToolset().create_chart(chart_type="bar", title="t", x_values=[], series=[])

    def test_unplottable_data_says_how_to_fix_it(self):
        """The model can only recover if it is told what was missing."""
        from app.agents.capabilities.charts import ChartsToolset
        from app.agents.capabilities.charts._toolset import ChartSeriesInput

        with pytest.raises(ModelRetry, match=r"'revenue' has 0 value\(s\) for 1 x value\(s\)"):
            ChartsToolset().create_chart(
                chart_type="bar",
                title="t",
                x_values=["only-a-label"],
                series=[ChartSeriesInput(key="revenue", values=[])],
            )

    def test_the_capability_exposes_the_toolset_tool(self):
        from app.agents.capabilities.charts import Charts
        from app.agents.capabilities.charts._toolset import ChartSeriesInput

        toolset = Charts().get_toolset()
        result = toolset.tools["create_chart"].function(
            chart_type="bar",
            title="Revenue",
            x_values=["Jan"],
            series=[ChartSeriesInput(key="y", values=[1])],
        )
        assert "Revenue" in result

    def test_a_malformed_payload_parses_to_nothing(self):
        from app.agents.capabilities.charts._spec import parse_chart_spec

        assert parse_chart_spec('{"kind": "chart", "chart_type": "not-a-chart-type"}') is None


class TestWebSearchFailureModes:
    def test_a_malformed_payload_parses_to_nothing(self):
        from app.agents.capabilities.web_research._search import parse_web_search

        assert parse_web_search('{"results": "not a list"}') is None

    @pytest.mark.anyio
    async def test_the_capability_wrapper_passes_its_limit_and_provider_through(self):
        from app.agents.capabilities.web_research import WebResearch
        from app.agents.capabilities.web_research._search import WebSearchResults

        toolset = WebResearch(provider="brave", max_results=3, api_key="k").get_toolset()
        with patch(
            "app.agents.capabilities.web_research._toolset.search",
            new=AsyncMock(return_value=WebSearchResults(query="x", provider="brave")),
        ) as backend:
            await toolset.tools["web_search"].function(query="x")

        assert backend.call_args.kwargs["max_results"] == 3
        assert backend.call_args.kwargs["provider"] == "brave"


class TestSandboxResultRendering:
    def test_an_unserialisable_value_falls_back_to_its_string_form(self):
        """A model that returns an object should still see something useful."""

        class Opaque:
            def __repr__(self) -> str:
                return "<opaque>"

        assert "<opaque>" in _format_result("", Opaque())

    def test_a_silent_program_says_it_ran(self):
        assert "no output" in _format_result("", None).lower()

    @pytest.mark.anyio
    async def test_a_successful_run_is_formatted(self):
        from app.agents.capabilities.code_execution._sandbox import run_python

        session = MagicMock()
        session.feed_run = AsyncMock(return_value=42)
        monty = MagicMock()
        monty.checkout.return_value.__aenter__ = AsyncMock(return_value=session)
        monty.checkout.return_value.__aexit__ = AsyncMock(return_value=False)
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=monty)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.agents.capabilities.code_execution._sandbox.AsyncMonty", return_value=client
        ):
            assert "42" in await run_python("6*7")


class TestCapabilityToolsetCaching:
    def test_every_capability_builds_its_toolset_once(self):
        """Rebuilding per call would re-derive schemas on every turn."""
        from app.agents.capabilities.charts import Charts
        from app.agents.capabilities.code_execution import CodeExecution
        from app.agents.capabilities.knowledge import Knowledge

        for capability in (Charts(), CodeExecution(), Knowledge(), WebResearch()):
            assert capability.get_toolset() is capability.get_toolset()


class TestLastMileBranches:
    """The branches a demo never reaches, pinned so a refactor cannot drop them."""

    def test_the_series_the_model_named_are_the_series_emitted(self):
        from app.agents.capabilities.charts import ChartsToolset
        from app.agents.capabilities.charts._spec import parse_chart_spec
        from app.agents.capabilities.charts._toolset import ChartSeriesInput

        spec = parse_chart_spec(
            ChartsToolset().create_chart(
                chart_type="bar",
                title="t",
                x_values=["Jan"],
                series=[ChartSeriesInput(key="revenue", values=[1])],
            )
        )
        assert spec is not None
        assert [s.key for s in spec.series] == ["revenue"]

    def test_a_web_search_payload_of_the_wrong_kind_is_ignored(self):
        from app.agents.capabilities.web_research._search import parse_web_search

        assert parse_web_search('{"kind": "something_else"}') is None

    def test_a_web_search_payload_that_is_not_an_object_is_ignored(self):
        from app.agents.capabilities.web_research._search import parse_web_search

        assert parse_web_search("[1, 2, 3]") is None

    def test_a_web_search_payload_with_a_bad_shape_is_ignored(self):
        from app.agents.capabilities.web_research._search import parse_web_search

        assert parse_web_search('{"kind": "web_search", "results": "not a list"}') is None

    def test_the_retrieval_service_is_a_singleton(self):
        """Rebuilding the embedder per search would reload a model on every turn."""
        import app.agents.capabilities.knowledge._search as search_module

        sentinel = object()
        original = search_module._retrieval_service
        search_module._retrieval_service = sentinel  # type: ignore[assignment]
        try:
            assert search_module.get_retrieval_service() is sentinel
        finally:
            search_module._retrieval_service = original

    def test_the_retrieval_service_is_built_on_first_use(self):
        import app.agents.capabilities.knowledge._search as search_module

        original = search_module._retrieval_service
        search_module._retrieval_service = None
        try:
            with (
                patch.object(search_module, "EmbeddingService"),
                patch.object(search_module, "PgVectorStore"),
                patch.object(search_module, "RetrievalService") as service_cls,
            ):
                assert search_module.get_retrieval_service() is service_cls.return_value
        finally:
            search_module._retrieval_service = original


class TestServerCatalog:
    def test_a_key_that_is_not_in_the_catalog_resolves_to_nothing(self):
        """The catalog is a list of servers we vetted; an unknown key must not become one.

        Callers branch on `None` to fall back to "custom server, supply your own
        URL". Anything else here would let a connect request name a server the
        platform never looked at and inherit a curated entry's auth settings.
        """
        assert get_entry("definitely-not-a-server") is None

    def test_a_catalog_key_resolves_to_the_server_it_names(self):
        entry = get_entry("github")
        assert entry is not None
        assert entry.name == "GitHub"
        assert entry.auth is CatalogAuth.TOKEN


class TestFinalBranches:
    def test_a_chart_payload_with_an_invalid_field_parses_to_nothing(self):
        """The channel renderer inspects every tool result; a near-miss must not raise."""
        from app.agents.capabilities.charts._spec import parse_chart_spec

        assert (
            parse_chart_spec('{"kind": "chart", "chart_type": "bar", "title": "t", "data": []}')
            is None
        )

    def test_a_circular_result_falls_back_to_its_string_form(self):
        """`default=str` handles unknown types; only a cycle still raises."""
        circular: list[object] = []
        circular.append(circular)
        assert "result:" in _format_result("", circular)

    def test_a_skills_toolset_is_built_once(self):
        skill = MagicMock(name="refunds", description="d", content="c", resources=[])
        capability = Skills(skills=[skill])
        assert capability.get_toolset() is capability.get_toolset()
